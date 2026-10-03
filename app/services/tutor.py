"""The talk loop: one LLM call per turn, validated before a single row is written.

The order inside `take_turn` is the point: load → prompt → model → sanitize → write, in one
transaction. A provider failure therefore leaves nothing behind and the frontend can simply retry
with the same text or recording. Model output goes through `sanitize_turn` rather than being trusted,
because a free-tier model will occasionally return a field as a string where a list was asked for.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from fastapi import HTTPException

from ..config import settings
from ..db import db, loads
from ..prompts import render
from ..providers import tts
from ..providers.base import Message
from ..providers.llm import LLMUnavailable, llm
from ..providers.stt import normalize_mime
from ..taxonomy import CATEGORY_SLUGS, normalize
from . import analyzer, curriculum, profile, vocab

log = logging.getLogger(__name__)

MAX_CORRECTIONS = 3
MAX_NEW_VOCAB = 3

# Sent to the model to open the conversation, never persisted: a stored copy would put a fake user
# line into the history and into the analyzer's transcript.
OPENING_MESSAGE = "[Das Gespräch beginnt. Begrüße mich kurz und starte das Szenario.]"

TUTOR_TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "German only. 1-3 short sentences, ends with one question. Spoken aloud verbatim."},
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "wrong": {"type": "string"},
                    "right": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORY_SLUGS},
                    "explanation": {"type": "string", "description": "One sentence, English."},
                },
                "required": ["wrong", "right", "category", "explanation"],
            },
        },
        "praise": {"type": ["string", "null"], "description": "Only when he did something new or hard."},
        "english_help": {
            "type": ["object", "null"],
            "properties": {"english": {"type": "string"}, "german": {"type": "string"},
                           "literal": {"type": "string", "description": "Word-by-word gloss, so he sees the structure."}},
            "required": ["english", "german", "literal"],
        },
        "new_vocab": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"word": {"type": "string", "description": "Nouns with article and plural: 'der Termin (die Termine)'"},
                                     "translation": {"type": "string"}, "example": {"type": "string"}},
                      "required": ["word", "translation"]},
        },
        "scenario_done": {"type": "boolean", "description": "True when the scenario's goal has been reached."},
    },
    "required": ["reply", "corrections", "new_vocab", "scenario_done"],
}

SESSION_FIELDS = ("id", "mode", "scenario_id", "scenario_title", "unit_id", "started_at", "ended_at", "summary",
                  "user_turns")
MESSAGE_FIELDS = ("id", "role", "content", "transcript_raw", "input_kind", "stt_provider", "llm_model", "created_at")


# -- API shapes (docs/API.md) -------------------------------------------------
def session_json(row: dict) -> dict:
    meta = loads(row.get("meta"), {})
    return {**{k: row.get(k) for k in SESSION_FIELDS}, "meta": meta if isinstance(meta, dict) else {}}


def message_json(row: dict) -> dict:
    return {**{k: row.get(k) for k in MESSAGE_FIELDS},
            "correction": loads(row.get("correction"), None),
            "english_help": loads(row.get("english_help"), None)}


def turn_json(user_message_id: int | None, message_id: int, turn: dict, *,
              transcript: str | None = None, transcript_provider: str | None = None) -> dict:
    return {"user_message_id": user_message_id, "message_id": message_id, "reply": turn["reply"],
            "corrections": turn["corrections"], "praise": turn["praise"], "english_help": turn["english_help"],
            "new_vocab": turn["new_vocab"], "scenario_done": turn["scenario_done"],
            "transcript": transcript, "transcript_provider": transcript_provider}


# -- validation of model output -----------------------------------------------
def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _items(value: object) -> list:
    return [x for x in value if isinstance(x, dict)] if isinstance(value, list) else []


def sanitize_turn(data: dict) -> dict:
    """Pure: the model's object → exactly what gets stored and returned. Raises LLMUnavailable only
    when there is no reply at all, because a turn without a reply is not a turn."""
    reply = _text(data.get("reply")) if isinstance(data, dict) else ""
    if not reply:
        raise LLMUnavailable("The tutor returned an unreadable answer. Please try again.")
    corrections = []
    for c in _items(data.get("corrections")):
        wrong, right = _text(c.get("wrong")), _text(c.get("right"))
        if wrong and right:
            corrections.append({"wrong": wrong, "right": right, "category": normalize(_text(c.get("category"))),
                                "explanation": _text(c.get("explanation"))})
    new_vocab = []
    for v in _items(data.get("new_vocab")):
        word, translation = _text(v.get("word")), _text(v.get("translation"))
        if word and translation:
            new_vocab.append({"word": word, "translation": translation, "example": _text(v.get("example"))})
    help_ = data.get("english_help")
    english_help = None
    if isinstance(help_, dict) and all(_text(help_.get(k)) for k in ("english", "german", "literal")):
        english_help = {k: _text(help_[k]) for k in ("english", "german", "literal")}
    done = data.get("scenario_done", False)
    if isinstance(done, str):
        done = done.strip().lower() in ("true", "yes", "1")
    return {"reply": reply, "corrections": corrections[:MAX_CORRECTIONS], "praise": _text(data.get("praise")) or None,
            "english_help": english_help, "new_vocab": new_vocab[:MAX_NEW_VOCAB], "scenario_done": bool(done)}


# -- background analysis --------------------------------------------------------
async def _swallow(coro, what: str) -> None:
    try:
        await coro
    except Exception:
        log.exception("%s failed", what)


def schedule_analysis(session_id: int) -> asyncio.Task:
    """Never awaited by a turn: a slow or failing analyzer must not delay or break the conversation."""
    return asyncio.create_task(_swallow(analyzer.analyze_session(session_id), f"background analysis of session {session_id}"))


def schedule_catch_up() -> asyncio.Task:
    """Housekeeping behind a new session: close what was abandoned, analyse what was missed."""
    return asyncio.create_task(_swallow(_catch_up(), "catch-up housekeeping"))


async def _catch_up() -> None:
    # Order matters: closing a stale session analyses it, and catch_up then mops up any whose
    # analysis failed (a 503 at the wrong moment).
    await close_stale_sessions()
    await analyzer.catch_up()
    await sweep_orphan_audio()


def schedule_tts(text: str) -> asyncio.Task:
    """Render the reply's audio while the phone is still receiving the JSON, so GET /api/tts hits
    the disk cache. Takes the ~2 s synthesis off the perceived turn; a failure only means the
    endpoint renders it on demand."""
    return asyncio.create_task(_swallow(tts.synthesize(text), "tts pre-warm"))


# -- the service ----------------------------------------------------------------
async def _load(session_id: int) -> dict:
    row = await db.fetchone("SELECT * FROM sessions WHERE id=?", (session_id,))
    if not row:
        raise HTTPException(status_code=404, detail="session not found")
    return row


async def _system_prompt(scenario: dict | None) -> str:
    # The profile's unit, even when the scenario was picked from another one: the context describes
    # where he is, the scenario only what is being played.
    unit = await curriculum.current_unit()
    return render("tutor_talk", **await profile.build_context(unit, scenario))


async def _history(session_id: int) -> list[Message]:
    rows = await db.fetchall("SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
                             (session_id, settings.history_window))
    return [Message(r["role"], r["content"]) for r in reversed(rows)]


async def _write_assistant(session_id: int, turn: dict, model: str | None, now: float) -> int:
    """The assistant row plus its vocab, uncommitted: the caller owns the transaction."""
    cur = await db.conn.execute(
        "INSERT INTO messages (session_id, role, content, correction, english_help, llm_model, created_at) "
        "VALUES (?, 'assistant', ?, ?, ?, ?, ?)",
        (session_id, turn["reply"], json.dumps(turn["corrections"], ensure_ascii=False),
         json.dumps(turn["english_help"], ensure_ascii=False) if turn["english_help"] else None, model, now))
    for v in turn["new_vocab"]:
        await vocab.upsert(v["word"], v["translation"], v["example"], source="tutor", now=now, commit=False)
    return int(cur.lastrowid or 0)


async def start_session(mode: str = "talk", scenario_id: str | None = None) -> dict:
    """Creates the session and its opening tutor turn. Nothing is written if the model is down."""
    found = curriculum.scenario(scenario_id)
    if scenario_id and not found:
        raise HTTPException(status_code=404, detail=f"unknown scenario {scenario_id!r}")
    scenario = found[1] if found else None
    unit = await curriculum.current_unit()
    system = await _system_prompt(scenario)
    data = await llm.complete_json(system, [Message("user", OPENING_MESSAGE)], TUTOR_TURN_SCHEMA)
    turn = sanitize_turn(data)
    # There is no user message yet, so anything "corrected" here would be hallucinated.
    turn.update(corrections=[], english_help=None, praise=None)
    now = time.time()
    try:
        cur = await db.conn.execute(
            "INSERT INTO sessions (mode, scenario_id, scenario_title, unit_id, started_at) VALUES (?, ?, ?, ?, ?)",
            (mode, scenario["id"] if scenario else None, scenario["title"] if scenario else None, unit["id"], now))
        session_id = int(cur.lastrowid or 0)
        message_id = await _write_assistant(session_id, turn, data.get("_model"), now)
        await db.conn.commit()
    except Exception:
        await db.conn.rollback()
        raise
    schedule_catch_up()
    schedule_tts(turn["reply"])
    return {"session": session_json(await _load(session_id)), "opening_turn": turn_json(None, message_id, turn)}


def turns_dir() -> Path:
    return settings.audio_dir / "turns"


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def _keep_recording(session_id: int, message_id: int, audio: bytes, ext: str) -> None:
    """The analyzer listens to the recording later, because the transcript hides the endings he got
    wrong. A failed save only means that analysis runs text-only, so it never fails the turn."""
    path = turns_dir() / f"{session_id}-{message_id}.{ext}"
    try:
        await asyncio.to_thread(_write_file, path, audio)
        await db.execute("UPDATE messages SET audio_path=? WHERE id=?", (str(path), message_id))
    except OSError:
        log.exception("could not keep the recording of message %s", message_id)


async def _sweep_audio(session_id: int) -> None:
    """Nothing in a session is ever listened to again once its final analysis is done."""
    rows = await db.fetchall("SELECT audio_path FROM messages WHERE session_id=? AND audio_path IS NOT NULL",
                             (session_id,))
    analyzer.discard_audio([r["audio_path"] for r in rows])
    await db.execute("UPDATE messages SET audio_path=NULL WHERE session_id=?", (session_id,))
    # A file whose row is gone (a discarded turn whose delete failed) is only findable by name.
    analyzer.discard_audio(turns_dir().glob(f"{session_id}-*"))


STALE_CLOSE_LIMIT = 3          # model calls spent on abandoned sessions per new session
ORPHAN_AUDIO_AGE_SECONDS = 48 * 3600


async def close_stale_sessions(limit: int = STALE_CLOSE_LIMIT, now: float | None = None) -> list[int]:
    """End talk sessions that were abandoned mid-conversation, so they get analysed and swept.

    On a phone the usual way out of a conversation is switching apps, not tapping "end session", so
    without this a session stays open forever: the turns since its last analysis boundary are never
    analysed — their mistakes never reach the log — and their recordings are never freed.
    `analyzer.catch_up()` cannot help, because it only considers sessions that were ended.

    Reuses `end_session`, so an abandoned session takes exactly the path a tidily ended one does.
    """
    now = now or time.time()
    cutoff = now - max(1, settings.session_stale_minutes) * 60
    rows = await db.fetchall(
        "SELECT s.id FROM sessions s WHERE s.ended_at IS NULL AND s.mode = 'talk' "
        "AND COALESCE((SELECT MAX(m.created_at) FROM messages m WHERE m.session_id = s.id), s.started_at) < ? "
        "ORDER BY s.started_at, s.id LIMIT ?", (cutoff, max(0, int(limit))))
    closed: list[int] = []
    for row in rows:
        try:
            await end_session(row["id"])
            closed.append(int(row["id"]))
            log.info("closed abandoned session %s", row["id"])
        except Exception:
            log.exception("could not close abandoned session %s", row["id"])
    return closed


async def sweep_orphan_audio(now: float | None = None) -> int:
    """Delete recordings on disk that no message row points at any more.

    Belt and braces for the paths that bypass the per-session sweep: a crash between writing the
    file and the UPDATE that records its path, or a failed delete. Only touches files older than
    two days, so a recording mid-flight is never pulled out from under a live turn.
    """
    now = now or time.time()
    directory = turns_dir()
    if not directory.is_dir():
        return 0
    known = {r["audio_path"] for r in
             await db.fetchall("SELECT audio_path FROM messages WHERE audio_path IS NOT NULL")}
    removed = 0
    for path in directory.iterdir():
        try:
            if str(path) in known or not path.is_file() or now - path.stat().st_mtime < ORPHAN_AUDIO_AGE_SECONDS:
                continue
            path.unlink()
            removed += 1
        except OSError:
            log.warning("could not remove orphaned recording %s", path)
    if removed:
        log.info("removed %d orphaned recording(s)", removed)
    return removed


async def take_turn(session_id: int, text: str, *, input_kind: str = "text",
                    transcript_raw: str | None = None, stt_provider: str | None = None,
                    audio: bytes | None = None, audio_mime: str | None = None, audio_ext: str | None = None) -> dict:
    session = await _load(session_id)
    if session["ended_at"] is not None:
        raise HTTPException(status_code=409, detail="session has ended")
    if session["mode"] != "talk":
        raise HTTPException(status_code=409, detail="not a talk session")
    if not _text(text):
        raise HTTPException(status_code=400, detail="Nothing to send.")
    found = curriculum.scenario(session["scenario_id"])
    if session["scenario_id"] and not found:
        # The curriculum moved on under a live session; carrying on as free talk beats a dead screen.
        log.warning("scenario %r is gone from the curriculum; continuing without it", session["scenario_id"])
    system = await _system_prompt(found[1] if found else None)
    history = await _history(session_id)
    data = await llm.complete_json(system, history + [Message("user", text)], TUTOR_TURN_SCHEMA)
    turn = sanitize_turn(data)
    now = time.time()
    try:
        cur = await db.conn.execute(
            "INSERT INTO messages (session_id, role, content, transcript_raw, input_kind, stt_provider, created_at) "
            "VALUES (?, 'user', ?, ?, ?, ?, ?)", (session_id, text, transcript_raw, input_kind, stt_provider, now))
        user_message_id = int(cur.lastrowid or 0)
        message_id = await _write_assistant(session_id, turn, data.get("_model"), now)
        await db.conn.execute("UPDATE sessions SET user_turns = user_turns + 1 WHERE id=?", (session_id,))
        await db.conn.commit()
    except Exception:
        await db.conn.rollback()
        raise
    await db.bump_activity("talk_turn")
    voice = input_kind == "voice"
    if voice and audio:
        await _keep_recording(session_id, user_message_id, audio, audio_ext or normalize_mime(audio_mime)[0])
    # One learner, one conversation at a time: the count read above plus this turn is the real one.
    turns = int(session["user_turns"] or 0) + 1
    if settings.analyze_every_turns > 0 and turns % settings.analyze_every_turns == 0:
        schedule_analysis(session_id)
    schedule_tts(turn["reply"])
    return turn_json(user_message_id, message_id, turn,
                     transcript=transcript_raw if voice else None, transcript_provider=stt_provider if voice else None)


async def discard_turn(session_id: int, user_message_id: int) -> dict:
    """"That's not what I said": drop the user message, the tutor's answer to it and its recording,
    so a transcription error never reaches the mistake log."""
    session = await _load(session_id)
    user = await db.fetchone("SELECT id, audio_path FROM messages WHERE id=? AND session_id=? AND role='user'",
                             (user_message_id, session_id))
    if not user:
        raise HTTPException(status_code=404, detail="no such message in this session")
    following = await db.fetchone("SELECT id, role FROM messages WHERE session_id=? AND id > ? ORDER BY id LIMIT 1",
                                  (session_id, user_message_id))
    ids = [user["id"]] + ([following["id"]] if following and following["role"] == "assistant" else [])
    # analyzed_count is a prefix length over the session's messages in id order; a deleted row
    # inside that prefix shortens it, one outside leaves it alone. Otherwise the rows after the
    # discarded ones would slide into the "seen" prefix and never be analysed.
    order = [r["id"] for r in await db.fetchall("SELECT id FROM messages WHERE session_id=? ORDER BY id", (session_id,))]
    seen = int(session["analyzed_count"] or 0)
    still_seen = seen - sum(1 for mid in ids if order.index(mid) < seen)
    try:
        await db.conn.execute(f"DELETE FROM messages WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))
        await db.conn.execute("UPDATE sessions SET user_turns = MAX(0, user_turns - 1), analyzed_count=? WHERE id=?",
                              (max(0, still_seen), session_id))
        await db.conn.commit()
    except Exception:
        await db.conn.rollback()
        raise
    analyzer.discard_audio([user["audio_path"]])
    return {"ok": True, "deleted": len(ids)}


async def end_session(session_id: int) -> dict:
    """Closes the session, then analyses what is new. Idempotent: ending twice costs no model call."""
    session = await _load(session_id)
    if session["ended_at"] is None:
        await db.execute("UPDATE sessions SET ended_at=? WHERE id=?", (time.time(), session_id))
    try:
        await analyzer.analyze_session(session_id)
    except Exception:
        # The session stays closed, its recordings too: catch_up() picks it up when the next
        # session starts.
        log.exception("analysis at the end of session %s failed", session_id)
        return {"summary": session["summary"] or "", "analyzed": False}
    await _sweep_audio(session_id)
    row = await _load(session_id)
    return {"summary": row["summary"] or "", "analyzed": True}


async def get_session(session_id: int) -> dict | None:
    row = await db.fetchone("SELECT * FROM sessions WHERE id=?", (session_id,))
    if not row:
        return None
    rows = await db.fetchall("SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,))
    return {"session": session_json(row), "messages": [message_json(m) for m in rows]}


async def recent_sessions(limit: int = 20) -> list[dict]:
    rows = await db.fetchall("SELECT * FROM sessions ORDER BY started_at DESC, id DESC LIMIT ?",
                             (max(1, min(int(limit), 100)),))
    return [session_json(r) for r in rows]
