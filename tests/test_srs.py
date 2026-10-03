"""D2: SM-2 scheduling maths, the review write path, and the due queue."""
from __future__ import annotations

import time

import pytest

from app.config import settings
from app.services import srs, vocab

NOW = 1_700_000_000.0
DAY = 86400
NEW = {"interval_days": 0, "ease": 2.5, "reps": 0, "lapses": 0, "last_review": None}
MATURE = {"interval_days": 30, "ease": 2.5, "reps": 5, "lapses": 1, "last_review": NOW - 30 * DAY}
PIN = lambda: 0.5  # noqa: E731 — mid-range rng: jitter factor exactly 1.0


# -- the pure function ----------------------------------------------------------------

def test_new_card_each_rating():
    again = srs.schedule(NEW, 1, NOW, rng=PIN)
    assert again["interval_days"] == 0 and again["due"] == NOW + 600
    assert again["reps"] == 0 and again["lapses"] == 1 and again["ease"] == 2.3 and again["last_review"] == NOW

    hard = srs.schedule(NEW, 2, NOW, rng=PIN)
    assert hard["interval_days"] == 1 and hard["due"] == NOW + DAY and hard["ease"] == 2.35 and hard["reps"] == 1

    good = srs.schedule(NEW, 3, NOW, rng=PIN)
    assert good["interval_days"] == 1 and good["ease"] == 2.5 and good["reps"] == 1 and good["lapses"] == 0

    easy = srs.schedule(NEW, 4, NOW, rng=PIN)
    assert easy["interval_days"] == 1.3 and easy["due"] == NOW + 1.3 * DAY and easy["ease"] == 2.65 and easy["reps"] == 1


def test_second_good_review_jumps_to_six_days():
    once = {**NEW, "reps": 1, "interval_days": 1}
    assert srs.schedule(once, 3, NOW, rng=PIN)["interval_days"] == 6
    assert srs.schedule(once, 4, NOW, rng=PIN)["interval_days"] == pytest.approx(7.8)


def test_mature_card_each_rating():
    again = srs.schedule(MATURE, 1, NOW, rng=PIN)
    assert again["interval_days"] == 0 and again["reps"] == 0 and again["lapses"] == 2 and again["due"] == NOW + 600

    hard = srs.schedule(MATURE, 2, NOW, rng=PIN)
    assert hard["interval_days"] == 36 and hard["ease"] == 2.35 and hard["reps"] == 6 and hard["lapses"] == 1

    good = srs.schedule(MATURE, 3, NOW, rng=PIN)
    assert good["interval_days"] == 75 and good["ease"] == 2.5 and good["reps"] == 6
    assert good["due"] == NOW + 75 * DAY

    easy = srs.schedule(MATURE, 4, NOW, rng=PIN)
    assert easy["interval_days"] == pytest.approx(97.5), "easy grows the interval with the ease it had, then bumps ease"
    assert easy["ease"] == 2.65


def test_ease_floors_and_ceilings():
    low = {**MATURE, "ease": 1.35}
    assert srs.schedule(low, 1, NOW, rng=PIN)["ease"] == 1.3
    assert srs.schedule(low, 2, NOW, rng=PIN)["ease"] == 1.3
    high = {**MATURE, "ease": 2.75}
    assert srs.schedule(high, 4, NOW, rng=PIN)["ease"] == 2.8
    assert srs.schedule(high, 3, NOW, rng=PIN)["ease"] == 2.75


def test_jitter_applies_only_above_seven_days():
    short = {**NEW, "reps": 1, "interval_days": 1}  # good → 6 days: no jitter
    assert srs.schedule(short, 3, NOW, rng=lambda: 0.0)["interval_days"] == 6
    assert srs.schedule(short, 3, NOW, rng=lambda: 1.0)["interval_days"] == 6
    lo = srs.schedule(MATURE, 3, NOW, rng=lambda: 0.0)
    hi = srs.schedule(MATURE, 3, NOW, rng=lambda: 1.0)
    assert lo["interval_days"] == pytest.approx(75 * 0.9) and hi["interval_days"] == pytest.approx(75 * 1.1)
    assert lo["due"] == pytest.approx(NOW + 67.5 * DAY)


def test_invalid_rating_raises():
    for bad in (0, 5, "3"):
        with pytest.raises(ValueError):
            srs.schedule(NEW, bad, NOW)  # type: ignore[arg-type]


# -- review() --------------------------------------------------------------------------

