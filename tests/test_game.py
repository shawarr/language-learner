"""XP, levels, rings, streak, badges and the leaderboard — all derived from `activity` and the
per-user tables, never from a write path of their own."""
from __future__ import annotations

import datetime as dt
import json
import time

import pytest

from app.services import game
from tests.conftest import as_user, login

# A fixed clock: Wednesday 2026-10-21 12:00 UTC. The week started Monday the 19th.
NOW = dt.datetime(2026, 10, 21, 12, 0, tzinfo=dt.timezone.utc).timestamp()
TODAY = "2026-10-21"
YESTERDAY = "2026-10-20"


# -- pure maths -----------------------------------------------------------------
def test_level_curve_boundaries():
    assert [game.level_for(x)["n"] for x in (0, 99, 100, 299, 300, 599, 600, 1000)] == [1, 1, 2, 2, 3, 3, 4, 5]
    lvl = game.level_for(150)
    assert lvl["n"] == 2 and lvl["xp_into_level"] == 50 and lvl["xp_for_next"] == 200 and lvl["fraction"] == 0.25
    assert game.level_for(0) == {"n": 1, "title": "Newcomer", "xp_into_level": 0, "xp_for_next": 100, "fraction": 0.0}
    assert game.level_for(-5)["n"] == 1


def test_level_titles_by_band():
    assert game.level_for(0)["title"] == "Newcomer"
    assert game.level_for(100)["title"] == "Tourist" and game.level_for(300)["title"] == "Tourist"
    assert game.level_for(600)["title"] == "Neighbour"
    assert game.level_for(game.xp_for_level(10))["title"] == "Fluent-ish"
    assert game.level_for(game.xp_for_level(40))["title"] == "Fluent-ish"


def test_xp_from_counts_uses_the_points_table():
    assert game.xp_from_counts({"talk_turn": 3, "review": 5, "drill": 1, "write": 1, "checkpoint": 1, "lesson": 1}) == \
        30 + 10 + 15 + 25 + 60 + 40
    assert game.xp_from_counts({"unknown": 99}) == 0
    assert game.xp_from_counts({}) == 0


def test_streak_from_days():
    today = dt.date(2026, 10, 21)
    assert game.streak_from_days({"2026-10-21", "2026-10-20", "2026-10-19"}, today) == 3
    assert game.streak_from_days({"2026-10-20", "2026-10-19"}, today) == 2, "yesterday-only still counts"
    assert game.streak_from_days({"2026-10-19", "2026-10-18"}, today) == 0, "a gap of a day breaks it"
    assert game.streak_from_days({"2026-10-21", "2026-10-19"}, today) == 1
    assert game.streak_from_days(set(), today) == 0


# -- readers --------------------------------------------------------------------
async def bump(db, uid, day, kind, n):
    await db.execute("INSERT INTO activity (user_id, day, kind, count) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT(user_id, day, kind) DO UPDATE SET count = count + excluded.count",
                     (uid, day, kind, n))


async def test_xp_totals_and_week_boundary(fresh_db):
    await bump(fresh_db, 1, TODAY, "talk_turn", 3)        # 30, today, this week
    await bump(fresh_db, 1, YESTERDAY, "review", 10)      # 20, this week
    await bump(fresh_db, 1, "2026-10-19", "lesson", 1)    # 40, Monday 00:00 is in the week
    await bump(fresh_db, 1, "2026-10-18", "drill", 1)     # 15, Sunday: last week
    await bump(fresh_db, 1, "2026-09-01", "write", 1)     # 25, long ago
    await bump(fresh_db, 2, TODAY, "checkpoint", 1)       # Maryan's, must not leak in
    led = await game.ledger(1, NOW)
    assert led.xp_total == 130
    assert led.xp_week == 90
    assert led.xp_today == 30
    assert led.week_start.isoformat() == "2026-10-19"
    assert (await game.ledger(2, NOW)).xp_total == 60


