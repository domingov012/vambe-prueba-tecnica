import asyncio
import logging
from datetime import datetime, timezone

from beanie import PydanticObjectId
from beanie.operators import In
from pydantic import BaseModel, Field

from app.aggregation.insights import recompute_insights
from app.config import get_settings
from app.db.session import get_client
from app.ingestion.mappers import ParsedRow
from app.ingestion.service import get_or_create_clients, insert_meetings
from app.llm.client import LLMError
from app.llm.processors.transcript_enrichment import enrich_batch
from app.models.enhanced_transcript import (
    EnhancedTranscript,
    TranscriptClassification,
    enrichment_key,
)
from app.models.job import EnrichmentJob, JobStatus

logger = logging.getLogger(__name__)

_STALL_INITIAL_DELAY = 30.0
_STALL_MAX_DELAY = 300.0
# Give up stalling on a single batch after this long and move on — the batch is
# counted as failed and its transcripts stay unenriched, so a later re-upload
# retries just them. Without a ceiling, a batch the model simply can't answer in
# time (too large, or a sustained outage) would wedge the whole job forever.
_STALL_MAX_ELAPSED = 1800.0

_QueueItem = tuple[PydanticObjectId, list[ParsedRow]]

_queue: "asyncio.Queue[_QueueItem] | None" = None
_worker_task: asyncio.Task | None = None


class _EnhancedKey(BaseModel):
    """id-only projection for the 'already enriched?' lookup."""

    id: str = Field(alias="_id")
    model_config = {"populate_by_name": True}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def start_worker() -> None:
    global _queue, _worker_task
    _queue = asyncio.Queue()
    _worker_task = asyncio.create_task(_worker_loop())


async def stop_worker() -> None:
    global _worker_task, _queue
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
        _worker_task = None
    _queue = None


async def enqueue_enrichment_job(
    rows: list[ParsedRow],
    batch_size: int | None = None,
    max_transcripts: int | None = None,
    filename: str | None = None,
) -> EnrichmentJob:
    """Queue a full CSV's worth of parsed rows. Filtering (drop already-enriched
    rows), the `max_transcripts` cap, the LLM calls and all persistence happen in
    the worker — see `_run_job`. The rows ride in the in-memory queue and are not
    persisted anywhere until the LLM classifies them, so a restart mid-job loses
    progress; re-uploading the same file then resumes cleanly (the filter step
    skips whatever already made it into `enhanced_transcripts`)."""
    if _queue is None:
        raise RuntimeError("Enrichment worker not started — call start_worker() first")

    settings = get_settings()
    job = EnrichmentJob(
        batch_size=batch_size or settings.llm_batch_size,
        max_transcripts=max_transcripts or settings.llm_max_transcripts_per_job,
        rows_in_file=len(rows),
        filename=filename,
    )
    await job.insert()
    await _queue.put((job.id, rows))
    return job


async def _worker_loop() -> None:
    assert _queue is not None
    while True:
        job_id, rows = await _queue.get()
        try:
            await _run_job(job_id, rows)
        except Exception as exc:
            logger.exception("Enrichment job %s failed", job_id)
            job = await EnrichmentJob.get(job_id)
            if job is not None:
                job.status = JobStatus.failed
                # str() on some exceptions (e.g. httpx.ReadTimeout) is empty —
                # keep the type so the job row is diagnostic on its own.
                job.error = f"{type(exc).__name__}: {exc}".rstrip(": ")
                job.updated_at = _utcnow()
                await job.save()
        finally:
            _queue.task_done()


async def _existing_enhanced_keys(keys: list[str]) -> set[str]:
    """Which of these enrichment keys already have an EnhancedTranscript."""
    if not keys:
        return set()
    found = await (
        EnhancedTranscript.find(In(EnhancedTranscript.id, keys)).project(_EnhancedKey).to_list()
    )
    return {row.id for row in found}


