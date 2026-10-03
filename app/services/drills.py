"""Drill mode: short items generated from his own mistakes, graded locally where the answer is exact.

The items are built from the stored examples of his weakest mistake categories, so he re-meets his
own sentences. Grading is a string compare for everything but free-text `transform` items, which go
to the fast model only when the normalised answer differs. A right answer bumps `mistakes.resolved`
on the source row, a wrong one bumps `count` — that is what retires a mistake from the tutor prompt.
"""
from __future__ import annotations

import json
import time
import unicodedata

from .. import taxonomy
from ..config import settings
from ..db import db, loads
from ..prompts import render
from ..providers.base import Message
from ..providers.llm import LLMUnavailable, llm
from . import curriculum, mistakes, profile

NONE_YET = profile.NONE_YET
TYPES = ["fill_blank", "choose", "reorder", "transform"]
MIN_ITEMS, MAX_ITEMS = 3, 12
MAX_TARGETS = 3          # categories per drill: fewer targets, more repetition
MAX_REFS = 12            # mistakes shown to the generator
MAX_EXAMPLES_PER_REF = 3
NOTHING_USABLE = "The drill generator returned nothing usable. Try again."

GENERATE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": TYPES},
                    "prompt": {"type": "string", "description": "The sentence with ___, the question, the scrambled words, or the sentence plus instruction."},
                    "options": {"type": "array", "items": {"type": "string"},
                                "description": "choose: 3-4 choices incl. the answer; fill_blank: 3 short choices; reorder/transform: empty."},
                    "answer": {"type": "string", "description": "Exactly what he must produce."},
                    "category": {"type": "string", "enum": taxonomy.CATEGORY_SLUGS},
                    "explanation": {"type": "string", "description": "One sentence, English, concrete: the rule and the result."},
                    "mistake_ref": {"type": "integer", "description": "Number of the mistake this item is built from, or -1."},
                },
                "required": ["type", "prompt", "options", "answer", "category", "explanation", "mistake_ref"],
            },
        },
    },
    "required": ["items"],
}

GRADE_SCHEMA = {
    "type": "object",
    "properties": {
        "correct": {"type": "boolean"},
        "note": {"type": "string", "description": "One short English sentence, or empty."},
    },
    "required": ["correct", "note"],
}


def _text(v: object) -> str:
    return " ".join(v.split()).strip() if isinstance(v, str) else ""


# -- grading ----------------------------------------------------------------------------

def normalize_answer(s: object) -> str:
    """Lowercase, punctuation stripped, whitespace collapsed — what a phone keyboard varies, not what grammar does."""
    out = []
    for ch in unicodedata.normalize("NFC", str(s or "")).lower():
        out.append(" " if unicodedata.category(ch).startswith("P") else ch)
    return " ".join("".join(out).split())


def grade_exact(expected: object, given: object) -> bool:
    e = normalize_answer(expected)
    return bool(e) and e == normalize_answer(given)


async def _grade(item: dict, given: str) -> tuple[bool, str]:
    """(correct, explanation). Only a transform item that differs from the key costs a model call."""
    if grade_exact(item["answer"], given):
        return True, item["explanation"]
    if item["type"] != "transform" or not given.strip():
        return False, item["explanation"]
    system = render("drill_grade", prompt=item["prompt"], expected=item["answer"], given=given.strip())
    data = await llm.complete_json(system, [Message("user", "Grade it.")], GRADE_SCHEMA, tier="fast",
                                   temperature=0.0, max_tokens=200)
    correct = data.get("correct") is True
    note = _text(data.get("note"))
    return correct, " ".join(x for x in (item["explanation"], note) if x)


async def _touch_mistake(item: dict, correct: bool) -> None:
    """Right → one step towards retiring the source mistake; wrong → it is still live."""
    mid = item.get("mistake_id")
    if mid is None:
        row = await mistakes.by_category(item["category"])
        mid = row["id"] if row else None
    if mid is None:
        return
    if correct:
        await mistakes.resolve(int(mid))
    else:
        await mistakes.fail(int(mid))


