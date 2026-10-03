"""The one place that writes the mistake log.

The analyzer, the writing feedback and the drills all go through `record`, so a recurring error
aggregates into one row whoever spotted it. The merge key is (category, normalised pattern):
lowercase, whitespace collapsed. A near-duplicate row per session would mean nothing ever reaches a
count of three and the drills would have nothing to aim at.
"""
from __future__ import annotations

import json
import time

from ..db import db, loads
from ..taxonomy import normalize

MAX_EXAMPLES = 5


def pattern_key(pattern: str | None) -> str:
    return " ".join(str(pattern or "").split()).strip().lower()


async def record(category: str, pattern: str, wrong: str = "", right: str = "", note: str = "",
                 *, now: float | None = None, commit: bool = True) -> int:
    """Merge one observation into the log. Returns the row id. `commit=False` lets a caller batch writes."""
    category = normalize(category)
    key = pattern_key(pattern) or pattern_key(f"{wrong} -> {right}") or category
    now = now or time.time()
    example = {"wrong": str(wrong or "").strip(), "right": str(right or "").strip(), "note": str(note or "").strip()}
    row = await db.fetchone("SELECT id, examples FROM mistakes WHERE category=? AND pattern=?", (category, key))
    if row:
        examples = [e for e in loads(row["examples"], []) if isinstance(e, dict)]
        if example["wrong"] or example["right"]:
            examples.append(example)
        examples = examples[-MAX_EXAMPLES:]
        await db.conn.execute("UPDATE mistakes SET count=count+1, examples=?, last_seen=? WHERE id=?",
                              (json.dumps(examples, ensure_ascii=False), now, row["id"]))
        row_id = int(row["id"])
    else:
        examples = [example] if (example["wrong"] or example["right"]) else []
        cur = await db.conn.execute(
            "INSERT INTO mistakes (category, pattern, count, resolved, examples, first_seen, last_seen) "
            "VALUES (?, ?, 1, 0, ?, ?, ?)",
            (category, key, json.dumps(examples, ensure_ascii=False), now, now))
        row_id = int(cur.lastrowid or 0)
    if commit:
        await db.conn.commit()
    return row_id


async def resolve(mistake_id: int) -> None:
    """A correct drill answer: one step towards retiring the mistake from the prompt."""
    await db.execute("UPDATE mistakes SET resolved=resolved+1 WHERE id=?", (mistake_id,))


async def fail(mistake_id: int, now: float | None = None) -> None:
    """A wrong drill answer: the mistake is still live."""
    await db.execute("UPDATE mistakes SET count=count+1, last_seen=? WHERE id=?", (now or time.time(), mistake_id))


async def by_category(category: str) -> dict | None:
    """The most pressing open mistake in a category, for drill items that carry no row reference."""
    return await db.fetchone(
        "SELECT * FROM mistakes WHERE category=? AND count > resolved ORDER BY (count - resolved) DESC, last_seen DESC LIMIT 1",
        (normalize(category),))


async def all_open(limit: int = 20) -> list[dict]:
    rows = await db.fetchall(
        "SELECT * FROM mistakes WHERE count > resolved ORDER BY (count - resolved) DESC, last_seen DESC LIMIT ?", (limit,))
    for r in rows:
        r["examples"] = [e for e in loads(r["examples"], []) if isinstance(e, dict)]
    return rows


async def beaten(limit: int = 20) -> list[dict]:
    rows = await db.fetchall(
        "SELECT * FROM mistakes WHERE count <= resolved ORDER BY last_seen DESC LIMIT ?", (limit,))
    for r in rows:
        r["examples"] = [e for e in loads(r["examples"], []) if isinstance(e, dict)]
    return rows
