"""
Periodic cleanup, running on a background thread inside the same process
(same "in-process, no external scheduler" approach as the conversion
worker — see app/workers/conversion_worker.py for the same tradeoff
discussion). Runs once at startup, then every CLEANUP_INTERVAL_HOURS.

What it does each run:
  1. Deletes conversion jobs (and their output files) older than
     FILE_RETENTION_DAYS.
  2. Deletes uploaded files (soft-deleted via DELETE /api/files/{id}, or
     just old) older than FILE_RETENTION_DAYS, removing them from storage
     and from the DB.
  3. Prunes revoked_tokens rows whose underlying JWT has already expired
     naturally — keeping that table from growing forever, since an
     expired token can never be presented again regardless of whether
     it's still listed as "revoked".

To move this to a real scheduler (cron, Celery beat) later: keep
run_cleanup_once() exactly as is and just call it from wherever the
scheduler triggers, instead of the threading loop below.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.conversion import ConversionJob, JobStatus
from app.models.file import File as FileModel
from app.models.revoked_token import RevokedToken
from app.services.storage_service import storage_service

logger = logging.getLogger("cleanup_worker")


def run_cleanup_once() -> None:
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=settings.FILE_RETENTION_DAYS)

        old_jobs = (
            db.query(ConversionJob)
            .filter(
                ConversionJob.created_at < cutoff,
                ConversionJob.status.in_([JobStatus.COMPLETED, JobStatus.FAILED]),
            )
            .all()
        )
        for job in old_jobs:
            if job.output_storage_key:
                storage_service.delete_file(job.output_storage_key)
            db.delete(job)
        if old_jobs:
            logger.info("Cleanup: removed %d conversion job(s) older than %d days", len(old_jobs), settings.FILE_RETENTION_DAYS)

        old_files = (
            db.query(FileModel)
            .filter(
                (FileModel.deleted_at.isnot(None)) | (FileModel.uploaded_at < cutoff)
            )
            .all()
        )
        for f in old_files:
            storage_service.delete_file(f.storage_key)
            db.delete(f)
        if old_files:
            logger.info("Cleanup: removed %d file(s) (soft-deleted or older than %d days)", len(old_files), settings.FILE_RETENTION_DAYS)

        now = datetime.now(timezone.utc)
        expired_tokens = db.query(RevokedToken).filter(RevokedToken.expires_at < now).all()
        for t in expired_tokens:
            db.delete(t)
        if expired_tokens:
            logger.info("Cleanup: pruned %d expired revoked-token record(s)", len(expired_tokens))

        db.commit()
    except Exception:
        logger.exception("Cleanup run failed")
        db.rollback()
    finally:
        db.close()


def _cleanup_loop():
    while True:
        run_cleanup_once()
        time.sleep(settings.CLEANUP_INTERVAL_HOURS * 3600)


def start_cleanup_scheduler() -> None:
    thread = threading.Thread(target=_cleanup_loop, daemon=True, name="cleanup-scheduler")
    thread.start()
    logger.info(
        "Cleanup scheduler started (retention=%d days, interval=%d hours)",
        settings.FILE_RETENTION_DAYS,
        settings.CLEANUP_INTERVAL_HOURS,
    )
