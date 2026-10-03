"""C1/C2: the curriculum JSON is valid pedagogy data and the service never crashes on stale state."""
from __future__ import annotations

import re

import pytest

from app.services import curriculum, profile


def test_curriculum_loads_and_is_well_formed():
    data = curriculum.load()
    assert [p["id"] for p in data["phases"]] == curriculum.PHASE_ORDER
    ids = []
    for p in data["phases"]:
        assert p["level"] == p["id"].upper()
        for u in p["units"]:
            ids.append(u["id"])
            assert u["can_do"] and u["grammar"] and u["vocab_themes"]
            assert len(u["scenarios"]) >= 2
            for sc in u["scenarios"]:
                ids.append(sc["id"])
                assert sc["setup"] and sc["goal"]
            assert u["checkpoint"]["speaking"]["prompt"] and u["checkpoint"]["writing"]["prompt"]
    assert len(ids) == len(set(ids))
    assert all(re.match(r"^[a-z0-9.\-]+$", i) for i in ids)


def test_validation_rejects_a_bad_tree():
    with pytest.raises(curriculum.CurriculumError):
        curriculum.validate({"phases": []})
    good = curriculum.load()
    bad = {"version": 1, "phases": [dict(p, units=[dict(u, scenarios=u["scenarios"][:1]) for u in p["units"]])
                                   for p in good["phases"]]}
    with pytest.raises(curriculum.CurriculumError, match="scenarios"):
        curriculum.validate(bad)


def test_navigation_helpers():
    units = curriculum.all_units()
    first = units[0]
    assert curriculum.unit(first["id"]) == first
    assert curriculum.phase_of(first["id"])["id"] == "a1.1"
    assert curriculum.next_unit(first["id"]) == units[1]
    assert curriculum.next_unit(units[-1]["id"]) is None
    assert curriculum.unit("nope") is None
    assert curriculum.unit_position(first["id"]) == (1, len(curriculum.phases()[0]["units"]))
    u, sc = curriculum.scenario(first["scenarios"][0]["id"])
    assert u == first and sc == first["scenarios"][0]
    assert curriculum.scenario("nope") is None
    assert curriculum.first_unit_of_level("B1.1")["id"].startswith("b1.1-")
    assert curriculum.first_unit_of_level("Z9")["id"] == first["id"]


async def test_stale_unit_id_falls_back_instead_of_crashing(fresh_db):
    await profile.update_profile(unit_id="a1.2-99", level="A1.2")
    u = await curriculum.current_unit()
    assert u["id"] == curriculum.first_unit_of_level("A1.2")["id"]
    cur = await curriculum.current()
    assert cur["phase"]["level"] == "A1.2" and cur["scenarios"]


async def test_advance_moves_and_clears_review_focus(fresh_db):
    units = curriculum.all_units()
    await profile.update_profile(unit_id=units[0]["id"], review_focus=["x"])
    res = await curriculum.advance()
    p = await profile.get_profile()
    assert res["unit"]["id"] == units[1]["id"] and p["unit_id"] == units[1]["id"] and p["review_focus"] == []
    assert p["level"] == curriculum.phase_of(units[1]["id"])["level"]
    await profile.update_profile(unit_id=units[-1]["id"])
    assert (await curriculum.advance())["finished"] is True


def test_curriculum_routes(client):
    assert client.get("/api/curriculum").status_code == 401
    client.post("/api/auth/login", json={"password": "test-password"})
    tree = client.get("/api/curriculum").json()
    assert [p["id"] for p in tree["phases"]] == curriculum.PHASE_ORDER
    assert tree["current"]["unit_id"] == "a1.1-1" and "checkpoint" not in tree["phases"][0]["units"][0]
    cur = client.get("/api/curriculum/current").json()
    assert cur["unit"]["id"] == "a1.1-1" and cur["scenarios"] and cur["checkpoint_available"] is False
