"""Vocabulary: upserts from the tutor/analyzer/writing/manual paths, browsing, and tap-to-translate.

`upsert` never touches an existing row's SRS state — a word the tutor mentions again must not reset
to "due now" and wipe out months of scheduling. The SRS scheduling itself lives in srs.py.
"""
from __future__ import annotations

import json
import time

from ..db import db, loads
from ..prompts import render
from ..providers.base import Message
from ..providers.llm import LLMUnavailable, llm

SOURCES = {"manual", "tutor", "analyzer", "writing"}

POS = ["noun", "verb", "adjective", "adverb", "preposition", "pronoun", "conjunction", "particle", "number", "other"]

TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "lemma": {"type": "string",
                  "description": "Dictionary form: nouns with article and plural 'der Termin (die Termine)', verbs in the infinitive."},
        "translation": {"type": "string", "description": "Short English translation for the sense used in the sentence."},
        "pos": {"type": "string", "enum": POS},
        "note": {"type": "string", "description": "One short sentence: gender hint, separable prefix, false friend. Empty when there is nothing to say."},
    },
    "required": ["lemma", "translation", "pos", "note"],
}

# Quotes and dashes German text uses on top of ASCII punctuation; a tapped word arrives with them attached.
_EDGE_PUNCT = "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~„“”‚‘’«»‹›…–—"
MAX_CONTEXT_CHARS = 300


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


# -- tap a word -> translation --------------------------------------------------

def surface_key(word: object) -> str:
    """The cache key: lowercase surface form with the punctuation a tap drags along stripped off."""
    return clean_word(word).strip(_EDGE_PUNCT).lower()


def _validate_translation(data: dict, word: str) -> dict:
    """Keep only the model's four fields, coerced to strings. A missing translation is unusable: never cache it."""
    translation = clean_word(data.get("translation"))
    if not translation:
        raise LLMUnavailable("The dictionary returned no translation for that word. Try again.")
    pos = str(data.get("pos") or "").strip().lower()
    return {
        "lemma": clean_word(data.get("lemma")) or word,
        "translation": translation,
        "pos": pos if pos in POS else "other",
        "note": clean_word(data.get("note")),
    }


async def in_vocab(lemma: str) -> bool:
    row = await db.fetchone("SELECT id FROM vocab WHERE word=? COLLATE NOCASE", (clean_word(lemma),))
    return row is not None


async def translate(word: str, context: str = "") -> dict:
    """docs/API.md POST /vocab/translate. The cache answers before the model: this fires on every tap."""
    key = surface_key(word)
    if not key:
        raise ValueError("word is required")
    surface = clean_word(word).strip(_EDGE_PUNCT)
    cached = await db.fetchone("SELECT data FROM translations WHERE word=?", (key,))
    entry = loads(cached["data"], None) if cached else None
    if not isinstance(entry, dict) or not entry.get("translation"):
        system = render("translate", word=surface,
                        context=clean_word(context)[:MAX_CONTEXT_CHARS] or "(no sentence given)")
        data = await llm.complete_json(system, [Message("user", surface)], TRANSLATE_SCHEMA, tier="fast",
                                       temperature=0.2, max_tokens=256)
        entry = _validate_translation(data, surface)
        await db.execute(
            "INSERT INTO translations (word, data, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(word) DO UPDATE SET data=excluded.data, created_at=excluded.created_at",
            (key, json.dumps(entry, ensure_ascii=False), time.time()))
    # in_vocab is live, never cached: he may add the word right after this call.
    return {"word": surface, **entry, "in_vocab": await in_vocab(entry["lemma"])}
