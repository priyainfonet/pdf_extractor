"""
Admin-only endpoints, all protected by require_admin (see app/core/deps.py)
— a 403 for any authenticated-but-non-admin user, a 401 for anyone not
authenticated at all.

GET   /api/admin/users
GET   /api/admin/users/{user_id}
PATCH /api/admin/users/{user_id}          (activate/deactivate, grant/revoke admin)
DELETE /api/admin/users/{user_id}
GET   /api/admin/conversions               (every user's jobs, not just your own)
GET   /api/admin/stats
"""

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.models.file import File as FileModel
from app.models.conversion import ConversionJob, JobStatus
from app.schemas.admin import AdminUserOut, AdminUserUpdateRequest, AdminConversionOut, AdminStatsOut
from app.services.storage_service import storage_service

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger("admin_api")


@router.get("/users", response_model=List[AdminUserOut])
def list_users(current_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(User).order_by(User.created_at.desc()).all()


@router.get("/users/{user_id}", response_model=AdminUserOut)
def get_user(user_id: int, current_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return user


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int,
    payload: AdminUserUpdateRequest,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if user.id == current_admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="You can't deactivate your own account.")
    if user.id == current_admin.id and payload.is_admin is False:
        raise HTTPException(status_code=400, detail="You can't remove your own admin access.")

    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin

    db.commit()
    db.refresh(user)
    logger.info("Admin %s updated user %s: %s", current_admin.id, user_id, payload.model_dump(exclude_none=True))
    return user


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: int, current_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="You can't delete your own account.")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Clean up their files/outputs from storage before the cascading DB
    # delete removes the rows (the FK relationships have ondelete=CASCADE,
    # but that only cleans up database rows, not files on disk).
    files = db.query(FileModel).filter(FileModel.user_id == user_id).all()
    for f in files:
        storage_service.delete_file(f.storage_key)

    jobs = db.query(ConversionJob).filter(ConversionJob.user_id == user_id).all()
    for job in jobs:
        if job.output_storage_key:
            storage_service.delete_file(job.output_storage_key)

    db.delete(user)
    db.commit()
    logger.info("Admin %s deleted user %s", current_admin.id, user_id)
    return None


@router.get("/conversions", response_model=List[AdminConversionOut])
def list_all_conversions(
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    limit: int = 100,
):
    jobs = (
        db.query(ConversionJob, User.email)
        .join(User, ConversionJob.user_id == User.id)
        .order_by(ConversionJob.created_at.desc())
        .limit(min(limit, 500))
        .all()
    )
    return [
        AdminConversionOut(
            id=job.id,
            user_id=job.user_id,
            user_email=email,
            output_format=job.output_format,
            status=job.status.value if hasattr(job.status, "value") else job.status,
            output_filename=job.output_filename,
            error_message=job.error_message,
            created_at=job.created_at,
            completed_at=job.completed_at,
        )
        for job, email in jobs
    ]


@router.get("/stats", response_model=AdminStatsOut)
def get_stats(current_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    total_users = db.query(User).count()
    active_users = db.query(User).filter(User.is_active.is_(True)).count()
    total_files = db.query(FileModel).filter(FileModel.deleted_at.is_(None)).count()
    total_conversions = db.query(ConversionJob).count()
    completed = db.query(ConversionJob).filter(ConversionJob.status == JobStatus.COMPLETED).count()
    failed = db.query(ConversionJob).filter(ConversionJob.status == JobStatus.FAILED).count()
    pending = db.query(ConversionJob).filter(
        ConversionJob.status.in_([JobStatus.PENDING, JobStatus.PROCESSING])
    ).count()

    return AdminStatsOut(
        total_users=total_users,
        active_users=active_users,
        total_files=total_files,
        total_conversions=total_conversions,
        conversions_completed=completed,
        conversions_failed=failed,
        conversions_pending_or_processing=pending,
    )
