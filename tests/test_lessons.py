"""The coursework: content validity and progress that never goes backwards."""
from __future__ import annotations

import pytest

from app.services import lessons


def test_every_lesson_is_well_formed():
    data = lessons.load()
    units = [k for k in data if not k.startswith("_") and k != "version"]
    assert units, "no lessons authored"
    for unit_id in units:
        lesson = lessons.for_unit(unit_id)
        assert lesson["intro"] and lesson["title"]
        # A lesson that only presents and never asks is a document, not a lesson.
        assert any(s["type"] == "check" for s in lesson["steps"]), f"{unit_id} has no checks"
        for step in lesson["steps"]:
            if step["type"] == "check":
                assert step["options"][step["answer"]], "the answer must point at a real option"
                assert step.get("why"), "a wrong answer must be explained"
            if step["type"] == "words":
                for item in step["items"]:
                    assert item.get("de") and item.get("en"), f"{unit_id}: a word needs both sides"


def test_lessons_cover_the_units_they_claim():
    """A lesson keyed to a unit that does not exist would never be reachable."""
    from app.services import curriculum

    known = {u["id"] for p in curriculum.load()["phases"] for u in p["units"]}
    for unit_id in lessons.load():
        if unit_id.startswith("_") or unit_id == "version":
            continue
        assert unit_id in known, f"lesson {unit_id} has no unit"


def test_bad_lesson_data_is_rejected(monkeypatch, tmp_path):
    bad = {"a1.1-1": {"title": "x", "steps": [{"type": "check", "question": "q",
                                               "options": ["a", "b"], "answer": 5}]}}
    import json

    from app.config import settings

    (tmp_path / "lessons.json").write_text(json.dumps(bad))
    monkeypatch.setattr(settings, "curriculum_path", tmp_path / "units.json")
    lessons.load.cache_clear()
    with pytest.raises(lessons.LessonError, match="answer"):
        lessons.load()
    lessons.load.cache_clear()


@pytest.mark.asyncio
async def test_progress_never_moves_backwards(fresh_db):
    await lessons.save_step("a1.1-1", 5)
    assert (await lessons.save_step("a1.1-1", 2))["step"] == 5, "re-reading a page is not losing progress"
    assert (await lessons.save_step("a1.1-1", 7))["step"] == 7


@pytest.mark.asyncio
async def test_checks_and_completion_are_recorded(fresh_db):
    await lessons.record_check("a1.1-1", True)
    await lessons.record_check("a1.1-1", False)
    p = await lessons.progress("a1.1-1")
    assert (p["checks_right"], p["checks_total"]) == (1, 2)

    done = await lessons.complete("a1.1-1")
    assert done["completed"] and done["completed_at"]
    first = done["completed_at"]
    again = await lessons.complete("a1.1-1")
    assert again["completed_at"] == first, "finishing twice keeps the first completion time"


@pytest.mark.asyncio
async def test_status_drives_the_landing_tab(fresh_db):
    s = await lessons.status_for("a1.1-1")
    assert s["has_lesson"] and not s["completed"] and s["steps"] > 0
    await lessons.complete("a1.1-1")
    assert (await lessons.status_for("a1.1-1"))["completed"]
    # A unit with no written lesson must not strand the learner on an empty tab.
    assert (await lessons.status_for("b1.2-5"))["has_lesson"] is False


def test_lesson_routes_need_auth(client):
    for path in ("/api/lesson/current", "/api/lesson/status", "/api/lesson/a1.1-1"):
        assert client.get(path).status_code == 401


# -- generated exercises ----------------------------------------------------
def test_a_lesson_is_mostly_doing_not_reading():
    """A page of text and a Next button is a textbook. Most of a lesson should be exercises."""
    from app.services import exercises

    seq = exercises.build(lessons.for_unit("a1.1-1"), 0)
    practise = [e for e in seq if e.get("mode") == "practise"]
    assert len(practise) > len(seq) / 2, f"only {len(practise)} of {len(seq)} steps are interactive"
    assert {e["type"] for e in practise} >= {"match", "listen", "build", "speak"}


def test_match_never_lines_its_answers_up():
    """Shuffling both columns independently lands on a fully aligned board about 1 in 120, and then
    the exercise is free. Every seed must be deranged."""
    from app.services import exercises

    for unit in ("a1.1-1", "a1.1-2"):
        for seed in range(40):
            for ex in exercises.build(lessons.for_unit(unit), seed):
                if ex["type"] != "match":
                    continue
                answer = {p["de"]: p["en"] for p in ex["pairs"]}
                aligned = [l for l, r in zip(ex["left"], ex["right"]) if answer[l] == r]
                assert not aligned, f"{unit} seed {seed}: {len(aligned)} row(s) give the answer away"


def test_build_tiles_contain_the_sentence_plus_a_decoy():
    from app.services import exercises

    for ex in exercises.build(lessons.for_unit("a1.1-1"), 3):
        if ex["type"] != "build":
            continue
        for word in ex["answer"]:
            assert word in ex["tiles"], "the sentence must be buildable from the tiles"
        assert len(ex["tiles"]) > len(ex["answer"]), "a decoy makes word order the thing being tested"


def test_listen_options_are_plausible_and_unique():
    from app.services import exercises

    for ex in exercises.build(lessons.for_unit("a1.1-1"), 7):
        if ex["type"] != "listen":
            continue
        assert len(set(ex["options"])) == len(ex["options"]), "a repeated option is a free answer"
        assert ex["options"][ex["answer"]] == ex["audio"]


def test_the_same_seed_gives_the_same_lesson():
    """A refresh must not reshuffle the exercise he is halfway through."""
    from app.services import exercises

    a = exercises.build(lessons.for_unit("a1.1-1"), 11)
    b = exercises.build(lessons.for_unit("a1.1-1"), 11)
    c = exercises.build(lessons.for_unit("a1.1-1"), 12)
    assert a == b
    assert a != c, "a second run through should not be identical"


def test_speech_is_graded_generously():
    """The transcriber mishears a beginner constantly; punishing that teaches him to stop talking."""
    from app.services.exercises import matches_spoken

    assert matches_spoken("Guten Morgen", "guten morgen")
    assert matches_spoken("Guten Morgen!", "Guten Morgen.")
    assert matches_spoken("Ich komme aus Jordanien", "ich komme aus jordanien bitte")
    assert matches_spoken("Ich bin Ahmad und ich wohne in Amman", "ich bin ahmad und ich wohne in berlin")
    assert not matches_spoken("Guten Morgen", "auf wiedersehen")
    assert not matches_spoken("Guten Morgen", "")


def test_grading_matches_the_client():
    from app.services import exercises

    assert exercises.grade({"type": "build", "answer": ["Ich", "bin", "Ahmad."]}, ["Ich", "bin", "Ahmad."])
    assert not exercises.grade({"type": "build", "answer": ["Ich", "bin", "Ahmad."]}, ["bin", "Ich", "Ahmad."])
    assert exercises.grade({"type": "listen", "answer": 2}, 2)
    assert not exercises.grade({"type": "listen", "answer": 2}, 1)


@pytest.mark.asyncio
async def test_a_lesson_can_be_taken_again(fresh_db):
    """save_step never moves backwards, so a second run needs its own door — without it the
    "do the lesson again" button reloads straight back onto the finished card."""
    await lessons.save_step("a1.1-1", 20)
    await lessons.complete("a1.1-1")
    again = await lessons.restart("a1.1-1")
    assert again["step"] == 0
    assert again["completed"], "restarting must not take away the credit for finishing"
