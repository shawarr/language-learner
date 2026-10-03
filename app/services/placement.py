"""Placement: a short flow, not a quiz, that decides where on the path the learner starts.

Four fixed tasks (three spoken, rising difficulty, then one written), each stored as it comes in,
graded once at the end with `app/prompts/placement.md`. The grading writes the profile; `finish`
is idempotent because a double tap on a phone is normal, and a second model call would both burn
quota and possibly place him somewhere else.

Everything the model returns is validated before it touches the DB, and the code is conservative
on top of the prompt: an unknown level is A1.1, and fewer than two answered tasks cannot place
him above A1.2 — a beginner placed too high is a learner who quits.
"""
from __future__ import annotations

import json
import time

from fastapi import HTTPException

from ..db import db, loads
from ..prompts import render
from ..providers.base import Message
from ..providers.llm import llm
from . import curriculum, profile

LEVELS = [p.upper() for p in curriculum.PHASE_ORDER]
# Where a skill lands when the model leaves it out or returns garbage: roughly the midpoint of the
# calibration the prompt gives (≈30 solid A1, ≈50 solid A2, ≈70 solid B1).
SKILL_BASELINE = {"A1.1": 10, "A1.2": 20, "A2.1": 32, "A2.2": 42, "B1.1": 55, "B1.2": 65}
MAX_LIST = 5
MAX_FACTS = 10
MAX_ANSWER_CHARS = 4000
# With fewer answers than this, the level is capped at A1.2 whatever the model says.
MIN_TASKS_FOR_FULL_RANGE = 2
CAP_LEVEL = "A1.2"

TASKS: list[dict] = [
    {
        "id": "intro", "kind": "speak", "title": "Stell dich vor",
        "instruction_en": "Introduce yourself in German: your name, where you come from, where you live, "
                          "what you do. Say as much as you can; it is fine to stop when you run out.",
        "prompt_de": "Stell dich bitte kurz vor. Wer bist du, woher kommst du, was machst du?",
    },
    {
        "id": "workday", "kind": "speak", "title": "Dein Arbeitstag",
        "instruction_en": "Describe a normal working day: when you start, what you do, who you talk to, "
                          "when you finish. Try to use full sentences.",
        "prompt_de": "Beschreib einen normalen Arbeitstag. Wann fängst du an, was machst du, wann hörst du auf?",
    },
    {
        "id": "problem", "kind": "speak", "title": "Ein Problem, das du gelöst hast",
        "instruction_en": "Tell the story of a problem you solved at work last week or last month: what "
                          "happened, what you did, how it ended. Past tense if you can.",
        "prompt_de": "Erzähl von einem Problem, das du letzte Woche gelöst hast. Was ist passiert, und was hast du gemacht?",
    },
    {
        "id": "message", "kind": "write", "title": "Eine Nachricht an einen Kollegen",
        "instruction_en": "Write a short message (three to five sentences) to a German colleague: you cannot "
                          "join tomorrow's meeting, say why, and suggest another time.",
        "prompt_de": "Schreib eine kurze Nachricht an einen Kollegen: Du kannst morgen nicht zum Meeting kommen. "
                     "Warum nicht? Wann passt es dir?",
    },
]

PLACEMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "level": {"type": "string", "enum": LEVELS},
        "skills": {
            "type": "object",
            "properties": {k: {"type": "integer", "minimum": 0, "maximum": 100} for k in profile.SKILLS},
            "required": list(profile.SKILLS),
        },
        "explanation": {"type": "string",
                        "description": "English, two or three sentences addressed to him: where he landed and why."},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
        "facts": {"type": "array", "items": {"type": "string"},
                  "description": "Durable personal facts he revealed, reusable as conversation material."},
    },
    "required": ["level", "skills", "explanation", "strengths", "gaps", "facts"],
}


def tasks() -> list[dict]:
    return [dict(t) for t in TASKS]


def task(task_id: str | None) -> dict | None:
    return next((t for t in TASKS if t["id"] == task_id), None)


