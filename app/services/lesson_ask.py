"""Ask about this: a question about the lesson screen the learner is looking at.

The client sends the exercise exactly as it is showing it (it is the learner's own lesson, so there is
nothing to trust or hide), plus what the learner picked and the question. The model gets the screen
written out as text, the unit and the level, and answers in a few lines with optional examples to
hear. One model call per question; a follow-up carries the earlier questions and answers.
"""
from __future__ import annotations

import json
from typing import Any

from .. import users
from ..prompts import render
from ..providers.base import Message
from ..providers.llm import LLMUnavailable, llm
from . import curriculum, profile

MAX_QUESTION_CHARS = 500
MAX_HISTORY = 4
MAX_EXAMPLES = 3

ASK_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string", "description": "The explanation: two to five short sentences, plain text."},
        "examples": {"type": "array", "items": {
            "type": "object",
            "properties": {"de": {"type": "string"}, "en": {"type": "string"}},
            "required": ["de", "en"]}},
    },
    "required": ["answer", "examples"],
}


def _text(v: Any, limit: int = 600) -> str:
    return " ".join(str(v or "").split())[:limit]


def describe_screen(ex: dict, picked: str | None) -> str:
    """The exercise as the learner sees it, in plain lines. Unknown fields are left out, so a client
    cannot stuff the prompt with anything but lesson content."""
    kind = _text(ex.get("type"), 20)
    lines = [f"Type: {kind}"]
    if ex.get("title"):
        lines.append(f"Title: {_text(ex['title'])}")
    if ex.get("body"):
        lines.append(f"Explanation shown: {_text(ex['body'], 900)}")
    if ex.get("question"):
        lines.append(f"Question: {_text(ex['question'])}")
    if kind == "gap":
        lines.append(f"Sentence: {_text(ex.get('before'))} ___ {_text(ex.get('after'))}")
        if ex.get("en"):
            lines.append(f"Meaning given: {_text(ex['en'])}")
    elif kind == "build":
        lines.append(f"Build this sentence from tiles: {_text(ex.get('en'))}")
        lines.append(f"Answer: {' '.join(_text(w, 40) for w in (ex.get('answer') or [])[:16])}")
    elif kind == "listen":
        lines.append(f"Heard: {_text(ex.get('audio'))} ({_text(ex.get('en'))})")
    elif kind == "speak":
        lines.append(f"Say: {_text(ex.get('de'))} ({_text(ex.get('en'))})")
    elif kind == "match":
        pairs = [f"{_text(p.get('de'), 80)} = {_text(p.get('en'), 80)}" for p in (ex.get("pairs") or [])[:8]]
        lines.append("Pairs: " + "; ".join(pairs))
    options = [_text(o, 160) for o in (ex.get("options") or [])[:6]]
    if options:
        lines.append("Options: " + " | ".join(options))
        answer = ex.get("answer")
        if isinstance(answer, int) and 0 <= answer < len(options):
            lines.append(f"Right answer: {options[answer]}")
    if ex.get("why"):
        lines.append(f"Explanation after answering: {_text(ex['why'])}")
    for key, label in (("items", "Words"), ("examples", "Examples"), ("lines", "Text")):
        rows = [f"{_text(i.get('de'), 160)} ({_text(i.get('en'), 160)})" for i in (ex.get(key) or [])[:16]
                if isinstance(i, dict) and i.get("de")]
        if rows:
            lines.append(f"{label}: " + "; ".join(rows))
    table = ex.get("table")
    if isinstance(table, dict) and isinstance(table.get("rows"), list):
        rows = [" / ".join(_text(c, 60) for c in r[:4]) for r in table["rows"][:10] if isinstance(r, list)]
        lines.append("Table: " + "; ".join(rows))
    if ex.get("note"):
        lines.append(f"Note: {_text(ex['note'])}")
    if picked:
        lines.append(f"The learner answered: {_text(picked, 200)}")
    return "\n".join(lines)


def _answer_language(level: str) -> str:
    if level.upper().startswith("C"):
        return ("Answer in German, as one would to an advanced learner, unless the question was asked in "
                "English; then answer in English.")
    return "Answer in plain English. German appears only as the words and sentences you are explaining."


async def ask(unit_id: str, exercise: dict, picked: str | None, question: str,
              history: list[dict] | None = None) -> dict:
    question = _text(question, MAX_QUESTION_CHARS)
    if not question:
        raise ValueError("Ask a question first.")
    user = users.current()
    p = await profile.get_profile()
    unit = curriculum.unit(unit_id)
    unit = curriculum.render_for_user(unit) if unit else {}
    past = [h for h in (history or []) if isinstance(h, dict) and h.get("q") and h.get("a")][-MAX_HISTORY:]
    system = render(
        "lesson_ask",
        name=user["name"],
        about=profile.about_text(user),
        level=p["level"],
        unit_title=unit.get("title") or profile.NONE_YET,
        grammar_targets="; ".join(unit.get("grammar") or []) or profile.NONE_YET,
        screen=describe_screen(exercise, picked),
        history="\n".join(f"Q: {_text(h['q'], 300)}\nA: {_text(h['a'], 600)}" for h in past) or profile.NONE_YET,
        answer_language=_answer_language(p["level"]),
    )
    data = await llm.complete_json(system, [Message("user", question)], ASK_SCHEMA,
                                   temperature=0.3, max_tokens=700)
    answer = _text(data.get("answer"), 1500)
    if not answer:
        raise LLMUnavailable("The answer came back empty. Ask again.")
    raw = data.get("examples") if isinstance(data.get("examples"), list) else []
    examples = [{"de": _text(e.get("de"), 200), "en": _text(e.get("en"), 200)} for e in raw
                if isinstance(e, dict) and _text(e.get("de")) and _text(e.get("en"))][:MAX_EXAMPLES]
    return {"answer": answer, "examples": examples}


def exercise_size_ok(exercise: dict) -> bool:
    return len(json.dumps(exercise, ensure_ascii=False)) <= 12000