# -- generation -------------------------------------------------------------------------

def _validate_item(raw: object, refs: list[dict]) -> dict | None:
    """One stored item, or None when the model's item cannot be graded safely."""
    if not isinstance(raw, dict):
        return None
    kind = _text(raw.get("type")).lower()
    prompt, answer = _text(raw.get("prompt")), _text(raw.get("answer"))
    if kind not in TYPES or not prompt or not answer:
        return None
    options = raw.get("options")
    options = [_text(o) for o in options if _text(o)] if isinstance(options, list) else []
    if kind == "choose":
        if not any(grade_exact(answer, o) for o in options):
            return None
    elif kind == "fill_blank":
        # Options that do not contain the key would mislead; the item still works as free text.
        if options and not any(grade_exact(answer, o) for o in options):
            options = []
    else:
        options = []
    ref = raw.get("mistake_ref")
    mistake_id = refs[ref - 1]["id"] if isinstance(ref, int) and not isinstance(ref, bool) and 1 <= ref <= len(refs) else None
    return {"type": kind, "prompt": prompt, "options": options, "answer": answer,
            "category": taxonomy.normalize(_text(raw.get("category"))),
            "explanation": _text(raw.get("explanation")), "mistake_id": mistake_id}


def _format_refs(refs: list[dict]) -> str:
    lines = []
    for i, r in enumerate(refs, 1):
        examples = [e for e in r.get("examples") or [] if e.get("wrong") and e.get("right")][-MAX_EXAMPLES_PER_REF:]
        shown = "; ".join(f"he wrote \"{e['wrong']}\", correct \"{e['right']}\"" for e in examples) or "(no example stored)"
        lines.append(f"{i}. [{r['category']}] {r['pattern']} — {shown}")
    return "\n".join(lines)


async def pick_targets() -> tuple[list[str], list[dict]]:
    """The 2-3 categories with the most open mistakes (count - resolved summed), and the rows behind them."""
    open_rows = await mistakes.all_open(limit=50)
    weight: dict[str, int] = {}
    for r in open_rows:
        weight[r["category"]] = weight.get(r["category"], 0) + max(1, int(r["count"]) - int(r["resolved"]))
    categories = sorted(weight, key=lambda c: (-weight[c], c))[:MAX_TARGETS]
    refs = [r for r in open_rows if r["category"] in categories][:MAX_REFS]
    return categories, refs


def public_item(item: dict, index: int) -> dict:
    """docs/API.md: answers, explanations and mistake links stay on the server until he answers."""
    return {"index": index, "type": item["type"], "prompt": item["prompt"],
            "options": item["options"] or None, "category": item["category"]}


async def new(n: int | None = None) -> dict:
    """docs/API.md GET /drill/new."""
    n = settings.drill_items if n is None else int(n)
    n = max(MIN_ITEMS, min(MAX_ITEMS, n))
    p = await profile.get_profile()
    unit = await curriculum.current_unit()
    categories, refs = await pick_targets()
    if categories:
        targets = ("The categories where he currently makes the most mistakes — every item drills one of these:\n"
                   + "\n".join(f"- {c}: {taxonomy.CATEGORIES[c]}" for c in categories))
    else:
        # Nothing in the log yet (first days, or everything beaten): drill the unit instead, and say so.
        targets = ("He has no open mistakes in the log yet, so drill this unit's grammar targets instead, "
                   "with sentences from his life. Use mistake_ref -1 for every item:\n"
                   + "\n".join(f"- {g}" for g in unit.get("grammar") or []))
    system = render(
        "drill_generate",
        level=p["level"],
        unit_title=unit.get("title") or NONE_YET,
        review_focus="; ".join(p["review_focus"]) or NONE_YET,
        targets=targets,
        mistakes=_format_refs(refs) or NONE_YET,
        count=n,
    )
    data = await llm.complete_json(system, [Message("user", f"Generate {n} items.")], GENERATE_SCHEMA,
                                   temperature=0.6, max_tokens=2048)
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise LLMUnavailable(NOTHING_USABLE)
    items: list[dict] = []
    for raw in raw_items:
        item = _validate_item(raw, refs)
        if item:
            items.append(item)
        if len(items) == n:
            break
    if len(items) < MIN_ITEMS:
        raise LLMUnavailable(NOTHING_USABLE)
    if not categories:
        categories = sorted({i["category"] for i in items})
    blanks = json.dumps([None] * len(items))
    drill_id = await db.execute(
        "INSERT INTO drills (categories, items, answers, results, created_at) VALUES (?, ?, ?, ?, ?)",
        (json.dumps(categories), json.dumps(items, ensure_ascii=False), blanks, blanks, time.time()))
    return {"id": drill_id, "categories": categories, "items": [public_item(it, i) for i, it in enumerate(items)]}


