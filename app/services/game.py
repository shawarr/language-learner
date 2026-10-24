"""The competitive layer: XP, levels, daily rings, streak and badges (docs/API.md "Game and leaderboard").

Nothing here has a write path of its own except the `badges` table. XP is derived from the
`activity` counters every mode already bumps, so a new mode earns points the moment it calls
`db.bump_activity`, and the two learners' totals are always computed from the same ledger. The
leaderboard reads totals only: never a mistake, never a transcript.

The streak rule is the same as progress.py's, re-implemented here so this module stays free of the
progress page's imports (profile, curriculum, mistakes).
"""
from __future__ import annotations

import datetime as dt
import time

from ..db import db, loads
from .. import users

# -- tunables -------------------------------------------------------------------
POINTS = {"talk_turn": 10, "review": 2, "drill": 15, "write": 25, "checkpoint": 60, "lesson": 40}
LEVEL_STEP = 100                      # level n needs LEVEL_STEP * n * (n - 1) / 2 total XP
LEVEL_TITLES = [                      # (minimum level, title) — neutral, English, no cheering
    (1, "Newcomer"), (2, "Tourist"), (4, "Neighbour"), (6, "Colleague"), (8, "Local"), (10, "Fluent-ish"),
]
GOALS = {                             # the three rings, per UTC day
    "speak": {"kinds": ("talk_turn",), "target": 5},
    "review": {"kinds": ("review",), "target": 10},
    "study": {"kinds": ("lesson", "drill", "write", "checkpoint"), "target": 1},
}
MATURE_INTERVAL_DAYS = 21             # a vocab row counts as a known word from this SM-2 interval

CATALOGUE: list[dict] = [
    {"id": "first_talk", "title": "First words", "description": "Your first turn in a conversation.", "icon": "mic"},
    {"id": "first_lesson", "title": "First lesson", "description": "Finished a lesson.", "icon": "book"},
    {"id": "streak_3", "title": "Three days", "description": "Practised three days in a row.", "icon": "flame"},
    {"id": "streak_7", "title": "One week", "description": "Practised seven days in a row.", "icon": "flame"},
    {"id": "streak_30", "title": "One month", "description": "Practised thirty days in a row.", "icon": "flame"},
    {"id": "xp_500", "title": "500 XP", "description": "Earned 500 XP in total.", "icon": "star"},
    {"id": "xp_2000", "title": "2000 XP", "description": "Earned 2000 XP in total.", "icon": "star"},
    {"id": "words_50", "title": "50 words", "description": "Fifty words you know by heart.", "icon": "book"},
    {"id": "words_200", "title": "200 words", "description": "Two hundred words you know by heart.", "icon": "book"},
    {"id": "checkpoint_first", "title": "First checkpoint", "description": "Passed a unit checkpoint.", "icon": "trophy"},
    {"id": "units_5", "title": "Five units", "description": "Passed five unit checkpoints.", "icon": "trophy"},
    {"id": "drill_clean", "title": "Clean sheet", "description": "A drill with every answer right.", "icon": "star"},
    {"id": "early_week", "title": "All three rings", "description": "Closed all three rings in one day.", "icon": "cat"},
]
CATALOGUE_IDS = [b["id"] for b in CATALOGUE]


# -- pure maths -----------------------------------------------------------------
def xp_for_level(n: int) -> int:
    """Total XP at which level n begins (triangular: 0, 100, 300, 600, 1000, ...)."""
    return LEVEL_STEP * n * (n - 1) // 2


def title_for(n: int) -> str:
    title = LEVEL_TITLES[0][1]
    for floor, name in LEVEL_TITLES:
        if n >= floor:
            title = name
    return title


def level_for(xp: int) -> dict:
    xp = max(0, int(xp))
    n = 1
    while xp >= xp_for_level(n + 1):
        n += 1
    start, nxt = xp_for_level(n), xp_for_level(n + 1)
    into, span = xp - start, nxt - start
    return {"n": n, "title": title_for(n), "xp_into_level": into, "xp_for_next": span,
            "fraction": round(into / span, 4)}


def xp_from_counts(counts: dict[str, int]) -> int:
    """{kind: count} -> XP. Unknown kinds are worth nothing rather than an error, so a new counter
    can land before its price is decided."""
    return sum(POINTS.get(kind, 0) * int(n or 0) for kind, n in counts.items())


