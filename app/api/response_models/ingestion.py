from pydantic import BaseModel


class IngestionSummary(BaseModel):
    # Rows accepted from the file. How many actually get classified depends on
    # de-duplication and the per-job cap, and is reported on the EnrichmentJob
    # (GET /api/jobs) as the enrichment progresses.
    rows_received: int


class IngestionResponse(BaseModel):
    summary: IngestionSummary
    enrichment_job_id: str
