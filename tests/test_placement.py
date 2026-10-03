"""C3: the placement stores raw answers, grades once, writes the profile, and never trusts the model blindly."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.db import loads
from app.prompts import placeholders
from app.providers.fake import FakeProvider
from app.services import placement, profile

GRADED = {
    "level": "A2.1",
    "skills": {"speaking": 35, "listening": 30, "writing": 28, "grammar": 25, "vocab": 33},
    "explanation": "You landed at A2.1 because your work-day description held together in full sentences.",
    "strengths": ["present tense word order", "work vocabulary"],
    "gaps": ["Perfekt with sein", "dative after mit"],
    "facts": ["Works with Kubernetes and Terraform", "Plays football on Fridays"],
}


async def _answer_all(sid: int) -> None:
    await placement.answer(sid, "intro", "Ich heiße Ahmad und ich komme aus Jordanien.")
    await placement.answer(sid, "workday", "Ich fange um neun Uhr an. Ich habe viele Meetings.")
    await placement.answer(sid, "problem", "Letzte Woche der Server ist kaputt. Ich habe neu gestartet.")
    await placement.answer(sid, "message", "Hallo Jonas, ich kann morgen nicht kommen. Passt Donnerstag?")


def test_prompt_and_service_agree_on_placeholders():
    assert placeholders("placement") == {"answered", "answers"}


async def test_start_creates_a_placement_session_with_four_tasks(fresh_db):
    out = await placement.start()
    assert [t["kind"] for t in out["tasks"]] == ["speak", "speak", "speak", "write"]
    assert all({"id", "kind", "title", "instruction_en", "prompt_de"} <= set(t) for t in out["tasks"])
    row = await fresh_db.fetchone("SELECT * FROM sessions WHERE id=?", (out["session_id"],))
    assert row["mode"] == "placement" and row["ended_at"] is None
    # Re-runnable: a second start works even once placement is done.
    await profile.update_profile(placement_done=1)
    assert (await placement.start())["session_id"] != out["session_id"]


async def test_answer_stores_text_and_a_re_answer_replaces_it(fresh_db):
    sid = (await placement.start())["session_id"]
    out = await placement.answer(sid, "intro", "  Ich bin   Ahmad. ")
    assert out == {"task_id": "intro", "text": "Ich bin Ahmad.", "transcript_provider": None}
    await placement.answer(sid, "intro", "Ich heiße Ahmad.")
    row = await fresh_db.fetchone("SELECT * FROM sessions WHERE id=?", (sid,))
    meta = loads(row["meta"], {})
    assert meta["answers"] == {"intro": {"text": "Ich heiße Ahmad.", "kind": "text", "provider": None}}
    assert row["user_turns"] == 2
    msgs = await fresh_db.fetchall("SELECT * FROM messages WHERE session_id=? ORDER BY id", (sid,))
    assert [m["content"] for m in msgs] == ["Ich bin Ahmad.", "Ich heiße Ahmad."]
    assert msgs[0]["role"] == "user" and msgs[0]["input_kind"] == "text" and msgs[0]["transcript_raw"] is None
    # Voice answers keep the raw transcript on the message row.
    await placement.answer(sid, "workday", "ich arbeite als devops", input_kind="voice", stt_provider="groq")
    m = await fresh_db.fetchone("SELECT * FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 1", (sid,))
    assert m["transcript_raw"] == "ich arbeite als devops" and m["input_kind"] == "voice" and m["stt_provider"] == "groq"


async def test_unknown_task_or_session_is_404_and_empty_answer_400(fresh_db):
    sid = (await placement.start())["session_id"]
    with pytest.raises(HTTPException) as e:
        await placement.answer(sid, "nope", "x")
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await placement.answer(sid + 99, "intro", "x")
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await placement.answer(sid, "intro", "   ")
    assert e.value.status_code == 400


async def test_finish_grades_writes_profile_and_is_idempotent(fresh_db):
    FakeProvider.canned = GRADED
    sid = (await placement.start())["session_id"]
    await _answer_all(sid)
    res = await placement.finish(sid)
    assert res["level"] == "A2.1" and res["unit"]["id"] == "a2.1-1" and res["phase"]["id"] == "a2.1"
    assert res["skills"] == GRADED["skills"] and res["skipped"] is False
    assert res["strengths"] == GRADED["strengths"] and res["gaps"] == GRADED["gaps"]
    assert "checkpoint" not in res["unit"]
    p = await profile.get_profile()
    assert p["level"] == "A2.1" and p["unit_id"] == "a2.1-1" and p["placement_done"] == 1
    assert p["skills"] == GRADED["skills"]
    assert p["facts"] == ["Works with Kubernetes and Terraform", "Plays football on Fridays"]
    row = await fresh_db.fetchone("SELECT * FROM sessions WHERE id=?", (sid,))
    assert row["ended_at"] is not None and row["summary"] == GRADED["explanation"]
    assert loads(row["meta"], {})["result"] == res
    # The grading prompt saw the raw answers and used the quality tier's chain.
    sent = FakeProvider.calls[-1]
    assert "Letzte Woche der Server ist kaputt" in sent.system and "4 of 4" in sent.system
    assert sent.json_schema is placement.PLACEMENT_SCHEMA

    calls_before = len(FakeProvider.calls)
    FakeProvider.canned = {**GRADED, "level": "B1.2"}  # would change the verdict if it were re-graded
    again = await placement.finish(sid)
    assert again == res and len(FakeProvider.calls) == calls_before
    assert (await profile.get_profile())["level"] == "A2.1"


async def test_finish_without_answers_is_400(fresh_db):
    sid = (await placement.start())["session_id"]
    with pytest.raises(HTTPException) as e:
        await placement.finish(sid)
    assert e.value.status_code == 400
    assert FakeProvider.calls == []


async def test_invalid_level_falls_back_to_a11_and_garbage_fields_are_sanitised(fresh_db):
    FakeProvider.canned = {"level": "C2", "skills": "high", "explanation": "", "strengths": "x",
                           "gaps": ["", 3, " dative "], "facts": None}
    sid = (await placement.start())["session_id"]
    await _answer_all(sid)
    res = await placement.finish(sid)
    assert res["level"] == "A1.1" and res["unit"]["id"] == "a1.1-1"
    assert res["skills"] == {k: placement.SKILL_BASELINE["A1.1"] for k in profile.SKILLS}
    assert res["explanation"] and res["strengths"] == [] and res["gaps"] == ["dative"]
    p = await profile.get_profile()
    assert p["level"] == "A1.1" and p["facts"] == []


def test_validate_clamps_skills_and_caps_level_on_thin_evidence():
    out = placement.validate_result({"level": "b1.1", "skills": {"speaking": 140, "grammar": -5, "vocab": True}},
                                    answered=4)
    assert out["level"] == "B1.1"
    assert out["skills"]["speaking"] == 100 and out["skills"]["grammar"] == 0
    assert out["skills"]["vocab"] == placement.SKILL_BASELINE["B1.1"]
    assert placement.validate_result({"level": "B1.1"}, answered=1)["level"] == "A1.2"
    assert placement.validate_result({"level": "A1.1"}, answered=1)["level"] == "A1.1"


async def test_fewer_than_two_answers_caps_the_level_at_a12(fresh_db):
    FakeProvider.canned = {**GRADED, "level": "A2.2"}
    sid = (await placement.start())["session_id"]
    await placement.answer(sid, "problem", "Letzte Woche habe ich einen Fehler im Deployment gefunden und behoben.")
    res = await placement.finish(sid)
    assert res["level"] == "A1.2" and res["unit"]["id"] == "a1.2-1"
    assert (await profile.get_profile())["unit_id"] == "a1.2-1"


async def test_skip_sets_a11_and_placement_done(fresh_db):
    await profile.update_profile(level="B1.1", unit_id="b1.1-3")
    res = await placement.skip()
    assert res["level"] == "A1.1" and res["unit"]["id"] == "a1.1-1" and res["skipped"] is True
    assert res["phase"]["level"] == "A1.1" and res["strengths"] == [] and res["gaps"] == []
    p = await profile.get_profile()
    assert p["level"] == "A1.1" and p["unit_id"] == "a1.1-1" and p["placement_done"] == 1
    assert res["skills"] == p["skills"]
    assert FakeProvider.calls == []
    assert await placement.status() == {"placement_done": True, "level": "A1.1", "unit_id": "a1.1-1"}


def test_routes_need_auth(client):
    assert client.post("/api/placement/start").status_code == 401
    assert client.get("/api/placement/status").status_code == 401
    assert client.post("/api/placement/skip").status_code == 401


def test_routes_end_to_end_with_text(auth_client):
    st = auth_client.get("/api/placement/status").json()
    assert st == {"placement_done": False, "level": "A1.1", "unit_id": "a1.1-1"}
    start = auth_client.post("/api/placement/start").json()
    sid = start["session_id"]
    assert len(start["tasks"]) == 4
    r = auth_client.post("/api/placement/answer", json={"session_id": sid, "task_id": "intro", "text": "Ich bin Ahmad."})
    assert r.status_code == 200 and r.json() == {"task_id": "intro", "text": "Ich bin Ahmad.", "transcript_provider": None}
    assert auth_client.post("/api/placement/answer", json={"session_id": sid, "task_id": "zzz", "text": "x"}).status_code == 404
    assert auth_client.post("/api/placement/answer", json={"session_id": "abc", "task_id": "intro", "text": "x"}).status_code == 400
    auth_client.post("/api/placement/answer", json={"session_id": sid, "task_id": "message", "text": "Hallo, morgen geht nicht."})
    FakeProvider.canned = GRADED
    r = auth_client.post("/api/placement/finish", json={"session_id": sid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"level", "unit", "phase", "skills", "explanation", "strengths", "gaps", "skipped"}
    assert body["level"] == "A2.1"
    assert auth_client.get("/api/placement/status").json() == {"placement_done": True, "level": "A2.1", "unit_id": "a2.1-1"}
    assert auth_client.post("/api/placement/finish", json={"session_id": sid + 1}).status_code == 404
    assert auth_client.post("/api/placement/skip").json()["skipped"] is True
    assert auth_client.get("/api/curriculum/current").json()["unit"]["id"] == "a1.1-1"


def test_multipart_answer_stores_the_raw_transcript(auth_client, monkeypatch):
    from app.providers import stt as stt_mod

    async def fake_transcribe(audio, mime, filename=None):
        assert audio == b"fake-audio"
        return stt_mod.Transcript("ich bin Ahmad", "groq", "m")

    monkeypatch.setattr(stt_mod.stt, "transcribe", fake_transcribe)
    sid = auth_client.post("/api/placement/start").json()["session_id"]
    r = auth_client.post("/api/placement/answer", data={"session_id": str(sid), "task_id": "intro"},
                         files={"file": ("clip.webm", b"fake-audio", "audio/webm")})
    assert r.status_code == 200, r.text
    assert r.json() == {"task_id": "intro", "text": "ich bin Ahmad", "transcript_provider": "groq"}

    async def silence(audio, mime, filename=None):
        return stt_mod.Transcript("   ", "groq", "m")

    monkeypatch.setattr(stt_mod.stt, "transcribe", silence)
    r = auth_client.post("/api/placement/answer", data={"session_id": str(sid), "task_id": "workday"},
                         files={"file": ("clip.webm", b"fake-audio", "audio/webm")})
    assert r.status_code == 400
    r = auth_client.post("/api/placement/answer", data={"session_id": str(sid), "task_id": "workday"},
                         files={"file": ("clip.webm", b"", "audio/webm")})
    assert r.status_code == 400
    # No transcript, no answer stored: grading sees only the one voice answer, raw.
    FakeProvider.canned = GRADED
    assert auth_client.post("/api/placement/finish", json={"session_id": sid}).status_code == 200
    sent = FakeProvider.calls[-1].system
    assert "1 of 4" in sent and "transcribed by groq" in sent and "ich bin Ahmad" in sent
