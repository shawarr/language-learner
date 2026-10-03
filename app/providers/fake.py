"""Offline provider for tests and for developing the UI without API keys (LLM_PRIMARY=fake:fake).

It returns a syntactically valid object for whatever JSON schema it is given: every `required`
property gets a plausible dummy value, so services and the frontend can be exercised end to end.
Set `FakeProvider.canned` in tests to control the reply exactly.
"""
from __future__ import annotations

import json
from typing import Any

from .base import LLMRequest, LLMResponse


def _dummy(schema: dict[str, Any], key: str = "") -> Any:
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if "enum" in schema:
        return schema["enum"][0]
    if t == "object":
        props = schema.get("properties", {})
        return {k: _dummy(v, k) for k, v in props.items() if k in schema.get("required", props.keys())}
    if t == "array":
        item = schema.get("items", {"type": "string"})
        # Three entries for an "items" list so services that need a minimum (the drill generator
        # wants 3+) can be driven offline; one entry everywhere else keeps replies small.
        n = max(schema.get("minItems", 1), 3 if key == "items" else 1)
        return [_dummy(item, key) for _ in range(n)]
    if t == "integer":
        return schema.get("minimum", 0)
    if t == "number":
        return float(schema.get("minimum", 0))
    if t == "boolean":
        return False
    if t == "null":
        return None
    return f"fake {key}".strip()


class FakeProvider:
    name = "fake"
    canned: str | dict[str, Any] | None = None
    calls: list[LLMRequest] = []

    async def complete(self, model: str, req: LLMRequest) -> LLMResponse:
        FakeProvider.calls.append(req)
        if FakeProvider.canned is not None:
            text = FakeProvider.canned if isinstance(FakeProvider.canned, str) else json.dumps(FakeProvider.canned)
        elif req.json_schema:
            text = json.dumps(_dummy(req.json_schema), ensure_ascii=False)
        elif req.audio:
            text = "ich habe gestern in die stadt gegangen"
        else:
            text = "Hallo! Wie geht es dir heute?"
        return LLMResponse(text=text, model=model, provider=self.name, usage={"input": 0, "output": 0})