async def test_goals_and_rings(fresh_db):
    assert await game.goals(1, TODAY) == {
        "speak": {"done": 0, "target": 5, "fraction": 0.0},
        "review": {"done": 0, "target": 10, "fraction": 0.0},
        "study": {"done": 0, "target": 1, "fraction": 0.0},
    }
    await bump(fresh_db, 1, TODAY, "talk_turn", 2)
    await bump(fresh_db, 1, TODAY, "review", 25)
    await bump(fresh_db, 1, TODAY, "drill", 1)
    await bump(fresh_db, 1, TODAY, "write", 1)
    g = await game.goals(1, dt.date(2026, 10, 21))
    assert g["speak"] == {"done": 2, "target": 5, "fraction": 0.4}
    assert g["review"] == {"done": 25, "target": 10, "fraction": 1.0}, "over-complete caps at 1"
    assert g["study"] == {"done": 2, "target": 1, "fraction": 1.0}
    assert game.rings_closed(g) == 2
    assert game.rings_closed(await game.goals(1, YESTERDAY)) == 0


async def test_streak_from_the_ledger(fresh_db):
    for day in ("2026-10-19", YESTERDAY, TODAY):
        await bump(fresh_db, 1, day, "talk_turn", 1)
    assert (await game.ledger(1, NOW)).streak_days == 3
    await fresh_db.execute("DELETE FROM activity WHERE day=?", (TODAY,))
    assert (await game.ledger(1, NOW)).streak_days == 2, "nothing yet today keeps yesterday's streak"
    await fresh_db.execute("DELETE FROM activity WHERE day=?", (YESTERDAY,))
    assert (await game.ledger(1, NOW)).streak_days == 0
    await bump(fresh_db, 1, TODAY, "review", 0)
    assert (await game.ledger(1, NOW)).streak_days == 0, "a zero counter is not activity"


# -- badges ---------------------------------------------------------------------
async def held(db, uid=1):
    return {r["badge_id"] for r in await db.fetchall("SELECT badge_id FROM badges WHERE user_id=?", (uid,))}


async def test_no_badges_from_nothing(fresh_db):
    assert await game.evaluate(1, NOW) == []
    assert await held(fresh_db) == set()


async def test_activity_badges(fresh_db):
    await bump(fresh_db, 1, TODAY, "talk_turn", 1)
    assert await game.evaluate(1, NOW) == ["first_talk"]
    await bump(fresh_db, 1, TODAY, "lesson", 1)
    assert await game.evaluate(1, NOW) == ["first_lesson"]
    # streaks: 3, 7, 30 — each only once its length is reached
    for i in range(1, 3):
        await bump(fresh_db, 1, (dt.date(2026, 10, 21) - dt.timedelta(days=i)).isoformat(), "review", 1)
    assert await game.evaluate(1, NOW) == ["streak_3"]
    for i in range(3, 7):
        await bump(fresh_db, 1, (dt.date(2026, 10, 21) - dt.timedelta(days=i)).isoformat(), "review", 1)
    assert await game.evaluate(1, NOW) == ["streak_7"]
    for i in range(7, 30):
        await bump(fresh_db, 1, (dt.date(2026, 10, 21) - dt.timedelta(days=i)).isoformat(), "review", 1)
    assert await game.evaluate(1, NOW) == ["streak_30"]


async def test_xp_badges(fresh_db):
    await bump(fresh_db, 1, TODAY, "talk_turn", 49)         # 490
    assert "xp_500" not in await game.evaluate(1, NOW)
    await bump(fresh_db, 1, TODAY, "talk_turn", 1)          # 500
    assert await game.evaluate(1, NOW) == ["xp_500"]
    await bump(fresh_db, 1, YESTERDAY, "checkpoint", 25)    # +1500 = 2000
    assert await game.evaluate(1, NOW) == ["xp_2000"]


async def test_vocab_badges(fresh_db):
    async def add_words(n, interval):
        for i in range(n):
            await fresh_db.execute(
                "INSERT INTO vocab (user_id, word, translation, created_at, due, interval_days) VALUES (?, ?, 'x', ?, ?, ?)",
                (1, f"wort-{interval}-{i}", NOW, NOW, interval))
    await add_words(50, 20)                                 # not mature yet
    assert await game.evaluate(1, NOW) == []
    await add_words(49, 21)
    assert await game.evaluate(1, NOW) == []
    await add_words(1, 30)
    assert await game.evaluate(1, NOW) == ["words_50"]
    await add_words(150, 60)
    assert await game.evaluate(1, NOW) == ["words_200"]


