"""A conversation abandoned mid-session must still be learned from, and must not leak recordings.

Tapping "end session" is the tidy exit; switching apps is the real one. Before this, an open
session was never analysed past its last boundary and its clips stayed on disk forever —
`analyzer.catch_up()` only looks at sessions that were ended.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.config import settings
from app.services import tutor


async def _session(db, *, age_minutes: float, voice_turns: int = 2, ended: bool = False) -> tuple[int, list[Path]]:
    """A talk session whose last message is `age_minutes` old, with recordings on disk."""
    when = time.time() - age_minutes * 60
    session_id = await db.execute(
        "INSERT INTO sessions (mode, unit_id, started_at, ended_at, user_turns) VALUES ('talk','a1.1-1',?,?,?)",
        (when, when if ended else None, voice_turns))
    turns = tutor.turns_dir()
    turns.mkdir(parents=True, exist_ok=True)
    clips = []
    for _ in range(voice_turns):
        mid = await db.execute(
            "INSERT INTO messages (session_id, role, content, input_kind, created_at) "
            "VALUES (?, 'user', 'ich habe gestern in die stadt gegangen', 'voice', ?)", (session_id, when))
        clip = turns / f"{session_id}-{mid}.webm"
        clip.write_bytes(b"fake-audio")
        clips.append(clip)
        await db.execute("UPDATE messages SET audio_path=? WHERE id=?", (str(clip), mid))
        await db.execute("INSERT INTO messages (session_id, role, content, created_at) "
                         "VALUES (?, 'assistant', 'Schön!', ?)", (session_id, when))
    return session_id, clips


@pytest.mark.asyncio
async def test_an_abandoned_session_is_closed_analysed_and_swept(fresh_db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "audio_dir", tmp_path)
    session_id, clips = await _session(fresh_db, age_minutes=settings.session_stale_minutes + 10)
    assert all(c.exists() for c in clips)

    closed = await tutor.close_stale_sessions()

    assert closed == [session_id]
    row = await fresh_db.fetchone("SELECT ended_at, analyzed_count, summary FROM sessions WHERE id=?", (session_id,))
    assert row["ended_at"] is not None, "the session must be closed"
    assert row["analyzed_count"] > 0, "its turns must reach the analyzer"
    assert not any(c.exists() for c in clips), "its recordings must be freed"
    assert not await fresh_db.fetchall(
        "SELECT 1 FROM messages WHERE session_id=? AND audio_path IS NOT NULL", (session_id,))


@pytest.mark.asyncio
async def test_a_live_session_is_left_alone(fresh_db, monkeypatch, tmp_path):
    """He may simply be thinking. Closing a session out from under a live conversation would make
    the next turn fail with 409."""
    monkeypatch.setattr(settings, "audio_dir", tmp_path)
    session_id, clips = await _session(fresh_db, age_minutes=1)

    assert await tutor.close_stale_sessions() == []
    row = await fresh_db.fetchone("SELECT ended_at FROM sessions WHERE id=?", (session_id,))
    assert row["ended_at"] is None
    assert all(c.exists() for c in clips), "a live session keeps its recordings"


@pytest.mark.asyncio
async def test_an_empty_abandoned_session_is_closed_too(fresh_db, monkeypatch, tmp_path):
    """Opened, never spoken into, backgrounded: judged on started_at, since it has no messages."""
    monkeypatch.setattr(settings, "audio_dir", tmp_path)
    session_id, _ = await _session(fresh_db, age_minutes=120, voice_turns=0)
    assert await tutor.close_stale_sessions() == [session_id]


@pytest.mark.asyncio
async def test_the_sweep_is_bounded(fresh_db, monkeypatch, tmp_path):
    """Each new session spends a bounded number of model calls on old ones."""
    monkeypatch.setattr(settings, "audio_dir", tmp_path)
    for _ in range(5):
        await _session(fresh_db, age_minutes=200, voice_turns=1)
    assert len(await tutor.close_stale_sessions(limit=2)) == 2


@pytest.mark.asyncio
async def test_one_failure_does_not_stop_the_rest(fresh_db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "audio_dir", tmp_path)
    first, _ = await _session(fresh_db, age_minutes=300, voice_turns=1)
    second, _ = await _session(fresh_db, age_minutes=200, voice_turns=1)
    real_end = tutor.end_session

    async def flaky(session_id: int):
        if session_id == first:
            raise RuntimeError("provider down")
        return await real_end(session_id)

    monkeypatch.setattr(tutor, "end_session", flaky)
    assert await tutor.close_stale_sessions() == [second]


@pytest.mark.asyncio
async def test_orphan_recordings_are_removed_but_fresh_ones_are_not(fresh_db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "audio_dir", tmp_path)
    turns = tutor.turns_dir()
    turns.mkdir(parents=True, exist_ok=True)

    old_orphan = turns / "99-1.webm"
    old_orphan.write_bytes(b"x")
    import os
    stale = time.time() - tutor.ORPHAN_AUDIO_AGE_SECONDS - 60
    os.utime(old_orphan, (stale, stale))

    recent_orphan = turns / "99-2.webm"   # could be a turn still in flight
    recent_orphan.write_bytes(b"x")

    referenced = turns / "98-1.webm"
    referenced.write_bytes(b"x")
    os.utime(referenced, (stale, stale))
    session_id = await fresh_db.execute(
        "INSERT INTO sessions (mode, started_at) VALUES ('talk', ?)", (time.time(),))
    mid = await fresh_db.execute(
        "INSERT INTO messages (session_id, role, content, input_kind, created_at) "
        "VALUES (?, 'user', 'hallo', 'voice', ?)", (session_id, time.time()))
    await fresh_db.execute("UPDATE messages SET audio_path=? WHERE id=?", (str(referenced), mid))

    assert await tutor.sweep_orphan_audio() == 1
    assert not old_orphan.exists()
    assert recent_orphan.exists(), "a recording younger than the grace period is left alone"
    assert referenced.exists(), "a recording a message still points at is never touched"
