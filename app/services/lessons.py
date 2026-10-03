"""The coursework: what actually teaches the language, before any of the practice modes.

`units.json` is a syllabus — "sein in the singular" is a note a teacher writes for themselves, not
something a learner can use. These lessons are the teaching, hand-written in
`curriculum/lessons.json` rather than generated: a beginner's first contact with German should be
identical every time, correct, and free of quota.

A unit's lesson is a list of steps (`sounds`, `words`, `grammar`, `check`). Progress is the furthest
step reached, so closing the app mid-lesson costs nothing.
"""
from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from typing import Any

from ..config import settings
from ..db import db

log = logging.getLogger(__name__)

STEP_TYPES = {"sounds", "words", "grammar", "check"}


class LessonError(Exception):
    pass


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    path = settings.curriculum_path.parent / "lessons.json"
    if not path.exists():
        raise LessonError(f"no lessons at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    for unit_id, lesson in data.items():
        if unit_id.startswith("_") or unit_id == "version":
            continue
        _validate(unit_id, lesson)
    return data


def _validate(unit_id: str, lesson: dict) -> None:
    if not lesson.get("title") or not isinstance(lesson.get("steps"), list) or not lesson["steps"]:
        raise LessonError(f"lesson {unit_id} needs a title and at least one step")
    for i, step in enumerate(lesson["steps"]):
        kind = step.get("type")
        if kind not in STEP_TYPES:
            raise LessonError(f"lesson {unit_id} step {i}: unknown type {kind!r}")
        if kind in ("words", "sounds") and not step.get("items"):
            raise LessonError(f"lesson {unit_id} step {i}: {kind} needs items")
        if kind == "check":
            options = step.get("options") or []
            if not step.get("question") or len(options) < 2:
                raise LessonError(f"lesson {unit_id} step {i}: a check needs a question and options")
            if not isinstance(step.get("answer"), int) or not 0 <= step["answer"] < len(options):
                raise LessonError(f"lesson {unit_id} step {i}: answer must index into options")


def for_unit(unit_id: str) -> dict[str, Any] | None:
    lesson = load().get(unit_id)
    return dict(lesson) if isinstance(lesson, dict) else None


def spoken_lines(lesson: dict) -> list[str]:
    """Every German line in the lesson, in order — what the Learn screen can play aloud."""
    out: list[str] = []
    for step in lesson.get("steps", []):
        for item in step.get("items", []) or []:
            if item.get("de"):
                out.append(item["de"])
        for ex in step.get("examples", []) or []:
            if ex.get("de"):
                out.append(ex["de"])
    return out


# -- progress ---------------------------------------------------------------
EMPTY = {"step": 0, "completed": False, "checks_right": 0, "checks_total": 0,
         "started_at": None, "completed_at": None}


async def progress(unit_id: str) -> dict[str, Any]:
    row = await db.fetchone("SELECT * FROM lesson_progress WHERE unit_id=?", (unit_id,))
    if not row:
        return dict(EMPTY)
    return {"step": int(row["step"]), "completed": bool(row["completed"]),
            "checks_right": int(row["checks_right"]), "checks_total": int(row["checks_total"]),
            "started_at": row["started_at"], "completed_at": row["completed_at"]}


async def save_step(unit_id: str, step: int) -> dict[str, Any]:
    """Record the furthest step reached. Never moves backwards: re-reading an earlier page is not
    losing progress."""
    now = time.time()
    await db.execute(
        "INSERT INTO lesson_progress (unit_id, step, started_at) VALUES (?, ?, ?) "
        "ON CONFLICT(unit_id) DO UPDATE SET step = MAX(step, excluded.step)",
        (unit_id, max(0, int(step)), now))
    return await progress(unit_id)


async def record_check(unit_id: str, correct: bool) -> dict[str, Any]:
    now = time.time()
    await db.execute(
        "INSERT INTO lesson_progress (unit_id, checks_right, checks_total, started_at) VALUES (?, ?, 1, ?) "
        "ON CONFLICT(unit_id) DO UPDATE SET checks_right = checks_right + ?, checks_total = checks_total + 1",
        (unit_id, 1 if correct else 0, now, 1 if correct else 0))
    return await progress(unit_id)


async def complete(unit_id: str) -> dict[str, Any]:
    """Idempotent: finishing twice keeps the first completion time."""
    lesson = for_unit(unit_id)
    if lesson is None:
        raise LessonError(f"no lesson for unit {unit_id}")
    now = time.time()
    last = len(lesson["steps"])
    await db.execute(
        "INSERT INTO lesson_progress (unit_id, step, completed, started_at, completed_at) VALUES (?, ?, 1, ?, ?) "
        "ON CONFLICT(unit_id) DO UPDATE SET step = MAX(step, excluded.step), completed = 1, "
        "completed_at = COALESCE(completed_at, excluded.completed_at)",
        (unit_id, last, now, now))
    await db.bump_activity("lesson")
    return await progress(unit_id)


async def status_for(unit_id: str) -> dict[str, Any]:
    """What the Talk screen and the tab badge need: is there a lesson, and has he done it?"""
    lesson = for_unit(unit_id)
    if lesson is None:
        return {"has_lesson": False, "completed": True, "step": 0, "steps": 0, "title": None}
    p = await progress(unit_id)
    return {"has_lesson": True, "completed": p["completed"], "step": p["step"],
            "steps": len(lesson["steps"]), "title": lesson["title"], "minutes": lesson.get("minutes")}
