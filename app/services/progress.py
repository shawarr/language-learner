"""The progress page in one payload (docs/API.md GET /progress).

Everything here is read-only aggregation. The honesty fields matter: `thin_data` tells the UI not
to draw a confident curve from three sessions, and a mistake's `trend` is "improving" only when
the drills have actually moved it.
"""
from __future__ import annotations

import datetime as dt
import time

from ..db import db, loads
from . import checkpoint, curriculum, mistakes, profile

ACTIVITY_KINDS = ("talk_turn", "review", "drill", "write", "checkpoint")
ACTIVITY_DAYS = 30
TOP_MISTAKES = 6
BEATEN_MISTAKES = 10
RECENT_SESSIONS = 10
THIN_DATA_SESSIONS = 4
MATURE_INTERVAL_DAYS = 21
IMPROVING_AFTER_DAYS = 7
PROFILE_FIELDS = ("name", "level", "unit_id", "placement_done", "rolling_summary")
SESSION_FIELDS = ("id", "mode", "scenario_id", "scenario_title", "unit_id", "started_at", "ended_at", "summary",
                  "user_turns", "meta")


def streak_days(active_days: set[str], today: dt.date) -> int:
    """Consecutive active days ending today — or yesterday, so the streak is not 0 at breakfast."""
    day = today if today.isoformat() in active_days else today - dt.timedelta(days=1)
    n = 0
    while day.isoformat() in active_days:
        n += 1
        day -= dt.timedelta(days=1)
    return n


def trend(row: dict, now: float) -> str:
    """"improving" once the drills have beaten back half of it, or it has stayed quiet for a week after a win."""
    count, resolved = int(row.get("count") or 0), int(row.get("resolved") or 0)
    if resolved <= 0:
        return "not_yet"
    if resolved * 2 >= count:
        return "improving"
    if float(row.get("last_seen") or now) < now - IMPROVING_AFTER_DAYS * 86400:
        return "improving"
    return "not_yet"


async def activity_strip(today: dt.date) -> list[dict]:
    start = today - dt.timedelta(days=ACTIVITY_DAYS - 1)
    rows = await db.fetchall("SELECT day, kind, count FROM activity WHERE day >= ?", (start.isoformat(),))
    by_day: dict[str, dict] = {}
    for i in range(ACTIVITY_DAYS):
        day = (start + dt.timedelta(days=i)).isoformat()
        by_day[day] = {"day": day, **{k: 0 for k in ACTIVITY_KINDS}}
    for r in rows:
        entry = by_day.get(r["day"])
        if entry is not None and r["kind"] in ACTIVITY_KINDS:
            entry[r["kind"]] = int(r["count"] or 0)
    return list(by_day.values())


async def vocab_counts(now: float) -> dict:
    row = await db.fetchone(
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN due <= ? THEN 1 ELSE 0 END) AS due, "
        "SUM(CASE WHEN interval_days >= ? THEN 1 ELSE 0 END) AS mature, "
        "SUM(CASE WHEN reps = 0 AND last_review IS NULL THEN 1 ELSE 0 END) AS new "
        "FROM vocab", (now, MATURE_INTERVAL_DAYS))
    return {k: int((row or {}).get(k) or 0) for k in ("total", "due", "mature", "new")}


async def payload(now: float | None = None) -> dict:
    now = now or time.time()
    today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
    p = await profile.get_profile()
    cur = await curriculum.current()
    unit_id = cur["unit"]["id"]

    active = {r["day"] for r in await db.fetchall(
        "SELECT day FROM activity GROUP BY day HAVING SUM(count) > 0")}
    top = [{**m, "trend": trend(m, now)} for m in await profile.top_mistakes(TOP_MISTAKES)]
    sessions = await db.fetchall(
        f"SELECT {', '.join(SESSION_FIELDS)} FROM sessions ORDER BY started_at DESC, id DESC LIMIT ?", (RECENT_SESSIONS,))
    for s in sessions:
        s["meta"] = loads(s["meta"], {})
    ended = (await db.fetchone("SELECT COUNT(*) AS n FROM sessions WHERE mode='talk' AND ended_at IS NOT NULL"))["n"]
    available = await checkpoint.is_available(unit_id)

    return {
        "profile": {k: p[k] for k in PROFILE_FIELDS},
        "phase": cur["phase"],
        "unit": cur["unit"],
        "unit_index": cur["unit_index"],
        "unit_count": cur["unit_count"],
        "skills": p["skills"],
        "streak_days": streak_days(active, today),
        "activity": await activity_strip(today),
        "top_mistakes": top,
        "beaten_mistakes": await mistakes.beaten(BEATEN_MISTAKES),
        "vocab": await vocab_counts(now),
        "recent_sessions": sessions,
        # C4 owns the real reason ("ready" | "sessions" | "not_yet"); until it exposes one, say only what we know.
        "checkpoint": {"available": bool(available), "unit_id": unit_id, "reason": "ready" if available else "not_yet"},
        "sessions_total": int(ended),
        "thin_data": int(ended) < THIN_DATA_SESSIONS,
    }
