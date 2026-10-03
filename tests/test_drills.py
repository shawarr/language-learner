"""D3: drills target his weakest categories, grade locally, and move the mistake log the right way."""
from __future__ import annotations

import time

import pytest

from app.db import loads
from app.providers.fake import FakeProvider
from app.providers.llm import LLMUnavailable
from app.services import drills, mistakes

NOW = 1_700_000_000.0


async def seed_mistakes() -> dict[str, int]:
    ids = {}
    for _ in range(4):
        ids["case"] = await mistakes.record("case", "dative after mit", "mit den Bus", "mit dem Bus", now=NOW)
    for _ in range(2):
        ids["word_order"] = await mistakes.record("word_order", "verb second", "Gestern ich habe", "Gestern habe ich", now=NOW)
    ids["gender"] = await mistakes.record("gender", "Termin is masculine", "das Termin", "der Termin", now=NOW)
    ids["verb"] = await mistakes.record("verb_conjugation", "sein for movement", "ich habe gegangen", "ich bin gegangen", now=NOW - 10)
    beaten = await mistakes.record("plural", "Busse", "Buse", "Busse", now=NOW)
    await mistakes.resolve(beaten)
    return ids


def item(kind: str, ref: int = -1, **kw) -> dict:
    base = {"type": kind, "prompt": f"{kind} prompt ___", "options": [], "answer": "mit dem", "category": "case",
            "explanation": "'mit' takes the dative.", "mistake_ref": ref}
    if kind in ("fill_blank", "choose"):
        base["options"] = ["mit dem", "mit den", "mit der"]
    return {**base, **kw}


ITEMS = {"items": [
    item("fill_blank", 1, prompt="Ich fahre ___ Bus zur Arbeit."),
    item("choose", 2, prompt="Which is right?", options=["Gestern ich habe gearbeitet.", "Gestern habe ich gearbeitet."],
         answer="Gestern habe ich gearbeitet.", category="word_order", explanation="The verb stays second."),
    item("reorder", -1, prompt="habe / Gestern / ich / gearbeitet.", answer="Gestern habe ich gearbeitet.",
         category="word_order"),
    item("transform", 3, prompt="Put it in the Perfekt: Ich gehe ins Büro.", answer="Ich bin ins Büro gegangen.",
         category="verb_conjugation", explanation="Movement verbs take 'sein'."),
]}


async def test_generation_targets_weakest_categories_and_links_mistake_ids(fresh_db):
    ids = await seed_mistakes()
    FakeProvider.canned = ITEMS
    out = await drills.new(8)
    assert out["categories"] == ["case", "word_order", "gender"], "ranked by open count, ties by name; beaten rows ignored"
    system = FakeProvider.calls[-1].system
    assert "1. [case] dative after mit" in system and 'he wrote "mit den Bus", correct "mit dem Bus"' in system
    assert "verb_conjugation" not in system.split("## His own mistakes")[1], "only the targeted categories are listed"
    assert "Generate 8 items." in FakeProvider.calls[-1].messages[-1].content
    assert set(out) == {"id", "categories", "items"}
    for i, it in enumerate(out["items"]):
        assert set(it) == {"index", "type", "prompt", "options", "category"} and it["index"] == i
    assert out["items"][2]["options"] is None and out["items"][0]["options"] == ["mit dem", "mit den", "mit der"]
    stored = loads((await fresh_db.fetchone("SELECT * FROM drills WHERE id=?", (out["id"],)))["items"], [])
    # refs are numbered in all_open order within the chosen categories: 1 case, 2 word_order, 3 gender
    assert [s["mistake_id"] for s in stored] == [ids["case"], ids["word_order"], None, ids["gender"]]
    assert stored[0]["answer"] == "mit dem" and stored[0]["explanation"]
    row = await fresh_db.fetchone("SELECT answers, results, score, finished_at FROM drills WHERE id=?", (out["id"],))
    assert loads(row["answers"], None) == [None] * 4 and loads(row["results"], None) == [None] * 4
    assert row["score"] is None and row["finished_at"] is None


async def test_generation_falls_back_to_unit_grammar_when_the_log_is_empty(fresh_db):
    FakeProvider.canned = {"items": [item("fill_blank", 1), item("choose", 7, category="gender"), item("reorder", 0)]}
    out = await drills.new()
    assert "no open mistakes" in FakeProvider.calls[-1].system
    assert out["categories"] == ["case", "gender"], "derived from the items when there was nothing to target"
    stored = loads((await fresh_db.fetchone("SELECT items FROM drills"))["items"], [])
    assert all(s["mistake_id"] is None for s in stored), "no list to reference, so every ref is generic"


