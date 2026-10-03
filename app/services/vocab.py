"""Vocabulary: upserts from the tutor/analyzer/writing/manual paths, browsing, and (D2) the SRS queue.

`upsert` never touches an existing row's SRS state — a word the tutor mentions again must not reset
to "due now" and wipe out months of scheduling.
"""
from __future__ import annotations

import time

from ..db import db

SOURCES = {"manual", "tutor", "analyzer", "writing"}


def clean_word(word: object) -> str:
    return " ".join(str(word or "").split()).strip()


async def upsert(word: str, translation: str, example: str = "", source: str = "manual",
                 *, now: float | None = None, commit: bool = True) -> tuple[int, bool]:
    """Returns (vocab_id, created). An existing row keeps its SRS state; an empty example gets filled in."""
    word = clean_word(word)
    translation = clean_word(translation)
    if not word or not translation:
        raise ValueError("word and translation are required")
    source = source if source in SOURCES else "manual"
    now = now or time.time()
    row = await db.fetchone("SELECT id, example FROM vocab WHERE word=? COLLATE NOCASE", (word,))
    if row:
        if example and not row["example"]:
            await db.conn.execute("UPDATE vocab SET example=? WHERE id=?", (clean_word(example), row["id"]))
        if commit:
            await db.conn.commit()
        return int(row["id"]), False
    cur = await db.conn.execute(
        "INSERT INTO vocab (word, translation, example, source, created_at, due) VALUES (?, ?, ?, ?, ?, ?)",
        (word, translation, clean_word(example), source, now, now))
    if commit:
        await db.conn.commit()
    return int(cur.lastrowid or 0), True


async def get(vocab_id: int) -> dict | None:
    row = await db.fetchone("SELECT * FROM vocab WHERE id=?", (vocab_id,))
    return card(row) if row else None


def card(row: dict) -> dict:
    """The API shape (docs/API.md)."""
    return {**row, "is_new": int(row.get("reps") or 0) == 0 and row.get("last_review") is None}


async def delete(vocab_id: int) -> bool:
    row = await db.fetchone("SELECT id FROM vocab WHERE id=?", (vocab_id,))
    if not row:
        return False
    await db.execute("DELETE FROM vocab WHERE id=?", (vocab_id,))
    return True


async def search(q: str = "", sort: str = "due", limit: int = 50) -> tuple[list[dict], int]:
    order = {"due": "due ASC", "word": "word COLLATE NOCASE ASC", "created": "created_at DESC"}.get(sort, "due ASC")
    where, params = "", ()
    if q:
        where, params = "WHERE word LIKE ? OR translation LIKE ?", (f"%{q}%", f"%{q}%")
    total = (await db.fetchone(f"SELECT COUNT(*) AS n FROM vocab {where}", params))["n"]
    rows = await db.fetchall(f"SELECT * FROM vocab {where} ORDER BY {order} LIMIT ?", (*params, max(1, min(limit, 500))))
    return [card(r) for r in rows], int(total)
