"""Two learners, one deployment: accounts, hashed passwords, per-user cookies, nothing leaking."""
from __future__ import annotations

import pytest

from app import users
from tests.conftest import as_user, login


def test_password_hashing_round_trip():
    h = users.hash_password("Correct Horse")
    assert h.startswith("pbkdf2_sha256$") and "Correct Horse" not in h
    assert users.verify_password("Correct Horse", h)
    assert not users.verify_password("correct horse", h)
    assert not users.verify_password("x", None) and not users.verify_password("x", "garbage")
    assert users.hash_password("same") != users.hash_password("same"), "a fresh salt every time"


async def test_seed_creates_both_accounts_and_profiles(fresh_db):
    rows = await fresh_db.fetchall("SELECT username, name, gender, password_hash FROM users ORDER BY id")
    assert [(r["username"], r["name"], r["gender"]) for r in rows] == [("ahmad", "Ahmad", "m"), ("maryan", "Maryan", "f")]
    assert all(r["password_hash"] and "password" not in r["password_hash"] for r in rows)
    profiles = await fresh_db.fetchall("SELECT user_id, name, level FROM profile ORDER BY user_id")
    assert [(p["name"], p["level"]) for p in profiles] == [("Ahmad", "A1.1"), ("Maryan", "A1.1")]
    await users.seed()   # idempotent
    assert len(await fresh_db.fetchall("SELECT * FROM users")) == 2
    assert len(await fresh_db.fetchall("SELECT * FROM profile")) == 2


async def test_seed_rotates_a_changed_password(fresh_db, monkeypatch):
    monkeypatch.setenv("USER_MARYAN_PASSWORD", "new-one")
    await users.seed()
    assert await users.authenticate("maryan", "new-one")
    assert not await users.authenticate("maryan", "maryan-password")
    assert not await users.authenticate("ahmad", "new-one")


async def test_app_password_only_opens_an_account_without_a_hash(fresh_db, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "app_password", "legacy")
    assert not await users.authenticate("ahmad", "legacy"), "a hashed account ignores the legacy password"
    await fresh_db.execute("UPDATE users SET password_hash=NULL WHERE username='maryan'")
    assert await users.authenticate("maryan", "legacy")


async def test_current_user_context(fresh_db):
    assert users.current()["username"] == "ahmad"
    await as_user("maryan")
    assert users.user_id() == 2
    users.set_current(None)
    with pytest.raises(RuntimeError):
        users.user_id()


def test_public_user_list_has_no_secrets(client):
    r = client.get("/api/auth/users")
    assert r.status_code == 200
    body = r.json()
    assert [u["username"] for u in body["users"]] == ["ahmad", "maryan"]
    assert "password" not in r.text and "hash" not in r.text
    assert body["avatars"] == users.AVATARS


def test_each_login_is_its_own_cookie(client):
    me = login(client, "maryan")
    assert me["username"] == "maryan" and me["gender"] == "f"
    r = client.get("/api/auth/me")
    assert r.json()["user"]["username"] == "maryan"
    login(client, "ahmad")
    assert client.get("/api/auth/me").json()["user"]["username"] == "ahmad"


def test_avatar_choice(auth_client):
    r = auth_client.post("/api/auth/avatar", json={"avatar": "katze-3"})
    assert r.status_code == 200 and r.json()["user"]["avatar"] == "katze-3"
    assert auth_client.post("/api/auth/avatar", json={"avatar": "dog-1"}).status_code == 422
    assert auth_client.get("/api/auth/me").json()["user"]["avatar"] == "katze-3"
