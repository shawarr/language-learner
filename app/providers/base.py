"""Provider-neutral types. Every LLM provider implements `complete`; see llm.py for the router."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(Exception):
    """Something the provider could not do. `retryable` means trying the fallback makes sense."""

    def __init__(self, message: str, *, retryable: bool = True, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class RateLimited(ProviderError):
    def __init__(self, message: str = "rate limited", retry_after: float | None = None):
        super().__init__(message, retryable=True, status=429)
        self.retry_after = retry_after


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class LLMRequest:
    system: str
    messages: list[Message]
    json_schema: dict[str, Any] | None = None  # when set, the reply must be JSON matching this schema
    temperature: float = 0.7
    max_tokens: int = 1024
    # Optional inline audio attached to the *last* user message (Gemini transcription path).
    audio: bytes | None = None
    audio_mime: str | None = None


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)


class LLMProvider(Protocol):
    name: str

    async def complete(self, model: str, req: LLMRequest) -> LLMResponse: ...
