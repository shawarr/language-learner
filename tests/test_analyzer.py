"""A3: the analyzer merges recurring mistakes, moves skills within bounds, and never double-reads."""
from __future__ import annotations

import time

import pytest

from app.db import loads
from app.prompts import placeholders
from app.providers.fake import FakeProvider
from app.services import analyzer, mistakes, profile

ANALYSIS = {
    "session_summary": "He introduced himself and asked one question back.",
    "rolling_summary": "Beginner at A1.1. Keen, short answers, mixes up haben and sein in the Perfekt.",
    "mistakes": [{"category": "case", "pattern": "dative after mit", "wrong": "mit den Bus", "right": "mit dem Bus",
                  "note": "mit always takes the dative."}],
    "new_vocab": [{"word": "der Bus (die Busse)", "translation": "bus", "example": "Ich fahre mit dem Bus."}],
    "skill_deltas": {"speaking": 1, "grammar": -1},
    "facts": ["Takes the bus to the office twice a week"],
    "unit_readiness": "almost",
}

LINES = [("assistant", "Hallo! Wie kommst du zur Arbeit?"), ("user", "Ich fahre mit den Bus."),
         ("assistant", "Gut. Und wie lange dauert das?"), ("user", "Zwanzig Minuten."),
         ("assistant", "Und am Wochenende, zu Fuß oder mit dem Bus?")]


async def seed(db, lines=LINES, *, ended=True, voice=False):
    now = time.time()
    sid = await db.execute("INSERT INTO sessions (mode, unit_id, started_at, ended_at) VALUES ('talk', 'a1.1-1', ?, ?)",
                           (now, now if ended else None))
    for role, content in lines:
        kind = "voice" if voice and role == "user" else "text"
        await db.execute("INSERT INTO messages (session_id, role, content, transcript_raw, input_kind, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)", (sid, role, content, content if kind == "voice" else None, kind, now))
    return sid


# --- validate: pure ----------------------------------------------------------
def test_validate_rejects_lists_that_came_back_as_strings():
    for bad in ({"mistakes": "none"}, {"facts": "he has a dog"}, {"new_vocab": "der Bus"}, {"skill_deltas": [1, 2]}):
        with pytest.raises(ValueError):
            analyzer.validate({**ANALYSIS, **bad})
    with pytest.raises(ValueError):
        analyzer.validate("not an object")  # type: ignore[arg-type]


def test_validate_cleans_every_field():
    out = analyzer.validate({
        **ANALYSIS,
        "mistakes": [
            {"category": "Case", "pattern": "dative after mit", "wrong": "mit den Bus", "right": "mit dem Bus"},
            {"category": "case", "pattern": "Dative  after MIT", "wrong": "mit den Zug", "right": "mit dem Zug"},
            {"category": "made-up", "pattern": "x", "wrong": "a", "right": "b", "note": 7},
            {"category": "case", "pattern": "no right", "wrong": "a"},
            {"pattern": "no category", "wrong": "a", "right": "b"},
            "not a dict",
        ],
        "new_vocab": [{"word": " der  Zug ", "translation": "train"}, {"word": "x"}, 3],
        "skill_deltas": {"speaking": 9, "grammar": -7, "vocab": "2", "listening": 2.5, "writing": True, "bogus": 1},
        "facts": ["Has a dog", 3, "  ", "Has a dog"],
        "unit_readiness": "sure",
        "rolling_summary": " ".join(f"w{i}" for i in range(200)),
        "session_summary": " ".join(f"s{i}" for i in range(100)),
    })
    assert [m["pattern"] for m in out["mistakes"]] == ["dative after mit", "x"], "same pattern once, incomplete ones dropped"
    assert out["mistakes"][0]["category"] == "case" and out["mistakes"][1]["category"] == "other"
    assert out["mistakes"][1]["note"] == "7"
    assert out["new_vocab"] == [{"word": "der Zug", "translation": "train", "example": ""}]
    assert out["skill_deltas"] == {"speaking": 3, "grammar": -3}
    assert out["facts"] == ["Has a dog", "Has a dog"], "profile.add_facts owns the de-duplication"
    assert out["unit_readiness"] == "not_yet"
    assert len(out["rolling_summary"].split()) == analyzer.ROLLING_SUMMARY_WORDS
    assert len(out["session_summary"].split()) == analyzer.SESSION_SUMMARY_WORDS