def streak_from_days(active_days: set[str], today: dt.date) -> int:
    """Consecutive active days ending today — or yesterday, so the streak is not 0 at breakfast."""
    day = today if today.isoformat() in active_days else today - dt.timedelta(days=1)
    n = 0
    while day.isoformat() in active_days:
        n += 1
        day -= dt.timedelta(days=1)
    return n


def goals_from_counts(counts: dict[str, int]) -> dict:
    out = {}
    for name, g in GOALS.items():
        done = sum(int(counts.get(k) or 0) for k in g["kinds"])
        out[name] = {"done": done, "target": g["target"], "fraction": min(1.0, round(done / g["target"], 4))}
    return out


def rings_closed(goals: dict) -> int:
    return sum(1 for g in goals.values() if g["done"] >= g["target"])


def week_start(today: dt.date) -> dt.date:
    return today - dt.timedelta(days=today.weekday())


def _today(now: float) -> dt.date:
    return dt.datetime.fromtimestamp(now, dt.timezone.utc).date()


# -- readers --------------------------------------------------------------------
class Ledger:
    """One pass over a user's `activity` rows, folded into everything the rest of the module needs."""

    def __init__(self, rows: list[dict], now: float) -> None:
        self.today = _today(now)
        self.week_start = week_start(self.today)
        today_s, week_s = self.today.isoformat(), self.week_start.isoformat()
        self.total: dict[str, int] = {}
        self.today_counts: dict[str, int] = {}
        self.week: dict[str, int] = {}
        self.per_day: dict[str, dict[str, int]] = {}
        self.active_days: set[str] = set()
        for r in rows:
            kind, n, day = r["kind"], int(r["count"] or 0), r["day"]
            self.total[kind] = self.total.get(kind, 0) + n
            self.per_day.setdefault(day, {})[kind] = self.per_day.get(day, {}).get(kind, 0) + n
            if n > 0:
                self.active_days.add(day)
            if day == today_s:
                self.today_counts[kind] = self.today_counts.get(kind, 0) + n
            if day >= week_s:
                self.week[kind] = self.week.get(kind, 0) + n

    @property
    def xp_total(self) -> int:
        return xp_from_counts(self.total)

    @property
    def xp_today(self) -> int:
        return xp_from_counts(self.today_counts)

    @property
    def xp_week(self) -> int:
        return xp_from_counts(self.week)

    @property
    def streak_days(self) -> int:
        return streak_from_days(self.active_days, self.today)

    @property
    def goals(self) -> dict:
        return goals_from_counts(self.today_counts)

    def any_day_all_rings(self) -> bool:
        return any(rings_closed(goals_from_counts(c)) == len(GOALS) for c in self.per_day.values())


async def ledger(uid: int, now: float | None = None) -> Ledger:
    rows = await db.fetchall("SELECT day, kind, count FROM activity WHERE user_id=?", (uid,))
    return Ledger(rows, now or time.time())


async def goals(uid: int, day: dt.date | str | None = None) -> dict:
    day_s = day.isoformat() if isinstance(day, dt.date) else (day or _today(time.time()).isoformat())
    rows = await db.fetchall("SELECT kind, count FROM activity WHERE user_id=? AND day=?", (uid, day_s))
    return goals_from_counts({r["kind"]: int(r["count"] or 0) for r in rows})


async def _facts(uid: int) -> dict:
    """The non-activity numbers the badges and the leaderboard need, one small query each."""
    mature = await db.fetchone("SELECT COUNT(*) AS n FROM vocab WHERE user_id=? AND interval_days >= ?",
                               (uid, MATURE_INTERVAL_DAYS))
    passed = await db.fetchone("SELECT COUNT(*) AS n FROM checkpoints WHERE user_id=? AND passed=1", (uid,))
    lessons = await db.fetchone("SELECT COUNT(*) AS n FROM lesson_progress WHERE user_id=? AND completed=1", (uid,))
    drills = await db.fetchall("SELECT items, score FROM drills WHERE user_id=? AND finished_at IS NOT NULL AND score IS NOT NULL",
                               (uid,))
    clean = any(int(d["score"] or 0) > 0 and int(d["score"]) == len(loads(d["items"], [])) for d in drills)
    return {"words_mature": int(mature["n"]), "units_passed": int(passed["n"]),
            "lessons_done": int(lessons["n"]), "drill_clean": clean}


