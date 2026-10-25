"""The CEFR path: phases → units → scenarios, from app/curriculum/units.json.

Loaded once and validated hard at first use, so a typo in the JSON fails at startup rather than
mid-conversation. A unit id stored in the DB that the JSON no longer has falls back to the first
unit of the profile's level (and logs it) — the app must never crash on stale state.

One curriculum, two learners. The JSON on disk never names anyone: it says `{{name}}`, `{{he}}`,
`{{work}}`, and a scenario that only makes sense for one kind of learner carries a `variants`
block with the other kind's version. `render_for_user` resolves both against the current user's
persona (app/curriculum/personas.json), so everything that leaves this module through
`current_unit`, `scenario`, `public_unit` or `lesson_for_user` reads as if it had been written for
whoever is logged in. The raw accessors (`load`, `unit`, `all_units`) keep the placeholders.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from functools import lru_cache

from .. import users
from ..config import settings
from . import profile as profile_svc

log = logging.getLogger(__name__)

PHASE_ORDER = ["a1.1", "a1.2", "a2.1", "a2.2", "b1.1", "b1.2",
               "b2.1", "b2.2", "c1.1", "c1.2", "c2.1", "c2.2"]
_ID = re.compile(r"^[a-z0-9.\-]+$")

# The only placeholders content may use. The pronouns are named after their masculine form but
# render from the persona's gender; a capitalised token ({{He}}) capitalises the value.
PLACEHOLDERS = ("name", "work", "role_de", "city", "he", "him", "his", "himself")
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_PRONOUNS = {"m": ("he", "him", "his", "himself"),
             "f": ("she", "her", "her", "herself"),
             "x": ("they", "them", "their", "themselves")}
VARIANT_KINDS = ("engineer", "student")
_SCENARIO_VARIANT_KEYS = ("title", "setup", "goal")
# Optional on a scenario (and its variants): what the learner reads before starting, in English, and
# the words and sentences it needs. A beginner dropped into "Am Empfang" with no context and no words
# has nothing to say.
_SCENARIO_BRIEF_KEYS = ("brief", "words")
_TASK_VARIANT_KEYS = ("prompt", "hint")
# A unit that is about one learner's job end to end (the standup, the postmortem) carries the other
# kind's title, goals, themes and grammar examples. Same grammar points, same level, so both learners
# move through one syllabus; lists must keep their length so no point is silently dropped.
_UNIT_VARIANT_KEYS = ("title", "can_do", "grammar", "vocab_themes")

# Used when no user is current (a script, a job without request context). Reads a little flat but
# never crashes; nothing user-facing should reach it.
NEUTRAL_PERSONA = {"name": "the learner", "gender": "x", "kind": None, "work": "a learner of German",
                   "role_de": "Deutschlerner", "city": "Amman"}


class CurriculumError(ValueError):
    pass


def _check_placeholders(node: object, where: str) -> None:
    """Only the known placeholders, anywhere in the tree: a typo like {{nmae}} would otherwise reach
    the tutor prompt verbatim."""
    if isinstance(node, str):
        for token in _PLACEHOLDER.findall(node):
            if token.lower() not in PLACEHOLDERS:
                raise CurriculumError(f"{where}: unknown placeholder {{{{{token}}}}}")
    elif isinstance(node, dict):
        for k, v in node.items():
            _check_placeholders(v, f"{where}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _check_placeholders(v, f"{where}[{i}]")


def _check_variants(owner: dict, where: str, required: tuple[str, ...], allowed: tuple[str, ...]) -> None:
    variants = owner.get("variants")
    if variants is None:
        return
    if not isinstance(variants, dict) or not variants:
        raise CurriculumError(f"{where}: variants must be a non-empty object")
    for kind, variant in variants.items():
        if kind not in VARIANT_KINDS:
            raise CurriculumError(f"{where}: unknown variant kind {kind!r} (expected one of {VARIANT_KINDS})")
        if not isinstance(variant, dict):
            raise CurriculumError(f"{where}: variant {kind} must be an object")
        for key in required:
            if not isinstance(variant.get(key), str) or not variant[key].strip():
                raise CurriculumError(f"{where}: variant {kind} needs {key}")
        extra = set(variant) - set(allowed)
        if extra:
            raise CurriculumError(f"{where}: variant {kind} has unexpected keys {sorted(extra)}")


def _check_brief(node: dict, where: str) -> None:
    if "brief" in node and (not isinstance(node["brief"], str) or not node["brief"].strip()):
        raise CurriculumError(f"{where}: brief must be a non-empty string")
    if "words" in node:
        words = node["words"]
        if not isinstance(words, list) or not words or not all(
                isinstance(w, dict) and set(w) == {"de", "en"} and all(isinstance(w[k], str) and w[k].strip() for k in w)
                for w in words):
            raise CurriculumError(f"{where}: words must be a list of {{de, en}} pairs")


def _check_unit_variants(unit: dict, uid: str) -> None:
    variants = unit.get("variants")
    if variants is None:
        return
    if not isinstance(variants, dict) or not variants:
        raise CurriculumError(f"unit {uid}: variants must be a non-empty object")
    for kind, variant in variants.items():
        if kind not in VARIANT_KINDS or not isinstance(variant, dict) or not variant:
            raise CurriculumError(f"unit {uid}: bad variant {kind!r}")
        extra = set(variant) - set(_UNIT_VARIANT_KEYS)
        if extra:
            raise CurriculumError(f"unit {uid}: variant {kind} has unexpected keys {sorted(extra)}")
        if "title" in variant and (not isinstance(variant["title"], str) or not variant["title"].strip()):
            raise CurriculumError(f"unit {uid}: variant {kind} needs a non-empty title")
        for key in ("can_do", "grammar", "vocab_themes"):
            if key not in variant:
                continue
            v = variant[key]
            if not isinstance(v, list) or not all(isinstance(x, str) and x.strip() for x in v):
                raise CurriculumError(f"unit {uid}: variant {kind}.{key} must be a list of strings")
            if key == "grammar" and len(v) != len(unit["grammar"]):
                raise CurriculumError(f"unit {uid}: variant {kind}.grammar must keep the unit's grammar points one for one")


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
                _check_brief(sc, f"scenario {sid}")
                for kind, variant in (sc.get("variants") or {}).items():
                    if isinstance(variant, dict):
                        _check_brief(variant, f"scenario {sid} variant {kind}")
                _check_variants(sc, f"scenario {sid}", _SCENARIO_VARIANT_KEYS,
                                _SCENARIO_VARIANT_KEYS + _SCENARIO_BRIEF_KEYS)
            cp = unit.get("checkpoint")
            if not isinstance(cp, dict) or not all(isinstance(cp.get(k), dict) and cp[k].get("prompt")
                                                   for k in ("speaking", "writing")):
                raise CurriculumError(f"unit {uid} needs checkpoint.speaking.prompt and checkpoint.writing.prompt")
            _check_unit_variants(unit, uid)
            for task in ("speaking", "writing"):
                _check_variants(cp[task], f"unit {uid} checkpoint.{task}", ("prompt",), _TASK_VARIANT_KEYS)
    _check_placeholders(data, "curriculum")


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


# -- personas and rendering -------------------------------------------------------------------
@lru_cache(maxsize=1)
def _personas() -> dict[str, dict]:
    return users.personas()


def persona_for(user: dict | None) -> dict:
    """The persona of a user row: personas.json by username, else the row's name and gender over the
    neutral defaults (an account with no persona entry still gets its own name)."""
    if user is None:
        return dict(NEUTRAL_PERSONA)
    p = _personas().get(str(user.get("username") or "").lower())
    if p:
        return {**NEUTRAL_PERSONA, **p}
    return {**NEUTRAL_PERSONA, "name": user.get("name") or NEUTRAL_PERSONA["name"],
            "gender": user.get("gender") or "x"}


def current_persona() -> dict:
    try:
        return persona_for(users.current())
    except RuntimeError:
        return dict(NEUTRAL_PERSONA)


def _persona_values(persona: dict) -> dict[str, str]:
    he, him, his, himself = _PRONOUNS.get(persona.get("gender") or "x", _PRONOUNS["x"])
    return {"name": str(persona.get("name") or NEUTRAL_PERSONA["name"]),
            "work": str(persona.get("work") or NEUTRAL_PERSONA["work"]),
            "role_de": str(persona.get("role_de") or NEUTRAL_PERSONA["role_de"]),
            "city": str(persona.get("city") or NEUTRAL_PERSONA["city"]),
            "he": he, "him": him, "his": his, "himself": himself}


def render_text(text: str, persona: dict) -> str:
    """Substitute the supported placeholders; an unknown one is left exactly as written."""
    values = _persona_values(persona)

    def sub(m: re.Match) -> str:
        token = m.group(1)
        value = values.get(token.lower())
        if value is None:
            return m.group(0)
        return value[:1].upper() + value[1:] if token[:1].isupper() else value

    return _PLACEHOLDER.sub(sub, text)


def render_for_user(obj, persona: dict | None = None):
    """A deep copy of any JSON-ish tree with placeholders rendered in every string and each
    `variants` block resolved: the persona's kind wins over the default fields, and the key is
    dropped so the API shape stays `{"id","title","setup","goal"}`."""
    persona = persona if persona is not None else current_persona()
    kind = persona.get("kind")

    def walk(node):
        if isinstance(node, str):
            return render_text(node, persona)
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, dict):
            variants = node.get("variants")
            base = {k: v for k, v in node.items() if k != "variants"}
            if isinstance(variants, dict) and isinstance(variants.get(kind), dict):
                base.update(variants[kind])
            return {k: walk(v) for k, v in base.items()}
        return copy.deepcopy(node)

    return walk(obj)


def lesson_for_user(lesson: dict) -> dict:
    """lessons.json teaches with the learner's own name in its examples; same rules as the units."""
    return render_for_user(lesson)


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
    """The unit's scenarios as the current learner should see them."""
    u = unit(unit_id)
    return render_for_user(u["scenarios"]) if u else []