async def test_review_updates_row_logs_and_bumps_activity(fresh_db):
    vid, _ = await vocab.upsert("der Zug (die Züge)", "train", source="tutor", now=NOW)
    card = await srs.review(vid, 3, now=NOW)
    assert card["id"] == vid and card["reps"] == 1 and card["interval_days"] == 1 and card["is_new"] is False
    row = await fresh_db.fetchone("SELECT * FROM vocab WHERE id=?", (vid,))
    assert row["due"] == NOW + DAY and row["last_review"] == NOW and row["reps"] == 1
    logged = await fresh_db.fetchall("SELECT * FROM vocab_reviews")
    assert len(logged) == 1 and logged[0]["vocab_id"] == vid and logged[0]["rating"] == 3 and logged[0]["reviewed_at"] == NOW
    day = time.strftime("%Y-%m-%d", time.gmtime())
    act = await fresh_db.fetchone("SELECT count FROM activity WHERE day=? AND kind='review'", (day,))
    assert act["count"] == 1
    again = await srs.review(vid, 1, now=NOW + DAY)
    assert again["reps"] == 0 and again["lapses"] == 1 and again["due"] == NOW + DAY + 600
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM vocab_reviews"))["n"] == 2


async def test_review_unknown_and_bad_rating(fresh_db):
    with pytest.raises(LookupError):
        await srs.review(999, 3)
    vid, _ = await vocab.upsert("x", "y")
    with pytest.raises(ValueError):
        await srs.review(vid, 9)
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM vocab_reviews"))["n"] == 0


# -- due_queue() -----------------------------------------------------------------------

async def _seed(db, *, reviewed: int, new: int, future: int = 0):
    for i in range(reviewed):
        # oldest-due first means the highest i (due furthest in the past) must come first
        await db.execute("INSERT INTO vocab (word, translation, created_at, due, reps, last_review, interval_days) "
                         "VALUES (?, 'r', ?, ?, 2, ?, 6)", (f"rev{i}", NOW, NOW - i * DAY, NOW - 7 * DAY))
    for i in range(new):
        await vocab.upsert(f"new{i}", "n", now=NOW - i)
    for i in range(future):
        await db.execute("INSERT INTO vocab (word, translation, created_at, due, reps, last_review) "
                         "VALUES (?, 'f', ?, ?, 1, ?)", (f"fut{i}", NOW, NOW + DAY, NOW))


async def test_due_queue_orders_oldest_first_and_interleaves_new(fresh_db):
    await _seed(fresh_db, reviewed=4, new=2, future=3)
    q = await srs.due_queue(limit=20, now=NOW)
    words = [c["word"] for c in q["cards"]]
    assert words == ["rev3", "rev2", "new1", "rev1", "rev0", "new0"], "every third slot is a new card, oldest due first"
    assert q["due_count"] == 6, "future cards are not due"
    assert [c["is_new"] for c in q["cards"]] == [False, False, True, False, False, True]


async def test_due_queue_caps_new_cards_and_counts_them(fresh_db, monkeypatch):
    monkeypatch.setattr(settings, "new_cards_per_review", 2)
    await _seed(fresh_db, reviewed=1, new=5)
    q = await srs.due_queue(limit=20, now=NOW)
    assert sum(c["is_new"] for c in q["cards"]) == 2 and len(q["cards"]) == 3
    assert q["due_count"] == 6, "paced new cards still count as due"
    q = await srs.due_queue(limit=20, new_cap=4, now=NOW)
    assert sum(c["is_new"] for c in q["cards"]) == 4
    only_new = await srs.due_queue(limit=2, new_cap=10, now=NOW - 1)  # rev0 and new0 are due at NOW, not yet
    assert [c["is_new"] for c in only_new["cards"]] == [True, True] and only_new["due_count"] == 4


async def test_due_queue_respects_limit(fresh_db):
    await _seed(fresh_db, reviewed=10, new=0)
    q = await srs.due_queue(limit=3, now=NOW)
    assert len(q["cards"]) == 3 and q["due_count"] == 10


# -- routes -----------------------------------------------------------------------------

def test_review_routes(auth_client):
    vid = auth_client.post("/api/vocab", json={"word": "der Bus (die Busse)", "translation": "bus"}).json()["id"]
    due = auth_client.get("/api/vocab/due", params={"limit": 5}).json()
    assert due["due_count"] == 1 and due["cards"][0]["id"] == vid and due["cards"][0]["is_new"] is True
    r = auth_client.post(f"/api/vocab/{vid}/review", json={"rating": 3})
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["reps"] == 1 and card["interval_days"] == 1 and card["is_new"] is False and "word" in card
    assert auth_client.get("/api/vocab/due").json()["due_count"] == 0
    assert auth_client.post("/api/vocab/999/review", json={"rating": 3}).status_code == 404
    assert auth_client.post(f"/api/vocab/{vid}/review", json={"rating": 5}).status_code == 422
    assert auth_client.post(f"/api/vocab/{vid}/review", json={}).status_code == 422
