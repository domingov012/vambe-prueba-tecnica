from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from app.api.response_models.ingestion import IngestionResponse, IngestionSummary
from app.ingestion.csv_loader import CSVValidationError, parse_csv
from app.ingestion.mappers import parse_row
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
        rows = [parse_row(row) for row in parse_csv(raw_bytes)]
    except CSVValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Malformed CSV row: {exc}") from exc

    if not rows:
        raise HTTPException(status_code=422, detail="CSV has no data rows")

    # Everything past here — de-dup, the max_transcripts cap, the LLM calls and
    # all persistence — runs in the enrichment worker. No clients or meetings are
    # written for rows the LLM never processes.
    job = await enqueue_enrichment_job(
        rows,
        batch_size=batch_size,
        max_transcripts=max_transcripts,
        filename=file.filename,
    )

    return IngestionResponse(
        summary=IngestionSummary(rows_received=len(rows)),
        enrichment_job_id=str(job.id),
    )
