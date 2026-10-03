"""Spaced repetition for the vocab table: SM-2 with four ratings (1 again, 2 hard, 3 good, 4 easy).

`schedule` is a pure function of (card, rating, now) so the maths is testable without a database;
`review` applies it to a row and `due_queue` builds what the Review screen shows. The SRS columns
live on `vocab` itself (db.py), and `vocab.upsert` never touches them.
"""
from __future__ import annotations

import random
import time

from ..config import settings
from ..db import db
from . import vocab as vocab_svc

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
RATINGS = (AGAIN, HARD, GOOD, EASY)

AGAIN_DELAY_SECONDS = 600          # "again" comes back in the same sitting, not tomorrow
EASE_MIN, EASE_MAX = 1.3, 2.8
JITTER_ABOVE_DAYS = 7
JITTER = 0.10                      # ±10 %: a big review day must not recur as a big day forever
NEW_EVERY = 3                      # a new card in every third slot of the queue


def schedule(card: dict, rating: int, now: float, rng=random.random) -> dict:
    """The new SRS fields for `card` after `rating`. Raises ValueError on a rating outside 1..4."""
    if rating not in RATINGS:
        raise ValueError(f"rating must be 1-4, got {rating!r}")
    interval = float(card.get("interval_days") or 0)
    ease = float(card.get("ease") or 2.5)
    reps = int(card.get("reps") or 0)
    lapses = int(card.get("lapses") or 0)

    if rating == AGAIN:
        # Back to the start of the ladder; the lapse count is what tells "leech" cards apart later.
        return {"due": now + AGAIN_DELAY_SECONDS, "interval_days": 0.0, "ease": _round(max(EASE_MIN, ease - 0.20)),
                "reps": 0, "lapses": lapses + 1, "last_review": now}

    if rating == HARD:
        interval = max(1.0, interval * 1.2)
        ease = max(EASE_MIN, ease - 0.15)
    else:
        # good: the classic 1 → 6 → interval × ease ladder; easy uses the ease it had, then grows it.
        interval = 1.0 if reps == 0 else (6.0 if reps == 1 else interval * ease)
        if rating == EASY:
            interval *= 1.3
            ease = min(EASE_MAX, ease + 0.15)
    if interval > JITTER_ABOVE_DAYS:
        interval *= 1 + (rng() * 2 - 1) * JITTER
    interval = _round(interval)
    return {"due": now + interval * 86400, "interval_days": interval, "ease": _round(ease),
            "reps": reps + 1, "lapses": lapses, "last_review": now}


def _round(x: float) -> float:
    return round(x, 3)


async def review(vocab_id: int, rating: int, now: float | None = None) -> dict:
    """Apply one rating: update the row, log it in vocab_reviews, count it as activity. Returns the card."""
    rating = int(rating)
    now = now or time.time()
    row = await db.fetchone("SELECT * FROM vocab WHERE id=?", (vocab_id,))
    if row is None:
        raise LookupError(f"no vocab row {vocab_id}")
    new = schedule(row, rating, now)
    await db.conn.execute(
        "UPDATE vocab SET due=?, interval_days=?, ease=?, reps=?, lapses=?, last_review=? WHERE id=?",
        (new["due"], new["interval_days"], new["ease"], new["reps"], new["lapses"], new["last_review"], vocab_id))
    await db.conn.execute("INSERT INTO vocab_reviews (vocab_id, rating, reviewed_at) VALUES (?, ?, ?)",
                          (vocab_id, rating, now))
    await db.conn.commit()
    await db.bump_activity("review")
    return vocab_svc.card({**row, **new})


async def due_queue(limit: int = 20, new_cap: int | None = None, now: float | None = None) -> dict:
    """docs/API.md GET /vocab/due: {"cards": [...], "due_count": n}.

    Cards already in rotation come oldest-due first; never-reviewed cards are interleaved one in
    every third slot and capped per queue, so a chatty tutor day does not turn into a 60-card wall.
    `due_count` is everything due right now, including new cards beyond the cap — those are paced,
    not hidden.
    """
    now = now or time.time()
    limit = max(1, min(int(limit), 200))
    new_cap = settings.new_cards_per_review if new_cap is None else max(0, int(new_cap))
    new_filter = "reps = 0 AND last_review IS NULL"
    total = (await db.fetchone("SELECT COUNT(*) AS n FROM vocab WHERE due <= ?", (now,)))["n"]
    in_rotation = await db.fetchall(
        f"SELECT * FROM vocab WHERE due <= ? AND NOT ({new_filter}) ORDER BY due ASC, id ASC LIMIT ?", (now, limit))
    fresh = await db.fetchall(
        f"SELECT * FROM vocab WHERE due <= ? AND {new_filter} ORDER BY due ASC, id ASC LIMIT ?",
        (now, min(new_cap, limit)))
    queue: list[dict] = []
    ri = ni = 0
    while len(queue) < limit and (ri < len(in_rotation) or ni < len(fresh)):
        take_new = ni < len(fresh) and (ri >= len(in_rotation) or (len(queue) + 1) % NEW_EVERY == 0)
        if take_new:
            queue.append(fresh[ni])
            ni += 1
        else:
            queue.append(in_rotation[ri])
            ri += 1
    return {"cards": [vocab_svc.card(r) for r in queue], "due_count": int(total)}