async def test_checkpoint_badges(fresh_db):
    async def checkpoint(unit, passed):
        await fresh_db.execute("INSERT INTO checkpoints (user_id, unit_id, tasks, passed, created_at, finished_at) "
                               "VALUES (1, ?, '{}', ?, ?, ?)", (unit, passed, NOW, NOW))
    await checkpoint("a1.1-1", 0)
    assert await game.evaluate(1, NOW) == [], "a failed checkpoint is not a passed one"
    await checkpoint("a1.1-1", 1)
    assert await game.evaluate(1, NOW) == ["checkpoint_first"]
    for u in ("a1.1-2", "a1.1-3", "a1.1-4"):
        await checkpoint(u, 1)
    assert await game.evaluate(1, NOW) == []
    await checkpoint("a1.1-5", 1)
    assert await game.evaluate(1, NOW) == ["units_5"]


async def test_drill_clean_badge(fresh_db):
    items = json.dumps([{"q": 1}, {"q": 2}, {"q": 3}])

    async def drill(score, finished=True):
        await fresh_db.execute("INSERT INTO drills (user_id, categories, items, score, created_at, finished_at) "
                               "VALUES (1, '[]', ?, ?, ?, ?)", (items, score, NOW, NOW if finished else None))
    await drill(2)
    await drill(3, finished=False)
    assert await game.evaluate(1, NOW) == []
    await drill(3)
    assert await game.evaluate(1, NOW) == ["drill_clean"]


async def test_early_week_badge_needs_all_three_rings_on_one_day(fresh_db):
    await bump(fresh_db, 1, YESTERDAY, "talk_turn", 5)
    await bump(fresh_db, 1, YESTERDAY, "review", 10)
    await bump(fresh_db, 1, TODAY, "lesson", 1)           # the third ring, but on another day
    assert "early_week" not in await game.evaluate(1, NOW)
    await bump(fresh_db, 1, YESTERDAY, "write", 1)
    assert "early_week" in await game.evaluate(1, NOW)


async def test_evaluate_is_idempotent_and_seen_sticks(fresh_db):
    await bump(fresh_db, 1, TODAY, "talk_turn", 1)
    assert await game.evaluate(1, NOW) == ["first_talk"]
    assert await game.evaluate(1, NOW) == []
    assert await game.new_badges(1) == ["first_talk"]
    await game.mark_seen(1, ["first_talk", "not-a-badge"])
    assert await game.new_badges(1) == []
    assert await game.evaluate(1, NOW) == [], "seen badges are not re-inserted"
    rows = await fresh_db.fetchall("SELECT badge_id, seen FROM badges WHERE user_id=1")
    assert rows == [{"badge_id": "first_talk", "seen": 1}]
    # a broken streak does not take a badge away
    await fresh_db.execute("DELETE FROM activity")
    assert await game.evaluate(1, NOW) == []
    assert await held(fresh_db) == {"first_talk"}


async def test_badges_are_per_user(fresh_db):
    await bump(fresh_db, 2, TODAY, "talk_turn", 1)
    assert await game.evaluate(1, NOW) == []
    assert await game.evaluate(2, NOW) == ["first_talk"]
    await as_user("maryan")
    body = await game.me(NOW)
    assert [b["id"] for b in body["badges"]] == ["first_talk"] and body["new_badges"] == ["first_talk"]
    assert body["badges"][0]["seen"] == 0 and body["badges"][0]["icon"] == "mic"


def test_catalogue_is_well_formed():
    ids = [b["id"] for b in game.CATALOGUE]
    assert len(ids) == len(set(ids))
    for b in game.CATALOGUE:
        assert set(b) == {"id", "title", "description", "icon"}
        assert b["icon"] in {"mic", "flame", "book", "star", "trophy", "cat"}
    assert set(ids) >= {"first_talk", "first_lesson", "streak_3", "streak_7", "streak_30", "xp_500", "xp_2000",
                        "words_50", "words_200", "checkpoint_first", "units_5", "drill_clean", "early_week"}


# -- HTTP -----------------------------------------------------------------------
def today_utc():
    return time.strftime("%Y-%m-%d", time.gmtime())


