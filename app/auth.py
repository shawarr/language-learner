"""Single-password login -> signed, long-lived httpOnly cookie. No accounts."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request, Response

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


def make_token() -> str:
    exp = int(time.time()) + settings.session_days * 86400
    payload = f"{exp}.{secrets.token_hex(8)}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: str | None) -> bool:
    if not token or token.count(".") != 2:
        return False
    exp, nonce, sig = token.split(".")
    payload = f"{exp}.{nonce}"
    if not hmac.compare_digest(sig, _sign(payload)):
        return False
    try:
        return int(exp) > time.time()
    except ValueError:
        return False


def check_password(password: str) -> bool:
    if not settings.app_password:
        return False
    return hmac.compare_digest(password.encode(), settings.app_password.encode())


def set_cookie(response: Response) -> None:
    response.set_cookie(
        COOKIE,
        make_token(),
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


async def require_auth(request: Request) -> None:
    """FastAPI dependency. Every /api route except login/health uses it."""
    if not verify_token(request.cookies.get(COOKIE)):
        raise HTTPException(status_code=401, detail="not authenticated")
