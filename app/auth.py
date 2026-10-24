"""Login -> signed, long-lived httpOnly cookie that names the user. Two accounts, no registration."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request, Response

from . import users
from .config import settings
from .db import db

COOKIE = "dt_session"
_secret: bytes | None = None


async def init_secret() -> None:
    """Use SESSION_SECRET if set, otherwise generate one once and keep it in the DB."""
    global _secret
    if settings.session_secret:
        _secret = settings.session_secret.encode()
        return
    stored = await db.kv_get("session_secret")
    if not stored:
        stored = secrets.token_hex(32)
        await db.kv_set("session_secret", stored)
    _secret = stored.encode()


def _sign(payload: str) -> str:
    assert _secret is not None, "init_secret() not called"
    return hmac.new(_secret, payload.encode(), hashlib.sha256).hexdigest()


def make_token(uid: int) -> str:
    exp = int(time.time()) + settings.session_days * 86400
    payload = f"{uid}.{exp}.{secrets.token_hex(8)}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str | None) -> int | None:
    """The user id the cookie names, or None when it is missing, forged or expired."""
    if not token or token.count(".") != 3:
        return None
    uid, exp, nonce, sig = token.split(".")
    payload = f"{uid}.{exp}.{nonce}"
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        return int(uid) if int(exp) > time.time() else None
    except ValueError:
        return None


def set_cookie(response: Response, uid: int) -> None:
    response.set_cookie(
        COOKIE,
        make_token(uid),
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


async def require_auth(request: Request) -> dict:
    """FastAPI dependency. Every /api route except login/health uses it. Sets the current user for
    the request (see app.users) and returns the row."""
    uid = verify_token(request.cookies.get(COOKIE))
    user = await users.get(uid) if uid is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    users.set_current(user)
    return user
