"""/api/checkpoint — the end-of-unit checkpoint: offered when available, graded on submit (docs/API.md)."""
from fastapi import APIRouter, Depends, File, Form, UploadFile

from .. import auth
from ..services import checkpoint, speech

router = APIRouter(prefix="/checkpoint", dependencies=[Depends(auth.require_auth)], tags=["checkpoint"])


@router.get("/current")
async def current():
    return await checkpoint.current()


@router.post("/{checkpoint_id}/submit")
async def submit(checkpoint_id: int, writing_text: str = Form(""), speaking_text: str = Form(""),
                 file: UploadFile | None = File(None)):
    """Multipart: writing_text plus either the speaking recording as `file` or its text as `speaking_text`."""
    provider = None
    if file is not None and file.filename:
        t = await speech.transcribe_upload(file)
        speaking_text, provider = t.text, t.provider
    return await checkpoint.submit(checkpoint_id, speaking_text, writing_text, stt_provider=provider)
