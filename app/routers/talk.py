"""/api/talk — the conversation (docs/API.md "Talk"). Thin: parse, call the tutor service, return."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from .. import auth
from ..services import tutor

router = APIRouter(prefix="/talk", dependencies=[Depends(auth.require_auth)], tags=["talk"])

MAX_TEXT_CHARS = 2000  # a typed turn is a few sentences; anything longer is a paste, not speech


class StartBody(BaseModel):
    scenario_id: str | None = None


def _session_id(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="session_id must be an integer") from None


@router.post("/session")
async def start_session(body: StartBody | None = None):
    return await tutor.start_session(scenario_id=body.scenario_id if body else None)


@router.post("/turn")
async def turn(request: Request):
    """JSON {"session_id", "text"}. Parsed by hand because the voice shape (V1) shares this path and
    FastAPI cannot mix Body and Form on one route."""
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="send JSON {session_id, text}")
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=422, detail="text is required")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(status_code=422, detail=f"text is too long ({MAX_TEXT_CHARS} characters max)")
    return await tutor.take_turn(_session_id(body.get("session_id")), text)


@router.post("/session/{session_id}/end")
async def end_session(session_id: int):
    return await tutor.end_session(session_id)


@router.get("/session/{session_id}")
async def get_session(session_id: int):
    found = await tutor.get_session(session_id)
    if not found:
        raise HTTPException(status_code=404, detail="session not found")
    return found


@router.get("/sessions")
async def recent_sessions(limit: int = Query(20, ge=1, le=100)):
    return {"sessions": await tutor.recent_sessions(limit)}
