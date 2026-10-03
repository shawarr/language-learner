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


# Every OpenAI-compatible endpoint is the same provider class with a different base URL, so
# switching to whatever is good and free today is a model string plus a key — no code.
# name -> (base url, env var holding the key). A provider with no key set is simply not registered.
OPENAI_COMPAT_PROVIDERS: dict[str, tuple[str, str]] = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "cerebras": ("https://api.cerebras.ai/v1", "CEREBRAS_API_KEY"),
    "mistral": ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
    "together": ("https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    # Anything else, including a local vLLM/Ollama: set CUSTOM_LLM_BASE_URL (+ CUSTOM_LLM_API_KEY)
    # and use "custom:<model>" in any of the LLM_* settings.
    "custom": ("", "CUSTOM_LLM_API_KEY"),
}


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
    custom_llm_base_url: str = field(default_factory=lambda: _env("CUSTOM_LLM_BASE_URL"))

    # "provider:model" strings. Providers: gemini, groq, fake. Three tiers, because the two
    # free providers have opposite strengths — measured numbers are in docs/FOUNDATION.md.
    # Conversation: latency is the whole experience. Groq answers in ~1s, Gemini in 2-3s and
    # 503s under load.
    llm_primary: str = field(default_factory=lambda: _env("LLM_PRIMARY", "groq:openai/gpt-oss-120b"))
    llm_fallback: str = field(default_factory=lambda: _env("LLM_FALLBACK", "gemini:gemini-3.5-flash-lite"))
    # Judgement calls that run rarely and can take a few seconds: analyzer, placement, checkpoint
    # grading. Chain is quality -> primary -> fallback. Gemini catches recurring patterns that Groq
    # misses (measured; see docs/FOUNDATION.md), which is exactly this tier's job.
    # NOT gemini-3.8-flash: its free quota is 20 requests per DAY.
    llm_quality: str = field(default_factory=lambda: _env("LLM_QUALITY", "gemini:gemini-3.5-flash"))
    # High-frequency, low-stakes calls (word translation, drill grading). Its own daily quota,
    # so tapping words all evening cannot eat the conversation budget.
    llm_fast: str = field(default_factory=lambda: _env("LLM_FAST", "groq:openai/gpt-oss-20b"))
    gemini_thinking_level: str = field(default_factory=lambda: _env("GEMINI_THINKING_LEVEL", "low"))
    groq_reasoning_effort: str = field(default_factory=lambda: _env("GROQ_REASONING_EFFORT", "low"))
    llm_timeout: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT", "60")))

    # STT: "groq" (whisper) or "gemini" (verbatim transcript via audio input). The other one is the fallback.
    stt_provider: str = field(default_factory=lambda: _env("STT_PROVIDER", "groq"))
    groq_stt_model: str = field(default_factory=lambda: _env("GROQ_STT_MODEL", "whisper-large-v3"))
    gemini_stt_model: str = field(default_factory=lambda: _env("GEMINI_STT_MODEL", "gemini-3.5-flash-lite"))
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
    # --- app layer (added at the bottom, per docs/TASKS.md rule 1) --------------
    # A checkpoint is offered after this many talk sessions in a unit, even without a "ready" verdict.
    checkpoint_min_sessions: int = field(default_factory=lambda: int(_env("CHECKPOINT_MIN_SESSIONS", "3")))
    # New (never reviewed) cards per review queue, so a chatty day doesn't create a 60-card backlog.
    new_cards_per_review: int = field(default_factory=lambda: int(_env("NEW_CARDS_PER_REVIEW", "10")))
    drill_items: int = field(default_factory=lambda: int(_env("DRILL_ITEMS", "8")))
    # A talk session with no new turn for this long counts as abandoned and is closed, analysed and
    # swept. On a phone the usual way out of a conversation is switching apps, not tapping "end".
    session_stale_minutes: int = field(default_factory=lambda: int(_env("SESSION_STALE_MINUTES", "45")))


settings = Settings()
