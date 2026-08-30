from beanie import PydanticObjectId
from fastapi import APIRouter, HTTPException, Query

from app.models.job import EnrichmentJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[EnrichmentJob])
async def list_jobs(limit: int = Query(50, gt=0, le=200)) -> list[EnrichmentJob]:
    return (
        await EnrichmentJob.find_all()
        .sort(-EnrichmentJob.created_at)
        .limit(limit)
        .to_list()
    )


@router.get("/{job_id}", response_model=EnrichmentJob)
async def get_job(job_id: PydanticObjectId) -> EnrichmentJob:
    job = await EnrichmentJob.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
