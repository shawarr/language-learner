"""/api/talk — the conversation (docs/API.md "Talk"). Thin: parse, call the tutor service, return."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from .. import auth
from ..services import speech, tutor

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
    """One path for both shapes, so the client has one call: JSON {"session_id", "text"} for a typed
    turn, multipart `session_id` + `file` for a recording. FastAPI cannot mix Body and Form on one
    route, hence the manual parsing."""
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise HTTPException(status_code=422, detail="file is required")
        session_id = _session_id(form.get("session_id"))
        audio, mime, ext = await speech.read_upload(file)
        t = await speech.transcribe_audio(audio, mime, f"clip.{ext}")  # 400 on silence, before any row is written
        # The bytes ride along: the analyzer listens to them later, because the transcript alone
        # hides the endings he got wrong.
        return await tutor.take_turn(session_id, t.text, input_kind="voice", transcript_raw=t.text,
                                     stt_provider=t.provider, audio=audio, audio_mime=mime, audio_ext=ext)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail="send JSON {session_id, text} or multipart session_id + file")
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
