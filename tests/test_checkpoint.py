"""C4: availability rules, one row per attempt, and a verdict the scores can overrule."""
from __future__ import annotations

import json
import time

import pytest
from fastapi import HTTPException

from app.config import settings
from app.db import loads
from app.prompts import placeholders
from app.providers.fake import FakeProvider
from app.providers.llm import LLMUnavailable
from app.services import checkpoint, curriculum, profile

SPEAK = "ich heiße ahmad ich komme aus jordanien und ich wohne in amman ich bin devops engineer"
WRITE = "Hallo zusammen! Ich bin Ahmad.\nIch komme aus Jordanien und arbeite als DevOps Engineer.\nViele Grüße"


def _grade(tc=4, rg=3, acc=3, flu=4, passed=True, focus=("Perfekt with sein",)):
    return {
        "scores": {
            "task_completion": {"score": tc, "comment": "All parts of both tasks are there."},
            "range": {"score": rg, "comment": "Uses sein and W-questions as taught."},
            "accuracy": {"score": acc, "comment": "'ich bin devops engineer' is fine; articles are missing twice."},
            "fluency": {"score": flu, "comment": "Sentences connect."},
        },
        "passed": passed,
        "summary": "You did what the tasks asked. Watch the articles.",
        "review_focus": list(focus),
    }


async def _talk_session(unit_id: str, *, ended: bool = True, meta: dict | None = None) -> int:
    from app.db import db

    now = time.time()
    return await db.execute(
        "INSERT INTO sessions (mode, unit_id, started_at, ended_at, meta) VALUES ('talk', ?, ?, ?, ?)",
        (unit_id, now - 600, now if ended else None, json.dumps(meta or {})))


def test_prompt_and_service_agree_on_placeholders():
    assert placeholders("checkpoint_grade") == {
        "level", "unit_title", "can_do", "grammar", "speaking_task", "writing_task", "words_range",
        "speaking_transcript", "writing_text"}


async def test_availability_by_ended_session_count(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "checkpoint_min_sessions", 2)
    assert await checkpoint.availability("a1.1-1") == {
        "available": False, "reason": "not_yet", "sessions_in_unit": 0, "sessions_needed": 2}
    await _talk_session("a1.1-1")
    await _talk_session("a1.1-1", ended=False)      # still open: does not count
    await _talk_session("a1.1-2")                   # another unit: does not count
    assert (await checkpoint.availability("a1.1-1"))["reason"] == "not_yet"
    await _talk_session("a1.1-1")
    a = await checkpoint.availability("a1.1-1")
    assert a == {"available": True, "reason": "sessions", "sessions_in_unit": 2, "sessions_needed": 2}
    assert await checkpoint.is_available("a1.1-1") is True and await checkpoint.is_available("a1.1-2") is False


async def test_availability_by_unit_readiness_in_meta(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "checkpoint_min_sessions", 3)
    await _talk_session("a1.1-1", ended=False, meta={"unit_readiness": "almost"})
    assert (await checkpoint.availability("a1.1-1"))["reason"] == "not_yet"
    await _talk_session("a1.1-1", ended=False, meta={"unit_readiness": "ready"})
    a = await checkpoint.availability("a1.1-1")
    assert a["available"] is True and a["reason"] == "ready" and a["sessions_in_unit"] == 0


async def test_current_creates_one_unfinished_row_and_reuses_it(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "checkpoint_min_sessions", 1)
    cur = await checkpoint.current()
    assert cur["available"] is False and cur["checkpoint_id"] is None and cur["last_result"] is None
    assert cur["unit"]["id"] == "a1.1-1" and "checkpoint" not in cur["unit"] and cur["phase"]["level"] == "A1.1"
    assert set(cur["tasks"]) == {"speaking", "writing"}
    assert cur["tasks"]["writing"]["words_min"] < cur["tasks"]["writing"]["words_max"]
    assert cur["tasks"]["speaking"]["prompt"] == curriculum.unit("a1.1-1")["checkpoint"]["speaking"]["prompt"]
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM checkpoints"))["n"] == 0

    await _talk_session("a1.1-1")
    first = await checkpoint.current()
    second = await checkpoint.current()
    assert first["available"] and first["checkpoint_id"] == second["checkpoint_id"]
    rows = await fresh_db.fetchall("SELECT * FROM checkpoints")
    assert len(rows) == 1 and rows[0]["unit_id"] == "a1.1-1" and rows[0]["finished_at"] is None
    assert loads(rows[0]["tasks"], {}) == first["tasks"]


