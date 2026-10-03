"""End-of-unit checkpoints: the unit's authored speaking and writing tasks, graded against a rubric.

A checkpoint is offered, never forced: it becomes available when the analyzer judged a talk session
in this unit as "ready", or after enough ended talk sessions in the unit. A pass moves the profile
to the next unit; a fail writes `review_focus` into the profile so the tutor and the drills aim at
the gap. Retakes cost nothing: every attempt is its own `checkpoints` row.

The model's verdict is validated and then overruled where the numbers disagree with it: `passed`
needs every dimension at 3 or more, whatever the boolean says. All writes happen after grading, so
a provider failure leaves the attempt unfinished and retakeable rather than half-written.
"""
from __future__ import annotations

import json
import time

from fastapi import HTTPException

from ..config import settings
from ..db import db, loads
from ..prompts import render
from ..providers.base import Message
from ..providers.llm import llm
from . import curriculum, profile

DIMENSIONS = ("task_completion", "range", "accuracy", "fluency")
PASS_MIN = 3
MAX_REVIEW_FOCUS = 3
MAX_TEXT_CHARS = 6000
DEFAULT_WORDS = (40, 80)

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {
                d: {
                    "type": "object",
                    "properties": {
                        "score": {"type": "integer", "minimum": 1, "maximum": 5},
                        "comment": {"type": "string", "description": "One concrete sentence, English, quoting him."},
                    },
                    "required": ["score", "comment"],
                }
                for d in DIMENSIONS
            },
            "required": list(DIMENSIONS),
        },
        "passed": {"type": "boolean", "description": "True only when every dimension scores 3 or more."},
        "summary": {"type": "string", "description": "English, two sentences addressed to him."},
        "review_focus": {"type": "array", "items": {"type": "string"},
                         "description": "One to three grammar or vocabulary gaps to work on next, phrased as drillable targets."},
    },
    "required": ["scores", "passed", "summary", "review_focus"],
}


# -- availability ---------------------------------------------------------------------------

async def availability(unit_id: str) -> dict:
    """docs/API.md: "ready" from the analyzer's verdict, "sessions" from the ended-session count, else "not_yet"."""
    needed = max(0, int(settings.checkpoint_min_sessions))
    rows = await db.fetchall("SELECT ended_at, meta FROM sessions WHERE mode='talk' AND unit_id=?", (unit_id,))
    ended = sum(1 for r in rows if r["ended_at"] is not None)
    ready = False
    for r in rows:
        meta = loads(r["meta"], {})
        if isinstance(meta, dict) and meta.get("unit_readiness") == "ready":
            ready = True
            break
    reason = "ready" if ready else ("sessions" if ended >= needed else "not_yet")
    return {"available": reason != "not_yet", "reason": reason, "sessions_in_unit": ended, "sessions_needed": needed}


async def is_available(unit_id: str) -> bool:
    return (await availability(unit_id))["available"]


# -- the current checkpoint -----------------------------------------------------------------

def tasks_for(unit: dict) -> dict:
    """The API shape of the unit's authored tasks; hints only when the author wrote one."""
    cp = unit.get("checkpoint") or {}
    sp, wr = cp.get("speaking") or {}, cp.get("writing") or {}
    speaking = {"prompt": str(sp.get("prompt") or "")}
    if sp.get("hint"):
        speaking["hint"] = str(sp["hint"])
    lo, hi = DEFAULT_WORDS
    try:
        lo, hi = int(wr.get("words_min", lo)), int(wr.get("words_max", hi))
    except (TypeError, ValueError):
        lo, hi = DEFAULT_WORDS
    writing = {"prompt": str(wr.get("prompt") or ""), "words_min": lo, "words_max": hi}
    if wr.get("hint"):
        writing["hint"] = str(wr["hint"])
    return {"speaking": speaking, "writing": writing}


async def _open_row(unit_id: str) -> dict | None:
    return await db.fetchone(
        "SELECT * FROM checkpoints WHERE unit_id=? AND finished_at IS NULL ORDER BY id DESC LIMIT 1", (unit_id,))


async def last_result(unit_id: str) -> dict | None:
    row = await db.fetchone(
        "SELECT result FROM checkpoints WHERE unit_id=? AND finished_at IS NOT NULL ORDER BY finished_at DESC, id DESC LIMIT 1",
        (unit_id,))
    result = loads(row["result"], None) if row else None
    return result if isinstance(result, dict) else None


async def current() -> dict:
    """docs/API.md GET /checkpoint/current. An unfinished row is created or reused only when available."""
    unit = await curriculum.current_unit()
    p = curriculum.phase_of(unit["id"])
    avail = await availability(unit["id"])
    tasks = tasks_for(unit)
    checkpoint_id = None
    if avail["available"]:
        row = await _open_row(unit["id"])
        if row is None:
            checkpoint_id = await db.execute(
                "INSERT INTO checkpoints (unit_id, tasks, created_at) VALUES (?, ?, ?)",
                (unit["id"], json.dumps(tasks, ensure_ascii=False), time.time()))
        else:
            checkpoint_id = int(row["id"])
    return {
        **avail,
        "unit": curriculum.public_unit(unit),
        "phase": {"id": p["id"], "level": p["level"], "title": p["title"]},
        "checkpoint_id": checkpoint_id,
        "tasks": tasks,
        "last_result": await last_result(unit["id"]),
    }


