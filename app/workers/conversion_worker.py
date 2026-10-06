"""
Background conversion processing.

JOB_QUEUE_TYPE=inprocess (current default): a local ThreadPoolExecutor.
No Redis needed, works out of the box. Fine for one dev server; not meant
for multiple server processes, since jobs only run in the process that
enqueued them.

To move to Celery later: implement a CeleryJobQueue with the same
enqueue_conversion_job(job_id) signature, register it in get_job_queue(),
and flip JOB_QUEUE_TYPE=celery in .env. Nothing that calls
enqueue_conversion_job() needs to change.
"""

import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.conversion import ConversionJob, JobStatus
from app.services.storage_service import storage_service
from app.services.excel_converter import convert_pdf_to_excel
from app.services.word_converter import convert_pdf_to_word
from app.services.powerpoint_converter import convert_pdf_to_ppt
from app.utils.filenames import generate_storage_key

logger = logging.getLogger("conversion_worker")

CONVERTERS = {
    "xlsx": convert_pdf_to_excel,
    "docx": convert_pdf_to_word,
    "pptx": convert_pdf_to_ppt,
}


class JobQueue(ABC):
    @abstractmethod
    def enqueue_conversion_job(self, job_id: int) -> None:
        ...


class InProcessJobQueue(JobQueue):
    def __init__(self, max_workers: int = 4):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="conversion")

    def enqueue_conversion_job(self, job_id: int) -> None:
        self._executor.submit(_process_conversion_job, job_id)


def _process_conversion_job(job_id: int) -> None:
    """Runs in a worker thread — opens its own DB session, since sessions
    aren't safe to share across threads."""
    db = SessionLocal()
    try:
        job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
        if not job:
            logger.error("Conversion job %s not found when worker picked it up", job_id)
            return

        job.status = JobStatus.PROCESSING
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        try:
            source_file = job.source_file
            if not source_file:
                raise ValueError("Source file no longer exists.")

            pdf_path = storage_service.get_file_path(source_file.storage_key)
            converter = CONVERTERS.get(job.output_format)
            if not converter:
                raise ValueError(f"Unsupported output format: {job.output_format}")

            output_key = generate_storage_key(job.user_id, "outputs", job.output_format)
            output_path = storage_service.get_file_path(output_key)

            converter(pdf_path, output_path)

            base_name = source_file.original_filename.rsplit(".", 1)[0]
            job.output_filename = f"{base_name}.{job.output_format}"
            job.output_storage_key = output_key
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            logger.info("Conversion job %s completed (user_id=%s)", job.id, job.user_id)

        except Exception as e:
            logger.exception("Conversion job %s failed", job_id)
            job.status = JobStatus.FAILED
            job.error_message = str(e)[:1000]
            job.completed_at = datetime.now(timezone.utc)

        db.commit()
    finally:
        db.close()


def get_job_queue() -> JobQueue:
    if settings.JOB_QUEUE_TYPE == "inprocess":
        return InProcessJobQueue()
    if settings.JOB_QUEUE_TYPE == "celery":
        return CeleryJobQueue()
    raise NotImplementedError(
        f"Job queue backend '{settings.JOB_QUEUE_TYPE}' isn't implemented yet. "
        "Valid values: 'inprocess', 'celery'."
    )


class CeleryJobQueue(JobQueue):
    """Sends the job to a real Celery worker via Redis instead of running
    it in this process. Requires JOB_QUEUE_TYPE=celery, a running Redis
    (REDIS_URL), and at least one `celery -A app.workers.celery_app
    worker` process actually running — see docker-compose.yml's `worker`
    service, or run that command yourself locally."""

    def enqueue_conversion_job(self, job_id: int) -> None:
        # Imported here (not at module level) so that importing this file
        # never requires Celery/Redis to be reachable unless you're
        # actually in celery mode — keeps `inprocess` mode fully
        # dependency-free at runtime.
        from app.workers.celery_tasks import process_conversion_job_task

        process_conversion_job_task.delay(job_id)


job_queue = get_job_queue()
