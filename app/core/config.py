"""
Central app configuration. Everything here is sourced from environment
variables (loaded from .env via python-dotenv), per the "never hard-code
secrets" requirement. See .env.example for the full list.
"""

import os
import secrets
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # --- Database -------------------------------------------------
    # SQLite for local dev by default — zero install required. Point this
    # at a postgresql:// URL later (after `pip install psycopg2-binary`)
    # and nothing else in the codebase needs to change; SQLAlchemy handles
    # the dialect switch transparently.
    DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./storage/app.db")

    # --- Auth -------------------------------------------------------
    SECRET_KEY: str = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    RESET_TOKEN_EXPIRE_MINUTES: int = int(os.environ.get("RESET_TOKEN_EXPIRE_MINUTES", "30"))
    ALGORITHM: str = "HS256"

    # --- Email (password reset) ---------------------------------------
    # Leave SMTP_HOST empty for local dev — reset emails get logged
    # instead of sent (see app/services/email_service.py).
    SMTP_HOST: str = os.environ.get("SMTP_HOST", "")
    SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME: str = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.environ.get("SMTP_FROM_EMAIL", "")
    SMTP_USE_TLS: bool = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"

    # Base URL of your FRONTEND (not this API) — used to build the link
    # inside password-reset emails, e.g. https://yourapp.com/html/reset-password.html
    FRONTEND_URL: str = os.environ.get("FRONTEND_URL", "http://127.0.0.1:5500/html/forgot-password.html")

    # --- Retention / cleanup -------------------------------------------
    FILE_RETENTION_DAYS: int = int(os.environ.get("FILE_RETENTION_DAYS", "30"))
    CLEANUP_INTERVAL_HOURS: int = int(os.environ.get("CLEANUP_INTERVAL_HOURS", "24"))

    # --- Storage ------------------------------------------------------
    # "local" writes to STORAGE_PATH on disk. Swap to "s3" later (Phase 2)
    # once StorageService grows an S3-backed implementation — nothing that
    # calls StorageService needs to change.
    STORAGE_TYPE: str = os.environ.get("STORAGE_TYPE", "local")
    STORAGE_PATH: str = os.environ.get("STORAGE_PATH", "./storage")

    S3_BUCKET: str = os.environ.get("S3_BUCKET", "")
    S3_ACCESS_KEY: str = os.environ.get("S3_ACCESS_KEY", "")
    S3_SECRET_KEY: str = os.environ.get("S3_SECRET_KEY", "")
    S3_REGION: str = os.environ.get("S3_REGION", "")

    # --- Background jobs ---------------------------------------------
    # "inprocess" runs conversions on a local thread pool — no Redis needed.
    # "celery" uses a real Celery worker + Redis broker (see
    # app/workers/celery_app.py) — set this once you're running the
    # docker-compose stack, or your own Redis + Celery worker locally.
    JOB_QUEUE_TYPE: str = os.environ.get("JOB_QUEUE_TYPE", "inprocess")
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # --- CORS ----------------------------------------------------------
    # Comma-separated list of allowed frontend origins. "*" for local dev.
    CORS_ORIGINS: list[str] = os.environ.get("CORS_ORIGINS", "*").split(",")

    # --- Misc ------------------------------------------------------------
    MAX_UPLOAD_SIZE_MB: int = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "25"))
    ENVIRONMENT: str = os.environ.get("ENVIRONMENT", "development")


settings = Settings()
