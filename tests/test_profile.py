"""A1: the profile service formats the tutor's memory, and keeps the prompt small."""
from __future__ import annotations

import time

import pytest

from app.prompts import placeholders, render
from app.services import mistakes, profile


async def test_skill_deltas_clamp_at_both_ends(fresh_db):
    await profile.update_profile(skills={"speaking": 99, "grammar": 1, "vocab": 50})
    skills = await profile.apply_skill_deltas({"speaking": 5, "grammar": -5, "vocab": "x", "bogus": 3})
    assert skills["speaking"] == 100 and skills["grammar"] == 0 and skills["vocab"] == 50
    assert "bogus" not in skills
    assert (await profile.get_profile())["skills"] == skills


async def test_update_profile_rejects_unknown_columns(fresh_db):
    with pytest.raises(ValueError):
        await profile.update_profile(password="nope")


async def test_facts_dedupe_case_insensitively_and_cap(fresh_db):
    await profile.add_facts(["Works at a German company", "works at a german company.", "  Lives in Amman  "])
    facts = (await profile.get_profile())["facts"]
    assert facts == ["Works at a German company", "Lives in Amman"]
    await profile.add_facts([f"fact {i}" for i in range(50)])
    facts = (await profile.get_profile())["facts"]
    assert len(facts) == profile.MAX_FACTS and facts[-1] == "fact 49"


async def test_beaten_mistakes_drop_out_and_ranking_holds(fresh_db):
    now = time.time()
    for _ in range(4):
        await mistakes.record("case", "dative after mit", "mit den Bus", "mit dem Bus", now=now - 100)
    for _ in range(2):
        await mistakes.record("gender", "Termin is masculine", "das Termin", "der Termin", now=now)
    beaten = await mistakes.record("word_order", "verb second", "gestern ich habe", "gestern habe ich", now=now)
    await mistakes.resolve(beaten)
    top = await profile.top_mistakes()
    assert [m["category"] for m in top] == ["case", "gender"], "resolved >= count is beaten and gone"
    assert top[0]["count"] == 4
    text = profile.format_mistakes(top)
    assert text.splitlines()[0] == "case: 'mit dem Bus' not 'mit den Bus' (4×)"


async def test_build_context_matches_the_prompt_exactly(fresh_db):
    unit = {"id": "a1.1-1", "title": "Hallo", "can_do": ["greet"], "grammar": ["sein"], "vocab_themes": ["x"]}
    ctx = await profile.build_context(unit)
    assert set(ctx) == placeholders("tutor_talk")
    assert ctx["top_mistakes"] == "(none yet)" and ctx["due_vocab"] == "(none yet)" and ctx["facts"] == "(none yet)"
    assert "[]" not in " ".join(ctx.values()) and "None" not in " ".join(ctx.values())
    render("tutor_talk", **ctx)  # must not raise


async def test_build_context_truncates_vocab_and_mistakes(fresh_db):
    now = time.time()
    for i in range(20):
        await fresh_db.execute(
            "INSERT INTO vocab (word, translation, created_at, due) VALUES (?, ?, ?, ?)",
            (f"wort{i}", "word", now, now - i))
    for i in range(10):
        await mistakes.record("other", f"pattern {i}", f"w{i}", f"r{i}", now=now)
    unit = {"id": "u", "title": "t", "can_do": ["c"], "grammar": ["g"], "vocab_themes": ["v"]}
    ctx = await profile.build_context(unit)
    assert len(ctx["due_vocab"].split(", ")) == profile.MAX_DUE_VOCAB
    assert len(ctx["top_mistakes"].splitlines()) == profile.MAX_TOP_MISTAKES


async def test_review_focus_reaches_the_grammar_targets(fresh_db):
    await profile.update_profile(review_focus=["dative after mit"])
    unit = {"id": "u", "title": "t", "can_do": ["c"], "grammar": ["sein"], "vocab_themes": ["v"]}
    ctx = await profile.build_context(unit)
    assert "sein" in ctx["grammar_targets"] and "dative after mit" in ctx["grammar_targets"]


async def test_scenario_formatting(fresh_db):
    unit = {"id": "u", "title": "t", "can_do": ["c"], "grammar": ["g"], "vocab_themes": ["v"]}
    free = await profile.build_context(unit)
    assert "scenario_done stays false" in free["scenario"]
    sc = {"id": "s", "title": "Meeting a neighbour", "setup": "You are Frau Keller.", "goal": "He says his name."}
    ctx = await profile.build_context(unit, sc)
    assert "Frau Keller" in ctx["scenario"] and "He says his name." in ctx["scenario"]
