"""
Shared pytest fixtures.

IMPORTANT: environment variables are set BEFORE importing anything from
`app`, because app.core.config.Settings reads os.environ at import time.
This is what makes the test suite use a throwaway SQLite file and a
temp storage directory instead of touching your real dev database.
"""

import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TEST_DIR = tempfile.mkdtemp(prefix="pdfkit_test_")
_TEST_DB_PATH = os.path.join(_TEST_DIR, "test.db")
_TEST_STORAGE_PATH = os.path.join(_TEST_DIR, "storage")

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB_PATH}"
os.environ["STORAGE_PATH"] = _TEST_STORAGE_PATH
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["JOB_QUEUE_TYPE"] = "inprocess"
os.environ["SMTP_HOST"] = ""  # forces the log-only email fallback
os.environ["CORS_ORIGINS"] = "*"
os.environ["ENVIRONMENT"] = "test"
# Large enough that the cleanup worker's startup run never deletes
# anything mid-test-suite.
os.environ["FILE_RETENTION_DAYS"] = "365"
os.environ["CLEANUP_INTERVAL_HOURS"] = "999999"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import SessionLocal, Base, engine
from app.utils import rate_limiter

# app.main no longer auto-creates tables (Alembic is the source of truth
# for real deployments — see the note in main.py's git history / README).
# Tests still want a from-scratch schema without needing the Alembic CLI,
# so create it directly here, once, against the throwaway test database.
Base.metadata.create_all(bind=engine)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
    shutil.rmtree(_TEST_DIR, ignore_errors=True)


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Without this, the in-memory rate limiter's state would persist
    across every test in the session (it's a module-level dict), and
    tests that hit login/register/forgot-password repeatedly would start
    tripping 429s that have nothing to do with what that specific test
    is checking. Rate limiting has its own dedicated test that
    deliberately exceeds the limit — everything else gets a clean slate."""
    rate_limiter._hits.clear()
    yield