async def test_submit_on_pass_advances_and_clears_review_focus(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "checkpoint_min_sessions", 1)
    await profile.update_profile(review_focus=["old gap"])
    await _talk_session("a1.1-1")
    cid = (await checkpoint.current())["checkpoint_id"]
    FakeProvider.canned = _grade()
    res = await checkpoint.submit(cid, SPEAK, WRITE)
    assert res["passed"] is True and res["finished_curriculum"] is False
    assert res["advanced_to"]["unit"]["id"] == "a1.1-2" and res["advanced_to"]["phase"]["id"] == "a1.1"
    assert res["advanced_to"]["phase_changed"] is False and "checkpoint" not in res["advanced_to"]["unit"]
    assert res["speaking_transcript"] == SPEAK and res["review_focus"] == ["Perfekt with sein"]
    assert set(res["scores"]) == {"task_completion", "range", "accuracy", "fluency"}
    p = await profile.get_profile()
    assert p["unit_id"] == "a1.1-2" and p["review_focus"] == []
    row = await fresh_db.fetchone("SELECT * FROM checkpoints WHERE id=?", (cid,))
    assert row["passed"] == 1 and row["finished_at"] is not None
    assert row["speaking_transcript"] == SPEAK and row["writing_text"] == WRITE
    assert loads(row["result"], {})["scores"] == res["scores"]
    day = time.strftime("%Y-%m-%d", time.gmtime())
    assert (await fresh_db.fetchone("SELECT count FROM activity WHERE day=? AND kind='checkpoint'", (day,)))["count"] == 1
    # The grader saw the raw transcript, the written text and the unit's goals, on the quality tier.
    sent = FakeProvider.calls[-1]
    assert SPEAK in sent.system and WRITE in sent.system and "Hallo und Tschüss" in sent.system
    assert sent.json_schema is checkpoint.GRADE_SCHEMA
    # The result stays with the unit it graded; the new unit starts with a clean slate.
    assert (await checkpoint.last_result("a1.1-1"))["passed"] is True
    assert (await checkpoint.current())["last_result"] is None


async def test_submit_on_fail_writes_review_focus_and_stays(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "checkpoint_min_sessions", 1)
    await _talk_session("a1.1-1")
    cid = (await checkpoint.current())["checkpoint_id"]
    FakeProvider.canned = _grade(acc=2, passed=False, focus=("articles with nouns", "sein forms", "x", "too many"))
    res = await checkpoint.submit(cid, SPEAK, WRITE)
    assert res["passed"] is False and res["advanced_to"] is None and res["finished_curriculum"] is False
    assert res["review_focus"] == ["articles with nouns", "sein forms", "x"]
    p = await profile.get_profile()
    assert p["unit_id"] == "a1.1-1" and p["review_focus"] == ["articles with nouns", "sein forms", "x"]
    assert (await fresh_db.fetchone("SELECT passed FROM checkpoints WHERE id=?", (cid,)))["passed"] == 0
    cur = await checkpoint.current()
    assert cur["last_result"]["passed"] is False and cur["last_result"]["summary"] == res["summary"]
    # Retake: a fresh unfinished row, the failed one untouched.
    assert cur["checkpoint_id"] != cid
    rows = await fresh_db.fetchall("SELECT id, finished_at FROM checkpoints ORDER BY id")
    assert len(rows) == 2 and rows[0]["finished_at"] is not None and rows[1]["finished_at"] is None
    FakeProvider.canned = _grade()
    assert (await checkpoint.submit(cur["checkpoint_id"], SPEAK, WRITE))["passed"] is True
    assert (await profile.get_profile())["unit_id"] == "a1.1-2"


