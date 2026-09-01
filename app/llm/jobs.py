import asyncio
import logging
import time
from datetime import datetime, timezone

from beanie import PydanticObjectId
from beanie.operators import In
from pydantic import BaseModel, Field

from app.aggregation.insights import recompute_insights
from app.config import get_settings
from app.db.session import get_client
from app.ingestion.mappers import ParsedRow
from app.ingestion.service import get_or_create_clients, insert_meetings
from app.llm.client import LLMError, LLMFatalError
from app.llm.processors.transcript_enrichment import BatchOutcome, enrich_batch
from app.models.enhanced_transcript import (
    EnhancedTranscript,
    TranscriptClassification,
    enrichment_key,
)
from app.models.job import EnrichmentJob, JobStatus

logger = logging.getLogger(__name__)

_STALL_INITIAL_DELAY = 30.0
_STALL_MAX_DELAY = 300.0

_QueueItem = tuple[PydanticObjectId, list[ParsedRow]]

_queue: "asyncio.Queue[_QueueItem] | None" = None
_worker_task: asyncio.Task | None = None


class _JobAborted(Exception):
    """Stop the job now and mark it failed with this message.

    Used for conditions where continuing is pointless — a rejected API key, an
    exhausted job deadline. Distinct from an unexpected crash so the worker loop
    can record it without a traceback that suggests a bug.
    """

    def __init__(self, message: str, kind: str = "aborted") -> None:
        super().__init__(message)
        self.kind = kind


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
    logger.info("Enrichment worker started")


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
    logger.info("Enrichment worker stopped")


async def fail_orphaned_jobs() -> None:
    """Mark jobs left `queued`/`running` by a previous process as failed.

    The queue is an in-process `asyncio.Queue` and the rows only live in memory,
    so nothing survives a restart — but the job *document* does, and it stays at
    `running` forever, which is indistinguishable from a job that is genuinely
    working. On a free host that idles the container out from under a running
    job, this is the single most likely reason a job looks stuck. Called from the
    lifespan, after init_db() and before the worker accepts anything new.
    """
    orphans = await EnrichmentJob.find(
        In(EnrichmentJob.status, [JobStatus.queued, JobStatus.running])
    ).to_list()
    if not orphans:
        return

    logger.warning(
        "Failing %d enrichment job(s) left unfinished by a previous process: %s",
        len(orphans),
        [str(job.id) for job in orphans],
    )
    for job in orphans:
        job.status = JobStatus.failed
        job.error = (
            "Interrupted by a server restart — the enrichment queue is in-memory, so "
            "queued rows did not survive. Re-upload the file to resume; already-enriched "
            "transcripts are skipped."
        )
        job.finished_at = _utcnow()
        job.updated_at = _utcnow()
        await job.save()


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
    logger.info(
        "Queued enrichment job %s (file=%r, rows=%d, batch_size=%d, cap=%d, queue_depth=%d)",
        job.id,
        filename,
        len(rows),
        job.batch_size,
        job.max_transcripts,
        _queue.qsize(),
    )
    return job


async def _worker_loop() -> None:
    assert _queue is not None
    while True:
        job_id, rows = await _queue.get()
        try:
            await _run_job(job_id, rows)
        except _JobAborted as exc:
            logger.error("Enrichment job %s aborted: %s", job_id, exc)
            await _mark_failed(job_id, str(exc))
        except Exception as exc:
            logger.exception("Enrichment job %s failed with an unexpected error", job_id)
            # str() on some exceptions (e.g. httpx.ReadTimeout) is empty —
            # keep the type so the job row is diagnostic on its own.
            await _mark_failed(job_id, f"{type(exc).__name__}: {exc}".rstrip(": "))
        finally:
            _queue.task_done()


