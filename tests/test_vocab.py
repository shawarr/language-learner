"""A5: tap-to-translate serves the cache first, in_vocab is live, and the vocab routes behave."""
from __future__ import annotations

import pytest

from app.db import loads
from app.providers.fake import FakeProvider
from app.providers.llm import LLMUnavailable
from app.services import vocab

TERMIN = {"lemma": "der Termin (die Termine)", "translation": "appointment", "pos": "noun",
          "note": "Masculine, unlike English intuition."}


async def test_translate_serves_the_cache_before_the_model(fresh_db):
    FakeProvider.canned = TERMIN
    first = await vocab.translate("Termin,", "Ich habe einen Termin, morgen.")
    assert len(FakeProvider.calls) == 1
    assert first == {"word": "Termin", **TERMIN, "in_vocab": False}
    # Different punctuation and case around the same surface form hit the same cache row.
    second = await vocab.translate("„TERMIN“")
    assert len(FakeProvider.calls) == 1, "the cache must answer without a model call"
    assert second["lemma"] == TERMIN["lemma"] and second["word"] == "TERMIN"
    rows = await fresh_db.fetchall("SELECT * FROM translations")
    assert len(rows) == 1 and rows[0]["word"] == "termin"
    assert set(loads(rows[0]["data"], {})) == {"lemma", "translation", "pos", "note"}, "only the model's fields are cached"


async def test_in_vocab_is_computed_live_not_cached(fresh_db):
    FakeProvider.canned = TERMIN
    assert (await vocab.translate("Termin"))["in_vocab"] is False
    await vocab.upsert("Der Termin (die Termine)", "appointment", source="tutor")
    assert (await vocab.translate("Termin"))["in_vocab"] is True
    assert len(FakeProvider.calls) == 1


async def test_translate_validates_the_model_output(fresh_db):
    FakeProvider.canned = {"lemma": "", "translation": "to call", "pos": "VERB", "note": 7}
    out = await vocab.translate("anrufen")
    assert out["lemma"] == "anrufen" and out["pos"] == "verb" and out["note"] == "7"
    FakeProvider.canned = {"lemma": "x", "translation": "x", "pos": "made-up", "note": ""}
    assert (await vocab.translate("x"))["pos"] == "other"
    FakeProvider.canned = {"lemma": "y", "translation": "", "pos": "noun", "note": ""}
    with pytest.raises(LLMUnavailable):
        await vocab.translate("y")
    assert await fresh_db.fetchone("SELECT 1 FROM translations WHERE word='y'") is None, "a bad reply is never cached"
    with pytest.raises(ValueError):
        await vocab.translate("...")


def test_translate_route_uses_the_fast_tier_and_rejects_empty(auth_client):
    FakeProvider.canned = TERMIN
    r = auth_client.post("/api/vocab/translate", json={"word": "Termin", "context": "Ich habe einen Termin."})
    assert r.status_code == 200 and r.json()["translation"] == "appointment"
    assert FakeProvider.calls[0].json_schema is vocab.TRANSLATE_SCHEMA
    assert auth_client.post("/api/vocab/translate", json={"word": "!!"}).status_code == 400
    assert auth_client.post("/api/vocab/translate", json={}).status_code == 422


def test_add_browse_and_delete_routes(auth_client):
    r = auth_client.post("/api/vocab", json={"word": "der Termin (die Termine)", "translation": "appointment"})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True and body["word"] == "der Termin (die Termine)"
    again = auth_client.post("/api/vocab", json={"word": "der Termin (die Termine)", "translation": "appointment",
                                                 "example": "Ich habe einen Termin.", "source": "tutor"}).json()
    assert again["id"] == body["id"] and again["created"] is False
    assert auth_client.post("/api/vocab", json={"word": "x"}).status_code == 422
    assert auth_client.post("/api/vocab", json={"word": " ", "translation": "x"}).status_code == 400

    listing = auth_client.get("/api/vocab", params={"q": "termin", "sort": "word", "limit": 10}).json()
    assert listing["total"] == 1 and listing["items"][0]["example"] == "Ich habe einen Termin."
    assert listing["items"][0]["is_new"] is True and listing["items"][0]["source"] == "manual"
    assert auth_client.get("/api/vocab", params={"sort": "bogus"}).status_code == 422

    assert auth_client.delete(f"/api/vocab/{body['id']}").json() == {"ok": True}
    assert auth_client.delete(f"/api/vocab/{body['id']}").status_code == 404
    assert auth_client.get("/api/vocab").json() == {"items": [], "total": 0}


def test_vocab_routes_need_auth(client):
    assert client.post("/api/vocab/translate", json={"word": "x"}).status_code == 401
    assert client.get("/api/vocab").status_code == 401