async def _session(session_id: int) -> dict:
    row = await db.fetchone("SELECT * FROM sessions WHERE id=? AND mode='placement'", (session_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="No such placement session.")
    row["meta"] = loads(row["meta"], {})
    if not isinstance(row["meta"], dict):
        row["meta"] = {}
    return row


async def start() -> dict:
    """A new placement session. Works when placement_done is already 1: the progress page offers a re-run."""
    sid = await db.execute("INSERT INTO sessions (mode, started_at, meta) VALUES ('placement', ?, '{}')",
                           (time.time(),))
    return {"session_id": sid, "tasks": tasks()}


async def answer(session_id: int, task_id: str, text: str, *, input_kind: str = "text",
                 stt_provider: str | None = None) -> dict:
    """Store one answer. A second answer to the same task replaces it in `meta`; every attempt stays in messages."""
    t = task(task_id)
    if t is None:
        raise HTTPException(status_code=404, detail="No such placement task.")
    row = await _session(session_id)
    text = " ".join(str(text or "").split()).strip()[:MAX_ANSWER_CHARS]
    if not text:
        raise HTTPException(status_code=400, detail="The answer was empty.")
    kind = "voice" if input_kind == "voice" else "text"
    meta = row["meta"]
    answers = meta.get("answers") if isinstance(meta.get("answers"), dict) else {}
    answers[task_id] = {"text": text, "kind": kind, "provider": stt_provider}
    meta["answers"] = answers
    now = time.time()
    # The message row keeps the raw transcript exactly as the engine produced it (docs/STT-FINDINGS.md).
    await db.conn.execute(
        "INSERT INTO messages (session_id, role, content, transcript_raw, input_kind, stt_provider, created_at) "
        "VALUES (?, 'user', ?, ?, ?, ?, ?)",
        (session_id, text, text if kind == "voice" else None, kind, stt_provider, now))
    await db.conn.execute("UPDATE sessions SET meta=?, user_turns=user_turns+1 WHERE id=?",
                          (json.dumps(meta, ensure_ascii=False), session_id))
    await db.conn.commit()
    return {"task_id": task_id, "text": text, "transcript_provider": stt_provider}


def _clean_list(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(" ".join(item.split()))
    return out[:limit]


def validate_result(data: dict, answered: int) -> dict:
    """Coerce the model's reply into something safe to write. Conservative on every doubt."""
    level = data.get("level") if isinstance(data.get("level"), str) else ""
    level = level.strip().upper()
    if level not in LEVELS:
        level = LEVELS[0]
    if answered < MIN_TASKS_FOR_FULL_RANGE and LEVELS.index(level) > LEVELS.index(CAP_LEVEL):
        level = CAP_LEVEL
    baseline = SKILL_BASELINE[level]
    raw = data.get("skills") if isinstance(data.get("skills"), dict) else {}
    skills = {}
    for key in profile.SKILLS:
        v = raw.get(key)
        try:
            skills[key] = max(0, min(100, int(v))) if not isinstance(v, bool) else baseline  # type: ignore[arg-type]
        except (TypeError, ValueError):
            skills[key] = baseline
    explanation = data.get("explanation")
    explanation = " ".join(explanation.split()) if isinstance(explanation, str) and explanation.strip() else ""
    if not explanation:
        explanation = f"You start at {level}. Not enough was said to explain more; the first sessions will show where you stand."
    return {
        "level": level,
        "skills": skills,
        "explanation": explanation,
        "strengths": _clean_list(data.get("strengths"), MAX_LIST),
        "gaps": _clean_list(data.get("gaps"), MAX_LIST),
        "facts": _clean_list(data.get("facts"), MAX_FACTS),
    }


def _format_answers(answers: dict) -> str:
    blocks = []
    for t in TASKS:
        a = answers.get(t["id"]) if isinstance(answers.get(t["id"]), dict) else None
        head = f"### Task: {t['title']} ({'spoken, raw transcript' if t['kind'] == 'speak' else 'written'})\n" \
               f"Instruction given to him: {t['instruction_en']}\n"
        if not a or not str(a.get("text", "")).strip():
            blocks.append(head + "Answer: (not answered)")
            continue
        source = "typed" if a.get("kind") != "voice" else f"transcribed by {a.get('provider') or 'the speech engine'}"
        blocks.append(head + f"Answer ({source}):\n{a['text']}")
    return "\n\n".join(blocks)


def _public_result(level: str, unit: dict, skills: dict, explanation: str, strengths: list[str],
                   gaps: list[str], *, skipped: bool) -> dict:
    p = curriculum.phase_of(unit["id"])
    return {"level": level, "unit": curriculum.public_unit(unit),
            "phase": {"id": p["id"], "level": p["level"], "title": p["title"]},
            "skills": skills, "explanation": explanation, "strengths": strengths, "gaps": gaps,
            "skipped": skipped}


async def finish(session_id: int) -> dict:
    """Grade and write the profile. Idempotent: a stored result comes back as-is, with no model call."""
    row = await _session(session_id)
    meta = row["meta"]
    if isinstance(meta.get("result"), dict):
        return meta["result"]
    answers = meta.get("answers") if isinstance(meta.get("answers"), dict) else {}
    answers = {k: v for k, v in answers.items() if task(k) and isinstance(v, dict) and str(v.get("text", "")).strip()}
    if not answers:
        raise HTTPException(status_code=400, detail="Answer at least one task before finishing.")
    system = render("placement", answered=f"{len(answers)} of {len(TASKS)}", answers=_format_answers(answers))
    data = await llm.complete_json(system, [Message("user", "Place him.")], PLACEMENT_SCHEMA,
                                   tier="quality", temperature=0.2, max_tokens=1024)
    graded = validate_result(data, answered=len(answers))
    unit = curriculum.first_unit_of_level(graded["level"])
    # Profile first, session last: if the session write fails, the next finish() re-grades and
    # overwrites the profile with a fresh verdict; the other order would leave a stored result
    # that the profile never received.
    await profile.update_profile(level=graded["level"], unit_id=unit["id"], skills=graded["skills"], placement_done=1)
    await profile.add_facts(graded["facts"])
    result = _public_result(graded["level"], unit, graded["skills"], graded["explanation"],
                            graded["strengths"], graded["gaps"], skipped=False)
    meta["result"] = result
    await db.execute("UPDATE sessions SET ended_at=?, summary=?, meta=? WHERE id=?",
                     (time.time(), graded["explanation"], json.dumps(meta, ensure_ascii=False), session_id))
    return result


async def skip() -> dict:
    """Start at the very beginning without grading. Skills stay as they are."""
    level = LEVELS[0]
    unit = curriculum.first_unit_of_level(level)
    await profile.update_profile(level=level, unit_id=unit["id"], placement_done=1)
    p = await profile.get_profile()
    return _public_result(level, unit, p["skills"],
                          "You chose to start from the beginning. The placement can be run later from the progress page.",
                          [], [], skipped=True)


async def status() -> dict:
    p = await profile.get_profile()
    return {"placement_done": bool(p["placement_done"]), "level": p["level"], "unit_id": p["unit_id"]}
