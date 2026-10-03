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
        gen: dict[str, Any] = {"temperature": req.temperature, "maxOutputTokens": req.max_tokens}
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
            raise RateLimited("gemini rate limited", retry_after=_retry_after(r))
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
            raise ProviderError(f"gemini stopped: {cand.get('finishReason')}", retryable=False)
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
            raise RateLimited("gemini tts rate limited", retry_after=_retry_after(r))
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
