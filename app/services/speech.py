"""Audio uploads → raw transcript, shared by the talk turn, placement and checkpoints.

The transcript is returned exactly as the engine produced it. Nothing here cleans it up: the raw
text is what the learner must see (docs/STT-FINDINGS.md).
"""
from __future__ import annotations

from fastapi import HTTPException, UploadFile

from ..providers.stt import Transcript, stt

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # Groq free-tier upload cap


async def transcribe_upload(file: UploadFile) -> Transcript:
    """Raises 400/413 for an unusable upload; ProviderError bubbles up as a retryable 503."""
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="The recording was empty. Hold the button a little longer.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Recording too large (25 MB max). Try a shorter one.")
    t = await stt.transcribe(audio, file.content_type, file.filename)
    if not t.text.strip():
        raise HTTPException(status_code=400,
                            detail="Nothing was heard in the recording. Check the microphone and try again.")
    return t
