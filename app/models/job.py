from datetime import datetime, timezone
from enum import Enum

from beanie import Document
from pydantic import Field


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class EnrichmentJob(Document):
    status: JobStatus = JobStatus.queued
    filename: str | None = None
    batch_size: int
    max_transcripts: int
    rows_in_file: int = 0
    # Rows dropped before the LLM step because that (client, meeting) was already
    # enriched. Set when the job starts running.
    skipped_existing: int = 0
    # Rows sent to the LLM (after de-duplication and the max_transcripts cap).
    # 0 until the job starts running.
    total_candidates: int = 0
    processed_count: int = 0
    failed_count: int = 0
    # Batches abandoned entirely (unparseable response, or upstream failures that
    # outlasted the stall budget). Distinct from failed_count, which counts
    # transcripts — one dead batch is `batch_size` failed transcripts.
    failed_batches: int = 0
    # Fatal reason; only set when status is `failed`.
    error: str | None = None
    # Most recent *non-fatal* problem, written while the job is still running.
    # This is what a job sitting at 0 processed shows the operator instead of
    # nothing: the UI reads it from the same /api/jobs poll it already does.
    last_error: str | None = None
    last_error_kind: str | None = None
    last_error_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    class Settings:
        name = "enrichment_jobs"
