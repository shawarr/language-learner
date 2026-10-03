"""A2/V1: the talk turn persists exactly what the model said, validated, and nothing on failure."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.config import settings
from app.db import loads
from app.providers.fake import FakeProvider
from app.providers.llm import LLMUnavailable
from app.services import analyzer, curriculum, tutor

TURN = {
    "reply": "Hallo Ahmad! Wie geht es dir heute?",
    "corrections": [{"wrong": "ich habe gegangen", "right": "ich bin gegangen", "category": "verb_conjugation",
                     "explanation": "gehen takes sein in the Perfekt."}],
    "praise": None,
    "english_help": None,
    "new_vocab": [{"word": "der Termin (die Termine)", "translation": "appointment", "example": "Ich habe einen Termin."}],
    "scenario_done": False,
}

ANALYSIS = {
    "session_summary": "He practised greetings.",
    "rolling_summary": "Beginner, keen, mixes up haben and sein.",
    "mistakes": [],
    "new_vocab": [],
    "skill_deltas": {"speaking": 1},
    "facts": [],
    "unit_readiness": "not_yet",
}


_REAL_SCHEDULE_CATCH_UP = tutor.schedule_catch_up


@pytest.fixture(autouse=True)
def quiet_catch_up(monkeypatch):
    """start_session kicks off a background catch-up; record it instead of racing the DB teardown."""
    calls = []
    monkeypatch.setattr(tutor, "schedule_catch_up", lambda: calls.append(1))
    return calls


# --- sanitize_turn: pure -----------------------------------------------------
def test_sanitize_truncates_normalises_and_drops():
    data = {
        "reply": "  Gut. Und du?  ",
        "corrections": [{"wrong": f"w{i}", "right": f"r{i}", "category": "Word Order", "explanation": "x"} for i in range(5)]
                       + [{"wrong": "no right", "category": "case", "explanation": "x"}, "junk"],
        "praise": "   ",
        "english_help": {"english": "I am tired", "german": "Ich bin müde"},   # literal missing
        "new_vocab": [{"word": f"das Wort{i}", "translation": "word"} for i in range(5)] + [{"word": "x"}],
        "scenario_done": "true",
    }
    out = tutor.sanitize_turn(data)
    assert out["reply"] == "Gut. Und du?"
    assert len(out["corrections"]) == tutor.MAX_CORRECTIONS
    assert {c["category"] for c in out["corrections"]} == {"word_order"}
    assert all(c["right"] for c in out["corrections"])
    assert out["praise"] is None and out["english_help"] is None
    assert len(out["new_vocab"]) == tutor.MAX_NEW_VOCAB and out["new_vocab"][0]["example"] == ""
    assert out["scenario_done"] is True


def test_sanitize_handles_wrong_types_and_unknown_category():
    out = tutor.sanitize_turn({"reply": "Ja.", "corrections": "none", "new_vocab": None, "scenario_done": None,
                               "english_help": {"english": "a", "german": "b", "literal": "c"},
                               "praise": "Sehr gut!"})
    assert out == {"reply": "Ja.", "corrections": [], "praise": "Sehr gut!", "new_vocab": [], "scenario_done": False,
                   "english_help": {"english": "a", "german": "b", "literal": "c"}}
    out = tutor.sanitize_turn({"reply": "Ja.", "corrections": [{"wrong": "a", "right": "b", "category": "made-up"}]})
    assert out["corrections"] == [{"wrong": "a", "right": "b", "category": "other", "explanation": ""}]


def test_sanitize_rejects_a_missing_reply():
    with pytest.raises(LLMUnavailable):
        tutor.sanitize_turn({"corrections": [], "new_vocab": [], "scenario_done": False})
    with pytest.raises(LLMUnavailable):
        tutor.sanitize_turn({"reply": "   "})


# --- the service -------------------------------------------------------------
async def test_start_session_persists_only_the_opening_turn(fresh_db, quiet_catch_up):
    FakeProvider.canned = TURN
    out = await tutor.start_session()
    s, turn = out["session"], out["opening_turn"]
    assert s["mode"] == "talk" and s["unit_id"] == "a1.1-1" and s["scenario_id"] is None and s["meta"] == {}
    assert turn["user_message_id"] is None and turn["reply"] == TURN["reply"]
    assert turn["corrections"] == [] and turn["english_help"] is None, "nothing to correct before he has spoken"
    rows = await fresh_db.fetchall("SELECT * FROM messages")
    assert len(rows) == 1 and rows[0]["role"] == "assistant" and rows[0]["id"] == turn["message_id"]
    req = FakeProvider.calls[0]
    assert [m.content for m in req.messages] == [tutor.OPENING_MESSAGE], "the synthetic opener is sent, not stored"
    assert quiet_catch_up == [1]


async def test_scenario_is_stored_and_reaches_the_prompt(fresh_db):
    FakeProvider.canned = TURN
    _, sc = curriculum.scenario("a1.1-1-a")
    s = (await tutor.start_session(scenario_id=sc["id"]))["session"]
    assert s["scenario_id"] == sc["id"] and s["scenario_title"] == sc["title"] and s["unit_id"] == "a1.1-1"
    assert sc["setup"] in FakeProvider.calls[0].system
    # A scenario from a later unit is played, but the context keeps the profile's unit.
    _, later = curriculum.scenario("a2.1-1-a")
    s2 = (await tutor.start_session(scenario_id=later["id"]))["session"]
    assert s2["unit_id"] == "a1.1-1" and s2["scenario_title"] == later["title"]
    with pytest.raises(HTTPException) as e:
        await tutor.start_session(scenario_id="nope")
    assert e.value.status_code == 404


async def test_turn_persists_both_rows_with_the_right_columns(fresh_db):
    FakeProvider.canned = TURN
    sid = (await tutor.start_session())["session"]["id"]
    out = await tutor.take_turn(sid, "Gestern ich habe gegangen.")
    assert set(out) == {"user_message_id", "message_id", "reply", "corrections", "praise", "english_help",
                        "new_vocab", "scenario_done", "transcript", "transcript_provider"}
    assert out["transcript"] is None and out["transcript_provider"] is None
    user = await fresh_db.fetchone("SELECT * FROM messages WHERE id=?", (out["user_message_id"],))
    assistant = await fresh_db.fetchone("SELECT * FROM messages WHERE id=?", (out["message_id"],))
    assert user["role"] == "user" and user["content"] == "Gestern ich habe gegangen."
    assert user["input_kind"] == "text" and user["transcript_raw"] is None and user["correction"] is None
    assert assistant["role"] == "assistant" and assistant["content"] == TURN["reply"]
    assert loads(assistant["correction"], None) == TURN["corrections"], "corrections live on the assistant row"
    assert assistant["english_help"] is None and assistant["llm_model"] == "fake:fake"
    session = await fresh_db.fetchone("SELECT * FROM sessions WHERE id=?", (sid,))
    assert session["user_turns"] == 1
    assert (await fresh_db.fetchone("SELECT count FROM activity WHERE kind='talk_turn'"))["count"] == 1


async def test_history_window_limits_what_the_model_sees(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "history_window", 2)
    FakeProvider.canned = TURN
    sid = (await tutor.start_session())["session"]["id"]
    for i in range(3):
        await tutor.take_turn(sid, f"Satz {i}")
    req = FakeProvider.calls[-1]
    assert [m.role for m in req.messages] == ["user", "assistant", "user"]
    assert req.messages[0].content == "Satz 1" and req.messages[-1].content == "Satz 2"
    assert req.messages[1].content == TURN["reply"], "history carries the reply text, never the JSON"
    assert "Recurring mistakes" in req.system


async def test_new_vocab_is_upserted_with_source_tutor_and_srs_untouched(fresh_db):
    from app.services import vocab

    vid, _ = await vocab.upsert("der Termin (die Termine)", "appointment", source="manual")
    await fresh_db.execute("UPDATE vocab SET reps=5, interval_days=30, due=9e9 WHERE id=?", (vid,))
    FakeProvider.canned = {**TURN, "new_vocab": TURN["new_vocab"] + [{"word": "die Wohnung (die Wohnungen)", "translation": "flat"}]}
    sid = (await tutor.start_session())["session"]["id"]
    await tutor.take_turn(sid, "Hallo")
    old = await fresh_db.fetchone("SELECT * FROM vocab WHERE id=?", (vid,))
    assert old["reps"] == 5 and old["due"] == 9e9 and old["source"] == "manual"
    new = await fresh_db.fetchone("SELECT * FROM vocab WHERE word='die Wohnung (die Wohnungen)'")
    assert new["source"] == "tutor" and new["reps"] == 0 and new["due"] <= old["due"]
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM vocab"))["n"] == 2


async def test_analyzer_fires_on_the_nth_turn_only(fresh_db, monkeypatch):
    FakeProvider.canned = TURN
    fired = []
    monkeypatch.setattr(tutor, "schedule_analysis", lambda sid: fired.append(sid))
    monkeypatch.setattr(settings, "analyze_every_turns", 8)
    sid = (await tutor.start_session())["session"]["id"]
    for i in range(7):
        await tutor.take_turn(sid, f"Satz {i}")
    assert fired == [], "turn 7 must not analyse"
    await tutor.take_turn(sid, "Satz 8")
    assert fired == [sid]
    for i in range(8):
        await tutor.take_turn(sid, f"Satz {9 + i}")
    assert fired == [sid, sid]


async def test_analyzer_failure_does_not_fail_the_turn(fresh_db, monkeypatch):
    FakeProvider.canned = TURN
    monkeypatch.setattr(settings, "analyze_every_turns", 1)

    async def boom(session_id):
        raise RuntimeError("analyzer down")

    monkeypatch.setattr(analyzer, "analyze_session", boom)
    sid = (await tutor.start_session())["session"]["id"]
    out = await tutor.take_turn(sid, "Hallo")
    for _ in range(3):
        await asyncio.sleep(0)  # let the background task run and swallow its error
    assert out["reply"] == TURN["reply"]
    assert (await fresh_db.fetchone("SELECT user_turns FROM sessions WHERE id=?", (sid,)))["user_turns"] == 1


async def test_a_failed_write_rolls_back_the_whole_turn(fresh_db, monkeypatch):
    FakeProvider.canned = TURN
    sid = (await tutor.start_session())["session"]["id"]

    async def broken(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(tutor.vocab, "upsert", broken)
    with pytest.raises(RuntimeError):
        await tutor.take_turn(sid, "Hallo")
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM messages"))["n"] == 1, "the user row went with it"
    assert (await fresh_db.fetchone("SELECT user_turns FROM sessions WHERE id=?", (sid,)))["user_turns"] == 0


async def test_turn_rejects_ended_unknown_and_empty(fresh_db):
    FakeProvider.canned = TURN
    sid = (await tutor.start_session())["session"]["id"]
    with pytest.raises(HTTPException) as e:
        await tutor.take_turn(sid, "   ")
    assert e.value.status_code == 400
    FakeProvider.canned = ANALYSIS
    await tutor.end_session(sid)
    with pytest.raises(HTTPException) as e:
        await tutor.take_turn(sid, "Hallo")
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        await tutor.take_turn(sid + 99, "Hallo")
    assert e.value.status_code == 404


async def test_end_session_returns_the_summary_and_is_idempotent(fresh_db):
    FakeProvider.canned = TURN
    sid = (await tutor.start_session())["session"]["id"]
    await tutor.take_turn(sid, "Ich bin müde.")
    FakeProvider.canned = ANALYSIS
    calls_before = len(FakeProvider.calls)
    out = await tutor.end_session(sid)
    assert out == {"summary": ANALYSIS["session_summary"], "analyzed": True}
    assert len(FakeProvider.calls) == calls_before + 1
    row = await fresh_db.fetchone("SELECT * FROM sessions WHERE id=?", (sid,))
    assert row["ended_at"] is not None and row["analyzed_count"] == 3
    assert loads(row["meta"], {})["unit_readiness"] == "not_yet"
    again = await tutor.end_session(sid)
    assert again == out and len(FakeProvider.calls) == calls_before + 1, "nothing new: no model call"


async def test_end_session_survives_an_analyzer_failure(fresh_db, monkeypatch):
    FakeProvider.canned = TURN
    sid = (await tutor.start_session())["session"]["id"]
    await tutor.take_turn(sid, "Hallo")

    async def boom(session_id):
        raise LLMUnavailable("down")

    monkeypatch.setattr(analyzer, "analyze_session", boom)
    assert await tutor.end_session(sid) == {"summary": "", "analyzed": False}
    row = await fresh_db.fetchone("SELECT ended_at, analyzed_count FROM sessions WHERE id=?", (sid,))
    assert row["ended_at"] is not None and row["analyzed_count"] == 0, "closed, and left for catch_up()"


async def test_start_session_catches_up_a_session_left_unanalysed(fresh_db, monkeypatch):
    monkeypatch.setattr(tutor, "schedule_catch_up", _REAL_SCHEDULE_CATCH_UP)
    FakeProvider.canned = TURN
    old = (await tutor.start_session())["session"]["id"]
    await tutor.take_turn(old, "Ich fahre mit den Bus.")
    FakeProvider.canned = {**ANALYSIS, "mistakes": "broken"}   # the end-of-session analysis fails
    assert (await tutor.end_session(old))["analyzed"] is False
    FakeProvider.canned = {**TURN, **ANALYSIS}   # one object that satisfies both schemas
    await tutor.start_session()
    for _ in range(100):
        await asyncio.sleep(0.01)
        row = await fresh_db.fetchone("SELECT analyzed_count, summary FROM sessions WHERE id=?", (old,))
        if row["analyzed_count"]:
            break
    assert row["analyzed_count"] == 3 and row["summary"] == ANALYSIS["session_summary"]


async def test_get_session_and_recent_sessions(fresh_db):
    FakeProvider.canned = TURN
    assert await tutor.get_session(1) is None
    first = (await tutor.start_session())["session"]["id"]
    second = (await tutor.start_session())["session"]["id"]
    await tutor.take_turn(second, "Hallo")
    found = await tutor.get_session(second)
    assert [m["role"] for m in found["messages"]] == ["assistant", "user", "assistant"]
    assert found["messages"][2]["correction"] == TURN["corrections"] and found["messages"][1]["correction"] is None
    assert [s["id"] for s in await tutor.recent_sessions()] == [second, first]
    assert len(await tutor.recent_sessions(limit=1)) == 1


# --- the routes --------------------------------------------------------------
def test_routes_need_auth(client):
    assert client.post("/api/talk/session", json={}).status_code == 401
    assert client.get("/api/talk/sessions").status_code == 401


def test_talk_routes_end_to_end(auth_client):
    FakeProvider.canned = TURN
    r = auth_client.post("/api/talk/session", json={"scenario_id": "a1.1-1-a"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"session", "opening_turn"}
    assert set(body["session"]) == {"id", "mode", "scenario_id", "scenario_title", "unit_id", "started_at", "ended_at",
                                    "summary", "user_turns", "meta"}
    assert body["opening_turn"]["user_message_id"] is None
    sid = body["session"]["id"]

    r = auth_client.post("/api/talk/turn", json={"session_id": sid, "text": "Ich heiße Ahmad."})
    assert r.status_code == 200, r.text
    turn = r.json()
    assert turn["corrections"] == TURN["corrections"] and turn["transcript"] is None
    assert auth_client.post("/api/talk/turn", json={"session_id": sid, "text": "  "}).status_code == 422
    assert auth_client.post("/api/talk/turn", json={"session_id": "x", "text": "Hi"}).status_code == 422
    assert auth_client.post("/api/talk/turn", json={"session_id": sid + 50, "text": "Hi"}).status_code == 404

    r = auth_client.get(f"/api/talk/session/{sid}")
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 3 and set(msgs[1]) == {"id", "role", "content", "transcript_raw", "input_kind", "correction",
                                               "english_help", "stt_provider", "llm_model", "created_at"}
    assert auth_client.get(f"/api/talk/session/{sid + 50}").status_code == 404

    FakeProvider.canned = ANALYSIS
    r = auth_client.post(f"/api/talk/session/{sid}/end")
    assert r.status_code == 200 and r.json() == {"summary": ANALYSIS["session_summary"], "analyzed": True}
    assert auth_client.post("/api/talk/turn", json={"session_id": sid, "text": "noch was"}).status_code == 409

    r = auth_client.get("/api/talk/sessions", params={"limit": 5})
    sessions = r.json()["sessions"]
    assert [s["id"] for s in sessions] == [sid] and sessions[0]["ended_at"] is not None
    assert sessions[0]["summary"] == ANALYSIS["session_summary"] and sessions[0]["meta"]["unit_readiness"] == "not_yet"
    FakeProvider.canned = TURN
    r = auth_client.post("/api/talk/session")
    assert r.status_code == 200 and r.json()["session"]["scenario_id"] is None, "an empty body starts free conversation"


def test_llm_failure_is_a_retryable_503_with_no_partial_rows(auth_client, monkeypatch):
    from app.providers import llm as llm_mod

    FakeProvider.canned = TURN
    sid = auth_client.post("/api/talk/session", json={}).json()["session"]["id"]

    async def down(*a, **k):
        raise LLMUnavailable("The tutor is unavailable right now")

    monkeypatch.setattr(llm_mod.llm, "complete_json", down)
    r = auth_client.post("/api/talk/turn", json={"session_id": sid, "text": "Hallo"})
    assert r.status_code == 503 and r.json()["retryable"] is True
    found = auth_client.get(f"/api/talk/session/{sid}").json()
    assert len(found["messages"]) == 1 and found["session"]["user_turns"] == 0
    assert auth_client.post("/api/talk/session", json={}).status_code == 503
    assert len(auth_client.get("/api/talk/sessions").json()["sessions"]) == 1, "a failed opening leaves no session"


def test_voice_turn_returns_the_raw_transcript(auth_client, monkeypatch):
    from app.providers import stt as stt_mod

    heard = []

    async def fake_transcribe(audio, mime, filename=None):
        heard.append((audio, mime, filename))
        return stt_mod.Transcript("ich habe gegangen", "groq", "m")

    monkeypatch.setattr(stt_mod.stt, "transcribe", fake_transcribe)
    FakeProvider.canned = TURN
    sid = auth_client.post("/api/talk/session", json={}).json()["session"]["id"]
    r = auth_client.post("/api/talk/turn", data={"session_id": str(sid)},
                         files={"file": ("clip.webm", b"\x1aE\xdf\xa3fake", "audio/webm")})
    assert r.status_code == 200, r.text
    turn = r.json()
    assert turn["transcript"] == "ich habe gegangen" and turn["transcript_provider"] == "groq"
    assert heard == [(b"\x1aE\xdf\xa3fake", "audio/webm", "clip.webm")]
    user = auth_client.get(f"/api/talk/session/{sid}").json()["messages"][1]
    assert user["input_kind"] == "voice" and user["stt_provider"] == "groq"
    assert user["transcript_raw"] == "ich habe gegangen" and user["content"] == "ich habe gegangen"
    assert FakeProvider.calls[-1].messages[-1].content == "ich habe gegangen", "the raw transcript goes to the tutor as is"


def test_silent_recording_is_a_400_with_no_rows(auth_client, monkeypatch):
    from app.providers import stt as stt_mod

    async def silence(audio, mime, filename=None):
        return stt_mod.Transcript("   ", "groq", "m")

    monkeypatch.setattr(stt_mod.stt, "transcribe", silence)
    FakeProvider.canned = TURN
    sid = auth_client.post("/api/talk/session", json={}).json()["session"]["id"]
    calls = len(FakeProvider.calls)
    r = auth_client.post("/api/talk/turn", data={"session_id": str(sid)}, files={"file": ("clip.m4a", b"abc", "audio/mp4")})
    assert r.status_code == 400 and "heard" in r.json()["detail"].lower()
    r = auth_client.post("/api/talk/turn", data={"session_id": str(sid)}, files={"file": ("clip.m4a", b"", "audio/mp4")})
    assert r.status_code == 400
    assert auth_client.post("/api/talk/turn", data={"session_id": str(sid)}).status_code == 422
    found = auth_client.get(f"/api/talk/session/{sid}").json()
    assert len(found["messages"]) == 1 and found["session"]["user_turns"] == 0
    assert len(FakeProvider.calls) == calls, "no tutor call without a transcript"
