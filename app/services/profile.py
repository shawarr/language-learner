"""The learner profile: the one row the tutor's memory hangs off, and the context the prompt needs.

Everything the tutor prompt knows about Ahmad comes through `build_context`, so the formatting rules
that keep the prompt small (six mistakes, twelve words, "(none yet)" instead of "[]") live here and
nowhere else.
"""
from __future__ import annotations

import json
import time

from ..db import db, loads

SKILLS = ("speaking", "listening", "writing", "grammar", "vocab")
_COLUMNS = {"name", "level", "unit_id", "skills", "facts", "rolling_summary", "review_focus", "placement_done"}
_JSON_COLUMNS = {"skills", "facts", "review_focus"}

MAX_FACTS = 40
MAX_TOP_MISTAKES = 6
MAX_DUE_VOCAB = 12
NONE_YET = "(none yet)"


async def get_profile() -> dict:
    """The profile row with skills/facts/review_focus parsed into objects."""
    row = await db.fetchone("SELECT * FROM profile WHERE id=1")
    assert row is not None, "profile row missing: db.connect() creates it"
    skills = loads(row["skills"], {})
    row["skills"] = {k: _clamp(skills.get(k, 10)) for k in SKILLS}
    row["facts"] = [f for f in loads(row["facts"], []) if isinstance(f, str) and f.strip()]
    row["review_focus"] = [f for f in loads(row["review_focus"], []) if isinstance(f, str) and f.strip()]
    return row


async def update_profile(**fields: object) -> None:
    """Write whitelisted columns only; dict/list values are JSON-encoded. Bumps updated_at."""
    unknown = set(fields) - _COLUMNS
    if unknown:
        raise ValueError(f"not a profile column: {sorted(unknown)}")
    if not fields:
        return
    sets, params = [], []
    for key, value in fields.items():
        if key in _JSON_COLUMNS and not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False)
        sets.append(f"{key}=?")
        params.append(value)
    sets.append("updated_at=?")
    params.append(time.time())
    await db.execute(f"UPDATE profile SET {', '.join(sets)} WHERE id=1", tuple(params))


def _clamp(v: object) -> int:
    try:
        return max(0, min(100, int(v)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 10


async def apply_skill_deltas(deltas: dict[str, int]) -> dict[str, int]:
    """Add each delta to its skill, clamped to 0..100. Unknown skills and non-numbers are ignored."""
    skills = (await get_profile())["skills"]
    for key, delta in (deltas or {}).items():
        if key not in SKILLS:
            continue
        try:
            skills[key] = _clamp(skills[key] + int(delta))
        except (TypeError, ValueError):
            continue
    await update_profile(skills=skills)
    return skills


async def add_facts(facts: list[str]) -> list[str]:
    """Append new facts, de-duplicated case-insensitively, keeping the newest MAX_FACTS."""
    have = (await get_profile())["facts"]
    seen = {f.lower() for f in have}
    for fact in facts or []:
        if not isinstance(fact, str):
            continue
        clean = " ".join(fact.split()).strip().rstrip(".")
        if clean and clean.lower() not in seen:
            have.append(clean)
            seen.add(clean.lower())
    have = have[-MAX_FACTS:]
    await update_profile(facts=have)
    return have


async def top_mistakes(limit: int = MAX_TOP_MISTAKES) -> list[dict]:
    """Open mistakes ranked by how many times they still need beating, then recency.

    A mistake with resolved >= count has been drilled away and drops out — otherwise a mistake from
    week one haunts the prompt forever.
    """
    rows = await db.fetchall(
        "SELECT * FROM mistakes WHERE count > resolved ORDER BY (count - resolved) DESC, last_seen DESC LIMIT ?",
        (limit,),
    )
    for r in rows:
        r["examples"] = [e for e in loads(r["examples"], []) if isinstance(e, dict)]
    return rows


async def due_vocab(limit: int = MAX_DUE_VOCAB, now: float | None = None) -> list[dict]:
    return await db.fetchall("SELECT id, word, translation FROM vocab WHERE due <= ? ORDER BY due LIMIT ?",
                             (now or time.time(), limit))


def format_mistakes(rows: list[dict]) -> str:
    """`case: 'mit dem Bus' not 'mit den Bus' (4×)` per line; falls back to the pattern when no example."""
    lines = []
    for r in rows:
        ex = next((e for e in reversed(r.get("examples") or []) if e.get("right") and e.get("wrong")), None)
        if ex:
            lines.append(f"{r['category']}: '{ex['right']}' not '{ex['wrong']}' ({r['count']}×)")
        else:
            lines.append(f"{r['category']}: {r['pattern']} ({r['count']}×)")
    return "\n".join(lines)


def format_scenario(scenario: dict | None) -> str:
    if not scenario:
        return ("Free conversation. Pick something from his life or this unit's can-do goals and start it. "
                "There is no fixed goal, so scenario_done stays false.")
    return (f"Title: {scenario.get('title', '')}\n"
            f"Setup: {scenario.get('setup', '')}\n"
            f"Goal (set scenario_done to true once it is reached, not before): {scenario.get('goal', '')}")


async def build_context(unit: dict, scenario: dict | None = None) -> dict[str, str]:
    """Exactly the placeholders app/prompts/tutor_talk.md declares. `render()` raises on a mismatch."""
    p = await get_profile()
    mistakes = await top_mistakes(MAX_TOP_MISTAKES)
    due = await due_vocab(MAX_DUE_VOCAB)
    targets = ", ".join(unit.get("grammar") or []) or NONE_YET
    if p["review_focus"]:
        # A failed checkpoint's gaps ride along with the unit's grammar so the tutor re-exposes them.
        targets += " | Review focus after the last checkpoint, bring these up again: " + "; ".join(p["review_focus"])
    return {
        "level": p["level"],
        "unit_title": unit.get("title") or NONE_YET,
        "unit_goals": "; ".join(unit.get("can_do") or []) or NONE_YET,
        "grammar_targets": targets,
        "top_mistakes": format_mistakes(mistakes) or NONE_YET,
        "due_vocab": ", ".join(v["word"] for v in due) or NONE_YET,
        "facts": "; ".join(p["facts"]) or NONE_YET,
        "rolling_summary": " ".join(p["rolling_summary"].split()) or NONE_YET,
        "scenario": format_scenario(scenario),
    }
