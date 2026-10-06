"""
POST   /api/files/upload   (multipart, supports multiple files)
GET    /api/files
GET    /api/files/{file_id}
DELETE /api/files/{file_id}

Every route here scopes to the current user's own files — a user ID
is never taken from the request, only from the verified JWT.
"""

import logging
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, UploadFile, File as FastAPIFile, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.models.file import File as FileModel
from app.schemas.file import FileOut
from app.services.storage_service import storage_service
from app.utils.filenames import sanitize_display_name, generate_storage_key
from app.utils.file_validation import get_pdf_page_count, validate_pdf_upload, FileValidationError

router = APIRouter(prefix="/api/files", tags=["files"])
logger = logging.getLogger("files_api")


@router.post("/upload", response_model=List[FileOut], status_code=201)
async def upload_files(
    files: List[UploadFile] = FastAPIFile(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail="Please select at least one PDF.")

    saved_records = []
    errors = []

    for upload in files:
        file_bytes = await upload.read()

        try:
            validate_pdf_upload(upload, file_bytes)
            page_count = get_pdf_page_count(file_bytes)
        except FileValidationError as e:
            errors.append(f"{upload.filename}: {e}")
            continue

        storage_key = generate_storage_key(current_user.id, "uploads", "pdf")

        import io
        storage_service.save_file(storage_key, io.BytesIO(file_bytes))

        file_record = FileModel(
            user_id=current_user.id,
            original_filename=sanitize_display_name(upload.filename),
            storage_key=storage_key,
            file_size=len(file_bytes),
            mime_type="application/pdf",
            page_count=page_count,
        )
        db.add(file_record)
        db.commit()
        db.refresh(file_record)
        saved_records.append(file_record)

        logger.info("File uploaded: file_id=%s user_id=%s", file_record.id, current_user.id)

    if not saved_records and errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    return saved_records


@router.get("", response_model=List[FileOut])
def list_files(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(FileModel)
        .filter(FileModel.user_id == current_user.id, FileModel.deleted_at.is_(None))
        .order_by(FileModel.uploaded_at.desc())
        .all()
    )


@router.get("/{file_id}", response_model=FileOut)
def get_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    file_record = _get_owned_file_or_404(db, file_id, current_user.id)
    return file_record


@router.delete("/{file_id}", status_code=204)
def delete_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    file_record = _get_owned_file_or_404(db, file_id, current_user.id)

    storage_service.delete_file(file_record.storage_key)
    file_record.deleted_at = datetime.now(timezone.utc)
    db.commit()

    logger.info("File deleted: file_id=%s user_id=%s", file_id, current_user.id)
    return None


def _get_owned_file_or_404(db: Session, file_id: int, user_id: int) -> FileModel:
    file_record = (
        db.query(FileModel)
        .filter(FileModel.id == file_id, FileModel.user_id == user_id, FileModel.deleted_at.is_(None))
        .first()
    )
    if not file_record:
        # Deliberately the same 404 whether the file doesn't exist or
        # belongs to someone else — never reveal which.
        raise HTTPException(status_code=404, detail="File not found.")
    return file_record
