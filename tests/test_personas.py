"""M4: one curriculum, two learners. The JSON names nobody; rendering makes it read as written for
whoever is logged in, and a scenario built on Ahmad's job becomes a student's version for Maryan."""
from __future__ import annotations

import copy
import json
import re

import pytest

from app.config import settings
from app.services import curriculum, lessons, profile
from tests.conftest import as_user

PERSONA = {"ahmad": curriculum.persona_for({"username": "ahmad"}),
           "maryan": curriculum.persona_for({"username": "maryan"})}
WORK_SCENARIO = "a1.1-3-standup"


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


def assert_rendered(tree, where: str) -> None:
    """Nothing the learner or the tutor sees may still hold a placeholder or a variants block."""
    leftover = [s for s in _strings(tree) if "{{" in s or "}}" in s]
    assert not leftover, f"{where}: unrendered placeholder in {leftover[0]!r}"
    assert "variants" not in set(_keys(tree)), f"{where}: a variants block leaked"


def _variants():
    for u in curriculum.all_units():
        for sc in u["scenarios"]:
            if "variants" in sc:
                yield sc["id"], "scenario", sc
        for task in ("speaking", "writing"):
            if "variants" in u["checkpoint"][task]:
                yield f"{u['id']} checkpoint.{task}", "task", u["checkpoint"][task]


# -- rendering ------------------------------------------------------------------------------------
def test_placeholders_render_for_each_learner():
    text = "{{name}}: {{He}} says {{he}} met {{him}} and {{his}} friend by {{himself}}. {{work}} / {{role_de}} / {{city}}"
    ahmad, maryan = PERSONA["ahmad"], PERSONA["maryan"]
    assert curriculum.render_text(text, ahmad) == (
        f"Ahmad: He says he met him and his friend by himself. {ahmad['work']} / {ahmad['role_de']} / Amman")
    assert curriculum.render_text(text, maryan) == (
        f"Maryan: She says she met her and her friend by herself. {maryan['work']} / {maryan['role_de']} / Amman")
    assert maryan["role_de"].endswith("in"), "her role is the feminine form: 'Ich bin {{role_de}}.' must read right"
    # A capitalised token capitalises the value, so {{Work}} can start a sentence.
    assert curriculum.render_text("{{Work}}.", maryan) == maryan["work"][:1].upper() + maryan["work"][1:] + "."


def test_an_account_without_a_persona_keeps_its_own_name_and_no_one_renders_with_braces():
    zoe = curriculum.persona_for({"username": "zoe", "name": "Zoe", "gender": "f"})
    assert curriculum.render_text("{{name}} and {{his}} bag", zoe) == "Zoe and her bag"
    # No current user at all (a script): flat but complete, and the generic text is used.
    neutral = curriculum.render_for_user(curriculum.load(), curriculum.NEUTRAL_PERSONA)
    assert_rendered(neutral, "neutral persona")


def test_rendering_is_a_copy_and_leaves_the_raw_tree_alone():
    before = copy.deepcopy(curriculum.load())
    curriculum.render_for_user(curriculum.load(), PERSONA["maryan"])
    assert curriculum.load() == before
    raw_setup = next(sc["setup"] for u in curriculum.all_units() for sc in u["scenarios"] if sc["id"] == WORK_SCENARIO)
    assert "{{name}}" in raw_setup


@pytest.mark.parametrize("username", ["ahmad", "maryan"])
async def test_nothing_handed_out_keeps_a_placeholder(fresh_db, username):
    await as_user(username)
    name = PERSONA[username]["name"]
    seen_name = False
    for u in curriculum.all_units():
        pub = curriculum.public_unit(u)
        assert_rendered(pub, f"public_unit {u['id']}")
        assert "checkpoint" not in pub
        scenarios = curriculum.scenarios_for(u["id"])
        assert_rendered(scenarios, f"scenarios_for {u['id']}")
        seen_name = seen_name or any(name in sc["setup"] for sc in scenarios)
        for sc in u["scenarios"]:
            found_unit, found = curriculum.scenario(sc["id"])
            assert_rendered(found_unit, f"scenario {sc['id']} (unit)")
            assert_rendered(found, f"scenario {sc['id']}")
            assert {"id", "title", "setup", "goal"} <= set(found) <= {"id", "title", "setup", "goal", "brief", "words"}
        await profile.update_profile(unit_id=u["id"])
        assert_rendered(await curriculum.current_unit(), f"current_unit {u['id']}")
        cur = await curriculum.current()
        assert_rendered(cur, f"current() at {u['id']}")
        assert cur["unit"]["id"] == u["id"]
    assert seen_name, f"{name} never appears in a scenario setup"
    for unit_id, lesson in lessons.load().items():
        if isinstance(lesson, dict):
            assert_rendered(curriculum.lesson_for_user(lesson), f"lesson {unit_id}")