async def _persist_classified(
    ok: list[tuple[str, ParsedRow]],
    classified: list[tuple[str, TranscriptClassification]],
) -> None:
    """Write the Client, MeetingTranscript and EnhancedTranscript rows for one
    classified batch inside a single transaction — either all three land or none
    do, so a crash mid-write can't leave an orphan meeting without its enhanced
    row (their cluster is a replica set, so multi-document transactions are
    available). The LLM call already happened outside this, so the transaction
    only spans fast local writes and stays well under the 60s commit window.

    A commit that comes back ambiguous (`UnknownTransactionCommitResult`) is left
    to fail the batch: on the next upload Stage 2 sees the key either fully
    present (skip) or fully absent (redo) — never half-written."""
    async with await get_client().start_session() as session:
        async with session.start_transaction():
            clients = await get_or_create_clients([r for _, r in ok], session=session)
            meetings = await insert_meetings(ok, clients, session=session)
            await EnhancedTranscript.insert_many(
                [
                    EnhancedTranscript(
                        id=key,
                        meeting=meetings[key],
                        closed=meetings[key].closed,
                        salesperson=meetings[key].salesperson,
                        meeting_date=meetings[key].meeting_date,
                        **classification.model_dump(),
                    )
                    for key, classification in classified
                ],
                session=session,
            )


async def _run_job(job_id: PydanticObjectId, rows: list[ParsedRow]) -> None:
    job = await EnrichmentJob.get(job_id)
    if job is None:
        return

    job.status = JobStatus.running
    job.updated_at = _utcnow()
    await job.save()

    # Stage 1 — one EnhancedTranscript per (client, meeting): collapse rows that
    # share the enrichment key (reworded near-duplicate transcripts).
    unique: dict[str, ParsedRow] = {}
    for row in rows:
        unique.setdefault(
            enrichment_key(row.name, row.email, row.phone_number, row.meeting_date), row
        )

    # Stage 2 — drop the ones a previous run already classified.
    already = await _existing_enhanced_keys(list(unique))
    pending = [(key, row) for key, row in unique.items() if key not in already]

    # Stage 3 — cap to the per-job budget (free-tier request count is the limit).
    selected = pending[: job.max_transcripts]
    job.skipped_existing = len(unique) - len(pending)
    job.total_candidates = len(selected)
    job.updated_at = _utcnow()
    await job.save()

    # Stage 4 — classify a batch, then persist client + meeting + enhanced rows
    # for exactly the transcripts the LLM returned. Nothing is written for rows
    # the model skipped or that this job never reached.
    enriched_any = False
    for i in range(0, len(selected), job.batch_size):
        chunk = selected[i : i + job.batch_size]
        classified = await _enrich_with_stall_tolerance([(k, r.transcript) for k, r in chunk])

        if classified:
            row_by_key = {k: r for k, r in chunk}
            ok = [(k, row_by_key[k]) for k, _ in classified]
            await _persist_classified(ok, classified)
            enriched_any = True

        job.processed_count += len(classified)
        job.failed_count += len(chunk) - len(classified)
        job.updated_at = _utcnow()
        await job.save()

    job.status = JobStatus.completed
    job.updated_at = _utcnow()
    await job.save()

    # New classifications landed — refresh the precomputed dashboard payload so
    # the cache never silently goes stale relative to enhanced_transcripts.
    # A failure here must not fail the (already-completed) enrichment job.
    if enriched_any:
        try:
            await recompute_insights()
        except Exception:
            logger.exception("Dashboard insights recompute failed after job %s", job_id)


async def _enrich_with_stall_tolerance(
    items: list[tuple[str, str]],
) -> list[tuple[str, TranscriptClassification]]:
    """enrich_batch(), but an upstream failure that outlasts chat_completion's own
    retries (a 429 from OpenRouter's shared free pool or a Google free-tier cap, a
    read timeout on a slow generation, a dropped connection) stalls this batch
    with backoff instead of failing the whole job — a 10k-row job should survive
    an extended free-tier outage, not abort on one. Gives up after
    `_STALL_MAX_ELAPSED` and returns `[]` (batch counted as failed)."""
    delay = _STALL_INITIAL_DELAY
    elapsed = 0.0
    while True:
        try:
            return await enrich_batch(items)
        except LLMError as exc:
            if elapsed >= _STALL_MAX_ELAPSED:
                logger.error("Giving up on batch after %.0fs of stalling: %s", elapsed, exc)
                return []
            logger.warning("Upstream stall enriching batch (%s), retrying in %.0fs", exc, delay)
            await asyncio.sleep(delay)
            elapsed += delay
            delay = min(delay * 2, _STALL_MAX_DELAY)
