"""Test fixtures. Every test runs against a fresh temp DB and the offline `fake` LLM provider,
so the suite never touches the network and needs no API keys.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Environment must be set before app.config is imported.
_TMP = tempfile.mkdtemp(prefix="tutor-test-")
os.environ.update(
    DATA_DIR=_TMP,
    APP_PASSWORD="test-password",
    SESSION_SECRET="test-secret",
    COOKIE_SECURE="0",
    LLM_PRIMARY="fake:fake",
    LLM_FALLBACK="",
    LLM_FAST="",
    GEMINI_API_KEY="",
    GROQ_API_KEY="",
)


@pytest.fixture
def client():
    """A logged-out TestClient with a per-test database file."""
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app

    dbfile = Path(_TMP) / f"test-{os.getpid()}-{id(app)}.db"
    settings.db_path = dbfile
    for suffix in ("", "-wal", "-shm"):
        Path(str(dbfile) + suffix).unlink(missing_ok=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client(client):
    """A TestClient that has already logged in (session cookie set)."""
    r = client.post("/api/auth/login", json={"password": "test-password"})
    assert r.status_code == 200, r.text
    return client


@pytest.fixture(autouse=True)
def reset_fake():
    from app.providers.fake import FakeProvider

    FakeProvider.canned = None
    FakeProvider.calls = []
    yield
    FakeProvider.canned = None


@pytest.fixture
async def fresh_db():
    """A connected `app.db.db` on a brand-new file, for service-level async tests (no HTTP)."""
    import uuid

    from app.config import settings
    from app.db import db

    settings.db_path = Path(_TMP) / f"svc-{uuid.uuid4().hex}.db"
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
