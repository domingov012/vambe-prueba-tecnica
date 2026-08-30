from pydantic import BaseModel

from app.ingestion.service import IngestionSummary


class IngestionResponse(BaseModel):
    summary: IngestionSummary
    enrichment_job_id: str | None