def test_validate_tolerates_missing_optional_fields():
    out = analyzer.validate({"session_summary": "ok", "rolling_summary": "ok", "mistakes": [], "new_vocab": [],
                             "skill_deltas": None, "unit_readiness": "ready"})
    assert out["facts"] == [] and out["skill_deltas"] == {} and out["unit_readiness"] == "ready"


def test_prompt_placeholders_match_the_service():
    assert placeholders("analyzer") == {"level", "unit_title", "grammar_targets", "categories", "known_mistakes",
                                        "rolling_summary", "transcript"}


# --- analyze_session -----------------------------------------------------------
async def test_same_pattern_in_two_sessions_is_one_row_with_count_two(fresh_db):
    FakeProvider.canned = ANALYSIS
    a, b = await seed(fresh_db), await seed(fresh_db)
    assert (await analyzer.analyze_session(a))["mistakes"][0]["pattern"] == "dative after mit"
    FakeProvider.canned = {**ANALYSIS, "mistakes": [{**ANALYSIS["mistakes"][0], "pattern": "Dative after MIT",
                                                     "wrong": "mit den Zug", "right": "mit dem Zug"}]}
    await analyzer.analyze_session(b)
    rows = await fresh_db.fetchall("SELECT * FROM mistakes")
    assert len(rows) == 1 and rows[0]["count"] == 2 and rows[0]["category"] == "case"
    assert [e["wrong"] for e in loads(rows[0]["examples"], [])] == ["mit den Bus", "mit den Zug"]
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM vocab WHERE source='analyzer'"))["n"] == 1


async def test_examples_are_capped_at_five(fresh_db):
    for i in range(7):
        FakeProvider.canned = {**ANALYSIS, "mistakes": [{**ANALYSIS["mistakes"][0], "wrong": f"w{i}", "right": f"r{i}"}]}
        await analyzer.analyze_session(await seed(fresh_db))
    row = await fresh_db.fetchone("SELECT * FROM mistakes")
    ex = loads(row["examples"], [])
    assert row["count"] == 7 and len(ex) == mistakes.MAX_EXAMPLES and ex[0]["wrong"] == "w2" and ex[-1]["wrong"] == "w6"


async def test_deltas_are_clamped_before_they_reach_the_profile(fresh_db):
    FakeProvider.canned = {**ANALYSIS, "skill_deltas": {"speaking": 9, "grammar": -7, "vocab": "lots"}}
    out = await analyzer.analyze_session(await seed(fresh_db))
    assert out["skill_deltas"] == {"speaking": 3, "grammar": -3}
    skills = (await profile.get_profile())["skills"]
    assert skills["speaking"] == 13 and skills["grammar"] == 7 and skills["vocab"] == 10


async def test_analyzed_count_advances_and_a_second_run_does_nothing(fresh_db):
    FakeProvider.canned = ANALYSIS
    sid = await seed(fresh_db)
    assert await analyzer.analyze_session(sid) is not None
    row = await fresh_db.fetchone("SELECT * FROM sessions WHERE id=?", (sid,))
    assert row["analyzed_count"] == len(LINES) and row["summary"] == ANALYSIS["session_summary"]
    assert loads(row["meta"], {}) == {"unit_readiness": "almost"}
    assert len(FakeProvider.calls) == 1
    assert await analyzer.analyze_session(sid) is None
    assert len(FakeProvider.calls) == 1, "nothing new, no model call"
    assert (await fresh_db.fetchone("SELECT count FROM mistakes"))["count"] == 1
    # New turns after the first run: only they are analysed, with the last tutor line as lead-in.
    now = time.time()
    await fresh_db.execute("INSERT INTO messages (session_id, role, content, created_at) VALUES (?, 'user', 'Ich gehe zu Fuß.', ?)",
                           (sid, now))
    assert await analyzer.analyze_session(sid) is not None
    transcript = FakeProvider.calls[-1].system
    assert "Ahmad: Ich gehe zu Fuß." in transcript and "Ahmad: Ich fahre mit den Bus." not in transcript
    assert "Tutor: Und am Wochenende, zu Fuß oder mit dem Bus?" in transcript, "the question he answered is the lead-in"
    assert "Tutor: Gut. Und wie lange dauert das?" not in transcript
    assert (await fresh_db.fetchone("SELECT analyzed_count FROM sessions WHERE id=?", (sid,)))["analyzed_count"] == len(LINES) + 1