async def test_model_passed_with_a_low_score_is_downgraded(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "checkpoint_min_sessions", 1)
    await _talk_session("a1.1-1")
    cid = (await checkpoint.current())["checkpoint_id"]
    FakeProvider.canned = _grade(rg=2, passed=True)
    res = await checkpoint.submit(cid, SPEAK, WRITE)
    assert res["passed"] is False and res["advanced_to"] is None
    assert (await profile.get_profile())["unit_id"] == "a1.1-1"
    assert (await fresh_db.fetchone("SELECT passed FROM checkpoints WHERE id=?", (cid,)))["passed"] == 0


def test_validate_grade_never_trusts_the_shape():
    out = checkpoint.validate_grade({"scores": "great", "passed": "yes", "summary": 5, "review_focus": "dative"})
    assert all(out["scores"][d] == {"score": 1, "comment": ""} for d in checkpoint.DIMENSIONS)
    assert out["passed"] is False and out["summary"] and out["review_focus"] == []
    out = checkpoint.validate_grade({"scores": {"task_completion": {"score": 9}, "range": {"score": "4"},
                                                "accuracy": {"score": True}, "fluency": {"score": -2, "comment": "  a  b "}},
                                     "passed": True})
    assert [out["scores"][d]["score"] for d in checkpoint.DIMENSIONS] == [5, 4, 1, 1]
    assert out["scores"]["fluency"]["comment"] == "a b" and out["passed"] is False
    good = {d: {"score": 3, "comment": "c"} for d in checkpoint.DIMENSIONS}
    assert checkpoint.validate_grade({"scores": good, "passed": True})["passed"] is True
    assert checkpoint.validate_grade({"scores": good, "passed": False})["passed"] is False
    low_tc = {**good, "task_completion": {"score": 2, "comment": "c"}}
    assert checkpoint.validate_grade({"scores": low_tc, "passed": True})["passed"] is False


async def test_malformed_scores_never_500_and_errors_leave_the_row_open(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "checkpoint_min_sessions", 1)
    await _talk_session("a1.1-1")
    cid = (await checkpoint.current())["checkpoint_id"]
    FakeProvider.canned = {"scores": [1, 2, 3], "passed": True, "summary": None, "review_focus": None}
    res = await checkpoint.submit(cid, SPEAK, WRITE)
    assert res["passed"] is False and res["summary"] and res["review_focus"] == []
    assert (await profile.get_profile())["unit_id"] == "a1.1-1"

    cid2 = (await checkpoint.current())["checkpoint_id"]
    FakeProvider.canned = "this is not json at all {"
    with pytest.raises(LLMUnavailable):
        await checkpoint.submit(cid2, SPEAK, WRITE)
    row = await fresh_db.fetchone("SELECT * FROM checkpoints WHERE id=?", (cid2,))
    assert row["finished_at"] is None and row["speaking_transcript"] is None and row["result"] is None
    assert (await checkpoint.current())["checkpoint_id"] == cid2


async def test_submit_guards(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "checkpoint_min_sessions", 1)
    with pytest.raises(HTTPException) as e:
        await checkpoint.submit(999, SPEAK, WRITE)
    assert e.value.status_code == 404
    await _talk_session("a1.1-1")
    cid = (await checkpoint.current())["checkpoint_id"]
    for sp, wr in (("", WRITE), (SPEAK, "  "), ("", "")):
        with pytest.raises(HTTPException) as e:
            await checkpoint.submit(cid, sp, wr)
        assert e.value.status_code == 400
    assert FakeProvider.calls == []
    FakeProvider.canned = _grade()
    await checkpoint.submit(cid, SPEAK, WRITE)
    with pytest.raises(HTTPException) as e:
        await checkpoint.submit(cid, SPEAK, WRITE)
    assert e.value.status_code == 409
    # A stale open row from a unit he already left cannot advance him again.
    stale = await fresh_db.execute("INSERT INTO checkpoints (unit_id, tasks, created_at) VALUES ('a1.1-1', '{}', ?)",
                                   (time.time(),))
    with pytest.raises(HTTPException) as e:
        await checkpoint.submit(stale, SPEAK, WRITE)
    assert e.value.status_code == 409


