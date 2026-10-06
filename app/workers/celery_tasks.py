"""
The actual Celery task. Deliberately reuses _process_conversion_job from
conversion_worker.py rather than duplicating the conversion logic — the
only difference between "inprocess" and "celery" mode is WHAT calls that
function (a thread pool vs. a Celery worker process), not the logic
itself.
"""

import logging

from app.workers.celery_app import celery_app
from app.workers.conversion_worker import _process_conversion_job

logger = logging.getLogger("celery_tasks")


@celery_app.task(name="process_conversion_job", bind=True, max_retries=0)
def process_conversion_job_task(self, job_id: int) -> None:
    logger.info("Celery worker picked up conversion job_id=%s", job_id)
    _process_conversion_job(job_id)
