"""E: the progress payload — streak maths, a 30-day strip with zeros, honest counts and trends."""
from __future__ import annotations

import datetime as dt
import json
import time

from app.services import mistakes, progress, vocab

NOW = 1_700_000_000.0
DAY = 86400
TODAY = dt.datetime.fromtimestamp(NOW, dt.timezone.utc).date()
KEYS = {"profile", "phase", "unit", "unit_index", "unit_count", "skills", "streak_days", "activity", "top_mistakes",
        "beaten_mistakes", "vocab", "recent_sessions", "checkpoint", "sessions_total", "thin_data"}


def day(offset: int) -> str:
    return (TODAY - dt.timedelta(days=offset)).isoformat()


async def bump(db, offset: int, kind: str = "talk_turn", n: int = 1):
    await db.execute("INSERT INTO activity (day, kind, count) VALUES (?, ?, ?) "
                     "ON CONFLICT(day, kind) DO UPDATE SET count = count + excluded.count", (day(offset), kind, n))


def test_streak_maths():
    s = progress.streak_days
    assert s(set(), TODAY) == 0
    assert s({day(0)}, TODAY) == 1
    assert s({day(0), day(1), day(2)}, TODAY) == 3
    assert s({day(1), day(2)}, TODAY) == 2, "nothing yet today: the streak still stands from yesterday"
    assert s({day(2), day(3)}, TODAY) == 0, "a gap of a full day breaks it"
    assert s({day(0), day(1), day(3)}, TODAY) == 2


async def test_streak_counts_days_with_activity_only(fresh_db):
    await bump(fresh_db, 0)
    await bump(fresh_db, 1, "review", 3)
    await bump(fresh_db, 2, "drill", 0)  # a zero row is not activity
    await bump(fresh_db, 3)
    assert (await progress.payload(now=NOW))["streak_days"] == 2


async def test_activity_strip_has_thirty_days_with_zeros(fresh_db):
    await bump(fresh_db, 0, "write", 2)
    await bump(fresh_db, 29, "review", 5)
    await bump(fresh_db, 30, "review", 9)  # just outside the window
    await bump(fresh_db, 5, "bogus_kind", 9)
    strip = (await progress.payload(now=NOW))["activity"]
    assert len(strip) == 30 and strip[0]["day"] == day(29) and strip[-1]["day"] == day(0)
    assert all(set(e) == {"day", "talk_turn", "review", "drill", "write", "checkpoint"} for e in strip)
    assert strip[-1]["write"] == 2 and strip[-1]["talk_turn"] == 0
    assert strip[0]["review"] == 5 and sum(e["review"] for e in strip) == 5
    assert all(e["drill"] == 0 for e in strip)


async def test_vocab_counts(fresh_db):
    await vocab.upsert("neu", "new", now=NOW)                                   # new and due
    await vocab.upsert("später", "later", now=NOW)
    await fresh_db.execute("UPDATE vocab SET due=? WHERE word='später'", (NOW + DAY,))    # new, not due
    await fresh_db.execute("INSERT INTO vocab (word, translation, created_at, due, interval_days, reps, last_review) "
                           "VALUES ('reif', 'mature', ?, ?, 30, 6, ?)", (NOW, NOW - DAY, NOW - 31 * DAY))
    await fresh_db.execute("INSERT INTO vocab (word, translation, created_at, due, interval_days, reps, last_review) "
                           "VALUES ('jung', 'young', ?, ?, 6, 2, ?)", (NOW, NOW + 3 * DAY, NOW - 3 * DAY))
    assert (await progress.payload(now=NOW))["vocab"] == {"total": 4, "due": 2, "mature": 1, "new": 2}


