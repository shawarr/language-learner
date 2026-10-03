"""LLM router: primary -> fallback with retry on rate limits, plus robust JSON parsing.

Usage from services:
    from app.providers.llm import llm
    data = await llm.complete_json(system, messages, schema)   # dict
    text = await llm.complete_text(system, messages)           # str
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from ..config import settings
from .base import LLMProvider, LLMRequest, LLMResponse, Message, ProviderError, RateLimited
from .fake import FakeProvider
from .gemini import GeminiProvider
from .groq import GroqProvider

log = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """All configured providers failed. The message is safe to show to the user."""


class LLMRouter:
    def __init__(self) -> None:
        self.gemini = GeminiProvider(settings.gemini_api_key, settings.llm_timeout)
        self.groq = GroqProvider(settings.groq_api_key, settings.llm_timeout)
        self.fake = FakeProvider()
        self._providers: dict[str, LLMProvider] = {"gemini": self.gemini, "groq": self.groq, "fake": self.fake}

    def _parse(self, spec: str) -> tuple[LLMProvider, str]:
        provider, _, model = spec.partition(":")
        if provider not in self._providers:
            raise ValueError(f"unknown LLM provider in '{spec}'")
        return self._providers[provider], model or "fake"

    def _chain(self, tier: str) -> list[str]:
        """Which models to try, in order. Unknown tiers fall back to the conversation chain."""
        head = {"fast": settings.llm_fast, "quality": settings.llm_quality}.get(tier)
        specs = ([head] if head else []) + [settings.llm_primary, settings.llm_fallback]
        seen: set[str] = set()
        return [s for s in specs if s and not (s in seen or seen.add(s))]

    # Retries before failing over, per provider. Free-tier Gemini Flash hands out 503
    # "high demand" often enough that giving up on the first one would send most turns to
    # the weaker fallback; 429 and 5xx both clear on their own within a second or two.
    ATTEMPTS = 2

    async def complete(self, req: LLMRequest, *, tier: str = "primary") -> LLMResponse:
        errors: list[str] = []
        for spec in self._chain(tier):
            provider, model = self._parse(spec)
            for attempt in range(self.ATTEMPTS):
                try:
                    return await provider.complete(model, req)
                except ProviderError as e:
                    transient = isinstance(e, RateLimited) or (e.status or 0) >= 500
                    errors.append(f"{spec}: {e}")
                    if not transient or attempt == self.ATTEMPTS - 1:
                        log.warning("%s failed (%s), moving on: %s",
                                    spec, "giving up" if transient else "permanent", e)
                        break
                    wait = min(getattr(e, "retry_after", None) or 1.5, 8.0)
                    log.warning("%s transient failure (attempt %d), waiting %.1fs: %s",
                                spec, attempt + 1, wait, e)
                    await asyncio.sleep(wait)
                except (asyncio.TimeoutError, OSError) as e:
                    errors.append(f"{spec}: {e}")
                    break
        raise LLMUnavailable("The tutor is unavailable right now (rate limit or provider error). Try again in a minute. "
                             + " | ".join(errors))

    async def complete_text(self, system: str, messages: list[Message], *, tier: str = "primary",
                            temperature: float = 0.7, max_tokens: int = 1024) -> str:
        res = await self.complete(LLMRequest(system=system, messages=messages, temperature=temperature,
                                             max_tokens=max_tokens), tier=tier)
        return res.text.strip()

    async def complete_json(self, system: str, messages: list[Message], schema: dict[str, Any], *,
                            tier: str = "primary", temperature: float = 0.4, max_tokens: int = 1536,
                            audio: bytes | None = None, audio_mime: str | None = None) -> dict[str, Any]:
        req = LLMRequest(system=system, messages=messages, json_schema=schema, temperature=temperature,
                         max_tokens=max_tokens, audio=audio, audio_mime=audio_mime)
        res = await self.complete(req, tier=tier)
        data = parse_json(res.text)
        if data is None:
            # One repair attempt: ask the same chain to fix its own output.
            log.warning("unparseable JSON from %s, retrying once", res.model)
            repair = messages + [Message("assistant", res.text), Message("user", "That was not valid JSON. Reply with only the JSON object.")]
            res = await self.complete(LLMRequest(system=system, messages=repair, json_schema=schema,
                                                 temperature=0.2, max_tokens=max_tokens), tier=tier)
            data = parse_json(res.text)
        if not isinstance(data, dict):
            raise LLMUnavailable("The tutor returned an unreadable answer. Please try again.")
        data["_model"] = f"{res.provider}:{res.model}"
        return data


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json(text: str) -> Any:
    """Tolerates code fences and leading/trailing prose around the JSON object."""
    text = text.strip()
    m = _FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except ValueError:
            return None
    return None


llm = LLMRouter()
