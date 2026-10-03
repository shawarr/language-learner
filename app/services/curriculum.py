"""The CEFR path: phases → units → scenarios, from app/curriculum/units.json.

Loaded once and validated hard at first use, so a typo in the JSON fails at startup rather than
mid-conversation. A unit id stored in the DB that the JSON no longer has falls back to the first
unit of the profile's level (and logs it) — the app must never crash on stale state.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from ..config import settings
from . import profile as profile_svc

log = logging.getLogger(__name__)

PHASE_ORDER = ["a1.1", "a1.2", "a2.1", "a2.2", "b1.1", "b1.2"]
_ID = re.compile(r"^[a-z0-9.\-]+$")


class CurriculumError(ValueError):
    pass


def validate(data: dict) -> None:
    phases = data.get("phases")
    if not isinstance(phases, list) or [p.get("id") for p in phases] != PHASE_ORDER:
        raise CurriculumError(f"phases must be exactly {PHASE_ORDER} in order")
    seen: set[str] = set()

    def check_id(value: object, what: str) -> str:
        if not isinstance(value, str) or not _ID.match(value):
            raise CurriculumError(f"{what} id {value!r} must match {_ID.pattern}")
        if value in seen:
            raise CurriculumError(f"duplicate id {value!r}")
        seen.add(value)
        return value

    for phase in phases:
        check_id(phase.get("id"), "phase")
        if not phase.get("level") or not phase.get("title"):
            raise CurriculumError(f"phase {phase.get('id')} needs level and title")
        units = phase.get("units")
        if not isinstance(units, list) or not units:
            raise CurriculumError(f"phase {phase['id']} has no units")
        for unit in units:
            uid = check_id(unit.get("id"), "unit")
            if not uid.startswith(phase["id"] + "-"):
                raise CurriculumError(f"unit {uid} must be prefixed with its phase id {phase['id']}-")
            if not unit.get("title"):
                raise CurriculumError(f"unit {uid} needs a title")
            for key in ("can_do", "grammar", "vocab_themes"):
                v = unit.get(key)
                if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
                    raise CurriculumError(f"unit {uid}: {key} must be a non-empty list of strings")
            scenarios = unit.get("scenarios")
            if not isinstance(scenarios, list) or len(scenarios) < 2:
                raise CurriculumError(f"unit {uid} needs at least 2 scenarios")
            for sc in scenarios:
                sid = check_id(sc.get("id"), "scenario")
                if not sid.startswith(uid + "-"):
                    raise CurriculumError(f"scenario {sid} must be prefixed with its unit id {uid}-")
                for key in ("title", "setup", "goal"):
                    if not isinstance(sc.get(key), str) or not sc[key].strip():
                        raise CurriculumError(f"scenario {sid} needs {key}")
            cp = unit.get("checkpoint")
            if not isinstance(cp, dict) or not all(isinstance(cp.get(k), dict) and cp[k].get("prompt")
                                                   for k in ("speaking", "writing")):
                raise CurriculumError(f"unit {uid} needs checkpoint.speaking.prompt and checkpoint.writing.prompt")


@lru_cache(maxsize=1)
def load() -> dict:
    with open(settings.curriculum_path, encoding="utf-8") as f:
        data = json.load(f)
    validate(data)
    return data


def reload() -> dict:
    load.cache_clear()
    return load()


def phases() -> list[dict]:
    return load()["phases"]


def all_units() -> list[dict]:
    return [u for p in phases() for u in p["units"]]


def unit(unit_id: str | None) -> dict | None:
    return next((u for u in all_units() if u["id"] == unit_id), None)


def phase_of(unit_id: str) -> dict:
    for p in phases():
        if any(u["id"] == unit_id for u in p["units"]):
            return p
    raise CurriculumError(f"unknown unit {unit_id!r}")


def phase(phase_id: str) -> dict | None:
    return next((p for p in phases() if p["id"] == phase_id), None)


def next_unit(unit_id: str) -> dict | None:
    units = all_units()
    for i, u in enumerate(units):
        if u["id"] == unit_id:
            return units[i + 1] if i + 1 < len(units) else None
    return None


def unit_position(unit_id: str) -> tuple[int, int]:
    """(1-based index within its phase, units in the phase)."""
    p = phase_of(unit_id)
    ids = [u["id"] for u in p["units"]]
    return ids.index(unit_id) + 1, len(ids)


def scenarios_for(unit_id: str) -> list[dict]:
    u = unit(unit_id)
    return list(u["scenarios"]) if u else []


def scenario(scenario_id: str | None) -> tuple[dict, dict] | None:
    """(unit, scenario) for a scenario id, or None."""
    if not scenario_id:
        return None
    for u in all_units():
        for sc in u["scenarios"]:
            if sc["id"] == scenario_id:
                return u, sc
    return None


def first_unit_of_level(level: str) -> dict:
    """Level strings look like "A1.2"; phase ids are their lowercase. Unknown level → the very first unit."""
    p = phase((level or "").strip().lower())
    return (p or phases()[0])["units"][0]


def public_unit(u: dict) -> dict:
    """What the API hands out: the unit without its checkpoint tasks (those are revealed by the checkpoint endpoint)."""
    return {k: v for k, v in u.items() if k != "checkpoint"}


async def current_unit() -> dict:
    """The profile's unit, or a sane fallback when the JSON moved on without the DB."""
    p = await profile_svc.get_profile()
    u = unit(p["unit_id"])
    if u is None:
        u = first_unit_of_level(p["level"])
        log.warning("profile unit_id %r not in curriculum; falling back to %s", p["unit_id"], u["id"])
    return u


async def current() -> dict:
    u = await current_unit()
    p = phase_of(u["id"])
    idx, count = unit_position(u["id"])
    return {"phase": {"id": p["id"], "level": p["level"], "title": p["title"]},
            "unit": public_unit(u), "unit_index": idx, "unit_count": count,
            "scenarios": list(u["scenarios"]), "next_unit": public_unit(next_unit(u["id"])) if next_unit(u["id"]) else None}


async def advance() -> dict:
    """Move the profile to the next unit and clear review_focus. At the very end, stay put."""
    u = await current_unit()
    nxt = next_unit(u["id"])
    if nxt is None:
        return {"finished": True, "unit": public_unit(u), "phase": phase_of(u["id"])["level"]}
    p = phase_of(nxt["id"])
    await profile_svc.update_profile(unit_id=nxt["id"], level=p["level"], review_focus=[])
    return {"finished": False, "unit": public_unit(nxt),
            "phase": {"id": p["id"], "level": p["level"], "title": p["title"]},
            "phase_changed": p["id"] != phase_of(u["id"])["id"]}
