"""
FastAPI entrypoint — Phase 6: admin endpoints, and Celery/Redis as a real
(optional) alternative to the in-process job queue, on top of Phases 1-5.

Run with:
    uvicorn app.main:app --reload --port 8000

New this phase:
  - /api/admin/* — user management, cross-user conversion visibility,
    stats (all require an admin account — see app/scripts/make_admin.py
    to create your first one)
  - JOB_QUEUE_TYPE=celery is now a real, working option (see
    app/workers/celery_app.py, celery_tasks.py) — still defaults to
    "inprocess" so nothing changes unless you opt in
  - Migrated off the deprecated @app.on_event("startup") to FastAPI's
    current lifespan pattern
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exception_handlers import unhandled_exception_handler
from app.api import auth, users, files, conversions, admin, merge, custom_converter
from app.workers.cleanup_worker import start_cleanup_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "PDFKit API starting up (env=%s, db=%s, storage=%s, jobs=%s, retention=%dd)",
        settings.ENVIRONMENT,
        settings.DATABASE_URL,
        settings.STORAGE_TYPE,
        settings.JOB_QUEUE_TYPE,
        settings.FILE_RETENTION_DAYS,
    )
    # Runs regardless of JOB_QUEUE_TYPE — file/token retention cleanup is
    # unrelated to which mechanism processes conversion jobs.
    start_cleanup_scheduler()
    yield
    logger.info("PDFKit API shutting down")


app = FastAPI(title="Extractor", version="0.6.0-phase6", lifespan=lifespan)

app.add_exception_handler(Exception, unhandled_exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(files.router)
app.include_router(conversions.router)
app.include_router(admin.router)
app.include_router(merge.router)
app.include_router(custom_converter.router)


@app.get("/health")
def health():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
