"""Who is using the app right now, and how they prove it.

Two learners share one deployment, so every table carries a `user_id` and every service reads the
current one from here instead of threading it through each signature:

    from app.users import user_id
    rows = await db.fetchall("SELECT * FROM vocab WHERE user_id=?", (user_id(),))

`auth.require_auth` sets the current user for the request; `asyncio.create_task` copies the
context, so background work (the analyzer, TTS pre-warm) stays attributed to the right person.

Accounts are seeded from configuration: `USERS` lists the usernames, `app/curriculum/personas.json`
holds each one's name, gender and the paragraph the tutor is told about them, and the password
comes from `USER_<USERNAME>_PASSWORD` in the environment — hashed with PBKDF2 before it touches the
database, never stored or committed in clear.
"""
from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import logging
import os
import secrets
import time

from .config import settings
from .db import DEFAULT_SKILLS, db

log = logging.getLogger(__name__)

PUBLIC_FIELDS = ("id", "username", "name", "gender", "avatar")
AVATARS = [f"katze-{i}" for i in range(1, 9)]   # the mascot's variants, drawn by the frontend
_HASH_ITERATIONS = 300_000

_current: contextvars.ContextVar[dict | None] = contextvars.ContextVar("current_user", default=None)


# -- the current user -----------------------------------------------------------
def set_current(user: dict | None) -> contextvars.Token:
    return _current.set(user)


def reset_current(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> dict:
    user = _current.get()
    if user is None:
        raise RuntimeError("no current user: this code must run inside an authenticated request or a test that set one")
    return user


def user_id() -> int:
    return int(current()["id"])


def public(user: dict) -> dict:
    return {k: user[k] for k in PUBLIC_FIELDS}


# -- passwords ------------------------------------------------------------------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _HASH_ITERATIONS).hex()
    return f"pbkdf2_sha256${_HASH_ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
    except ValueError:
        return False
    return hmac.compare_digest(calc, digest)


# -- accounts -------------------------------------------------------------------
def personas() -> dict[str, dict]:
    path = settings.base_dir / "curriculum" / "personas.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def configured_usernames() -> list[str]:
    return [u.strip().lower() for u in settings.users.split(",") if u.strip()]


def password_from_env(username: str) -> str:
    return os.environ.get(f"USER_{username.upper()}_PASSWORD", "").strip()


async def seed() -> None:
    """Create or refresh the configured accounts and their profile rows. Safe to run on every boot:
    a changed USER_*_PASSWORD in .env rotates the hash, nothing else about the learner is touched."""
    people = personas()
    now = time.time()
    for username in configured_usernames():
        p = people.get(username, {})
        name = p.get("name") or username.capitalize()
        gender = p.get("gender") or "x"
        about = p.get("about") or ""
        row = await db.fetchone("SELECT * FROM users WHERE username=?", (username,))
        if row is None:
            await db.execute(
                "INSERT INTO users (username, name, gender, about, avatar, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (username, name, gender, about, AVATARS[0], now))
            row = await db.fetchone("SELECT * FROM users WHERE username=?", (username,))
        else:
            await db.execute("UPDATE users SET name=?, gender=?, about=? WHERE id=?", (name, gender, about, row["id"]))
        password = password_from_env(username)
        if password and not verify_password(password, row["password_hash"]):
            await db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), row["id"]))
        elif not password and not row["password_hash"]:
            log.error("user %r has no password: set USER_%s_PASSWORD in .env", username, username.upper())
        await db.execute(
            "INSERT OR IGNORE INTO profile (user_id, name, skills, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (row["id"], name, json.dumps(DEFAULT_SKILLS), now, now))


async def get(uid: int) -> dict | None:
    return await db.fetchone("SELECT * FROM users WHERE id=?", (uid,))


async def get_by_username(username: str) -> dict | None:
    return await db.fetchone("SELECT * FROM users WHERE username=?", ((username or "").strip().lower(),))


async def list_public() -> list[dict]:
    rows = await db.fetchall("SELECT * FROM users ORDER BY id")
    return [public(r) for r in rows]


async def set_avatar(uid: int, avatar: str) -> dict:
    if avatar not in AVATARS:
        raise ValueError("unknown avatar")
    await db.execute("UPDATE users SET avatar=? WHERE id=?", (avatar, uid))
    return public(await get(uid))


async def authenticate(username: str, password: str) -> dict | None:
    """The user row on success, else None. APP_PASSWORD still opens an account that has no hash
    yet, so a deploy before the new .env lines are in place does not lock anyone out."""
    user = await get_by_username(username)
    if not user:
        return None
    if verify_password(password, user["password_hash"]):
        return user
    if not user["password_hash"] and settings.app_password and hmac.compare_digest(password.encode(), settings.app_password.encode()):
        return user
    return None
