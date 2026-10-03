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
