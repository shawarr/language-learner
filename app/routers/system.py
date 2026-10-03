"""Health and a status endpoint that tells the UI which providers are configured (never the keys)."""
import shutil

from fastapi import APIRouter, Depends

from .. import auth
from ..config import settings
from ..db import db

router = APIRouter(tags=["system"])


@router.get("/health")
async def health():
    await db.fetchone("SELECT 1")
    return {"ok": True}


@router.get("/system/status", dependencies=[Depends(auth.require_auth)])
async def status():
    return {
        "llm": {"primary": settings.llm_primary, "fallback": settings.llm_fallback,
                "quality": settings.llm_quality, "fast": settings.llm_fast},
        "stt": {"provider": settings.stt_provider, "groq_model": settings.groq_stt_model,
                "gemini_model": settings.gemini_stt_model},
        "tts": {"provider": settings.tts_provider, "voice": settings.tts_voice,
                "rates": {"normal": settings.tts_rate_normal, "slow": settings.tts_rate_slow}},
        "keys": {"gemini": bool(settings.gemini_api_key), "groq": bool(settings.groq_api_key)},
        "ffmpeg": shutil.which("ffmpeg") is not None,
    }
