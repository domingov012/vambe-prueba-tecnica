import asyncio
import logging
from datetime import datetime, timezone

from beanie import PydanticObjectId
from beanie.operators import In

from app.config import get_settings
from app.llm.client import LLMError
from app.llm.processors.transcript_enrichment import enrich_batch
from app.models.enhanced_transcript import EnhancedTranscript, enrichment_key
from app.models.job import EnrichmentJob, JobStatus
from app.models.meeting import MeetingTranscript

logger = logging.getLogger(__name__)

_STALL_INITIAL_DELAY = 30.0
_STALL_MAX_DELAY = 300.0

_QueueItem = tuple[PydanticObjectId, list[PydanticObjectId]]

_queue: "asyncio.Queue[_QueueItem] | None" = None
_worker_task: asyncio.Task | None = None


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
    meeting_ids: list[PydanticObjectId],
    batch_size: int | None = None,
    max_transcripts: int | None = None,
    filename: str | None = None,
) -> EnrichmentJob:
    if _queue is None:
        raise RuntimeError("Enrichment worker not started — call start_worker() first")

    settings = get_settings()
    batch_size = batch_size or settings.llm_batch_size
    max_transcripts = max_transcripts or settings.llm_max_transcripts_per_job
    candidate_ids = meeting_ids[:max_transcripts]

    job = EnrichmentJob(
        batch_size=batch_size,
        total_candidates=len(candidate_ids),
        filename=filename,
    )
    await job.insert()

    if candidate_ids:
        await _queue.put((job.id, candidate_ids))
    else:
        job.status = JobStatus.completed
        await job.save()

    return job


async def _worker_loop() -> None:
    assert _queue is not None
    while True:
        job_id, meeting_ids = await _queue.get()
        try:
            await _run_job(job_id, meeting_ids)
        except Exception as exc:
            logger.exception("Enrichment job %s failed", job_id)
            job = await EnrichmentJob.get(job_id)
            if job is not None:
                job.status = JobStatus.failed
                job.error = str(exc)
                job.updated_at = datetime.now(timezone.utc)
                await job.save()
        finally:
            _queue.task_done()


async def _run_job(job_id: PydanticObjectId, meeting_ids: list[PydanticObjectId]) -> None:
    job = await EnrichmentJob.get(job_id)
    if job is None:
        return

    job.status = JobStatus.running
    await job.save()

    for i in range(0, len(meeting_ids), job.batch_size):
        chunk_ids = meeting_ids[i : i + job.batch_size]
        # fetch_links=True goes through Motor's aggregate(), which is broken for
        # this beanie/motor version pair (aggregate() isn't awaitable here) —
        # fetch each Link individually instead, which uses plain find/get.
        meetings = await MeetingTranscript.find(In(MeetingTranscript.id, chunk_ids)).to_list()

        to_enrich: list[tuple[str, MeetingTranscript]] = []
        for meeting in meetings:
            client = await meeting.client.fetch()
            key = enrichment_key(
                client.name,
                client.email,
                client.phone_number,
                meeting.meeting_date,
            )
            if await EnhancedTranscript.get(key) is not None:
                continue
            to_enrich.append((key, meeting))

        results = await _enrich_with_stall_tolerance(to_enrich) if to_enrich else []
        if results:
            await EnhancedTranscript.insert_many(results)

        job.processed_count += len(meetings)
        job.failed_count += len(to_enrich) - len(results)
        job.updated_at = datetime.now(timezone.utc)
        await job.save()

    job.status = JobStatus.completed
    job.updated_at = datetime.now(timezone.utc)
    await job.save()


async def _enrich_with_stall_tolerance(
    items: list[tuple[str, MeetingTranscript]],
) -> list[EnhancedTranscript]:
    """enrich_batch(), but a provider 429 that outlasts chat_completion's own
    retries (e.g. OpenRouter's shared free pool, or a Google free-tier daily cap)
    stalls this batch with backoff instead of failing the whole job — a 10k-row
    job should survive an extended free-tier outage, not abort on one."""
    delay = _STALL_INITIAL_DELAY
    while True:
        try:
            return await enrich_batch(items)
        except LLMError:
            logger.warning("Upstream stall enriching batch, retrying in %.0fs", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, _STALL_MAX_DELAY)
