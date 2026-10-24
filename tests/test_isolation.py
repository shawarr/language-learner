"""Two learners, one database: nothing one of them owns is visible to, or changeable by, the other.

Every id-taking route must answer the other learner's id exactly like a missing one (404), lists
and the progress payload must only ever contain the caller's rows, and background work (the
analyzer, stale-session cleanup) must write to the session's owner, not to whoever happens to be
current when it runs.
"""
from __future__ import annotations

import time

from app import users
from app.db import db
from app.providers.fake import FakeProvider
from app.services import analyzer, mistakes, profile, tutor
from tests.conftest import as_user, login


def _ahmad_owns_everything(client) -> dict:
    """Log in as Ahmad and create one of each thing a learner owns. Returns their ids."""
    login(client, "ahmad")
    s = client.post("/api/talk/session", json={}).json()
    sid = s["session"]["id"]
    assert client.post("/api/talk/turn", json={"session_id": sid, "text": "Ich bin Ahmad."}).status_code == 200
    vid = client.post("/api/vocab", json={"word": "der Termin", "translation": "appointment"}).json()["id"]
    drill = client.get("/api/drill/new?n=3").json()
    wid = client.post("/api/write/submit", json={"prompt": "Write to the landlord.", "text": "Hallo, die Heizung ist kaputt."}).json()["id"]
    return {"session": sid, "vocab": vid, "drill": drill["id"], "writing": wid}


def test_the_other_learners_ids_are_404(client):
    ids = _ahmad_owns_everything(client)
    login(client, "maryan")
    assert client.get(f"/api/talk/session/{ids['session']}").status_code == 404
    assert client.post("/api/talk/turn", json={"session_id": ids["session"], "text": "Hallo"}).status_code == 404
    assert client.post(f"/api/talk/session/{ids['session']}/end").status_code == 404
    assert client.post(f"/api/vocab/{ids['vocab']}/review", json={"rating": 3}).status_code == 404
    assert client.delete(f"/api/vocab/{ids['vocab']}").status_code == 404
    assert client.post(f"/api/drill/{ids['drill']}/answer", json={"index": 0, "answer": "x"}).status_code == 404
    # ...and nothing of Ahmad's was touched by the attempts.
    login(client, "ahmad")
    assert client.get(f"/api/talk/session/{ids['session']}").status_code == 200
    card = client.get("/api/vocab?q=Termin").json()["items"][0]
    assert card["id"] == ids["vocab"] and card["reps"] == 0


def test_lists_and_progress_hold_only_the_callers_rows(client):
    _ahmad_owns_everything(client)
    ahmad = {
        "sessions": client.get("/api/talk/sessions").json()["sessions"],
        "vocab": client.get("/api/vocab").json()["total"],
        "writings": client.get("/api/write/recent").json()["items"],
        "progress": client.get("/api/progress").json(),
    }
    assert ahmad["sessions"] and ahmad["vocab"] >= 1 and ahmad["writings"]
    login(client, "maryan")
    assert client.get("/api/talk/sessions").json()["sessions"] == []
    assert client.get("/api/vocab").json()["total"] == 0
    assert client.get("/api/vocab/due").json()["cards"] == []
    assert client.get("/api/write/recent").json()["items"] == []
    p = client.get("/api/progress").json()
    assert p["profile"]["name"] == "Maryan" and p["recent_sessions"] == [] and p["vocab"]["total"] == 0
    assert all(sum(v for k, v in day.items() if k != "day") == 0 for day in p["activity"])
    assert p["top_mistakes"] == []


async def test_mistakes_profile_and_activity_are_per_learner(fresh_db):
    await mistakes.record("case", "dative after mit", "mit den Bus", "mit dem Bus")
    await profile.add_facts(["Works remotely"])
    await db.bump_activity("talk_turn", 3)
    assert [m["pattern"] for m in await profile.top_mistakes()] == ["dative after mit"]
    await as_user("maryan")
    assert await profile.top_mistakes() == []
    assert (await profile.get_profile())["facts"] == []
    assert await mistakes.by_category("case") is None
    rows = await fresh_db.fetchall("SELECT user_id, count FROM activity")
    assert [(r["user_id"], r["count"]) for r in rows] == [(1, 3)]
    # The same pattern recorded for Maryan is her own row, not a bump of Ahmad's.
    await mistakes.record("case", "dative after mit", "mit die Bahn", "mit der Bahn")
    counts = await fresh_db.fetchall("SELECT user_id, count FROM mistakes ORDER BY user_id")
    assert [(r["user_id"], r["count"]) for r in counts] == [(1, 1), (2, 1)]