async def test_malformed_items_are_dropped_and_too_few_is_a_503(fresh_db, auth_client):
    FakeProvider.canned = {"items": [
        item("fill_blank"), item("choose", options=["x", "y"]), "junk", item("transform", prompt=""),
        item("bogus_type"), item("reorder", answer=""), {"type": "choose", "prompt": "p", "answer": "a"},
    ]}
    with pytest.raises(LLMUnavailable):
        await drills.new(5)
    assert (await fresh_db.fetchone("SELECT COUNT(*) AS n FROM drills"))["n"] == 0
    FakeProvider.canned = {"items": "not a list"}
    with pytest.raises(LLMUnavailable):
        await drills.new(5)
    FakeProvider.canned = {"items": [item("choose", options=["x"])] + [item("fill_blank")] * 2}
    r = auth_client.get("/api/drill/new", params={"n": 5})
    assert r.status_code == 503 and r.json()["retryable"] is True


async def test_item_validation_details(fresh_db):
    FakeProvider.canned = {"items": [
        item("FILL_BLANK", options=["ganz", "anders"]),            # options without the key → free text
        item("choose", category="Made Up", mistake_ref="1"),       # category → other, ref → None
        item("transform", options=["should", "vanish"], mistake_ref=True),
        item("reorder", mistake_ref=-1),
    ] + [item("fill_blank")] * 20}
    out = await drills.new(50)
    assert len(out["items"]) == drills.MAX_ITEMS, "n clamps to 12"
    stored = loads((await fresh_db.fetchone("SELECT items FROM drills"))["items"], [])
    assert stored[0]["type"] == "fill_blank" and stored[0]["options"] == []
    assert stored[1]["category"] == "other" and stored[1]["mistake_id"] is None
    assert stored[2]["options"] == [] and stored[2]["mistake_id"] is None
    FakeProvider.canned = {"items": [item("fill_blank")] * 5}
    assert len((await drills.new(1))["items"]) == drills.MIN_ITEMS, "n clamps up to 3"


def test_exact_grading_normalisation():
    assert drills.grade_exact("mit dem Bus", "  Mit DEM   bus. ")
    assert drills.grade_exact("Gestern habe ich gearbeitet.", "gestern habe ich gearbeitet")
    assert drills.grade_exact("Ich bin ins Büro gegangen.", "ich bin ins büro gegangen!")
    assert not drills.grade_exact("mit dem", "mit den")
    assert not drills.grade_exact("mit dem", "mit dem Bus")
    assert not drills.grade_exact("", "")
    assert drills.normalize_answer("„Hallo, Welt!“") == "hallo welt"


async def test_answering_moves_the_mistake_log_and_finishes_the_drill(fresh_db):
    ids = await seed_mistakes()
    FakeProvider.canned = ITEMS
    d = await drills.new(8)
    calls_before = len(FakeProvider.calls)

    right = await drills.answer(d["id"], 0, "MIT DEM")
    assert right == {"index": 0, "correct": True, "answer": "mit dem", "your_answer": "MIT DEM",
                     "explanation": "'mit' takes the dative.", "finished": False, "score": None, "total": 4}
    assert (await fresh_db.fetchone("SELECT resolved, count FROM mistakes WHERE id=?", (ids["case"],)))["resolved"] == 1

    wrong = await drills.answer(d["id"], 1, "Gestern ich habe gearbeitet.")
    assert wrong["correct"] is False and wrong["answer"] == "Gestern habe ich gearbeitet."
    wo = await fresh_db.fetchone("SELECT resolved, count FROM mistakes WHERE id=?", (ids["word_order"],))
    assert (wo["count"], wo["resolved"]) == (3, 0)

    # Answering the same index again returns the stored result and touches nothing.
    again = await drills.answer(d["id"], 1, "Gestern habe ich gearbeitet.")
    assert again["correct"] is False and again["your_answer"] == "Gestern ich habe gearbeitet."
    wo = await fresh_db.fetchone("SELECT resolved, count FROM mistakes WHERE id=?", (ids["word_order"],))
    assert (wo["count"], wo["resolved"]) == (3, 0)

    # An item without a mistake id falls back to the most pressing open row in its category.
    reorder = await drills.answer(d["id"], 2, "gestern habe ich gearbeitet")
    assert reorder["correct"] is True
    wo = await fresh_db.fetchone("SELECT resolved, count FROM mistakes WHERE id=?", (ids["word_order"],))
    assert (wo["count"], wo["resolved"]) == (3, 1)
    assert len(FakeProvider.calls) == calls_before, "exact items never call the model"

    # The last item closes the drill: score, finished_at, activity.
    last = await drills.answer(d["id"], 3, "ich bin ins büro gegangen")
    assert last["finished"] is True and last["score"] == 3 and last["total"] == 4
    row = await fresh_db.fetchone("SELECT * FROM drills WHERE id=?", (d["id"],))
    assert row["score"] == 3 and row["finished_at"] is not None
    assert loads(row["answers"], []) == ["MIT DEM", "Gestern ich habe gearbeitet.", "gestern habe ich gearbeitet",
                                         "ich bin ins büro gegangen"]
    assert [r["correct"] for r in loads(row["results"], [])] == [True, False, True, True]
    day = time.strftime("%Y-%m-%d", time.gmtime())
    assert (await fresh_db.fetchone("SELECT count FROM activity WHERE day=? AND kind='drill'", (day,)))["count"] == 1
    assert (await fresh_db.fetchone("SELECT resolved FROM mistakes WHERE id=?", (ids["gender"],)))["resolved"] == 1


