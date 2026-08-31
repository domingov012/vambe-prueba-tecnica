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
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "enrichment_jobs"