# -- grading ----------------------------------------------------------------------------------

def _sentence(v: object) -> str:
    return " ".join(str(v).split()).strip() if isinstance(v, str) else ""


def validate_grade(data: dict) -> dict:
    """Scores clamped to 1..5 (missing → 1); `passed` only when the scores allow it, whatever the model said."""
    raw = data.get("scores") if isinstance(data.get("scores"), dict) else {}
    scores: dict[str, dict] = {}
    for d in DIMENSIONS:
        item = raw.get(d) if isinstance(raw.get(d), dict) else {}
        v = item.get("score")
        try:
            score = 1 if isinstance(v, bool) else max(1, min(5, int(v)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            score = 1
        scores[d] = {"score": score, "comment": _sentence(item.get("comment"))}
    earned = all(scores[d]["score"] >= PASS_MIN for d in DIMENSIONS)
    passed = bool(data.get("passed")) and earned
    summary = _sentence(data.get("summary"))
    if not summary:
        summary = ("Passed: the unit's goals are reached well enough to move on." if passed
                   else "Not yet: at least one part of the checkpoint fell short of the unit's goals. Retake it any time.")
    focus = data.get("review_focus")
    review_focus = [_sentence(x) for x in focus if _sentence(x)] if isinstance(focus, list) else []
    return {"passed": passed, "scores": scores, "summary": summary, "review_focus": review_focus[:MAX_REVIEW_FOCUS]}


def _bullets(items: list) -> str:
    return "\n".join(f"- {x}" for x in items) or "- (none)"


async def submit(checkpoint_id: int, speaking_text: str, writing_text: str, *, stt_provider: str | None = None) -> dict:
    """Grade one attempt. 404 unknown, 409 already graded or no longer the current unit, 400 missing text."""
    row = await db.fetchone("SELECT * FROM checkpoints WHERE id=?", (checkpoint_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="No such checkpoint.")
    if row["finished_at"] is not None:
        raise HTTPException(status_code=409, detail="This checkpoint was already graded. Open the current unit for a new attempt.")
    # The raw transcript stays raw; only surrounding whitespace goes. The written text keeps its line breaks.
    speaking = str(speaking_text or "").strip()[:MAX_TEXT_CHARS]
    writing = str(writing_text or "").strip()[:MAX_TEXT_CHARS]
    if not speaking:
        raise HTTPException(status_code=400, detail="The speaking part is missing: record it or type what you said.")
    if not writing:
        raise HTTPException(status_code=400, detail="The written part is missing.")
    unit = await curriculum.current_unit()
    if unit["id"] != row["unit_id"]:
        # A stale row from a unit he already left must not advance him a second time.
        raise HTTPException(status_code=409, detail="This checkpoint belongs to a unit you are no longer in.")
    phase = curriculum.phase_of(unit["id"])
    tasks = loads(row["tasks"], None)
    if not isinstance(tasks, dict) or "speaking" not in tasks or "writing" not in tasks:
        tasks = tasks_for(unit)
    system = render(
        "checkpoint_grade",
        level=phase["level"], unit_title=unit["title"],
        can_do=_bullets(unit.get("can_do") or []), grammar=_bullets(unit.get("grammar") or []),
        speaking_task=tasks["speaking"].get("prompt", ""), writing_task=tasks["writing"].get("prompt", ""),
        words_range=f"{tasks['writing'].get('words_min', DEFAULT_WORDS[0])}–{tasks['writing'].get('words_max', DEFAULT_WORDS[1])}",
        speaking_transcript=speaking, writing_text=writing,
    )
    data = await llm.complete_json(system, [Message("user", "Grade the checkpoint.")], GRADE_SCHEMA,
                                   tier="quality", temperature=0.2, max_tokens=1024)
    graded = validate_grade(data)

    # Writes start only now, and the first commit (inside advance/update_profile) lands the row and
    # the profile change together, so an outage during grading leaves nothing behind.
    result = {**graded, "speaking_transcript": speaking, "stt_provider": stt_provider}
    await db.conn.execute(
        "UPDATE checkpoints SET speaking_transcript=?, writing_text=?, result=?, passed=?, finished_at=? WHERE id=?",
        (speaking, writing, json.dumps(result, ensure_ascii=False), int(graded["passed"]), time.time(), checkpoint_id))
    advanced_to = None
    finished = False
    if graded["passed"]:
        adv = await curriculum.advance()
        if adv.get("finished"):
            finished = True
            await profile.update_profile(review_focus=[])
        else:
            advanced_to = {"phase": adv["phase"], "unit": adv["unit"], "phase_changed": bool(adv.get("phase_changed"))}
    else:
        await profile.update_profile(review_focus=graded["review_focus"])
    await db.conn.commit()
    await db.bump_activity("checkpoint")
    return {
        "passed": graded["passed"], "scores": graded["scores"], "summary": graded["summary"],
        "review_focus": graded["review_focus"], "speaking_transcript": speaking,
        "advanced_to": advanced_to, "finished_curriculum": finished,
    }
