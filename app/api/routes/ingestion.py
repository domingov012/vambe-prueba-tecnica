from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.ingestion.csv_loader import CSVValidationError
from app.ingestion.service import IngestionSummary, ingest_csv

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/csv", response_model=IngestionSummary, status_code=status.HTTP_201_CREATED)
async def upload_csv(file: UploadFile = File(...)) -> IngestionSummary:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv file")

    raw_bytes = await file.read()
    try:
        return await ingest_csv(raw_bytes)
    except CSVValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
