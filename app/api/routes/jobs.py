from beanie import PydanticObjectId
from fastapi import APIRouter, HTTPException

from app.models.job import EnrichmentJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=EnrichmentJob)
async def get_job(job_id: PydanticObjectId) -> EnrichmentJob:
    job = await EnrichmentJob.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