async def test_profile_memory_is_updated(fresh_db):
    await profile.update_profile(rolling_summary="Old picture.")
    await mistakes.record("gender", "Termin is masculine", "das Termin", "der Termin")
    FakeProvider.canned = ANALYSIS
    await analyzer.analyze_session(await seed(fresh_db, voice=True))
    system = FakeProvider.calls[0].system
    assert "gender: termin is masculine" in system, "open patterns are offered for reuse"
    assert "Old picture." in system and "Ahmad: Ich fahre mit den Bus." in system
    p = await profile.get_profile()
    assert p["rolling_summary"] == ANALYSIS["rolling_summary"]
    assert p["facts"] == ["Takes the bus to the office twice a week"]


async def test_bad_shape_is_rejected_without_touching_the_db(fresh_db):
    await profile.update_profile(rolling_summary="Old picture.")
    FakeProvider.canned = {**ANALYSIS, "mistakes": "mit den Bus -> mit dem Bus"}
    sid = await seed(fresh_db)
    with pytest.raises(ValueError):
        await analyzer.analyze_session(sid)
    assert await fresh_db.fetchall("SELECT * FROM mistakes") == []
    assert await fresh_db.fetchall("SELECT * FROM vocab") == []
    row = await fresh_db.fetchone("SELECT analyzed_count, summary, meta FROM sessions WHERE id=?", (sid,))
    assert (row["analyzed_count"], row["summary"], row["meta"]) == (0, "", "{}")
    p = await profile.get_profile()
    assert p["rolling_summary"] == "Old picture." and p["skills"]["speaking"] == 10 and p["facts"] == []


async def test_no_new_user_message_means_no_model_call(fresh_db):
    FakeProvider.canned = ANALYSIS
    sid = await seed(fresh_db, [("assistant", "Hallo! Wie geht es dir?")])
    assert await analyzer.analyze_session(sid) is None and FakeProvider.calls == []
    assert (await fresh_db.fetchone("SELECT analyzed_count FROM sessions WHERE id=?", (sid,)))["analyzed_count"] == 1
    assert await analyzer.analyze_session(sid + 99) is None


async def test_catch_up_analyses_ended_sessions_only(fresh_db):
    FakeProvider.canned = ANALYSIS
    live = await seed(fresh_db, ended=False)
    done = await seed(fresh_db)
    assert await analyzer.catch_up(limit=5) == 1
    assert (await fresh_db.fetchone("SELECT analyzed_count FROM sessions WHERE id=?", (done,)))["analyzed_count"] == len(LINES)
    assert (await fresh_db.fetchone("SELECT analyzed_count FROM sessions WHERE id=?", (live,)))["analyzed_count"] == 0
    assert await analyzer.catch_up(limit=5) == 0 and len(FakeProvider.calls) == 1


async def test_catch_up_logs_a_failure_and_carries_on(fresh_db):
    FakeProvider.canned = {**ANALYSIS, "mistakes": "broken"}
    sid = await seed(fresh_db)
    assert await analyzer.catch_up() == 0
    assert (await fresh_db.fetchone("SELECT analyzed_count FROM sessions WHERE id=?", (sid,)))["analyzed_count"] == 0
