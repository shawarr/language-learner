"""Speech to text. Two engines, both returning the raw transcript *with* the learner's mistakes:

- groq: whisper-large-v3, language="de", no prompt (a prompt in clean German nudges it to "fix" grammar)
- gemini: audio sent inline to a Gemini model with a strict verbatim-transcription instruction

STT_PROVIDER picks the primary; the other is the fallback. `transcribe_compare` runs both for the
pitfall test (scripts/stt_compare.py and the in-app lab).
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from .base import LLMRequest, Message, ProviderError

log = logging.getLogger(__name__)

# MediaRecorder mime -> (extension, mime to send). iOS Safari records audio/mp4 (AAC); Chrome audio/webm (Opus).
_FORMATS = {
    "audio/webm": ("webm", "audio/webm"),
    "audio/ogg": ("ogg", "audio/ogg"),
    "audio/mp4": ("m4a", "audio/mp4"),
    "audio/x-m4a": ("m4a", "audio/mp4"),
    "audio/m4a": ("m4a", "audio/mp4"),
    "audio/aac": ("aac", "audio/aac"),
    "audio/mpeg": ("mp3", "audio/mpeg"),
    "audio/mp3": ("mp3", "audio/mpeg"),
    "audio/wav": ("wav", "audio/wav"),
    "audio/x-wav": ("wav", "audio/wav"),
    "audio/flac": ("flac", "audio/flac"),
}

VERBATIM_PROMPT = (
    "You are a verbatim transcription engine for a German learner. Transcribe exactly what is said in German, "
    "word for word, INCLUDING every grammar mistake, wrong article, wrong word order, wrong ending, hesitation "
    "word (ähm, also) and English word the speaker uses. Do NOT correct, improve, translate or complete anything. "
    "Use normal German spelling and punctuation. If the audio has no speech, return an empty transcript."
)
VERBATIM_SCHEMA = {
    "type": "object",
    "properties": {"transcript": {"type": "string"}},
    "required": ["transcript"],
}


@dataclass
class Transcript:
    text: str
    provider: str
    model: str


def normalize_mime(mime: str | None, filename: str | None = None) -> tuple[str, str]:
    """Returns (extension, canonical mime)."""
    base = (mime or "").split(";")[0].strip().lower()
    if base in _FORMATS:
        return _FORMATS[base]
    ext = Path(filename or "").suffix.lstrip(".").lower()
    for e, m in _FORMATS.values():
        if ext == e:
            return e, m
    return "webm", "audio/webm"


async def _to_mp3(audio: bytes, ext: str) -> tuple[bytes, str, str] | None:
    """Re-encode with ffmpeg (16 kHz mono mp3) when available. Returns None if ffmpeg is missing or fails."""
    if not shutil.which("ffmpeg"):
        return None
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / f"in.{ext}", Path(d) / "out.mp3"
        src.write_bytes(audio)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "16000",
            "-b:a", "48k", str(dst))
        await proc.wait()
        if proc.returncode != 0 or not dst.exists():
            log.warning("ffmpeg failed for .%s input", ext)
            return None
        return dst.read_bytes(), "mp3", "audio/mpeg"


class STT:
    def __init__(self) -> None:
        from .llm import llm  # late import: llm.py owns the provider instances
        self._llm = llm

    async def _groq(self, audio: bytes, ext: str, mime: str) -> Transcript:
        text = await self._llm.groq.transcribe(settings.groq_stt_model, audio, f"audio.{ext}", mime,
                                               language="de", prompt=settings.whisper_prompt)
        return Transcript(text=text, provider="groq", model=settings.groq_stt_model)

    async def _gemini(self, audio: bytes, ext: str, mime: str) -> Transcript:
        # Gemini is happier with mp3/wav than with browser webm/mp4 containers; convert when we can.
        conv = await _to_mp3(audio, ext)
        if conv:
            audio, ext, mime = conv
        req = LLMRequest(system=VERBATIM_PROMPT, messages=[Message("user", "Transcribe this audio verbatim.")],
                         json_schema=VERBATIM_SCHEMA, temperature=0.0, max_tokens=512, audio=audio, audio_mime=mime)
        res = await self._llm.gemini.complete(settings.gemini_stt_model, req)
        from .llm import parse_json
        data = parse_json(res.text) or {}
        return Transcript(text=str(data.get("transcript", "")).strip(), provider="gemini", model=settings.gemini_stt_model)

    def _engines(self) -> list:
        order = [settings.stt_provider, "gemini" if settings.stt_provider == "groq" else "groq"]
        return [getattr(self, f"_{name}") for name in order]

    async def transcribe(self, audio: bytes, mime: str | None, filename: str | None = None) -> Transcript:
        """Primary engine, then the other one. Raises ProviderError if both fail (caller keeps the recording)."""
        if not audio:
            raise ProviderError("empty recording", retryable=False)
        ext, mime_c = normalize_mime(mime, filename)
        errors: list[str] = []
        for engine in self._engines():
            try:
                return await engine(audio, ext, mime_c)
            except ProviderError as e:
                log.warning("stt %s failed: %s", engine.__name__, e)
                errors.append(str(e))
        raise ProviderError("Transcription failed: " + " | ".join(errors))

    async def transcribe_compare(self, audio: bytes, mime: str | None, filename: str | None = None) -> dict[str, str]:
        """Run both engines; used by the pitfall test. Errors are returned as strings, never raised."""
        ext, mime_c = normalize_mime(mime, filename)
        out: dict[str, str] = {}
        for name in ("groq", "gemini"):
            try:
                out[name] = (await getattr(self, f"_{name}")(audio, ext, mime_c)).text
            except ProviderError as e:
                out[name] = f"ERROR: {e}"
        return out


stt = STT()
