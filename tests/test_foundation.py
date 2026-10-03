"""Tests for the server foundation: auth, schema, provider router, audio plumbing."""
from __future__ import annotations

import json

import pytest

from app.providers.base import LLMRequest, Message, ProviderError, RateLimited
from app.providers.llm import LLMRouter, LLMUnavailable, parse_json


# --- auth -------------------------------------------------------------------
def test_health_needs_no_auth(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_protected_route_rejects_anonymous(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/system/status").status_code == 401


def test_login_sets_cookie_and_unlocks(client):
    assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    r = client.post("/api/auth/login", json={"password": "test-password"})
    assert r.status_code == 200
    assert "dt_session" in r.cookies or client.cookies.get("dt_session")
    assert client.get("/api/auth/me").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401


def test_tampered_cookie_is_rejected(client):
    client.post("/api/auth/login", json={"password": "test-password"})
    token = client.cookies.get("dt_session")
    exp, nonce, sig = token.split(".")
    client.cookies.set("dt_session", f"{int(exp) + 86400}.{nonce}.{sig}")
    assert client.get("/api/auth/me").status_code == 401


def test_status_never_leaks_keys(auth_client):
    body = auth_client.get("/api/system/status").text
    assert "test-password" not in body
    assert json.loads(body)["keys"] == {"gemini": False, "groq": False}


# --- schema -----------------------------------------------------------------
@pytest.mark.asyncio
async def test_schema_and_singleton_profile():
    from app.db import Database

    d = Database()
    await d.connect()
    try:
        tables = {r["name"] for r in await d.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"profile", "sessions", "messages", "mistakes", "vocab", "checkpoints", "activity"} <= tables
        rows = await d.fetchall("SELECT * FROM profile")
        assert len(rows) == 1 and rows[0]["level"] == "A1.1"
        await d.connect()  # reconnecting must not duplicate the profile row
        assert len(await d.fetchall("SELECT * FROM profile")) == 1
        await d.bump_activity("talk_turn", 2)
        await d.bump_activity("talk_turn", 3)
        assert (await d.fetchone("SELECT count FROM activity WHERE kind='talk_turn'"))["count"] == 5
    finally:
        await d.close()


# --- llm router -------------------------------------------------------------
def test_parse_json_tolerates_fences_and_prose():
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure!\n{"a": 1}\nHope that helps') == {"a": 1}
    assert parse_json("not json at all") is None


@pytest.mark.asyncio
async def test_fake_provider_satisfies_a_schema():
    from app.providers.fake import FakeProvider

    schema = {
        "type": "object",
        "properties": {"reply": {"type": "string"}, "score": {"type": "integer"},
                       "tags": {"type": "array", "items": {"type": "string"}}},
        "required": ["reply", "score", "tags"],
    }
    res = await FakeProvider().complete("fake", LLMRequest(system="", messages=[Message("user", "hi")],
                                                           json_schema=schema))
    data = json.loads(res.text)
    assert isinstance(data["reply"], str) and isinstance(data["score"], int) and isinstance(data["tags"], list)


@pytest.mark.asyncio
async def test_router_falls_back_to_the_second_provider(monkeypatch):
    from app.config import settings

    router = LLMRouter()
    monkeypatch.setattr(settings, "llm_primary", "gemini:x")
    monkeypatch.setattr(settings, "llm_fallback", "fake:fake")

    async def boom(model, req):
        raise ProviderError("gemini down")

    monkeypatch.setattr(router.gemini, "complete", boom)
    res = await router.complete(LLMRequest(system="", messages=[Message("user", "hi")]))
    assert res.provider == "fake"


@pytest.mark.asyncio
async def test_router_retries_a_rate_limit_then_falls_back(monkeypatch):
    from app.config import settings

    router = LLMRouter()
    monkeypatch.setattr(settings, "llm_primary", "gemini:x")
    monkeypatch.setattr(settings, "llm_fallback", "fake:fake")
    calls = []

    async def limited(model, req):
        calls.append(1)
        raise RateLimited("slow down", retry_after=0)

    monkeypatch.setattr(router.gemini, "complete", limited)
    res = await router.complete(LLMRequest(system="", messages=[Message("user", "hi")]))
    assert len(calls) == 2, "a rate limit should be retried once before failing over"
    assert res.provider == "fake"


@pytest.mark.asyncio
async def test_router_raises_a_user_safe_error_when_everything_fails(monkeypatch):
    from app.config import settings

    router = LLMRouter()
    monkeypatch.setattr(settings, "llm_primary", "gemini:x")
    monkeypatch.setattr(settings, "llm_fallback", "groq:y")
    with pytest.raises(LLMUnavailable) as e:
        await router.complete(LLMRequest(system="", messages=[Message("user", "hi")]))
    assert "unavailable" in str(e.value).lower()


@pytest.mark.asyncio
async def test_complete_json_repairs_unparseable_output(monkeypatch):
    from app.config import settings
    from app.providers.base import LLMResponse

    router = LLMRouter()
    monkeypatch.setattr(settings, "llm_primary", "fake:fake")
    monkeypatch.setattr(settings, "llm_fallback", "")
    replies = iter(["I am not JSON", '{"ok": true}'])

    async def flaky(model, req):
        return LLMResponse(text=next(replies), model="fake", provider="fake")

    monkeypatch.setattr(router.fake, "complete", flaky)
    data = await router.complete_json("sys", [Message("user", "hi")], {"type": "object"})
    assert data["ok"] is True and data["_model"] == "fake:fake"


# --- audio ------------------------------------------------------------------
def test_mime_normalization_covers_ios_and_android():
    from app.providers.stt import normalize_mime

    assert normalize_mime("audio/webm;codecs=opus") == ("webm", "audio/webm")   # Android Chrome
    assert normalize_mime("audio/mp4") == ("m4a", "audio/mp4")                  # iOS Safari
    assert normalize_mime("audio/x-m4a") == ("m4a", "audio/mp4")
    assert normalize_mime(None, "clip.wav") == ("wav", "audio/wav")             # mime missing
    assert normalize_mime("application/octet-stream", "x.bin") == ("webm", "audio/webm")


def test_whisper_prompt_is_empty_by_default():
    """A prompt in clean German makes Whisper correct the learner's grammar. See docs/STT-FINDINGS.md."""
    from app.config import settings

    assert settings.whisper_prompt == ""


@pytest.mark.asyncio
async def test_transcribe_rejects_empty_audio():
    from app.providers.stt import stt

    with pytest.raises(ProviderError):
        await stt.transcribe(b"", "audio/webm")


@pytest.mark.asyncio
async def test_transcribe_falls_back_to_the_other_engine(monkeypatch):
    from app.providers import stt as stt_mod

    async def groq_fails(audio, ext, mime):
        raise ProviderError("whisper down")

    async def gemini_works(audio, ext, mime):
        return stt_mod.Transcript(text="ich bin müde", provider="gemini", model="g")

    monkeypatch.setattr(stt_mod.stt, "_groq", groq_fails)
    monkeypatch.setattr(stt_mod.stt, "_gemini", gemini_works)
    t = await stt_mod.stt.transcribe(b"fake-audio", "audio/mp4")
    assert t.text == "ich bin müde" and t.provider == "gemini"


@pytest.mark.asyncio
async def test_compare_reports_errors_instead_of_raising(monkeypatch):
    from app.providers import stt as stt_mod

    async def fails(audio, ext, mime):
        raise ProviderError("nope")

    monkeypatch.setattr(stt_mod.stt, "_groq", fails)
    monkeypatch.setattr(stt_mod.stt, "_gemini", fails)
    out = await stt_mod.stt.transcribe_compare(b"x", "audio/webm")
    assert out["groq"].startswith("ERROR:") and out["gemini"].startswith("ERROR:")


def test_pcm_to_wav_header():
    from app.providers.tts import _pcm_to_wav

    wav = _pcm_to_wav(b"\x00\x01" * 100, rate=24000)
    assert wav[:4] == b"RIFF" and wav[8:12] == b"WAVE"
    assert len(wav) == 44 + 200


@pytest.mark.asyncio
async def test_tts_cache_is_keyed_by_speed(monkeypatch, tmp_path):
    from app.config import settings
    from app.providers import tts as tts_mod

    monkeypatch.setattr(settings, "audio_dir", tmp_path)
    calls = []

    async def fake_edge(text, speed, voice, path):
        calls.append(speed)
        path.write_bytes(b"ID3")

    monkeypatch.setitem(tts_mod._ENGINES, "edge", ("mp3", lambda: "voice", fake_edge))
    a = await tts_mod.synthesize("Guten Tag", "normal")
    b = await tts_mod.synthesize("Guten Tag", "slow")
    await tts_mod.synthesize("Guten Tag", "normal")
    assert a != b
    assert calls == ["normal", "slow"], "the second normal request should come from cache"


@pytest.mark.asyncio
async def test_tts_falls_back_when_edge_fails(monkeypatch, tmp_path):
    from app.config import settings
    from app.providers import tts as tts_mod

    monkeypatch.setattr(settings, "audio_dir", tmp_path)

    async def edge_fails(text, speed, voice, path):
        raise ProviderError("edge down")

    async def gemini_works(text, speed, voice, path):
        path.write_bytes(b"RIFF")

    monkeypatch.setitem(tts_mod._ENGINES, "edge", ("mp3", lambda: "v", edge_fails))
    monkeypatch.setitem(tts_mod._ENGINES, "gemini", ("wav", lambda: "v", gemini_works))
    assert (await tts_mod.synthesize("Hallo")).suffix == ".wav"


def test_tts_endpoint_requires_auth_and_validates_speed(client, auth_client, monkeypatch, tmp_path):
    from app.providers import tts as tts_mod

    async def fake_synth(text, speed="normal"):
        p = tmp_path / "x.mp3"
        p.write_bytes(b"ID3")
        return p

    monkeypatch.setattr(tts_mod, "synthesize", fake_synth)
    assert auth_client.get("/api/tts", params={"text": "Hallo", "speed": "turbo"}).status_code == 422
    r = auth_client.get("/api/tts", params={"text": "Hallo", "speed": "slow"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"


def test_provider_error_becomes_a_retryable_503(auth_client, monkeypatch):
    from app.providers import tts as tts_mod

    async def fails(text, speed="normal"):
        raise ProviderError("everything is down")

    monkeypatch.setattr(tts_mod, "synthesize", fails)
    r = auth_client.get("/api/tts", params={"text": "Hallo"})
    assert r.status_code == 503 and r.json()["retryable"] is True