def seed_both(client):
    """Ahmad talked a lot today; Maryan passed a checkpoint and has a mistake row that must never show."""
    from app.db import db

    async def run():
        today = today_utc()
        await db.execute("INSERT INTO activity (user_id, day, kind, count) VALUES (1, ?, 'talk_turn', 6)", (today,))
        await db.execute("INSERT INTO activity (user_id, day, kind, count) VALUES (2, ?, 'checkpoint', 1)", (today,))
        await db.execute("INSERT INTO activity (user_id, day, kind, count) VALUES (2, ?, 'review', 10)", (today,))
        await db.execute("INSERT INTO checkpoints (user_id, unit_id, tasks, passed, created_at, finished_at) "
                         "VALUES (2, 'a1.1-1', '{}', 1, ?, ?)", (NOW, NOW))
        await db.execute("UPDATE profile SET level='A1.2' WHERE user_id=2")
        await db.execute("INSERT INTO mistakes (user_id, category, pattern, examples, first_seen, last_seen) "
                         "VALUES (2, 'verb_position', 'SECRET_PATTERN', '[]', ?, ?)", (NOW, NOW))
        sid = await db.execute("INSERT INTO sessions (user_id, mode, started_at) VALUES (2, 'talk', ?)", (NOW,))
        await db.execute("INSERT INTO messages (session_id, role, content, created_at) VALUES (?, 'user', 'SECRET_TRANSCRIPT', ?)",
                         (sid, NOW))
    client.portal.call(run)


def test_game_me_over_http(auth_client):
    seed_both(auth_client)
    r = auth_client.get("/api/game/me")
    assert r.status_code == 200
    body = r.json()
    assert body["xp_total"] == 60 and body["xp_today"] == 60 and body["xp_week"] == 60
    assert body["level"] == {"n": 1, "title": "Newcomer", "xp_into_level": 60, "xp_for_next": 100, "fraction": 0.6}
    assert body["streak_days"] == 1
    assert body["goals"]["speak"] == {"done": 6, "target": 5, "fraction": 1.0}
    assert body["rings_closed"] == 1
    assert [b["id"] for b in body["badges"]] == ["first_talk"] and body["new_badges"] == ["first_talk"]
    assert set(body["badges"][0]) == {"id", "title", "description", "icon", "earned_at", "seen"}
    assert body["catalogue"] == game.CATALOGUE

    r = auth_client.post("/api/game/seen", json={"badge_ids": ["first_talk"]})
    assert r.status_code == 200 and r.json() == {"ok": True}
    body = auth_client.get("/api/game/me").json()
    assert body["new_badges"] == [] and body["badges"][0]["seen"] == 1


def test_leaderboard_over_http(auth_client):
    seed_both(auth_client)
    assert auth_client.get("/api/game/me").status_code == 200   # evaluates Ahmad's badges
    r = auth_client.get("/api/leaderboard")
    assert r.status_code == 200
    body = r.json()
    assert body["me"] == 1
    assert body["week_start"] <= today_utc()
    assert dt.date.fromisoformat(body["week_start"]).weekday() == 0
    assert [u["id"] for u in body["users"]] == [2, 1], "Maryan's 80 XP this week beats Ahmad's 60"
    maryan, ahmad = body["users"]
    assert set(maryan) == {"id", "name", "avatar", "gender", "xp_week", "xp_total", "level", "streak_days", "cefr_level",
                           "units_passed", "words_mature", "rings_closed_today", "badges_count"}
    assert maryan["name"] == "Maryan" and maryan["gender"] == "f" and maryan["avatar"].startswith("katze-")
    assert maryan["xp_week"] == 80 and maryan["xp_total"] == 80 and maryan["level"] == {"n": 1, "title": "Newcomer"}
    assert maryan["cefr_level"] == "A1.2" and maryan["units_passed"] == 1 and maryan["rings_closed_today"] == 2
    assert ahmad["cefr_level"] == "A1.1" and ahmad["units_passed"] == 0 and ahmad["rings_closed_today"] == 1
    assert ahmad["badges_count"] == 1, "/game/me evaluated Ahmad; the board counts what is held"
    text = r.text
    assert "SECRET_PATTERN" not in text and "SECRET_TRANSCRIPT" not in text and "verb_position" not in text

    login(auth_client, "maryan")
    body = auth_client.get("/api/leaderboard").json()
    assert body["me"] == 2 and [u["id"] for u in body["users"]] == [2, 1]
    me = auth_client.get("/api/game/me").json()
    assert me["xp_total"] == 80 and [b["id"] for b in me["badges"]] == ["checkpoint_first"]


@pytest.mark.parametrize("method,path", [("get", "/api/game/me"), ("post", "/api/game/seen"), ("get", "/api/leaderboard")])
def test_routes_need_auth(client, method, path):
    r = getattr(client, method)(path, json={"badge_ids": []}) if method == "post" else client.get(path)
    assert r.status_code == 401
