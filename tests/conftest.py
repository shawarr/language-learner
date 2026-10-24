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
    USERS="ahmad,maryan",
    USER_AHMAD_PASSWORD="test-password",
    USER_MARYAN_PASSWORD="maryan-password",
    APP_PASSWORD="",
    SESSION_SECRET="test-secret",
    COOKIE_SECURE="0",
    LLM_PRIMARY="fake:fake",
    LLM_FALLBACK="",
    LLM_FAST="",
    LLM_QUALITY="",
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


PASSWORDS = {"ahmad": "test-password", "maryan": "maryan-password"}


def login(client, username="ahmad"):
    """Log the TestClient in as one of the two seeded learners."""
    r = client.post("/api/auth/login", json={"username": username, "password": PASSWORDS[username]})
    assert r.status_code == 200, r.text
    return r.json()["user"]


@pytest.fixture
def auth_client(client):
    """A TestClient logged in as Ahmad (session cookie set)."""
    login(client, "ahmad")
    return client


@pytest.fixture(autouse=True)
def offline_tts(request, monkeypatch):
    """The tutor pre-renders every reply's audio in the background; in tests that would reach for
    edge-tts on the network. A test about the pre-warm itself opts out with @pytest.mark.real_tts
    and patches the engine instead."""
    if request.node.get_closest_marker("real_tts"):
        return
    from app.services import tutor

    monkeypatch.setattr(tutor, "schedule_tts", lambda text: None)


@pytest.fixture(autouse=True)
def reset_fake():
    from app.providers.fake import FakeProvider

    FakeProvider.canned = None
    FakeProvider.calls = []
    yield
    FakeProvider.canned = None


@pytest.fixture
async def fresh_db():
    """A connected `app.db.db` on a brand-new file with both learners seeded, for service-level
    async tests (no HTTP). The current user is Ahmad; use `as_user("maryan")` to switch."""
    import uuid

    from app import users
    from app.config import settings
    from app.db import db

    settings.db_path = Path(_TMP) / f"svc-{uuid.uuid4().hex}.db"
    await db.connect()
    await users.seed()
    token = users.set_current(await users.get_by_username("ahmad"))
    try:
        yield db
    finally:
        users.reset_current(token)
        await db.close()


async def as_user(username: str) -> dict:
    """Switch the current user in a service-level test."""
    from app import users

    user = await users.get_by_username(username)
    assert user, username
    users.set_current(user)
    return user