# -- answering --------------------------------------------------------------------------

async def _load(drill_id: int) -> dict:
    row = await db.fetchone("SELECT * FROM drills WHERE id=?", (drill_id,))
    if row is None:
        raise LookupError(f"no drill {drill_id}")
    items = [i for i in loads(row["items"], []) if isinstance(i, dict)]
    answers = loads(row["answers"], None)
    results = loads(row["results"], None)
    # A row written before an item was dropped, or by hand, must still line up with its items.
    if not isinstance(answers, list) or len(answers) != len(items):
        answers = [None] * len(items)
    if not isinstance(results, list) or len(results) != len(items):
        results = [None] * len(items)
    return {**row, "items": items, "answers": answers, "results": results}


async def _grade_one(drill: dict, index: int, given: str) -> dict:
    """Grade one unanswered item, persist it, touch its mistake, and close the drill when it was the last."""
    item = drill["items"][index]
    correct, explanation = await _grade(item, given)
    result = {"index": index, "correct": correct, "answer": item["answer"], "your_answer": given,
              "explanation": explanation}
    drill["answers"][index] = given
    drill["results"][index] = result
    finished = all(r is not None for r in drill["results"])
    if finished:
        drill["score"] = sum(1 for r in drill["results"] if r["correct"])
        drill["finished_at"] = time.time()
    await db.execute(
        "UPDATE drills SET answers=?, results=?, score=?, finished_at=? WHERE id=?",
        (json.dumps(drill["answers"], ensure_ascii=False), json.dumps(drill["results"], ensure_ascii=False),
         drill["score"], drill["finished_at"], drill["id"]))
    await _touch_mistake(item, correct)
    if finished:
        await db.bump_activity("drill")
    return result


def _check_index(drill: dict, index: object) -> int:
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(drill["items"]):
        raise ValueError(f"no item at index {index!r}")
    return index


async def answer(drill_id: int, index: int, answer: str) -> dict:
    """docs/API.md POST /drill/{id}/answer. A second answer to the same index returns the stored result untouched."""
    drill = await _load(drill_id)
    index = _check_index(drill, index)
    result = drill["results"][index] or await _grade_one(drill, index, str(answer or ""))
    return {**result, "finished": drill["finished_at"] is not None, "score": drill["score"], "total": len(drill["items"])}


async def submit(drill_id: int, answers: list) -> dict:
    """docs/API.md POST /drill/{id}/submit. null entries stay unanswered; already graded indexes are skipped."""
    drill = await _load(drill_id)
    if not isinstance(answers, list):
        raise ValueError("answers must be a list")
    for index, given in enumerate(answers[:len(drill["items"])]):
        if given is None or drill["results"][index] is not None:
            continue
        await _grade_one(drill, index, str(given))
    graded = [r for r in drill["results"] if r is not None]
    return {"results": graded, "score": sum(1 for r in graded if r["correct"]), "total": len(drill["items"]),
            "finished": drill["finished_at"] is not None}