async def test_pass_on_the_last_unit_finishes_the_curriculum(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "checkpoint_min_sessions", 1)
    last = curriculum.all_units()[-1]
    await profile.update_profile(unit_id=last["id"], level="B1.2", review_focus=["x"])
    await _talk_session(last["id"])
    cid = (await checkpoint.current())["checkpoint_id"]
    FakeProvider.canned = _grade()
    res = await checkpoint.submit(cid, SPEAK, WRITE)
    assert res["passed"] is True and res["finished_curriculum"] is True and res["advanced_to"] is None
    p = await profile.get_profile()
    assert p["unit_id"] == last["id"] and p["review_focus"] == []


def test_routes(auth_client, client, monkeypatch):
    monkeypatch.setattr(settings, "checkpoint_min_sessions", 0)
    cur = auth_client.get("/api/checkpoint/current")
    assert cur.status_code == 200, cur.text
    body = cur.json()
    assert set(body) == {"available", "reason", "unit", "phase", "checkpoint_id", "tasks", "sessions_in_unit",
                         "sessions_needed", "last_result"}
    assert body["available"] is True and body["reason"] == "sessions" and body["checkpoint_id"]
    cid = body["checkpoint_id"]
    assert auth_client.post(f"/api/checkpoint/{cid}/submit", data={"writing_text": WRITE}).status_code == 400
    FakeProvider.canned = _grade()
    r = auth_client.post(f"/api/checkpoint/{cid}/submit", data={"writing_text": WRITE, "speaking_text": SPEAK})
    assert r.status_code == 200, r.text
    res = r.json()
    assert set(res) == {"passed", "scores", "summary", "review_focus", "speaking_transcript", "advanced_to",
                        "finished_curriculum"}
    assert res["passed"] is True and res["advanced_to"]["unit"]["id"] == "a1.1-2"
    assert auth_client.get("/api/curriculum/current").json()["unit"]["id"] == "a1.1-2"
    assert auth_client.post(f"/api/checkpoint/{cid}/submit", data={"writing_text": WRITE, "speaking_text": SPEAK}).status_code == 409
    assert auth_client.post("/api/checkpoint/999/submit", data={"writing_text": WRITE, "speaking_text": SPEAK}).status_code == 404

    # Speaking as audio: the raw transcript is what gets graded and returned.
    from app.providers import stt as stt_mod

    async def fake_transcribe(audio, mime, filename=None):
        return stt_mod.Transcript("ich habe gestern in die stadt gegangen", "groq", "m")

    monkeypatch.setattr(stt_mod.stt, "transcribe", fake_transcribe)
    cid2 = auth_client.get("/api/checkpoint/current").json()["checkpoint_id"]
    r = auth_client.post(f"/api/checkpoint/{cid2}/submit", data={"writing_text": WRITE},
                         files={"file": ("clip.webm", b"fake-audio", "audio/webm")})
    assert r.status_code == 200, r.text
    assert r.json()["speaking_transcript"] == "ich habe gestern in die stadt gegangen"
    assert "ich habe gestern in die stadt gegangen" in FakeProvider.calls[-1].system

    client.cookies.clear()
    assert client.get("/api/checkpoint/current").status_code == 401
    assert client.post("/api/checkpoint/1/submit", data={"writing_text": "x", "speaking_text": "y"}).status_code == 401