async def test_mistake_trends_and_beaten(fresh_db):
    half = await mistakes.record("case", "dative after mit", "mit den", "mit dem", now=NOW)
    await mistakes.record("case", "dative after mit", "mit den", "mit dem", now=NOW)
    await mistakes.resolve(half)                                            # 1 of 2 resolved → improving
    fresh = await mistakes.record("gender", "Termin", "das Termin", "der Termin", now=NOW)
    for _ in range(3):
        await mistakes.record("gender", "Termin", "das Termin", "der Termin", now=NOW)
    await mistakes.resolve(fresh)                                           # 1 of 4, seen today → not yet
    quiet = await mistakes.record("word_order", "verb second", "w", "r", now=NOW - 10 * DAY)
    for _ in range(3):
        await mistakes.record("word_order", "verb second", "w", "r", now=NOW - 10 * DAY)
    await mistakes.resolve(quiet)                                           # 1 of 4 but quiet for 10 days → improving
    untouched = await mistakes.record("plural", "Busse", "w", "r", now=NOW - 30 * DAY)
    beaten = await mistakes.record("article", "ein/eine", "w", "r", now=NOW)
    await mistakes.resolve(beaten)
    out = await progress.payload(now=NOW)
    trends = {m["id"]: m["trend"] for m in out["top_mistakes"]}
    assert trends == {half: "improving", fresh: "not_yet", quiet: "improving", untouched: "not_yet"}
    assert [m["id"] for m in out["beaten_mistakes"]] == [beaten]
    assert isinstance(out["top_mistakes"][0]["examples"], list)


async def test_thin_data_sessions_and_profile_fields(fresh_db):
    out = await progress.payload(now=NOW)
    assert set(out) == KEYS
    assert out["sessions_total"] == 0 and out["thin_data"] is True and out["streak_days"] == 0
    assert set(out["profile"]) == {"name", "level", "unit_id", "placement_done", "rolling_summary"}
    assert set(out["skills"]) == {"speaking", "listening", "writing", "grammar", "vocab"}
    assert out["unit"]["id"] == out["profile"]["unit_id"] and "checkpoint" not in out["unit"]
    assert out["phase"]["id"] == "a1.1" and out["unit_index"] == 1 and out["unit_count"] >= 1
    assert out["checkpoint"] == {"available": False, "unit_id": out["unit"]["id"], "reason": "not_yet"}
    assert out["recent_sessions"] == [] and out["beaten_mistakes"] == [] and out["top_mistakes"] == []

    for i in range(5):
        await fresh_db.execute(
            "INSERT INTO sessions (mode, unit_id, started_at, ended_at, meta) VALUES (?, 'a1.1-1', ?, ?, ?)",
            ("talk" if i < 4 else "placement", NOW - i * 100, NOW - i * 100 + 50 if i != 3 else None,
             json.dumps({"unit_readiness": "ready"})))
    out = await progress.payload(now=NOW)
    assert out["sessions_total"] == 3, "only ended talk sessions count"
    assert out["thin_data"] is True
    await fresh_db.execute("UPDATE sessions SET ended_at=? WHERE ended_at IS NULL", (NOW,))
    out = await progress.payload(now=NOW)
    assert out["sessions_total"] == 4 and out["thin_data"] is False
    assert len(out["recent_sessions"]) == 5 and out["recent_sessions"][0]["started_at"] == NOW
    assert out["recent_sessions"][0]["meta"] == {"unit_readiness": "ready"}
    assert set(out["recent_sessions"][0]) == {"id", "mode", "scenario_id", "scenario_title", "unit_id", "started_at",
                                              "ended_at", "summary", "user_turns", "meta"}


async def test_checkpoint_uses_c4_availability_when_it_exists(fresh_db, monkeypatch):
    from app.services import checkpoint

    assert not hasattr(checkpoint, "availability"), "the stub: the fallback path is what the other tests cover"

    async def availability(unit_id):
        return {"available": True, "reason": "sessions", "sessions_in_unit": 3, "sessions_needed": 3}

    monkeypatch.setattr(checkpoint, "availability", availability, raising=False)
    out = await progress.payload(now=NOW)
    assert out["checkpoint"] == {"available": True, "unit_id": out["unit"]["id"], "reason": "sessions",
                                 "sessions_in_unit": 3, "sessions_needed": 3}

    async def not_yet(unit_id):
        return {"available": False, "reason": "not_yet"}

    monkeypatch.setattr(checkpoint, "availability", not_yet, raising=False)
    assert (await progress.payload(now=NOW))["checkpoint"] == {"available": False, "unit_id": out["unit"]["id"],
                                                               "reason": "not_yet"}


def test_progress_route(auth_client):
    r = auth_client.get("/api/progress")
    assert r.status_code == 200 and set(r.json()) == KEYS
    assert len(r.json()["activity"]) == 30
    assert r.json()["activity"][-1]["day"] == time.strftime("%Y-%m-%d", time.gmtime())


def test_progress_route_needs_auth(client):
    assert client.get("/api/progress").status_code == 401
