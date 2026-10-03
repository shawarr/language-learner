"""Gemini via the plain REST generateContent endpoint (no SDK: fewer moving parts, no breaking changes)."""
from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from ..config import settings
from .base import LLMRequest, LLMResponse, ProviderError, RateLimited

log = logging.getLogger(__name__)
BASE = "https://generativelanguage.googleapis.com/v1beta"

# Gemini 3.x counts *thinking* tokens against maxOutputTokens, and thinking happens even at
# thinkingLevel=low — a bare "Sag Hallo" spent 115 tokens on thoughts. A caller's max_tokens is
# meant as "how long may the answer be", so the budget is topped up here rather than every caller
# having to know this. Without it, a short-answer call comes back with finishReason=MAX_TOKENS and
# no text at all, which looks like an outage and silently drops the turn to the fallback model.
THINKING_HEADROOM = 768


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, timeout: float):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def _body(self, req: LLMRequest, *, full: bool) -> dict[str, Any]:
        """full=False drops the newer optional fields (thinkingConfig, responseJsonSchema) for a compatibility retry."""
        contents: list[dict[str, Any]] = []
        last = len(req.messages) - 1
        for i, m in enumerate(req.messages):
            parts: list[dict[str, Any]] = [{"text": m.content}]
            if req.audio and i == last and m.role == "user":
                parts.append({"inlineData": {"mimeType": req.audio_mime or "audio/webm",
                                             "data": base64.b64encode(req.audio).decode()}})
            contents.append({"role": "user" if m.role == "user" else "model", "parts": parts})
        gen: dict[str, Any] = {"temperature": req.temperature,
                               "maxOutputTokens": req.max_tokens + (THINKING_HEADROOM if full else 0)}
        system = req.system
        if req.json_schema:
            gen["responseMimeType"] = "application/json"
            if full:
                gen["responseJsonSchema"] = req.json_schema
            else:
                system = f"{system}\n\nReply with JSON only, matching this JSON Schema:\n{req.json_schema}"
        if full and settings.gemini_thinking_level:
            gen["thinkingConfig"] = {"thinkingLevel": settings.gemini_thinking_level.lower()}
        body: dict[str, Any] = {"contents": contents, "generationConfig": gen}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    async def complete(self, model: str, req: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY not set")
        url = f"{BASE}/models/{model}:generateContent"
        try:
            r = await self.client.post(url, json=self._body(req, full=True), headers=self._headers())
            if r.status_code == 400:
                log.warning("gemini 400 with full body, retrying compat body: %s", r.text[:200])
                r = await self.client.post(url, json=self._body(req, full=False), headers=self._headers())
        except httpx.HTTPError as e:
            raise ProviderError(f"gemini network error: {e}") from e
        if r.status_code == 429:
            raise RateLimited(f"gemini rate limited ({_quota_detail(r) or 'no detail'})",
                              retry_after=_retry_after(r))
        if r.status_code >= 500:
            # Free-tier Flash returns 503 UNAVAILABLE ("high demand") intermittently; the router
            # retries on the status, so pass it through rather than flattening it to a bare error.
            raise ProviderError(f"gemini server error {r.status_code}", status=r.status_code)
        if r.status_code != 200:
            raise ProviderError(f"gemini error {r.status_code}: {r.text[:300]}", retryable=False, status=r.status_code)
        data = r.json()
        try:
            cand = data["candidates"][0]
            parts = cand.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        except (KeyError, IndexError) as e:
            block = data.get("promptFeedback", {}).get("blockReason")
            raise ProviderError(f"gemini returned no candidates ({block or 'unknown'})", retryable=False) from e
        if not text and cand.get("finishReason") not in (None, "STOP"):
            reason = cand.get("finishReason")
            thoughts = data.get("usageMetadata", {}).get("thoughtsTokenCount", 0)
            raise ProviderError(f"gemini stopped: {reason}"
                                + (f" (spent {thoughts} tokens thinking)" if thoughts else ""),
                                retryable=False)
        um = data.get("usageMetadata", {})
        usage = {"input": um.get("promptTokenCount", 0), "output": um.get("candidatesTokenCount", 0)}
        return LLMResponse(text=text, model=model, provider=self.name, usage=usage)

    async def tts(self, model: str, text: str, voice: str) -> tuple[bytes, str]:
        """Returns (audio_bytes, mime). Gemini TTS returns raw 24 kHz 16-bit mono PCM."""
        if not self.api_key:
            raise ProviderError("GEMINI_API_KEY not set")
        url = f"{BASE}/models/{model}:generateContent"
        body = {
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
            },
        }
        try:
            r = await self.client.post(url, json=body, headers=self._headers())
        except httpx.HTTPError as e:
            raise ProviderError(f"gemini tts network error: {e}") from e
        if r.status_code == 429:
            raise RateLimited(f"gemini tts rate limited ({_quota_detail(r) or 'no detail'})",
                              retry_after=_retry_after(r))
        if r.status_code != 200:
            raise ProviderError(f"gemini tts error {r.status_code}: {r.text[:200]}", status=r.status_code)
        try:
            part = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
        except (KeyError, IndexError) as e:
            raise ProviderError("gemini tts returned no audio") from e
        return base64.b64decode(part["data"]), part.get("mimeType", "audio/L16;codec=pcm;rate=24000")


def _retry_after(r: httpx.Response) -> float | None:
    v = r.headers.get("retry-after")
    try:
        return float(v) if v else None
    except ValueError:
        return None


def _quota_detail(r: httpx.Response) -> str:
    """Pull the quota id, its limit and the retry delay out of a 429 body.

    Worth the effort: Gemini's free per-day quota is per model and is not published anywhere, and
    some of the newest models allow as few as 20 requests a day. Without this, a quota wall looks
    like a generic rate limit and costs an afternoon to diagnose.
    """
    try:
        details = r.json().get("error", {}).get("details", [])
    except ValueError:
        return ""
    bits: list[str] = []
    for d in details:
        for v in d.get("violations", []):
            quota = v.get("quotaId", "")
            model = (v.get("quotaDimensions") or {}).get("model", "")
            limit = v.get("quotaValue")
            if quota or limit:
                bits.append(f"{quota}{f'[{model}]' if model else ''}"
                            f"{f' limit={limit}' if limit else ''}")
        if delay := d.get("retryDelay"):
            bits.append(f"retry in {delay}")
    return " ".join(bits)
