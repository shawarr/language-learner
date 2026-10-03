"""One provider class for every OpenAI-compatible endpoint.

Groq, OpenRouter, Cerebras, Mistral, Together, a local vLLM or Ollama — they all speak
`POST /chat/completions` and most also speak `POST /audio/transcriptions`. So they are all this
class with a different base URL, and adding a provider is a line in
`config.OPENAI_COMPAT_PROVIDERS` plus its key in the environment, not new code. Only Gemini needs
its own module, because its REST shape is genuinely different (and it is the only one here that
takes audio directly into the chat model).
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import settings
from .base import LLMRequest, LLMResponse, ProviderError, RateLimited

log = logging.getLogger(__name__)


class OpenAICompatProvider:
    def __init__(self, name: str, base_url: str, api_key: str, timeout: float):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _check(self, r: httpx.Response, what: str) -> None:
        if r.status_code == 429:
            v = r.headers.get("retry-after")
            raise RateLimited(f"{self.name} {what} rate limited", retry_after=float(v) if v else None)
        if r.status_code >= 500:
            raise ProviderError(f"{self.name} {what} server error {r.status_code}", status=r.status_code)
        if r.status_code != 200:
            raise ProviderError(f"{self.name} {what} error {r.status_code}: {r.text[:300]}",
                                retryable=False, status=r.status_code)

    async def complete(self, model: str, req: LLMRequest) -> LLMResponse:
        if not self.api_key:
            raise ProviderError(f"{self.name} api key not set")
        if req.audio:
            raise ProviderError(f"{self.name} chat models do not take audio", retryable=False)
        messages: list[dict[str, Any]] = []
        system = req.system
        if req.json_schema:
            # json_object mode is near-universal; a strict json_schema field is not. Putting the
            # schema in the prompt works everywhere, and the router repairs the rare bad reply.
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
            r = await self.client.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers())
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name} network error: {e}") from e
        self._check(r, "chat")
        data = r.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise ProviderError(f"{self.name} returned no choices", retryable=False) from e
        u = data.get("usage", {})
        return LLMResponse(text=text, model=model, provider=self.name,
                           usage={"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)})

    async def transcribe(self, model: str, audio: bytes, filename: str, mime: str,
                         language: str = "de", prompt: str = "") -> str:
        """Whisper-style transcription. No prompt by default: a prompt written in clean German
        makes Whisper fix the learner's grammar (docs/STT-FINDINGS.md)."""
        if not self.api_key:
            raise ProviderError(f"{self.name} api key not set")
        data: dict[str, Any] = {"model": model, "language": language, "response_format": "json",
                                "temperature": "0"}
        if prompt:
            data["prompt"] = prompt
        try:
            r = await self.client.post(f"{self.base_url}/audio/transcriptions", data=data,
                                       files={"file": (filename, audio, mime)}, headers=self._headers())
        except httpx.HTTPError as e:
            raise ProviderError(f"{self.name} stt network error: {e}") from e
        self._check(r, "stt")
        return (r.json().get("text") or "").strip()
