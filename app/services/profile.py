"""The learner profile: one row per user the tutor's memory hangs off, and the context the prompt needs.

Everything the tutor prompt knows about the learner comes through `build_context`, so the formatting
rules that keep the prompt small (six mistakes, twelve words, "(none yet)" instead of "[]") live here
and nowhere else. Every query is scoped to the current user (`app.users`): the row is keyed by
`user_id`, never by `id`.
"""
from __future__ import annotations

import json
import time

from .. import users
from ..db import db, loads

SKILLS = ("speaking", "listening", "writing", "grammar", "vocab")
_COLUMNS = {"name", "level", "unit_id", "skills", "facts", "rolling_summary", "review_focus", "placement_done"}
_JSON_COLUMNS = {"skills", "facts", "review_focus"}

MAX_FACTS = 40
MAX_TOP_MISTAKES = 6
MAX_DUE_VOCAB = 12
NONE_YET = "(none yet)"


async def get_profile() -> dict:
    """The current user's profile row with skills/facts/review_focus parsed into objects."""
    row = await db.fetchone("SELECT * FROM profile WHERE user_id=?", (users.user_id(),))
    assert row is not None, "profile row missing: users.seed() creates it"
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
    params.extend([time.time(), users.user_id()])
    await db.execute(f"UPDATE profile SET {', '.join(sets)} WHERE user_id=?", tuple(params))


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
        "SELECT * FROM mistakes WHERE user_id=? AND count > resolved "
        "ORDER BY (count - resolved) DESC, last_seen DESC LIMIT ?",
        (users.user_id(), limit),
    )
    for r in rows:
        r["examples"] = [e for e in loads(r["examples"], []) if isinstance(e, dict)]
    return rows


async def due_vocab(limit: int = MAX_DUE_VOCAB, now: float | None = None) -> list[dict]:
    return await db.fetchall(
        "SELECT id, word, translation FROM vocab WHERE user_id=? AND due <= ? ORDER BY due LIMIT ?",
        (users.user_id(), now or time.time(), limit))


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


def about_text(user: dict | None = None) -> str:
    """The paragraph the prompts are told about the learner (personas.json, via `users.about`).

    It carries the name, the situation and, for Maryan, the feminine forms, so every prompt that used
    to hard-code one learner reads it instead. A user seeded without a persona still gets one line,
    so no prompt ever describes nobody.
    """
    user = user or users.current()
    return " ".join(str(user.get("about") or "").split()) or f"{user['name']} is learning German."


def format_scenario(scenario: dict | None) -> str:
    if not scenario:
        return ("Free conversation. Pick something from the learner's life or this unit's can-do goals and "
                "start it. There is no fixed goal, so scenario_done stays false.")
    out = (f"Title: {scenario.get('title', '')}\n"
           f"Setup: {scenario.get('setup', '')}\n"
           f"Goal (set scenario_done to true once it is reached, not before): {scenario.get('goal', '')}")
    if scenario.get("brief"):
        out += f"\nWhat the learner read before starting (English): {scenario['brief']}"
    if scenario.get("words"):
        out += ("\nWords and sentences the learner was shown, with audio, before starting. Build the "
                "conversation from these; anything else needs explaining: "
                + "; ".join(f"{w['de']} ({w['en']})" for w in scenario["words"]))
    return out


async def build_context(unit: dict, scenario: dict | None = None) -> dict[str, str]:
    """Exactly the placeholders app/prompts/tutor_talk.md declares. `render()` raises on a mismatch."""
    user = users.current()
    p = await get_profile()
    mistakes = await top_mistakes(MAX_TOP_MISTAKES)
    due = await due_vocab(MAX_DUE_VOCAB)
    targets = ", ".join(unit.get("grammar") or []) or NONE_YET
    if p["review_focus"]:
        # A failed checkpoint's gaps ride along with the unit's grammar so the tutor re-exposes them.
        targets += " | Review focus after the last checkpoint, bring these up again: " + "; ".join(p["review_focus"])
    return {
        "name": user["name"],
        "about": about_text(user),
        "level": p["level"],
        "unit_title": unit.get("title") or NONE_YET,
        "unit_goals": "; ".join(unit.get("can_do") or []) or NONE_YET,
        "grammar_targets": targets,
        "top_mistakes": format_mistakes(mistakes) or NONE_YET,
        "due_vocab": ", ".join(v["word"] for v in due) or NONE_YET,
        "facts": "; ".join(p["facts"]) or NONE_YET,
        "rolling_summary": " ".join(p["rolling_summary"].split()) or NONE_YET,
        "scenario": format_scenario(scenario),
        "english_policy": english_policy(p["level"]),
    }


def english_policy(level: str | None) -> str:
    """How much English the tutor may speak, by level. A beginner cannot be tutored in German alone:
    at A1 it explains in English whenever the learner needs it; by B1 it stays in German unless asked."""
    lv = str(level or "A1").upper()
    if lv.startswith("A1"):
        return ("The learner is a beginner. Use `coach_en` freely: whenever the learner writes in English, "
                "says they do not understand, asks anything about German, or gives a one-word or confused answer, "
                "explain in plain English (two or three short sentences) and tell them exactly what to say next. "
                "It is fine to use it on most turns early in a conversation.")
    if lv.startswith("A2"):
        return ("Use `coach_en` when the learner writes in English, is clearly lost, or asks about German: "
                "a short English explanation, then back to German. Not on turns that go fine.")
    return ("Stay in German. Use `coach_en` only when the learner explicitly asks for English or asks a question "
            "about German grammar or words, and keep it to one or two sentences.")