async def _mark_failed(job_id: PydanticObjectId, message: str) -> None:
    job = await EnrichmentJob.get(job_id)
    if job is None:
        return
    job.status = JobStatus.failed
    job.error = message
    job.finished_at = _utcnow()
    job.updated_at = _utcnow()
    await job.save()


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
    settings = get_settings()
    job = await EnrichmentJob.get(job_id)
    if job is None:
        logger.warning("Enrichment job %s vanished before it could run", job_id)
        return

    job_started = time.monotonic()
    job_deadline = job_started + settings.llm_job_timeout_seconds

    job.status = JobStatus.running
    job.started_at = _utcnow()
    job.updated_at = _utcnow()
    await job.save()
    logger.info(
        "Job %s running: %d row(s) from %r, provider=%s, model=%s",
        job_id,
        len(rows),
        job.filename,
        settings.llm_provider,
        settings.google_model if settings.llm_provider == "google" else settings.openrouter_model,
    )

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

    batch_count = (len(selected) + job.batch_size - 1) // job.batch_size
    logger.info(
        "Job %s selection: %d row(s) -> %d unique -> %d new (%d already enriched) "
        "-> %d selected after the %d cap; %d batch(es) of %d",
        job_id,
        len(rows),
        len(unique),
        len(pending),
        job.skipped_existing,
        len(selected),
        job.max_transcripts,
        batch_count,
        job.batch_size,
    )

    # Stage 4 — classify a batch, then persist client + meeting + enhanced rows
    # for exactly the transcripts the LLM returned. Nothing is written for rows
    # the model skipped or that this job never reached.
    enriched_any = False
    for index, start in enumerate(range(0, len(selected), job.batch_size), start=1):
        chunk = selected[start : start + job.batch_size]
        label = f"job {job_id} batch {index}/{batch_count}"

        remaining = job_deadline - time.monotonic()
        if remaining <= 0:
            raise _JobAborted(
                f"Job deadline of {settings.llm_job_timeout_seconds:.0f}s exceeded after "
                f"{index - 1}/{batch_count} batches "
                f"({job.processed_count} enriched, {job.failed_count} failed). "
                f"Re-upload the file to continue where this left off.",
                kind="job_timeout",
            )

        logger.info("%s: sending %d transcript(s) (%.0fs left on the job)", label, len(chunk), remaining)
        batch_started = time.monotonic()
        outcome = await _enrich_with_stall_tolerance(
            [(k, r.transcript) for k, r in chunk], label, job_deadline
        )
        batch_elapsed = time.monotonic() - batch_started

        if outcome.classified:
            row_by_key = {k: r for k, r in chunk}
            ok = [(k, row_by_key[k]) for k, _ in outcome.classified]
            await _persist_classified(ok, outcome.classified)
            enriched_any = True

        job.processed_count += len(outcome.classified)
        job.failed_count += len(chunk) - len(outcome.classified)
        if not outcome.classified:
            job.failed_batches += 1
        if outcome.error is not None:
            job.last_error = f"Batch {index}/{batch_count}: {outcome.error}"
            job.last_error_kind = outcome.error_kind
            job.last_error_at = _utcnow()
        job.updated_at = _utcnow()
        await job.save()

        log = logger.info if outcome.classified else logger.error
        log(
            "%s done in %.1fs: %d enriched, %d failed (%d invalid, %d missing)%s",
            label,
            batch_elapsed,
            len(outcome.classified),
            len(chunk) - len(outcome.classified),
            outcome.invalid_count,
            outcome.missing_count,
            f" — {outcome.error}" if outcome.error else "",
        )

    job_elapsed = time.monotonic() - job_started

    # A job that classified nothing is a failure, not a success. It used to end
    # `completed` with 0 processed, which reads as "there was nothing to do" —
    # the opposite of what happened.
    if job.total_candidates and not job.processed_count:
        raise _JobAborted(
            f"All {batch_count} batch(es) failed — 0 of {job.total_candidates} transcripts "
            f"were enriched. Last error: {job.last_error or 'unknown'}",
            kind="all_batches_failed",
        )

    job.status = JobStatus.completed
    job.finished_at = _utcnow()
    job.updated_at = _utcnow()
    await job.save()
    logger.info(
        "Job %s completed in %.1fs: %d enriched, %d failed, %d dead batch(es)",
        job_id,
        job_elapsed,
        job.processed_count,
        job.failed_count,
        job.failed_batches,
    )

    # New classifications landed — refresh the precomputed dashboard payload so
    # the cache never silently goes stale relative to enhanced_transcripts.
    # A failure here must not fail the (already-completed) enrichment job.
    if enriched_any:
        try:
            await recompute_insights()
            logger.info("Dashboard insights recomputed after job %s", job_id)
        except Exception:
            logger.exception("Dashboard insights recompute failed after job %s", job_id)