# -- variants -------------------------------------------------------------------------------------
async def test_maryan_gets_the_student_version_of_a_work_scenario_and_ahmad_the_original(fresh_db):
    raw = next(sc for u in curriculum.all_units() for sc in u["scenarios"] if sc["id"] == WORK_SCENARIO)
    student = raw["variants"]["student"]

    _, sc = curriculum.scenario(WORK_SCENARIO)
    assert sc["title"] == raw["title"] == "Das Daily Standup"
    assert "Ahmad" in sc["setup"] and "standup" in sc["setup"]

    await as_user("maryan")
    _, sc = curriculum.scenario(WORK_SCENARIO)
    assert sc["id"] == WORK_SCENARIO, "the id stays, so stored sessions still resolve"
    assert sc["title"] == student["title"] != raw["title"]
    assert sc["setup"] == curriculum.render_text(student["setup"], PERSONA["maryan"])
    assert "Maryan" in sc["setup"] and "standup" not in sc["setup"].lower() and " she " in sc["setup"]
    assert sc in curriculum.scenarios_for("a1.1-3")
    # A scenario without a variant is the shared text, rendered with her name.
    _, plain = curriculum.scenario("a1.1-1-nachbarin")
    assert "Maryan's new neighbour" in plain["setup"] and " her " in plain["setup"]


async def test_checkpoint_task_variants_replace_only_what_they_name(fresh_db):
    raw = curriculum.unit("a1.1-1")["checkpoint"]
    await profile.update_profile(unit_id="a1.1-1")
    ahmad = (await curriculum.current_unit())["checkpoint"]
    assert ahmad["speaking"]["prompt"] == raw["speaking"]["prompt"]

    await as_user("maryan")
    await profile.update_profile(unit_id="a1.1-1")
    maryan = (await curriculum.current_unit())["checkpoint"]
    assert maryan["speaking"]["prompt"] == raw["speaking"]["variants"]["student"]["prompt"]
    assert maryan["speaking"]["hint"] == raw["speaking"]["variants"]["student"]["hint"]
    # The writing variant names no hint, so the default hint and the word range stay.
    assert maryan["writing"]["prompt"] == raw["writing"]["variants"]["student"]["prompt"] != raw["writing"]["prompt"]
    assert maryan["writing"]["hint"] == raw["writing"]["hint"]
    assert (maryan["writing"]["words_min"], maryan["writing"]["words_max"]) == (raw["writing"]["words_min"], raw["writing"]["words_max"])


def test_every_variant_is_complete_and_written_like_its_default():
    found = list(_variants())
    scenario_variants = [v for v in found if v[1] == "scenario"]
    assert len(scenario_variants) >= 25 and len(found) - len(scenario_variants) >= 20
    curriculum.validate(curriculum.load())
    for where, kind, owner in found:
        assert set(owner["variants"]) == {"student"}, where
        v = owner["variants"]["student"]
        if kind == "scenario":
            assert {"title", "setup", "goal"} <= set(v) <= {"title", "setup", "goal", "brief", "words"}, where
            assert v["setup"].startswith("You are "), where
            assert "{{name}}" in v["setup"] or "{{he}}" in v["setup"].lower(), f"{where}: the setup never names the learner"
        else:
            assert v["prompt"].strip() and set(v) <= {"prompt", "hint"}, where


def test_every_unit_with_a_job_scenario_still_reads_for_a_student():
    """The units that are about Ahmad's job end to end must not hand Maryan a standup or a pipeline."""
    maryan = PERSONA["maryan"]
    job_words = re.compile(r"standup|scrum|pull request|deploy|pipeline|postmortem|kubernetes|serverless|on-call|"
                           r"(your|her|'s) manager|code review", re.I)
    for u in curriculum.all_units():
        r = curriculum.render_for_user(u, maryan)
        for sc in r["scenarios"]:
            assert not job_words.search(sc["setup"] + " " + sc["goal"]), f"{sc['id']}: {sc['setup']}"
        for task in ("speaking", "writing"):
            assert not job_words.search(r["checkpoint"][task]["prompt"]), f"{u['id']} {task}"


# -- the content never names anyone ---------------------------------------------------------------
def test_the_content_files_name_no_learner():
    with open(settings.base_dir / "curriculum" / "personas.json", encoding="utf-8") as f:
        names = {p["name"] for p in json.load(f).values()} | {"Ahmad", "Maryan"}
    for filename in ("units.json", "lessons.json"):
        text = (settings.base_dir / "curriculum" / filename).read_text(encoding="utf-8")
        for name in names:
            assert name not in text, f"{filename} says {name!r}: use {{{{name}}}}"


