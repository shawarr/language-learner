"""Text to speech with on-disk caching.

Primary: edge-tts (Microsoft neural voices, free, no key). Fallback: Gemini TTS (PCM -> WAV).
Files land in DATA_DIR/audio/<sha1>.<ext>; the cache key covers provider, voice, speed and text,
so a "slow" replay is a separate file generated on first request.

`synthesize` owns the cache lookup: an engine is only ever called for a file that is missing.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import struct
from pathlib import Path

from ..config import settings
from .base import ProviderError

log = logging.getLogger(__name__)

SPEEDS = {"normal": settings.tts_rate_normal, "slow": settings.tts_rate_slow}


def _cache_path(text: str, speed: str, provider: str, voice: str, ext: str) -> Path:
    key = hashlib.sha1(f"{provider}|{voice}|{speed}|{text}".encode()).hexdigest()
    return settings.audio_dir / f"{key}.{ext}"


async def _edge(text: str, speed: str, voice: str, path: Path) -> None:
    import edge_tts  # imported lazily: keeps startup fast and the tests off the network

    tmp = path.with_suffix(".part")
    try:
        comm = edge_tts.Communicate(text, voice, rate=SPEEDS.get(speed, SPEEDS["normal"]))
        await asyncio.wait_for(comm.save(str(tmp)), timeout=30)
    except Exception as e:  # edge-tts raises its own exception zoo plus aiohttp errors
        tmp.unlink(missing_ok=True)
        raise ProviderError(f"edge-tts failed: {e}") from e
    if not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise ProviderError("edge-tts produced no audio")
    tmp.rename(path)  # atomic: a reader never sees a half-written file


def _pcm_to_wav(pcm: bytes, rate: int = 24000, channels: int = 1, width: int = 2) -> bytes:
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ", 16, 1, channels, rate,
                         rate * channels * width, channels * width, width * 8, b"data", len(pcm))
    return header + pcm


async def _gemini(text: str, speed: str, voice: str, path: Path) -> None:
    from .llm import llm

    # Gemini TTS has no rate control; the instruction is the only lever.
    prompt = text if speed == "normal" else f"Say this slowly and clearly, for a beginner: {text}"
    audio, mime = await llm.gemini.tts(settings.gemini_tts_model, prompt, voice)
    rate = 24000
    for part in mime.split(";"):
        if part.strip().startswith("rate="):
            rate = int(part.split("=", 1)[1])
    tmp = path.with_suffix(".part")
    tmp.write_bytes(audio if "wav" in mime else _pcm_to_wav(audio, rate))
    tmp.rename(path)


# provider -> (extension, voice setting, engine)
_ENGINES = {
    "edge": ("mp3", lambda: settings.tts_voice, _edge),
    "gemini": ("wav", lambda: settings.gemini_tts_voice, _gemini),
}


async def synthesize(text: str, speed: str = "normal") -> Path:
    """Returns the path of a cached audio file. Raises ProviderError when every engine fails."""
    text = " ".join(text.split())
    if not text:
        raise ProviderError("nothing to say", retryable=False)
    order = [settings.tts_provider] + [n for n in _ENGINES if n != settings.tts_provider]
    errors: list[str] = []
    for name in order:
        ext, voice_of, engine = _ENGINES[name]
        voice = voice_of()
        path = _cache_path(text, speed, name, voice, ext)
        if path.exists():
            return path
        try:
            await engine(text, speed, voice, path)
            return path
        except ProviderError as e:
            log.warning("tts %s failed: %s", name, e)
            errors.append(str(e))
    raise ProviderError("Speech synthesis failed: " + " | ".join(errors))


def media_type(path: Path) -> str:
    return "audio/mpeg" if path.suffix == ".mp3" else "audio/wav"
