"""All runtime configuration comes from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    app_password: str = field(default_factory=lambda: _env("APP_PASSWORD"))
    session_secret: str = field(default_factory=lambda: _env("SESSION_SECRET"))
    cookie_secure: bool = field(default_factory=lambda: _bool("COOKIE_SECURE", True))
    session_days: int = field(default_factory=lambda: int(_env("SESSION_DAYS", "365")))

    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")))
    db_path: Path | None = field(default_factory=lambda: Path(_env("DB_PATH")) if _env("DB_PATH") else None)

    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    groq_api_key: str = field(default_factory=lambda: _env("GROQ_API_KEY"))

    # "provider:model" strings. Providers: gemini, groq, fake. Three tiers, because the two
    # free providers have opposite strengths — measured numbers are in docs/FOUNDATION.md.
    # Conversation: latency is the whole experience. Groq answers in ~1s, Gemini in 2-3s and
    # 503s under load.
    llm_primary: str = field(default_factory=lambda: _env("LLM_PRIMARY", "groq:openai/gpt-oss-120b"))
    llm_fallback: str = field(default_factory=lambda: _env("LLM_FALLBACK", "gemini:gemini-3.8-flash"))
    # Judgement calls that run rarely and can take a few seconds: analyzer, placement, checkpoint
    # grading. Worth the stronger model; chain is quality -> primary -> fallback.
    llm_quality: str = field(default_factory=lambda: _env("LLM_QUALITY", "gemini:gemini-3.8-flash"))
    # High-frequency, low-stakes calls (word translation, drill grading). Its own daily quota,
    # so tapping words all evening cannot eat the conversation budget.
    llm_fast: str = field(default_factory=lambda: _env("LLM_FAST", "groq:openai/gpt-oss-20b"))
    gemini_thinking_level: str = field(default_factory=lambda: _env("GEMINI_THINKING_LEVEL", "low"))
    groq_reasoning_effort: str = field(default_factory=lambda: _env("GROQ_REASONING_EFFORT", "low"))
    llm_timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "60")))

    # STT: "groq" (whisper) or "gemini" (verbatim transcript via audio input). The other one is the fallback.
    stt_provider: str = field(default_factory=lambda: _env("STT_PROVIDER", "groq"))
    groq_stt_model: str = field(default_factory=lambda: _env("GROQ_STT_MODEL", "whisper-large-v3"))
    gemini_stt_model: str = field(default_factory=lambda: _env("GEMINI_STT_MODEL", "gemini-3.8-flash"))
    whisper_prompt: str = field(default_factory=lambda: _env("WHISPER_PROMPT", ""))

    # TTS: "edge" (free, no key) with gemini as fallback.
    tts_provider: str = field(default_factory=lambda: _env("TTS_PROVIDER", "edge"))
    tts_voice: str = field(default_factory=lambda: _env("TTS_VOICE", "de-DE-SeraphinaMultilingualNeural"))
    tts_rate_normal: str = field(default_factory=lambda: _env("TTS_RATE_NORMAL", "-5%"))
    tts_rate_slow: str = field(default_factory=lambda: _env("TTS_RATE_SLOW", "-30%"))
    gemini_tts_model: str = field(default_factory=lambda: _env("GEMINI_TTS_MODEL", "gemini-3.8-flash-lite-tts"))
    gemini_tts_voice: str = field(default_factory=lambda: _env("GEMINI_TTS_VOICE", "Kore"))

    analyze_every_turns: int = field(default_factory=lambda: int(_env("ANALYZE_EVERY_TURNS", "8")))
    history_window: int = field(default_factory=lambda: int(_env("HISTORY_WINDOW", "14")))

    def __post_init__(self) -> None:
        self.data_dir = self.data_dir.resolve()
        if self.db_path is None:
            self.db_path = self.data_dir / "tutor.db"
        self.audio_dir = self.data_dir / "audio"
        # Derived paths are plain attributes, so tests and scripts can point them elsewhere.
        self.base_dir = Path(__file__).resolve().parent
        self.prompts_dir = self.base_dir / "prompts"
        self.static_dir = self.base_dir.parent / "static"
        self.curriculum_path = self.base_dir / "curriculum" / "units.json"


settings = Settings()
