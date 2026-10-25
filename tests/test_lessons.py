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



@pytest.mark.asyncio
async def test_a_unit_without_a_lesson_does_not_strand_the_learner(fresh_db, monkeypatch):
    """Every unit has a lesson today, but one added to units.json before its lesson is written must
    not leave an empty tab or lock the lessons after it."""
    data = {k: v for k, v in lessons.load().items() if k != "a1.1-2"}
    monkeypatch.setattr(lessons, "load", lambda: data)
    assert (await lessons.status_for("a1.1-2"))["has_lesson"] is False
    await lessons.complete("a1.1-1")
    o = {x["unit_id"]: x for x in await lessons.overview(["a1.1-1", "a1.1-2", "a1.1-3"])}
    assert o["a1.1-3"]["open"], "a missing lesson cannot hold the next one hostage"


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


@pytest.mark.asyncio
async def test_status_counts_the_exercises_the_screen_walks(fresh_db):
    """Progress is saved per exercise, so the step count must be the exercise count too; counting
    the authored pages made Home say "step 6 of 12" in a 34-step lesson."""
    from app.services import exercises

    s = await lessons.status_for("a1.1-1")
    assert s["steps"] == len(exercises.build(lessons.for_unit("a1.1-1")))


def test_listening_distractors_are_confusable():
    """Hearing a whole sentence and choosing between it, "eins" and "zehn" tests nothing. Every
    distractor is a near-miss: same shape (word count within one), never a swapped first word."""
    from app.services import exercises

    seen = 0
    for unit_id in ("a1.1-1", "a1.1-2"):
        lesson = lessons.for_unit(unit_id)
        for seed in range(4):
            for ex in exercises.build(lesson, seed):
                if ex["type"] != "listen":
                    continue
                seen += 1
                target = ex["audio"].split()
                for opt in ex["options"]:
                    if opt == ex["audio"]:
                        continue
                    words = opt.split()
                    assert abs(len(words) - len(target)) <= 1 or len(target) >= 4, (ex["audio"], opt)
                    if len(words) == len(target) and len(target) > 1 and words[1:] == target[1:]:
                        raise AssertionError(f"first word swapped: {opt!r} for {ex['audio']!r}")
                    assert len(set(w.lower() for w in words)) == len(words), f"repeated word in {opt!r}"
    assert seen > 10


def test_a_spoken_number_counts_however_the_transcriber_writes_it():
    """Saying "fünf" came back from Whisper as "5" and was marked wrong."""
    from app.services.exercises import german_number, matches_spoken

    assert [german_number(n) for n in (1, 5, 17, 21, 30, 101, 2500)] == [
        "eins", "fünf", "siebzehn", "einundzwanzig", "dreißig", "hunderteins", "zweitausendfünfhundert"]
    assert matches_spoken("fünf", "5")
    assert matches_spoken("einundzwanzig", "21.")
    assert matches_spoken("Es ist drei Uhr.", "Es ist 3 Uhr.")
    assert matches_spoken("eins", "1")
    assert not matches_spoken("fünf", "6")


@pytest.mark.asyncio
async def test_the_next_lesson_opens_when_this_one_is_finished(fresh_db):
    """Learning ahead is never locked behind a checkpoint: a lesson opens when the one before it is done."""
    units = ["a1.1-1", "a1.1-2", "a1.1-3"]
    o = {x["unit_id"]: x for x in await lessons.overview(units)}
    assert o["a1.1-1"]["open"] and not o["a1.1-2"]["open"]
    await lessons.complete("a1.1-1")
    o = {x["unit_id"]: x for x in await lessons.overview(units)}
    assert o["a1.1-2"]["open"] and o["a1.1-1"]["completed"]


def test_every_unit_from_a1_to_c2_is_taught():
    """The whole path is coursework, not a syllabus with two lessons at the front: every unit has a
    lesson that teaches each of its grammar points, trains reading and listening on connected text,
    and checks understanding (docs/CURRICULUM.md §5)."""
    from app.services import curriculum

    assert curriculum.PHASE_ORDER[0] == "a1.1" and curriculum.PHASE_ORDER[-1] == "c2.2"
    assert len(curriculum.PHASE_ORDER) == 12
    for u in curriculum.all_units():
        lesson = lessons.for_unit(u["id"])
        assert lesson, f"{u['id']} has no lesson"
        types = [s["type"] for s in lesson["steps"]]
        assert types.count("grammar") >= len(u["grammar"]), u["id"]
        assert types.count("check") >= 5 and types.count("words") >= 2, u["id"]
        skills = {s["skill"] for s in lesson["steps"] if s["type"] == "text"}
        assert skills, f"{u['id']} has no text to read or hear"
        if u["id"] >= "a2.1":
            assert skills == {"read", "listen"}, u["id"]
        for i, s in enumerate(lesson["steps"]):
            if s["type"] == "text":
                assert types[i + 1:i + 3] == ["check", "check"], f"{u['id']} step {i}: a text is followed by its checks"


