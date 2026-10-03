"""D1: writing feedback is stored, its corrections merge into the mistake log, and bad replies never half-write."""
from __future__ import annotations

import time

import pytest

from app.db import loads
from app.prompts import placeholders
from app.providers.fake import FakeProvider
from app.providers.llm import LLMUnavailable
from app.services import profile, writing

TEXT = "Ich fahre mit den Bus zur Arbeit. Gestern ich habe ein Meeting gehabt."
FEEDBACK = {
    "corrections": [
        {"wrong": "mit den Bus", "right": "mit dem Bus", "category": "case", "explanation": "'mit' takes the dative.",
         "pattern": "dative after mit"},
        {"wrong": "Gestern ich habe", "right": "Gestern habe ich", "category": "word_order",
         "explanation": "The verb stays second.", "pattern": "verb second after time expression"},
    ],
    "improved": "Ich fahre mit dem Bus zur Arbeit. Gestern hatte ich ein Meeting.",
    "score": 4, "strengths": "Clear and on task.", "next_time": "Try one sentence with 'weil'.",
}


async def test_submit_stores_row_and_merges_corrections_into_the_log(fresh_db):
    FakeProvider.canned = FEEDBACK
    out = await writing.submit("Write a standup update.", TEXT)
    assert set(out) == {"id", "corrections", "improved", "score", "strengths", "next_time"}
    assert out["score"] == 4 and len(out["corrections"]) == 2 and out["corrections"][0]["category"] == "case"
    rows = await fresh_db.fetchall("SELECT * FROM writings")
    assert len(rows) == 1 and rows[0]["text"] == TEXT and rows[0]["score"] == 4 and rows[0]["prompt"] == "Write a standup update."
    assert loads(rows[0]["feedback"], {})["improved"] == FEEDBACK["improved"]
    assert rows[0]["unit_id"] == (await profile.get_profile())["unit_id"]
    log = await fresh_db.fetchall("SELECT * FROM mistakes ORDER BY id")
    assert [(m["category"], m["pattern"], m["count"]) for m in log] == [
        ("case", "dative after mit", 1), ("word_order", "verb second after time expression", 1)]
    assert loads(log[0]["examples"], [])[0] == {"wrong": "mit den Bus", "right": "mit dem Bus", "note": "'mit' takes the dative."}
    day = time.strftime("%Y-%m-%d", time.gmtime())
    assert (await fresh_db.fetchone("SELECT count FROM activity WHERE day=? AND kind='write'", (day,)))["count"] == 1

    # The same pattern from a second text merges into the same row: one row, count 2.
    await writing.submit("Another task.", "Ich gehe mit den Zug.")
    log = await fresh_db.fetchall("SELECT * FROM mistakes WHERE category='case'")
    assert len(log) == 1 and log[0]["count"] == 2
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM writings"))["n"] == 2


async def test_validation_normalises_and_drops_bad_corrections(fresh_db):
    FakeProvider.canned = {
        "corrections": [
            {"wrong": "x", "right": "y", "category": "Made Up", "explanation": "e", "pattern": "p"},
            {"wrong": "", "right": "y", "category": "case", "explanation": "", "pattern": "no wrong span"},
            "not a dict",
            {"wrong": "a", "right": "b", "category": "gender"},
        ] + [{"wrong": f"w{i}", "right": f"r{i}", "category": "other", "explanation": "", "pattern": f"p{i}"} for i in range(10)],
        "improved": "", "score": 9, "strengths": "s", "next_time": "n",
    }
    out = await writing.submit("t", "Mein Text.")
    assert out["score"] == 5, "score clamped to 5"
    assert out["improved"] == "Mein Text.", "an empty improved text falls back to his own"
    assert len(out["corrections"]) == writing.MAX_CORRECTIONS
    assert out["corrections"][0]["category"] == "other" and out["corrections"][1]["category"] == "gender"
    assert out["corrections"][1]["explanation"] == "" and out["corrections"][1]["pattern"] == ""
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM mistakes"))["n"] == writing.MAX_CORRECTIONS
    FakeProvider.canned = {**FEEDBACK, "score": -3}
    assert (await writing.submit("t", "Noch ein Text."))["score"] == 1
    FakeProvider.canned = {**FEEDBACK, "score": "lots"}
    assert (await writing.submit("t", "Noch ein Text."))["score"] == 3


