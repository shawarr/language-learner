"""Infrastructure endpoints for audio: TTS playback and standalone transcription (incl. the pitfall lab).

The chat turn endpoint (built by the app layer) calls `stt.transcribe` itself and returns the raw
transcript; the frontend then fetches audio from GET /api/tts?text=...&speed=..., cached on disk.
"""
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse

from .. import auth
from ..providers import tts
from ..providers.stt import stt

router = APIRouter(dependencies=[Depends(auth.require_auth)], tags=["voice"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # Groq free-tier upload limit


@router.get("/tts")
async def speak(text: str = Query(min_length=1, max_length=1500),
                speed: str = Query("normal", pattern="^(normal|slow)$")):
    path = await tts.synthesize(text, speed)
    return FileResponse(path, media_type=tts.media_type(path),
                        headers={"Cache-Control": "private, max-age=31536000"})


@router.post("/voice/transcribe")
async def transcribe(file: UploadFile = File(...), compare: bool = Form(False)):
    """Returns {"text", "provider", "model"} or, with compare=true, {"groq": ..., "gemini": ...}."""
    audio = await file.read()
    if len(audio) > MAX_AUDIO_BYTES:
        return {"detail": "recording too large (25 MB max)", "retryable": False}
    if compare:
        return await stt.transcribe_compare(audio, file.content_type, file.filename)
    t = await stt.transcribe(audio, file.content_type, file.filename)
    return {"text": t.text, "provider": t.provider, "model": t.model}
