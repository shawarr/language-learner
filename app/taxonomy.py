"""The canonical mistake taxonomy.

Every part of the app that writes or reads `mistakes.category` uses this list: the analyzer
prompt, the tutor's per-turn corrections, the drill generator and the progress page. If the
categories drift apart, recurring mistakes stop aggregating and the drills target nothing.

Keep it short. A taxonomy with forty buckets never reaches a count of three in any of them.
"""
from __future__ import annotations

# slug -> what it covers, in the words used in the prompts and the UI
CATEGORIES: dict[str, str] = {
    "gender": "wrong grammatical gender of a noun (der/die/das)",
    "case": "wrong case after a verb or preposition (nominative/accusative/dative/genitive)",
    "article": "missing, extra or wrong article or determiner ending",
    "word_order": "verb position, time-manner-place order, subordinate clause order",
    "verb_conjugation": "wrong person, tense, auxiliary (haben/sein), or participle form",
    "preposition": "wrong preposition for the meaning, or the wrong case governed by it",
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
