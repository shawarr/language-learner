"""Groq via its OpenAI-compatible REST API: chat completions (LLM fallback) and whisper transcription."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import settings
from .base import LLMRequest, LLMResponse, ProviderError, RateLimited

log = logging.getLogger(__name__)
BASE = "https://api.groq.com/openai/v1"


class GroqProvider:
    name = "groq"

    def __init__(self, api_key: str, timeout: float):
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _check(self, r: httpx.Response, what: str) -> None:
        if r.status_code == 429:
            v = r.headers.get("retry-after")
            raise RateLimited(f"groq {what} rate limited", retry_after=float(v) if v else None)
        if r.status_code >= 500:
            raise ProviderError(f"groq {what} server error {r.status_code}", status=r.status_code)
        if r.status_code != 200:
            raise ProviderError(f"groq {what} error {r.status_code}: {r.text[:300]}", retryable=False, status=r.status_code)

    async def complete(self, model: str, req: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise ProviderError("GROQ_API_KEY not set")
        if req.audio:
            raise ProviderError("groq chat models do not take audio", retryable=False)
        messages: list[dict[str, Any]] = []
        system = req.system
        if req.json_schema:
            # json_object mode is supported by every Groq model; the schema goes into the prompt.
            system = f"{system}\n\nReply with JSON only, matching this JSON Schema:\n{json.dumps(req.json_schema)}"
        if system:
            messages.append({"role": "system", "content": system})
        messages += [{"role": m.role, "content": m.content} for m in req.messages]
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": req.temperature,
            "max_completion_tokens": req.max_tokens,
        }
        if req.json_schema:
            body["response_format"] = {"type": "json_object"}
        if "gpt-oss" in model and settings.groq_reasoning_effort:
            body["reasoning_effort"] = settings.groq_reasoning_effort
        try:
            r = await self.client.post(f"{BASE}/chat/completions", json=body, headers=self._headers())
        except httpx.HTTPError as e:
            raise ProviderError(f"groq network error: {e}") from e
        self._check(r, "chat")
        data = r.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise ProviderError("groq returned no choices", retryable=False) from e
        u = data.get("usage", {})
        return LLMResponse(text=text, model=model, provider=self.name,
                           usage={"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)})

    async def transcribe(self, model: str, audio: bytes, filename: str, mime: str,
                         language: str = "de", prompt: str = "") -> str:
        """Whisper transcription. No prompt by default: a 'clean German' prompt makes Whisper fix grammar."""
        if not self.api_key:
            raise ProviderError("GROQ_API_KEY not set")
        data: dict[str, Any] = {"model": model, "language": language, "response_format": "json", "temperature": "0"}
        if prompt:
            data["prompt"] = prompt
        try:
            r = await self.client.post(f"{BASE}/audio/transcriptions", data=data,
                                       files={"file": (filename, audio, mime)}, headers=self._headers())
        except httpx.HTTPError as e:
            raise ProviderError(f"groq stt network error: {e}") from e
        self._check(r, "stt")
        return (r.json().get("text") or "").strip()
