"""The analyzer: the step from a conversation to memory.

It reads the messages of a session the previous run has not seen (`sessions.analyzed_count`
onward), asks the model for mistakes, vocabulary, skill movement, facts and a rewritten learner
summary, validates the answer, and only then writes. It runs every Nth turn and at session end, so
it has to be incremental and idempotent: a second run right after the first finds nothing new and
does nothing, and two runs never see the same user message twice.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

from ..db import db, loads
from ..prompts import render
from ..providers.base import Message
from ..providers.llm import LLMUnavailable, llm
from ..taxonomy import CATEGORY_SLUGS, describe_for_prompt, normalize
from . import curriculum, mistakes, profile, vocab

log = logging.getLogger(__name__)

READINESS = ("not_yet", "almost", "ready")
MAX_DELTA = 3
ROLLING_SUMMARY_WORDS = 120
SESSION_SUMMARY_WORDS = 80
KNOWN_MISTAKES = 20
NONE_YET = "(none yet)"
# Gemini takes the recording inline in the request body; a few minutes of 48 kbps mono mp3 is far
# below this, so hitting it means something is wrong and text-only is the safe answer.
MAX_AUDIO_BYTES = 15 * 1024 * 1024

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "session_summary": {"type": "string", "description": "2-3 sentences, English: what he practised and how it went."},
        "rolling_summary": {"type": "string", "description": "Rewritten cumulative picture of the learner, max 120 words."},
        "mistakes": {"type": "array", "items": {"type": "object", "properties": {
            "category": {"type": "string", "enum": CATEGORY_SLUGS},
            "pattern": {"type": "string", "description": "The recurring error in a few words, not this one instance."},
            "wrong": {"type": "string"}, "right": {"type": "string"}, "note": {"type": "string"}},
            "required": ["category", "pattern", "wrong", "right"]}},
        "new_vocab": {"type": "array", "items": {"type": "object", "properties": {
            "word": {"type": "string"}, "translation": {"type": "string"}, "example": {"type": "string"}},
            "required": ["word", "translation"]}},
        "skill_deltas": {"type": "object", "properties": {
            "speaking": {"type": "integer"}, "listening": {"type": "integer"}, "writing": {"type": "integer"},
            "grammar": {"type": "integer"}, "vocab": {"type": "integer"}},
            "description": "Change for this session only, each between -3 and +3."},
        "facts": {"type": "array", "items": {"type": "string"},
                  "description": "New durable personal facts worth using as conversation material later."},
        "unit_readiness": {"type": "string", "enum": ["not_yet", "almost", "ready"],
                           "description": "Is he ready for this unit's checkpoint?"},
    },
    "required": ["session_summary", "rolling_summary", "mistakes", "new_vocab", "skill_deltas", "unit_readiness"],
}


# -- validation -------------------------------------------------------------------
def _text(value: object) -> str:
    if value is None or isinstance(value, (list, dict, bool)):
        return ""
    return " ".join(str(value).split())


def _words(text: str, limit: int) -> str:
    return " ".join(text.split()[:limit])


def validate(data: dict) -> dict:
    """A cleaned copy of the model's answer, or ValueError when its shape cannot be trusted at all.

    A list that came back as a string is rejected rather than parsed: the model misunderstood the
    task, and whatever it wrote would corrupt the mistake log for weeks.
    """
    if not isinstance(data, dict):
        raise ValueError("analysis must be an object")
    lists = {}
    for key in ("mistakes", "new_vocab", "facts"):
        value = data.get(key)
        if value is None:
            value = []
        if not isinstance(value, list):
            raise ValueError(f"{key} must be a list")
        lists[key] = value
    deltas = data.get("skill_deltas")
    if deltas is None:
        deltas = {}
    if not isinstance(deltas, dict):
        raise ValueError("skill_deltas must be an object")

    cleaned_mistakes, seen = [], set()
    for m in lists["mistakes"]:
        if not isinstance(m, dict):
            continue
        category = normalize(_text(m.get("category")))
        pattern, wrong, right = _text(m.get("pattern")), _text(m.get("wrong")), _text(m.get("right"))
        if not (m.get("category") and pattern and wrong and right):
            continue
        key = (category, mistakes.pattern_key(pattern))
        if key in seen:
            continue  # the log counts sessions, not slips: one bump per pattern per analysis
        seen.add(key)
        cleaned_mistakes.append({"category": category, "pattern": pattern, "wrong": wrong, "right": right,
                                 "note": _text(m.get("note"))})

    cleaned_vocab = []
    for v in lists["new_vocab"]:
        if not isinstance(v, dict):
            continue
        word, translation = _text(v.get("word")), _text(v.get("translation"))
        if word and translation:
            cleaned_vocab.append({"word": word, "translation": translation, "example": _text(v.get("example"))})

    cleaned_deltas = {}
    for skill in profile.SKILLS:
        delta = deltas.get(skill)
        if isinstance(delta, int) and not isinstance(delta, bool):
            cleaned_deltas[skill] = max(-MAX_DELTA, min(MAX_DELTA, delta))

    readiness = data.get("unit_readiness")
    return {
        "session_summary": _words(_text(data.get("session_summary")), SESSION_SUMMARY_WORDS),
        "rolling_summary": _words(_text(data.get("rolling_summary")), ROLLING_SUMMARY_WORDS),
        "mistakes": cleaned_mistakes,
        "new_vocab": cleaned_vocab,
        "skill_deltas": cleaned_deltas,
        "facts": [f for f in (_text(x) for x in lists["facts"] if isinstance(x, str)) if f],
        "unit_readiness": readiness if readiness in READINESS else "not_yet",
    }


# -- the analysis -------------------------------------------------------------------
_lock: asyncio.Lock | None = None
_lock_loop: asyncio.AbstractEventLoop | None = None


def _serial() -> asyncio.Lock:
    """One analysis at a time. The turn-8 trigger and an immediate "end" would otherwise both read the
    same analyzed_count and record every mistake twice. Re-created per event loop because the test
    suite starts a loop per test and a Lock stays bound to the first loop it waited on."""
    global _lock, _lock_loop
    loop = asyncio.get_running_loop()
    if _lock is None or _lock_loop is not loop:
        _lock, _lock_loop = asyncio.Lock(), loop
    return _lock


def _line(row: dict) -> str:
    if row["role"] == "assistant":
        return f"Tutor: {row['content']}"
    # The raw STT output is what he actually said; `content` is the same text today, but the
    # column is the contract.
    spoken = row.get("transcript_raw") if row.get("input_kind") == "voice" else None
    return f"Ahmad: {spoken or row['content']}"


def _audio_note(attached: int, spoken: int) -> str:
    """What the model is told about the recording; the rules for using it live in the prompt file."""
    if not attached:
        return "Not attached."
    if attached < spoken:
        return f"Attached: {attached} of his {spoken} spoken turns, in order (the others were not kept)."
    return f"Attached: his {attached} spoken turns, in order."


async def _system_prompt(transcript: str, audio_note: str) -> str:
    unit = await curriculum.current_unit()
    p = await profile.get_profile()
    known = await mistakes.all_open(KNOWN_MISTAKES)
    return render(
        "analyzer",
        level=p["level"],
        unit_title=unit.get("title") or NONE_YET,
        grammar_targets=", ".join(unit.get("grammar") or []) or NONE_YET,
        categories=describe_for_prompt(),
        known_mistakes="\n".join(f"{m['category']}: {m['pattern']}" for m in known) or NONE_YET,
        rolling_summary=" ".join(p["rolling_summary"].split()) or NONE_YET,
        transcript=transcript,
        audio=audio_note,
    )


# -- the recordings ---------------------------------------------------------------
def discard_audio(paths: Iterable[str | Path | None]) -> None:
    """Best effort: a recording that outlives its analysis is a leak, never an error."""
    for p in paths:
        if not p:
            continue
        try:
            Path(p).unlink(missing_ok=True)
        except OSError:
            log.warning("could not delete %s", p)


async def _ffmpeg(*args: str) -> bool:
    proc = await asyncio.create_subprocess_exec("ffmpeg", "-nostdin", "-loglevel", "error", "-y", *args)
    await proc.wait()
    return proc.returncode == 0


async def build_audio(clips: list[Path]) -> bytes | None:
    """The clips as one 16 kHz mono mp3, in order. None when ffmpeg is missing or fails: the analysis
    then runs text-only, which is still worth doing. Each clip is re-encoded first because the
    concat demuxer needs identical streams, and the phone sends whatever MediaRecorder picked."""
    if not clips or not shutil.which("ffmpeg"):
        return None
    with tempfile.TemporaryDirectory() as d:
        parts: list[Path] = []
        for i, src in enumerate(clips):
            dst = Path(d) / f"part{i}.mp3"
            if not await _ffmpeg("-i", str(src), "-ac", "1", "-ar", "16000", "-b:a", "48k", str(dst)):
                log.warning("ffmpeg could not convert %s", src)
                return None
            parts.append(dst)
        listing = Path(d) / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts), encoding="utf-8")
        out = Path(d) / "out.mp3"
        if not await _ffmpeg("-f", "concat", "-safe", "0", "-i", str(listing), "-ac", "1", "-ar", "16000",
                             "-b:a", "48k", str(out)) or not out.exists():
            log.warning("ffmpeg could not concatenate %d clips", len(parts))
            return None
        return out.read_bytes()


async def analyze_session(session_id: int) -> dict | None:
    """Analyse what the session has said since the last run. None when there is nothing new."""
    async with _serial():
        return await _analyze(session_id)


async def _analyze(session_id: int) -> dict | None:
    session = await db.fetchone("SELECT * FROM sessions WHERE id=?", (session_id,))
    if not session:
        return None
    rows = await db.fetchall("SELECT * FROM messages WHERE session_id=? ORDER BY id", (session_id,))
    seen = int(session["analyzed_count"] or 0)
    new = rows[seen:]
    if not any(r["role"] == "user" for r in new):
        if new:
            # Only tutor lines (a session opened and closed without a word): mark them seen so
            # catch_up() stops offering this session.
            await db.execute("UPDATE sessions SET analyzed_count=? WHERE id=?", (len(rows), session_id))
        return None
    lines = [_line(r) for r in new]
    if seen and rows[seen - 1]["role"] == "assistant":
        # The question his first new line answers; without it a short reply reads as a fragment.
        lines.insert(0, _line(rows[seen - 1]))
    transcript = "\n".join(lines)
    # The transcript hides what Whisper repaired ("mit den Bus" came out as "mit dem Bus"), so the
    # model also hears the recordings. Same call, nothing extra on the quota.
    spoken = [r for r in new if r.get("input_kind") == "voice" and r.get("audio_path")]
    clips = [Path(r["audio_path"]) for r in spoken if Path(r["audio_path"]).is_file()]
    audio = await build_audio(clips) if clips else None
    if audio and len(audio) > MAX_AUDIO_BYTES:
        log.warning("session %s: %d bytes of audio is over the inline limit, analysing text-only", session_id, len(audio))
        audio = None
    system = await _system_prompt(transcript, _audio_note(len(clips) if audio else 0, len(spoken)))
    ask = [Message("user", "Analyse the session now. Reply with JSON only.")]
    # The quality tier: this runs once every eight turns, so it can afford the stronger model and
    # a few seconds, and that model is the one that catches recurring patterns.
    try:
        data = await llm.complete_json(system, ask, ANALYSIS_SCHEMA, tier="quality",
                                       audio=audio, audio_mime="audio/mpeg" if audio else None)
    except LLMUnavailable:
        if audio is None:
            raise
        # Only text-only providers answered (OpenAI-compatible chat models reject audio). A
        # text-only analysis still beats none.
        log.warning("session %s: analysis with audio failed, retrying text-only", session_id)
        system = await _system_prompt(transcript, _audio_note(0, len(spoken)))
        data = await llm.complete_json(system, ask, ANALYSIS_SCHEMA, tier="quality")
    result = validate(data)

    now = time.time()
    meta = loads(session["meta"], {})
    meta = meta if isinstance(meta, dict) else {}
    meta["unit_readiness"] = result["unit_readiness"]
    try:
        for m in result["mistakes"]:
            await mistakes.record(m["category"], m["pattern"], m["wrong"], m["right"], m["note"], now=now, commit=False)
        for v in result["new_vocab"]:
            await vocab.upsert(v["word"], v["translation"], v["example"], source="analyzer", now=now, commit=False)
        await db.conn.execute(
            "UPDATE sessions SET summary=?, meta=?, analyzed_count=? WHERE id=?",
            (result["session_summary"] or session["summary"], json.dumps(meta, ensure_ascii=False), len(rows), session_id))
        if spoken:
            # Heard once, never again: the recordings go with the analysis that consumed them.
            await db.conn.execute(f"UPDATE messages SET audio_path=NULL WHERE id IN ({','.join('?' * len(spoken))})",
                                  tuple(r["id"] for r in spoken))
        await db.conn.commit()
    except Exception:
        await db.conn.rollback()
        raise
    discard_audio(r["audio_path"] for r in spoken)
    await profile.apply_skill_deltas(result["skill_deltas"])
    await profile.add_facts(result["facts"])
    if result["rolling_summary"]:
        # An empty rewrite would wipe the only memory the tutor has of past sessions.
        await profile.update_profile(rolling_summary=result["rolling_summary"])
    return result


async def catch_up(limit: int = 1) -> int:
    """Analyse ended talk sessions the analyzer missed (a 503 at session end), oldest first.

    Returns how many analyses ran. Failures are logged per session and never raised: this runs in the
    background behind a new session. `limit` bounds the model calls spent on old sessions.
    """
    rows = await db.fetchall(
        "SELECT id FROM sessions s WHERE mode='talk' AND ended_at IS NOT NULL "
        "AND analyzed_count < (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) ORDER BY ended_at, id")
    ran = 0
    for row in rows[:max(0, int(limit))]:
        try:
            if await analyze_session(row["id"]) is not None:
                ran += 1
        except Exception:
            log.exception("catch-up analysis of session %s failed", row["id"])
    return ran