def test_a_text_step_must_have_lines_and_a_skill(monkeypatch, tmp_path):
    import json

    from app.config import settings

    monkeypatch.setattr(settings, "curriculum_path", tmp_path / "units.json")
    for bad, match in ((({"type": "text", "title": "t", "skill": "watch", "lines": [{"de": "a", "en": "b"}]}), "skill"),
                       (({"type": "text", "title": "t", "skill": "read", "lines": [{"de": "a"}]}), "lines")):
        (tmp_path / "lessons.json").write_text(json.dumps({"a1.1-1": {"title": "x", "steps": [bad]}}))
        lessons.load.cache_clear()
        with pytest.raises(lessons.LessonError, match=match):
            lessons.load()
    lessons.load.cache_clear()


def test_text_lines_are_playable():
    step = {"type": "text", "skill": "listen", "title": "t", "lines": [{"who": "A", "de": "Hallo!", "en": "Hi!"}]}
    assert lessons.spoken_lines({"steps": [step]}) == ["Hallo!"]


def test_every_scenario_comes_with_a_briefing_and_its_words():
    """Not only at A1.1: a learner opening any scene reads what is happening and gets its key phrases,
    in their own version of the scene."""
    from app.services import curriculum

    for kind in ("engineer", "student"):
        persona = {"kind": kind, "name": "X", "about": "", "work": "", "role_de": "", "city": "Amman", "gender": "m"}
        for u in curriculum.all_units():
            for sc in curriculum.render_for_user(u["scenarios"], persona):
                assert sc.get("brief") and 6 <= len(sc.get("words") or []) <= 9, (kind, sc["id"])
                assert "{{" not in sc["brief"] + sc["setup"] + sc["goal"]


def test_beginner_scenarios_come_with_a_briefing_and_their_words():
    """'Am Empfang' with no context and no words gave a beginner nothing to say. Every A1.1 scene
    (and each learner's version of it) says in English what is happening and gives the words."""
    from app.services import curriculum

    for kind in ("engineer", "student"):
        persona = {"kind": kind, "name": "X", "about": "", "work": "", "role_de": "", "city": "Amman", "gender": "m"}
        for u in curriculum.phase("a1.1")["units"]:
            for sc in curriculum.render_for_user(u["scenarios"], persona):
                assert sc.get("brief") and len(sc.get("words") or []) >= 5, (kind, sc["id"])
                assert "one question per turn" in sc["setup"], sc["id"]
                assert "{{" not in sc["brief"] + sc["setup"]


def test_a_gap_tests_the_form_the_step_teaches():
    """Tiles test word order; the gap tests the form: one word blanked, offered with its siblings."""
    import random

    from app.services import exercises

    g = exercises._gap({"de": "Ich fahre mit dem neuen Bus.", "en": "I take the new bus."}, random.Random(0))
    assert g["options"][g["answer"]] == "neuen" and g["before"] == "Ich fahre mit dem" and g["after"] == "Bus."
    g = exercises._gap({"de": "Der Kollege, dessen Laptop kaputt ist, wartet.", "en": "x"}, random.Random(0))
    assert g["options"][g["answer"]] == "dessen", "the rarer form is the one the step is about"
    g = exercises._gap({"de": "Ich bleibe zu Hause, weil ich krank bin.", "en": "x"}, random.Random(0))
    assert g["options"][g["answer"]] == "weil" and len(set(g["options"])) == 3
    # "Das ist gut": a pronoun, where "Der ist gut" would be right too. The verb is the gap, never "Das".
    for seed in range(5):
        assert exercises._gap({"de": "Das ist gut.", "en": "x"}, random.Random(seed))["before"] == "Das"
    assert exercises.grade(g, g["answer"]) and not exercises.grade(g, (g["answer"] + 1) % 3)