def scenario(scenario_id: str | None) -> tuple[dict, dict] | None:
    """(unit, scenario) for a scenario id, both rendered for the current learner, or None."""
    if not scenario_id:
        return None
    for u in all_units():
        if any(sc["id"] == scenario_id for sc in u["scenarios"]):
            rendered = render_for_user(u)
            return rendered, next(sc for sc in rendered["scenarios"] if sc["id"] == scenario_id)
    return None


def first_unit_of_level(level: str) -> dict:
    """Level strings look like "A1.2"; phase ids are their lowercase. Unknown level → the very first unit."""
    p = phase((level or "").strip().lower())
    return (p or phases()[0])["units"][0]


def public_unit(u: dict) -> dict:
    """What the API hands out: the unit rendered for the current learner, without its checkpoint
    tasks (those are revealed by the checkpoint endpoint)."""
    return {k: v for k, v in render_for_user(u).items() if k != "checkpoint"}


async def current_unit() -> dict:
    """The profile's unit, rendered for the current learner (the tutor, the checkpoint and the
    writing prompts all read it), or a sane fallback when the JSON moved on without the DB."""
    p = await profile_svc.get_profile()
    u = unit(p["unit_id"])
    if u is None:
        u = first_unit_of_level(p["level"])
        log.warning("profile unit_id %r not in curriculum; falling back to %s", p["unit_id"], u["id"])
    return render_for_user(u)


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
