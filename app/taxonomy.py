"""The canonical mistake taxonomy.

Every part of the app that writes or reads `mistakes.category` uses this list: the analyzer
prompt, the tutor's per-turn corrections, the drill generator and the progress page. If the
categories drift apart, recurring mistakes stop aggregating and the drills target nothing.

Keep it short. A taxonomy with forty buckets never reaches a count of three in any of them.
"""
from __future__ import annotations

# slug -> what it covers, in the words used in the prompts and the UI
CATEGORIES: dict[str, str] = {
    # gender/article and case/preposition each describe one error from two angles, so the boundary
    # is drawn explicitly. Live testing had "das Termin" land in `article` and the same case slip
    # land in `case` once and `preposition` once — which splits one recurring mistake across two
    # rows and keeps either from ever looking recurring.
    "gender": "the noun's gender is wrong: der/die/das picked wrong, as in 'das Termin' for 'der Termin'",
    "case": "wrong case, whatever caused it — after a preposition, a verb, or in a bare phrase "
            "('mit den Bus' for 'mit dem Bus'). Use this, not 'preposition', when the preposition itself was right",
    "article": "an article is missing or should not be there, while its gender and case are right",
    "word_order": "verb position, time-manner-place order, subordinate clause order",
    "verb_conjugation": "wrong person, tense, auxiliary (haben/sein), or participle form",
    "preposition": "the wrong preposition word for the meaning (auf/an/in, nach/zu) — not the case after it",
    "plural": "wrong plural form of a noun",
    "adjective_ending": "wrong adjective ending after an article or on its own",
    "pronoun": "wrong personal, possessive or reflexive pronoun",
    "negation": "nicht vs kein, or negation in the wrong position",
    "vocabulary": "wrong or non-existent word, false friend, English word used instead",
    "separable_verb": "separable prefix left attached or dropped in the wrong place",
    "pronunciation": "a sound or stress error clear enough to hear in the transcript",
    "other": "anything that does not fit above",
}

CATEGORY_SLUGS: list[str] = list(CATEGORIES)


def is_valid(category: str) -> bool:
    return category in CATEGORIES


def normalize(category: str) -> str:
    """Map whatever the model produced onto a known slug; unknown values become 'other'."""
    c = (category or "").strip().lower().replace(" ", "_").replace("-", "_")
    return c if c in CATEGORIES else "other"


def describe_for_prompt() -> str:
    """The taxonomy as prompt text, so the model sees exactly the slugs the DB stores."""
    return "\n".join(f"- {slug}: {desc}" for slug, desc in CATEGORIES.items())
