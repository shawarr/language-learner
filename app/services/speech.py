"""Audio uploads → raw transcript, shared by the talk turn, placement and checkpoints.

The transcript is returned exactly as the engine produced it. Nothing here cleans it up: the raw
text is what the learner must see (docs/STT-FINDINGS.md). The talk turn also keeps the bytes
(`read_upload`) so the analyzer can later hear the recording — Whisper silently repairs unstressed
endings, and only the audio has the truth.
"""
from __future__ import annotations

from fastapi import HTTPException, UploadFile

from ..providers.stt import Transcript, normalize_mime, stt

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # Groq free-tier upload cap


async def read_upload(file: UploadFile) -> tuple[bytes, str, str]:
    """(bytes, canonical mime, extension). Raises 400/413 for an unusable upload."""
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="The recording was empty. Hold the button a little longer.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Recording too large (25 MB max). Try a shorter one.")
    ext, mime = normalize_mime(file.content_type, file.filename)
    return audio, mime, ext


async def transcribe_audio(audio: bytes, mime: str | None, filename: str | None = None) -> Transcript:
    """Raw transcript or a 400 when nothing was heard; ProviderError bubbles up as a retryable 503."""
    t = await stt.transcribe(audio, mime, filename)
    if not t.text.strip():
        raise HTTPException(status_code=400,
                            detail="Nothing was heard in the recording. Check the microphone and try again.")
    return t


async def transcribe_upload(file: UploadFile) -> Transcript:
    audio, mime, ext = await read_upload(file)
    return await transcribe_audio(audio, mime, f"clip.{ext}")
