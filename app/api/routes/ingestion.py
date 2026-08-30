from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.api.response_models.ingestion import IngestionResponse
from app.ingestion.csv_loader import CSVValidationError
from app.ingestion.service import ingest_csv
from app.llm.jobs import enqueue_enrichment_job

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/csv", response_model=IngestionResponse, status_code=status.HTTP_201_CREATED)
async def upload_csv(
    file: UploadFile = File(...),
    batch_size: int | None = Query(None, gt=0),
    max_transcripts: int | None = Query(None, gt=0),
) -> IngestionResponse:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv file")

    raw_bytes = await file.read()
    try:
        result = await ingest_csv(raw_bytes)
    except CSVValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = None
    if result.meetings:
        job = await enqueue_enrichment_job(
            meeting_ids=[m.id for m in result.meetings],
            batch_size=batch_size,
            max_transcripts=max_transcripts,
        )

    return IngestionResponse(
        summary=result.summary,
        enrichment_job_id=str(job.id) if job is not None else None,
    )