async def _enrich_with_stall_tolerance(
    items: list[tuple[str, str]],
    label: str,
    job_deadline: float,
) -> BatchOutcome:
    """enrich_batch(), but an upstream failure that outlasts chat_completion's own
    retries (a 429 from OpenRouter's shared free pool or a Google free-tier cap, a
    read timeout on a slow generation, a dropped connection) stalls this batch
    with backoff instead of failing the whole job — a 10k-row job should survive
    an extended free-tier outage, not abort on one.

    Every wait here is measured against a **monotonic deadline**, not by summing
    the sleeps. The previous version added up only its own `asyncio.sleep` calls
    and ignored the time spent inside `enrich_batch` — but that call can itself
    run `LLM_MAX_RETRIES × LLM_REQUEST_TIMEOUT_SECONDS` plus backoff, so a
    nominal 30-minute cap really allowed several hours per batch. That is the
    reason a stuck job looked like it had no timeout at all.

    Three ceilings apply, innermost first: `LLM_REQUEST_TIMEOUT_SECONDS` per HTTP
    request, `LLM_BATCH_TIMEOUT_SECONDS` per enrich_batch() attempt (retries
    included), `LLM_BATCH_MAX_STALL_SECONDS` for this whole batch — itself capped
    by whatever is left of the job deadline. On expiry the batch is abandoned and
    counted as failed; a later re-upload retries just those transcripts.

    `LLMFatalError` (a refused key, an unknown model) propagates as `_JobAborted`
    rather than stalling: the server already told us retrying won't help.
    """
    settings = get_settings()
    stall_deadline = min(
        time.monotonic() + settings.llm_batch_max_stall_seconds, job_deadline
    )
    delay = _STALL_INITIAL_DELAY
    attempt = 0
    # Carried across iterations so the give-up message names the actual upstream
    # failure ("429 quota exceeded") rather than just "we ran out of time".
    failure: LLMError | None = None

    while True:
        attempt += 1
        remaining = stall_deadline - time.monotonic()
        if remaining <= 0:
            return _give_up(label, attempt - 1, settings.llm_batch_max_stall_seconds, failure)

        # Never let one attempt run past the batch budget, and never past the
        # job's own deadline.
        budget = min(settings.llm_batch_timeout_seconds, remaining)
        try:
            async with asyncio.timeout(budget):
                return await enrich_batch(items)
        except TimeoutError:
            failure = LLMError(
                f"attempt {attempt} exceeded its {budget:.0f}s ceiling", kind="timeout"
            )
        except LLMFatalError as exc:
            raise _JobAborted(str(exc), kind=exc.kind) from exc
        except LLMError as exc:
            failure = exc

        remaining = stall_deadline - time.monotonic()
        if remaining <= 0:
            return _give_up(label, attempt, settings.llm_batch_max_stall_seconds, failure)

        wait = min(delay, remaining)
        logger.warning(
            "%s: upstream failure on attempt %d (%s: %s) — retrying in %.0fs, %.0fs left",
            label,
            attempt,
            failure.kind,
            failure,
            wait,
            remaining,
        )
        await asyncio.sleep(wait)
        delay = min(delay * 2, _STALL_MAX_DELAY)


def _give_up(label: str, attempts: int, budget: float, failure: LLMError | None) -> BatchOutcome:
    """Abandon a batch whose stall budget is spent, naming what it died of."""
    reason = str(failure) if failure is not None else "no time left in the batch budget"
    message = f"gave up after {attempts} attempt(s) and up to {budget:.0f}s — last error: {reason}"
    logger.error("%s: %s", label, message)
    return BatchOutcome(
        error=message, error_kind=failure.kind if failure is not None else "timeout"
    )
