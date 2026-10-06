"""
Celery app instance. Only imported/used when JOB_QUEUE_TYPE=celery —
importing celery itself is harmless either way (it's in requirements.txt
unconditionally), but the worker process (`celery -A app.workers.celery_app
worker`) is only meant to be run when you're actually using this backend,
e.g. via docker-compose's `worker` service.
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "pdfkit",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Conversions are usually quick, but don't let a stuck one hold a
    # worker forever.
    task_time_limit=600,
    task_soft_time_limit=540,
)

# Registers the @celery_app.task-decorated function in celery_tasks.py
# with this app instance.
import app.workers.celery_tasks  # noqa: E402,F401