async def test_corrections_as_a_string_is_rejected_without_a_row(fresh_db):
    FakeProvider.canned = {**FEEDBACK, "corrections": "mit dem Bus"}
    with pytest.raises(LLMUnavailable):
        await writing.submit("t", TEXT)
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM writings"))["n"] == 0
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM mistakes"))["n"] == 0
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM activity"))["n"] == 0


async def test_empty_text_is_refused_before_any_model_call(fresh_db):
    with pytest.raises(ValueError):
        await writing.submit("t", "   ")
    assert FakeProvider.calls == []


async def test_new_prompt_shape_and_word_clamping(fresh_db):
    FakeProvider.canned = {"task": "Write an email to your colleague Jonas about the broken deploy.",
                           "to": "Jonas, a colleague", "must_include": ["say what broke", 3, "ask for help", "x", "y", "z"],
                           "words_min": 5, "words_max": 900}
    out = await writing.new_prompt()
    assert set(out) == {"task", "to", "must_include", "words_min", "words_max", "unit_id"}
    assert (out["words_min"], out["words_max"]) == (20, 250)
    assert out["must_include"] == ["say what broke", "ask for help", "x", "y"]
    assert out["unit_id"] == (await profile.get_profile())["unit_id"]
    assert FakeProvider.calls[-1].json_schema is writing.PROMPT_SCHEMA
    # An inverted or unusable range falls back to the level's default (A1: 40-80).
    FakeProvider.canned = {"task": "t", "to": "", "must_include": "not a list", "words_min": 80, "words_max": 40}
    out = await writing.new_prompt()
    assert (out["words_min"], out["words_max"]) == (40, 80) and out["must_include"] == []
    FakeProvider.canned = {"task": "", "to": "", "must_include": [], "words_min": 40, "words_max": 80}
    with pytest.raises(LLMUnavailable):
        await writing.new_prompt()


async def test_new_prompt_feeds_recent_prompts_and_review_focus(fresh_db):
    await profile.update_profile(review_focus=["dative after mit"])
    FakeProvider.canned = FEEDBACK
    await writing.submit("Write to your landlord about the heating.", "Text.")
    FakeProvider.canned = {"task": "t", "to": "x", "must_include": ["a"], "words_min": 40, "words_max": 80}
    await writing.new_prompt()
    system = FakeProvider.calls[-1].system
    assert "Write to your landlord about the heating." in system and "dative after mit" in system
    assert "[]" not in system and "None" not in system
    assert "mistakes" not in placeholders("write_prompt")


def test_write_routes(auth_client):
    FakeProvider.canned = {"task": "t", "to": "x", "must_include": ["a"], "words_min": 40, "words_max": 80}
    assert auth_client.get("/api/write/prompt").status_code == 200
    FakeProvider.canned = FEEDBACK
    r = auth_client.post("/api/write/submit", json={"prompt": "t", "text": TEXT})
    assert r.status_code == 200 and r.json()["corrections"][0]["right"] == "mit dem Bus"
    assert auth_client.post("/api/write/submit", json={"prompt": "t", "text": "  "}).status_code == 400
    assert auth_client.post("/api/write/submit", json={"prompt": "t"}).status_code == 422
    FakeProvider.canned = {**FEEDBACK, "corrections": "nope"}
    r = auth_client.post("/api/write/submit", json={"prompt": "t", "text": TEXT})
    assert r.status_code == 503 and r.json()["retryable"] is True
    items = auth_client.get("/api/write/recent", params={"limit": 5}).json()["items"]
    assert len(items) == 1 and set(items[0]) == {"id", "prompt", "text", "feedback", "score", "created_at"}
    assert isinstance(items[0]["feedback"], dict) and items[0]["feedback"]["score"] == 4


def test_write_routes_need_auth(client):
    assert client.get("/api/write/prompt").status_code == 401