async def test_the_analyzer_writes_to_the_sessions_owner(fresh_db):
    await as_user("maryan")
    start = await tutor.start_session()
    sid = start["session"]["id"]
    await tutor.take_turn(sid, "Ich habe mit die Bahn gefahren.")
    # Ahmad is current when the analysis runs (it is a background task behind his request).
    await as_user("ahmad")
    FakeProvider.canned = {
        "session_summary": "Talked about the train.", "rolling_summary": "Maryan mixes up the dative.",
        "mistakes": [{"category": "case", "pattern": "dative after mit", "wrong": "mit die Bahn", "right": "mit der Bahn"}],
        "new_vocab": [{"word": "die Bahn", "translation": "the train"}],
        "skill_deltas": {"grammar": 2}, "facts": ["Studies mechanical engineering"], "unit_readiness": "not_yet"}
    assert await analyzer.analyze_session(sid) is not None
    assert users.current()["username"] == "ahmad", "the analyzer restores whoever was current"
    owners = {r["user_id"] for r in await fresh_db.fetchall("SELECT user_id FROM mistakes")}
    assert owners == {2}
    assert {r["user_id"] for r in await fresh_db.fetchall("SELECT user_id FROM vocab")} == {2}
    assert (await profile.get_profile())["rolling_summary"] == "", "Ahmad's memory is untouched"
    await as_user("maryan")
    assert (await profile.get_profile())["rolling_summary"] == "Maryan mixes up the dative."
    assert "Studies mechanical engineering" in (await profile.get_profile())["facts"]


async def test_each_learner_gets_their_own_tutor(fresh_db):
    await tutor.start_session()
    ahmad_prompt = FakeProvider.calls[-1].system
    await as_user("maryan")
    await tutor.start_session()
    maryan_prompt = FakeProvider.calls[-1].system
    assert "You are Ahmad's personal German tutor" in ahmad_prompt and "DevOps" in ahmad_prompt
    assert "You are Maryan's personal German tutor" in maryan_prompt
    assert "mechanical engineering student" in maryan_prompt and "feminine forms" in maryan_prompt
    assert "Ahmad" not in maryan_prompt and "DevOps" not in maryan_prompt


async def test_stale_sessions_of_both_learners_are_closed_by_their_owner(fresh_db):
    ids = {}
    for name in ("ahmad", "maryan"):
        await as_user(name)
        sid = (await tutor.start_session())["session"]["id"]
        await tutor.take_turn(sid, "Hallo, ich bin hier.")
        ids[name] = sid
    # Both age past the stale limit only now, so neither start_session above closed the other's.
    old = time.time() - 3 * 3600
    for sid in ids.values():
        await fresh_db.execute("UPDATE sessions SET started_at=? WHERE id=?", (old, sid))
        await fresh_db.execute("UPDATE messages SET created_at=? WHERE session_id=?", (old, sid))
    await as_user("ahmad")
    closed = await tutor.close_stale_sessions(now=time.time())
    assert sorted(closed) == sorted(ids.values())
    rows = await fresh_db.fetchall("SELECT id, user_id, ended_at FROM sessions ORDER BY id")
    assert all(r["ended_at"] for r in rows)
    assert {r["user_id"] for r in rows} == {1, 2}
    assert users.current()["username"] == "ahmad", "cleanup restores whoever was current"


def test_lessons_render_for_the_logged_in_learner(client, monkeypatch):
    """A lesson line written with {{name}} greets each learner by their own name."""
    from app.services import lessons

    raw = lessons.load()
    unit_id = next(k for k, v in raw.items() if isinstance(v, dict))
    patched = {**raw, unit_id: {**raw[unit_id], "intro": "Hallo {{name}}, {{he}} schafft das."}}
    monkeypatch.setattr(lessons, "load", lambda: patched)
    login(client, "maryan")
    assert client.get(f"/api/lesson/{unit_id}").json()["lesson"]["intro"] == "Hallo Maryan, she schafft das."
    login(client, "ahmad")
    assert client.get(f"/api/lesson/{unit_id}").json()["lesson"]["intro"] == "Hallo Ahmad, he schafft das."
