from app.services import vocab


async def test_upsert_never_resets_srs_state(fresh_db):
    vid, created = await vocab.upsert("der Termin (die Termine)", "appointment", source="tutor")
    assert created
    await fresh_db.execute("UPDATE vocab SET reps=5, interval_days=30, due=9e9, ease=2.1 WHERE id=?", (vid,))
    vid2, created2 = await vocab.upsert("Der Termin (die Termine)", "appointment", example="Ich habe einen Termin.")
    assert vid2 == vid and not created2
    row = await vocab.get(vid)
    assert row["reps"] == 5 and row["due"] == 9e9 and row["example"] == "Ich habe einen Termin." and row["is_new"] is False
    items, total = await vocab.search("termin")
    assert total == 1 and items[0]["id"] == vid
    assert await vocab.delete(vid) and not await vocab.delete(vid)
