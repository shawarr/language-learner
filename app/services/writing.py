"""Write mode: a task from the current unit, then feedback on what he wrote.

The feedback's corrections go into the mistake log through `mistakes.record`, the same merge path
the analyzer uses, so an error he makes in writing and in speech is one row with one count.
"""
from __future__ import annotations

import json
import time

from .. import taxonomy
from ..db import db, loads
from ..prompts import render
from ..providers.base import Message
from ..providers.llm import LLMUnavailable, llm
from . import curriculum, mistakes, profile

NONE_YET = profile.NONE_YET
WORDS_MIN, WORDS_MAX = 20, 250
MAX_CORRECTIONS = 8
RECENT_PROMPTS = 5
# Defaults when the model's word range is unusable. Scaled by level: a beginner given 200 words quits.
WORDS_BY_LEVEL = {"A1": (40, 80), "A2": (60, 120), "B1": (90, 160), "B2": (120, 200)}

PROMPT_SCHEMA = {
    "type": "object",
    "properties": {
        "task": {"type": "string",
                 "description": "English instructions: who the text is to, the situation, and what it must achieve."},
        "to": {"type": "string", "description": "The recipient in a few words."},
        "must_include": {"type": "array", "items": {"type": "string"},
                         "description": "Two to four concrete, checkable things the text must contain."},
        "words_min": {"type": "integer"},
        "words_max": {"type": "integer"},
    },
    "required": ["task", "to", "must_include", "words_min", "words_max"],
}

FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "wrong": {"type": "string", "description": "The exact span from his text."},
                    "right": {"type": "string", "description": "The fixed span."},
                    "category": {"type": "string", "enum": taxonomy.CATEGORY_SLUGS},
                    "explanation": {"type": "string", "description": "One sentence, English, about his sentence."},
                    "pattern": {"type": "string",
                                "description": "The recurring error in a few words; reuse the wording of a known mistake when it is the same error."},
                },
                "required": ["wrong", "right", "category", "explanation", "pattern"],
            },
        },
        "improved": {"type": "string",
                     "description": "His text rewritten one level above his own: recognisably his, not a new text."},
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "strengths": {"type": "string", "description": "One sentence."},
        "next_time": {"type": "string", "description": "One concrete thing to try next time."},
    },
    "required": ["corrections", "improved", "score", "strengths", "next_time"],
}


def _text(v: object) -> str:
    return " ".join(str(v).split()).strip() if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def _default_words(level: str) -> tuple[int, int]:
    return WORDS_BY_LEVEL.get((level or "")[:2].upper(), WORDS_BY_LEVEL["A1"])


def _word_range(lo: object, hi: object, level: str) -> tuple[int, int]:
    """Clamp the model's range to 20..250 and keep min below max; fall back to the level's default."""
    d_lo, d_hi = _default_words(level)
    try:
        lo_i, hi_i = int(lo), int(hi)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return d_lo, d_hi
    lo_i = max(WORDS_MIN, min(WORDS_MAX, lo_i))
    hi_i = max(WORDS_MIN, min(WORDS_MAX, hi_i))
    if hi_i <= lo_i:
        return d_lo, d_hi
    return lo_i, hi_i


