"""
POST   /api/conversions                 -> creates a job, enqueues it, returns immediately
GET    /api/conversions                 -> current user's conversion history
GET    /api/conversions/{job_id}        -> poll a single job's status
GET    /api/conversions/{job_id}/download
DELETE /api/conversions/{job_id}

Ownership is always checked against the JWT-verified user, never a value
from the request.
"""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.file import File as FileModel
from app.models.conversion import ConversionJob, JobStatus
from app.schemas.conversion import ConversionCreateRequest, ConversionJobOut
from app.services.storage_service import storage_service
from app.workers.conversion_worker import job_queue

router = APIRouter(prefix="/api/conversions", tags=["conversions"])
logger = logging.getLogger("conversions_api")

MEDIA_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


@router.post("", response_model=ConversionJobOut, status_code=201)
def create_conversion(
    payload: ConversionCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source_file = (
        db.query(FileModel)
        .filter(
            FileModel.id == payload.file_id,
            FileModel.user_id == current_user.id,
            FileModel.deleted_at.is_(None),
        )
        .first()
    )
    if not source_file:
        raise HTTPException(status_code=404, detail="File not found.")

    job = ConversionJob(
        user_id=current_user.id,
        file_id=source_file.id,
        input_format="pdf",
        output_format=payload.output_format,
        page_count=source_file.page_count,
        status=JobStatus.PENDING,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    job_queue.enqueue_conversion_job(job.id)
    logger.info("Conversion job created: job_id=%s user_id=%s format=%s", job.id, current_user.id, payload.output_format)

    return job


@router.get("", response_model=List[ConversionJobOut])
def list_conversions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(ConversionJob)
        .filter(ConversionJob.user_id == current_user.id)
        .order_by(ConversionJob.created_at.desc())
        .all()
    )


@router.get("/{job_id}", response_model=ConversionJobOut)
def get_conversion(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_owned_job_or_404(db, job_id, current_user.id)


@router.get("/{job_id}/download")
def download_conversion(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_job_or_404(db, job_id, current_user.id)

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=409, detail=f"Conversion is not ready yet (status: {job.status.value}).")

    if not job.output_storage_key or not storage_service.file_exists(job.output_storage_key):
        raise HTTPException(status_code=404, detail="Output file not found. It may have been cleaned up.")

    path = storage_service.get_file_path(job.output_storage_key)
    media_type = MEDIA_TYPES.get(job.output_format, "application/octet-stream")

    return FileResponse(path, media_type=media_type, filename=job.output_filename or f"converted.{job.output_format}")


@router.delete("/{job_id}", status_code=204)
def delete_conversion(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = _get_owned_job_or_404(db, job_id, current_user.id)

    if job.output_storage_key:
        storage_service.delete_file(job.output_storage_key)

    db.delete(job)
    db.commit()

    logger.info("Conversion job deleted: job_id=%s user_id=%s", job_id, current_user.id)
    return None


def _get_owned_job_or_404(db: Session, job_id: int, user_id: int) -> ConversionJob:
    job = (
        db.query(ConversionJob)
        .filter(ConversionJob.id == job_id, ConversionJob.user_id == user_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Conversion job not found.")
    return job