async def test_transform_calls_the_model_only_when_the_answer_differs(fresh_db):
    ids = await seed_mistakes()
    FakeProvider.canned = ITEMS
    d = await drills.new(8)
    n = len(FakeProvider.calls)
    assert (await drills.answer(d["id"], 3, "Ich bin ins Büro gegangen"))["correct"] is True
    assert len(FakeProvider.calls) == n, "an exact transform answer is graded locally"

    d2 = await drills.new(8)
    FakeProvider.canned = {"correct": True, "note": "Also fine; the expected form is 'Ich bin ins Büro gegangen.'"}
    res = await drills.answer(d2["id"], 3, "Ins Büro bin ich gegangen.")
    assert res["correct"] is True and res["explanation"].startswith("Movement verbs take 'sein'.") and "Also fine" in res["explanation"]
    assert len(FakeProvider.calls) == n + 2, "generation plus one grading call"
    assert FakeProvider.calls[-1].json_schema is drills.GRADE_SCHEMA
    assert "Ins Büro bin ich gegangen." in FakeProvider.calls[-1].system
    # The first drill beat the gender row (resolved >= count), so the second drill targeted
    # verb_conjugation instead and ref 3 now points at that row.
    assert d2["categories"] == ["case", "word_order", "verb_conjugation"]
    assert (await fresh_db.fetchone("SELECT resolved FROM mistakes WHERE id=?", (ids["gender"],)))["resolved"] == 1
    assert (await fresh_db.fetchone("SELECT resolved FROM mistakes WHERE id=?", (ids["verb"],)))["resolved"] == 1

    FakeProvider.canned = ITEMS
    d3 = await drills.new(8)
    FakeProvider.canned = {"correct": "yes", "note": ""}  # a non-boolean never counts as right
    assert (await drills.answer(d3["id"], 3, "Ich habe ins Büro gegangen."))["correct"] is False
    assert (await drills.answer(d3["id"], 0, ""))["correct"] is False

    FakeProvider.canned = ITEMS
    d4 = await drills.new(8)
    n = len(FakeProvider.calls)
    assert (await drills.answer(d4["id"], 3, "   "))["correct"] is False
    assert len(FakeProvider.calls) == n, "an empty transform answer is wrong without a model call"


async def test_submit_grades_the_rest_and_skips_graded_and_null(fresh_db):
    await seed_mistakes()
    FakeProvider.canned = ITEMS
    d = await drills.new(8)
    await drills.answer(d["id"], 0, "mit den")
    out = await drills.submit(d["id"], ["mit dem", "Gestern habe ich gearbeitet.", None, "Ich bin ins Büro gegangen."])
    assert [r["index"] for r in out["results"]] == [0, 1, 3] and out["score"] == 2 and out["total"] == 4
    assert out["results"][0]["your_answer"] == "mit den" and out["results"][0]["correct"] is False, "index 0 was not re-graded"
    assert out["finished"] is False
    out = await drills.submit(d["id"], [None, None, "Gestern habe ich gearbeitet."])
    assert out["finished"] is True and out["score"] == 3
    assert (await fresh_db.fetchone("SELECT score FROM drills WHERE id=?", (d["id"],)))["score"] == 3
    with pytest.raises(ValueError):
        await drills.answer(d["id"], 9, "x")
    with pytest.raises(LookupError):
        await drills.submit(999, [])


def test_drill_routes(auth_client):
    FakeProvider.canned = ITEMS
    r = auth_client.get("/api/drill/new", params={"n": 8})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["items"]) == 4 and "answer" not in d["items"][0] and "explanation" not in d["items"][0]
    r = auth_client.post(f"/api/drill/{d['id']}/answer", json={"index": 0, "answer": "mit dem"})
    assert r.status_code == 200 and r.json()["correct"] is True and r.json()["finished"] is False
    assert auth_client.post(f"/api/drill/{d['id']}/answer", json={"index": 9, "answer": "x"}).status_code == 422
    assert auth_client.post(f"/api/drill/{d['id']}/answer", json={"index": 0}).status_code == 422
    assert auth_client.post("/api/drill/999/answer", json={"index": 0, "answer": "x"}).status_code == 404
    r = auth_client.post(f"/api/drill/{d['id']}/submit",
                         json={"answers": [None, "wrong", "Gestern habe ich gearbeitet.", "Ich bin ins Büro gegangen."]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 4 and body["score"] == 3 and len(body["results"]) == 4
    assert auth_client.post("/api/drill/999/submit", json={"answers": []}).status_code == 404
    assert auth_client.post(f"/api/drill/{d['id']}/submit", json={"answers": "x"}).status_code == 422
    assert auth_client.get("/api/drill/new").status_code == 200, "n defaults to settings.drill_items"


def test_drill_routes_need_auth(client):
    assert client.get("/api/drill/new").status_code == 401