def earned_now(led: Ledger, facts: dict) -> list[str]:
    xp, streak = led.xp_total, led.streak_days
    checks = {
        "first_talk": led.total.get("talk_turn", 0) >= 1,
        "first_lesson": led.total.get("lesson", 0) >= 1 or facts["lessons_done"] >= 1,
        "streak_3": streak >= 3,
        "streak_7": streak >= 7,
        "streak_30": streak >= 30,
        "xp_500": xp >= 500,
        "xp_2000": xp >= 2000,
        "words_50": facts["words_mature"] >= 50,
        "words_200": facts["words_mature"] >= 200,
        "checkpoint_first": facts["units_passed"] >= 1,
        "units_5": facts["units_passed"] >= 5,
        "drill_clean": facts["drill_clean"],
        "early_week": led.any_day_all_rings(),
    }
    return [b for b in CATALOGUE_IDS if checks.get(b)]


async def evaluate(uid: int, now: float | None = None) -> list[str]:
    """Insert every badge the user has earned but does not hold yet; returns the newly inserted ids.
    A badge is never taken away: a broken streak does not un-earn 'Three days'."""
    now = now or time.time()
    led = await ledger(uid, now)
    facts = await _facts(uid)
    held = {r["badge_id"] for r in await db.fetchall("SELECT badge_id FROM badges WHERE user_id=?", (uid,))}
    fresh = [b for b in earned_now(led, facts) if b not in held]
    for b in fresh:
        await db.execute("INSERT OR IGNORE INTO badges (user_id, badge_id, earned_at, seen) VALUES (?, ?, ?, 0)",
                         (uid, b, now))
    return fresh


async def earned(uid: int) -> list[dict]:
    rows = await db.fetchall("SELECT badge_id, earned_at, seen FROM badges WHERE user_id=? ORDER BY earned_at, badge_id",
                             (uid,))
    by_id = {b["id"]: b for b in CATALOGUE}
    out = []
    for r in rows:
        meta = by_id.get(r["badge_id"])
        if meta is None:
            continue   # a badge retired from the catalogue stays in the table but is not shown
        out.append({**meta, "earned_at": r["earned_at"], "seen": int(r["seen"] or 0)})
    return out


async def new_badges(uid: int) -> list[str]:
    rows = await db.fetchall("SELECT badge_id FROM badges WHERE user_id=? AND seen=0 ORDER BY earned_at, badge_id", (uid,))
    return [r["badge_id"] for r in rows if r["badge_id"] in CATALOGUE_IDS]


async def mark_seen(uid: int, ids: list[str]) -> None:
    for b in ids:
        await db.execute("UPDATE badges SET seen=1 WHERE user_id=? AND badge_id=?", (uid, str(b)))


async def me(now: float | None = None) -> dict:
    """GET /game/me for the current user. Evaluates first, so a badge earned by the last action
    is already in `new_badges` when the client opens the page."""
    now = now or time.time()
    uid = users.user_id()
    await evaluate(uid, now)
    led = await ledger(uid, now)
    g = led.goals
    return {
        "xp_total": led.xp_total,
        "xp_today": led.xp_today,
        "xp_week": led.xp_week,
        "level": level_for(led.xp_total),
        "streak_days": led.streak_days,
        "goals": g,
        "rings_closed": rings_closed(g),
        "badges": await earned(uid),
        "new_badges": await new_badges(uid),
        "catalogue": CATALOGUE,
    }


async def leaderboard(now: float | None = None) -> dict:
    """Totals for every learner, best week first. Reads `profile.level` straight from the table so
    this module does not pull in the profile service."""
    now = now or time.time()
    rows = []
    for u in await users.list_public():
        uid = int(u["id"])
        led = await ledger(uid, now)
        facts = await _facts(uid)
        prof = await db.fetchone("SELECT level FROM profile WHERE user_id=?", (uid,))
        lvl = level_for(led.xp_total)
        rows.append({
            "id": uid, "name": u["name"], "avatar": u["avatar"], "gender": u["gender"],
            "xp_week": led.xp_week, "xp_total": led.xp_total,
            "level": {"n": lvl["n"], "title": lvl["title"]},
            "streak_days": led.streak_days,
            "cefr_level": (prof or {}).get("level") or "A1.1",
            "units_passed": facts["units_passed"],
            "words_mature": facts["words_mature"],
            "rings_closed_today": rings_closed(led.goals),
            "badges_count": len(await earned(uid)),
        })
    rows.sort(key=lambda r: (-r["xp_week"], -r["xp_total"], r["id"]))
    return {"week_start": week_start(_today(now)).isoformat(), "me": users.user_id(), "users": rows}
