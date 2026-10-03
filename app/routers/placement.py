"""/api/placement — the first-launch placement flow (docs/API.md "Placement")."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from starlette.datastructures import UploadFile  # what request.form() yields; fastapi.UploadFile subclasses it

from .. import auth
from ..services import placement, speech

router = APIRouter(prefix="/placement", dependencies=[Depends(auth.require_auth)], tags=["placement"])


class FinishBody(BaseModel):
    session_id: int


def _int(value: object, name: str) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{name} must be a number.")


@router.post("/start")
async def start():
    return await placement.start()


@router.post("/answer")
async def answer(request: Request):
    """JSON {session_id, task_id, text} or multipart session_id, task_id, file (audio → raw transcript)."""
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        file = form.get("file")
        if not isinstance(file, UploadFile):
            raise HTTPException(status_code=400, detail="Attach the recording as 'file'.")
        session_id = _int(form.get("session_id"), "session_id")
        task_id = str(form.get("task_id") or "")
        t = await speech.transcribe_upload(file)
        return await placement.answer(session_id, task_id, t.text, input_kind="voice", stt_provider=t.provider)
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Send JSON or multipart form data.")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Send JSON or multipart form data.")
    session_id = _int(body.get("session_id"), "session_id")
    return await placement.answer(session_id, str(body.get("task_id") or ""), str(body.get("text") or ""))


@router.post("/finish")
async def finish(body: FinishBody):
    return await placement.finish(body.session_id)


@router.post("/skip")
async def skip():
    return await placement.skip()


@router.get("/status")
async def status():
    return await placement.status()
