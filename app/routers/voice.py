"""Infrastructure endpoints for audio: TTS playback and standalone transcription (incl. the pitfall lab).

The chat turn endpoint (built by the app layer) calls `stt.transcribe` itself and returns the raw
transcript; the frontend then fetches audio from GET /api/tts?text=...&speed=..., cached on disk.
"""
import json
import logging
import time

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse

from .. import auth
from ..config import settings
from ..providers import tts
from ..providers.stt import normalize_mime, stt

log = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(auth.require_auth)], tags=["voice"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # Groq free-tier upload limit


@router.get("/tts")
async def speak(text: str = Query(min_length=1, max_length=1500),
                speed: str = Query("normal", pattern="^(normal|slow)$")):
    path = await tts.synthesize(text, speed)
    return FileResponse(path, media_type=tts.media_type(path),
                        headers={"Cache-Control": "private, max-age=31536000"})


@router.post("/voice/transcribe")
async def transcribe(file: UploadFile = File(...), compare: bool = Form(False), said: str = Form("")):
    """Returns {"text", "provider", "model"} or, with compare=true, both engines side by side.

    `compare` is the transcription lab: it keeps the clip and both transcripts on disk so the
    pitfall test (docs/STT-FINDINGS.md) can be re-run against Ahmad's real voice from the phone,
    instead of recording voice memos and shuttling files to the server. `said` is what he meant to
    say, which is what makes the diff meaningful.
    """
    audio = await file.read()
    if len(audio) > MAX_AUDIO_BYTES:
        return {"detail": "recording too large (25 MB max)", "retryable": False}
    if not compare:
        t = await stt.transcribe(audio, file.content_type, file.filename)
        return {"text": t.text, "provider": t.provider, "model": t.model}

    results = await stt.transcribe_compare(audio, file.content_type, file.filename)
    ext, _ = normalize_mime(file.content_type, file.filename)
    stamp = f"{time.time():.0f}"
    lab = settings.data_dir / "stt-lab"
    try:
        lab.mkdir(parents=True, exist_ok=True)
        (lab / f"{stamp}.{ext}").write_bytes(audio)
        (lab / f"{stamp}.json").write_text(json.dumps(
            {"said": said.strip(), "mime": file.content_type, **results}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    except OSError as e:  # a full or unwritable volume must not lose the transcription itself
        log.warning("could not save stt-lab sample: %s", e)
    return {**results, "saved": stamp}