def test_learner_pronouns_in_scenario_text_are_placeholders():
    """A bare he/his in a setup is how a learner gets misgendered; tutor roles are addressed as 'you'."""
    bare = re.compile(r"(?<!\{\{)\b(he|him|his|himself|she|her|herself)\b(?!\}\})", re.I)
    for where, text in ((sc["id"], f"{sc['setup']} {sc['goal']}") for u in curriculum.all_units() for sc in u["scenarios"]):
        assert not bare.search(text), f"{where}: {bare.search(text).group(0)!r} in {text!r}"
    for where, kind, owner in _variants():
        if kind == "scenario":
            v = owner["variants"]["student"]
            assert not bare.search(f"{v['setup']} {v['goal']}"), where


async def test_lessons_render_with_the_learners_name_and_role(fresh_db):
    raw = lessons.load()["a1.1-1"]
    ahmad = json.dumps(curriculum.lesson_for_user(raw), ensure_ascii=False)
    assert "Ich bin Ahmad." in ahmad and "Ich bin DevOps-Ingenieur." in ahmad
    await as_user("maryan")
    maryan = json.dumps(curriculum.lesson_for_user(raw), ensure_ascii=False)
    assert "Ich bin Maryan." in maryan and "Ich heiße Maryan." in maryan and "Ich bin Maschinenbau-Studentin." in maryan
    assert "Ahmad" not in maryan and "DevOps" not in maryan
    assert "{{name}}" in json.dumps(lessons.load()["a1.1-1"]), "the cached raw lesson is untouched"


# -- the validator --------------------------------------------------------------------------------
def _tree_with(mutate) -> dict:
    tree = copy.deepcopy(curriculum.load())
    mutate(tree["phases"][0]["units"][0])
    return tree


def test_validator_rejects_an_unknown_placeholder():
    def typo(u):
        u["scenarios"][0]["setup"] = "You are Frau Keller, {{nmae}}'s new neighbour."
    with pytest.raises(curriculum.CurriculumError, match="unknown placeholder"):
        curriculum.validate(_tree_with(typo))

    def in_a_variant(u):
        u["scenarios"][0]["variants"] = {"student": {"title": "T", "setup": "You are {{job}}.", "goal": "G"}}
    with pytest.raises(curriculum.CurriculumError, match="unknown placeholder"):
        curriculum.validate(_tree_with(in_a_variant))


def test_validator_rejects_an_incomplete_or_unknown_variant():
    def no_goal(u):
        u["scenarios"][0]["variants"] = {"student": {"title": "T", "setup": "You are someone."}}
    with pytest.raises(curriculum.CurriculumError, match="variant student needs goal"):
        curriculum.validate(_tree_with(no_goal))

    def unknown_kind(u):
        u["scenarios"][0]["variants"] = {"pilot": {"title": "T", "setup": "You are someone.", "goal": "G"}}
    with pytest.raises(curriculum.CurriculumError, match="unknown variant kind"):
        curriculum.validate(_tree_with(unknown_kind))

    def extra_key(u):
        u["checkpoint"]["writing"]["variants"] = {"student": {"prompt": "P", "words_max": 10}}
    with pytest.raises(curriculum.CurriculumError, match="unexpected keys"):
        curriculum.validate(_tree_with(extra_key))


async def test_job_only_units_read_as_student_life_for_maryan(fresh_db):
    """Ten units are about the engineer's job end to end; their title and goals reach the tutor's
    prompt, so the student sees her own version, with the same grammar points."""
    from app.services import curriculum
    from tests.conftest import as_user

    raw = curriculum.unit("a1.2-1")
    ahmad = curriculum.public_unit(raw)
    await as_user("maryan")
    maryan = curriculum.public_unit(raw)
    assert "code review" in " ".join(ahmad["can_do"]) and "code review" not in " ".join(maryan["can_do"])
    assert maryan["title"] != ahmad["title"] and "variants" not in maryan
    assert len(maryan["grammar"]) == len(ahmad["grammar"])
    assert "Server" not in " ".join(maryan["grammar"])


def test_unit_variant_must_keep_every_grammar_point():
    import copy

    import pytest

    from app.services import curriculum

    data = copy.deepcopy(curriculum.load())
    unit = data["phases"][0]["units"][0]
    unit["variants"] = {"student": {"title": "X", "grammar": unit["grammar"][:-1]}}
    with pytest.raises(curriculum.CurriculumError, match="grammar"):
        curriculum.validate(data)
    unit["variants"] = {"student": {"title": "X", "colour": "red"}}
    with pytest.raises(curriculum.CurriculumError, match="unexpected"):
        curriculum.validate(data)