async def new_prompt() -> dict:
    """docs/API.md GET /write/prompt."""
    p = await profile.get_profile()
    unit = await curriculum.current_unit()
    recent = await db.fetchall("SELECT prompt FROM writings ORDER BY created_at DESC, id DESC LIMIT ?", (RECENT_PROMPTS,))
    system = render(
        "write_prompt",
        level=p["level"],
        unit_title=unit.get("title") or NONE_YET,
        can_do="; ".join(unit.get("can_do") or []) or NONE_YET,
        grammar_targets=", ".join(unit.get("grammar") or []) or NONE_YET,
        vocab_themes=", ".join(unit.get("vocab_themes") or []) or NONE_YET,
        facts="; ".join(p["facts"]) or NONE_YET,
        review_focus="; ".join(p["review_focus"]) or NONE_YET,
        recent_prompts="\n".join(f"- {r['prompt']}" for r in recent) or NONE_YET,
    )
    data = await llm.complete_json(system, [Message("user", "Set the next writing task.")], PROMPT_SCHEMA,
                                   tier="fast", temperature=0.8, max_tokens=512)
    task = _text(data.get("task"))
    if not task:
        raise LLMUnavailable("The writing task came back empty. Try again.")
    raw_include = data.get("must_include")
    must_include = [_text(x) for x in raw_include if isinstance(x, str) and _text(x)][:4] if isinstance(raw_include, list) else []
    lo, hi = _word_range(data.get("words_min"), data.get("words_max"), p["level"])
    return {"task": task, "to": _text(data.get("to")), "must_include": must_include,
            "words_min": lo, "words_max": hi, "unit_id": unit["id"]}


def validate_feedback(data: dict, text: str) -> dict:
    """What gets stored and returned. Raises LLMUnavailable when the reply cannot be used at all."""
    raw = data.get("corrections")
    if not isinstance(raw, list):
        raise LLMUnavailable("The feedback came back unreadable. Try again.")
    corrections = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        wrong, right = _text(c.get("wrong")), _text(c.get("right"))
        if not wrong or not right:
            continue
        corrections.append({"wrong": wrong, "right": right, "category": taxonomy.normalize(_text(c.get("category"))),
                            "explanation": _text(c.get("explanation")), "pattern": _text(c.get("pattern"))})
        if len(corrections) == MAX_CORRECTIONS:
            break
    try:
        score = max(1, min(5, int(round(float(data.get("score"))))))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        score = 3
    return {"corrections": corrections, "improved": _text(data.get("improved")) or text, "score": score,
            "strengths": _text(data.get("strengths")), "next_time": _text(data.get("next_time"))}


async def submit(prompt: str, text: str) -> dict:
    """docs/API.md POST /write/submit: grade, store the writing, feed the mistake log, count the activity."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Write something first.")
    prompt = (prompt or "").strip() or "(free writing)"
    p = await profile.get_profile()
    unit = await curriculum.current_unit()
    system = render(
        "write_feedback",
        level=p["level"],
        grammar_targets=", ".join(unit.get("grammar") or []) or NONE_YET,
        top_mistakes=profile.format_mistakes(await profile.top_mistakes()) or NONE_YET,
        categories=taxonomy.describe_for_prompt(),
        prompt=prompt,
        text=text,
    )
    # Feedback is the one place a weak model does real damage (a wrong "correction" gets logged as his
    # mistake), so it takes the quality tier; the task prompt above is fine on the fast one.
    data = await llm.complete_json(system, [Message("user", "Give your feedback as JSON.")], FEEDBACK_SCHEMA,
                                   tier="quality", temperature=0.3, max_tokens=1536)
    feedback = validate_feedback(data, text)
    now = time.time()
    # One transaction: the writing row and its corrections land together or not at all.
    cur = await db.conn.execute(
        "INSERT INTO writings (unit_id, prompt, text, feedback, score, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (unit["id"], prompt, text, json.dumps(feedback, ensure_ascii=False), feedback["score"], now))
    for c in feedback["corrections"]:
        await mistakes.record(c["category"], c["pattern"], c["wrong"], c["right"], note=c["explanation"],
                              now=now, commit=False)
    await db.conn.commit()
    await db.bump_activity("write")
    return {"id": int(cur.lastrowid or 0), **feedback}


async def recent(limit: int = 10) -> list[dict]:
    rows = await db.fetchall(
        "SELECT id, prompt, text, feedback, score, created_at FROM writings ORDER BY created_at DESC, id DESC LIMIT ?",
        (max(1, min(int(limit), 100)),))
    for r in rows:
        r["feedback"] = loads(r["feedback"], {})
    return rows
