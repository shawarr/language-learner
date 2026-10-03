"""The mistake log merges on (category, normalised pattern); nothing else keeps a count."""
from __future__ import annotations

from app.db import loads
from app.services import mistakes


async def test_same_pattern_merges_into_one_row(fresh_db):
    a = await mistakes.record("Case", "Dative  after MIT", "mit den Bus", "mit dem Bus")
    b = await mistakes.record("case", "dative after mit", "mit den Zug", "mit dem Zug")
    assert a == b
    rows = await fresh_db.fetchall("SELECT * FROM mistakes")
    assert len(rows) == 1 and rows[0]["count"] == 2 and rows[0]["pattern"] == "dative after mit"
    assert [e["wrong"] for e in loads(rows[0]["examples"], [])] == ["mit den Bus", "mit den Zug"]


async def test_examples_capped_at_five_newest(fresh_db):
    for i in range(8):
        await mistakes.record("gender", "termin", f"w{i}", f"r{i}")
    row = await fresh_db.fetchone("SELECT * FROM mistakes")
    ex = loads(row["examples"], [])
    assert len(ex) == 5 and ex[0]["wrong"] == "w3" and ex[-1]["wrong"] == "w7"


async def test_unknown_category_becomes_other_and_empty_pattern_falls_back(fresh_db):
    await mistakes.record("made-up", "", "ich habe gegangen", "ich bin gegangen")
    row = await fresh_db.fetchone("SELECT * FROM mistakes")
    assert row["category"] == "other" and row["pattern"] == "ich habe gegangen -> ich bin gegangen"


async def test_resolve_and_fail(fresh_db):
    mid = await mistakes.record("case", "p", "w", "r")
    await mistakes.resolve(mid)
    await mistakes.fail(mid)
    row = await fresh_db.fetchone("SELECT count, resolved FROM mistakes WHERE id=?", (mid,))
    assert (row["count"], row["resolved"]) == (2, 1)
