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
    total_candidates: int
    processed_count: int = 0
    failed_count: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "enrichment_jobs"
