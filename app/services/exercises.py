"""Turns an authored lesson into an interactive exercise sequence.

A lesson's JSON holds the *teaching* — the words, the rule, the examples. Reading that and tapping
Next is a textbook. What makes a course stick is doing something every few seconds, so each teaching
chunk is immediately followed by generated practice on exactly the material just presented:

    teach 6 greetings  ->  match them  ->  hear one, pick it  ->  say one out loud
    teach "verb second" ->  build the sentence from tiles    ->  the authored check

Generated rather than authored, because the exercises are mechanical while the explanations are the
part that needs a human. Distractors come from the same lesson, which is also the pedagogically
right place for them: confusable material, not random noise.

Deterministic for a given (lesson, seed), so a page refresh does not reshuffle mid-exercise, but a
second run through the lesson is a different order.
"""
from __future__ import annotations

import random
from typing import Any

# How much practice follows each teaching chunk. More than this and a lesson outstays its welcome.
MAX_MATCH_PAIRS = 5
LISTEN_PER_WORDS = 2
BUILD_PER_GRAMMAR = 2
MIN_BUILD_WORDS = 3
MAX_BUILD_WORDS = 9


def _clean(s: str) -> str:
    return " ".join(str(s or "").split())


def _words_of(sentence: str) -> list[str]:
    return [w for w in _clean(sentence).split(" ") if w]


def _pick(rng: random.Random, pool: list[str], exclude: str, n: int) -> list[str]:
    options = [p for p in dict.fromkeys(pool) if p != exclude]
    rng.shuffle(options)
    return options[:n]


def build(lesson: dict[str, Any], seed: int = 0) -> list[dict[str, Any]]:
    """The full sequence the Learn screen walks: teaching steps interleaved with practice."""
    rng = random.Random(f"{lesson.get('title')}:{seed}")
    steps = lesson.get("steps", [])

    # Everything sayable in this lesson, for distractors that are plausibly confusable.
    vocabulary = [i["de"] for s in steps for i in (s.get("items") or []) if s.get("type") == "words" and i.get("de")]
    sentences = [e["de"] for s in steps for e in (s.get("examples") or []) if e.get("de")]

    out: list[dict[str, Any]] = []
    for step in steps:
        kind = step.get("type")
        out.append({**step, "mode": "teach"})
        if kind == "words":
            out.extend(_practise_words(step, vocabulary, rng))
        elif kind == "grammar":
            out.extend(_practise_grammar(step, sentences, rng))
        # `check` and `sounds` already are what they are: a question, and a reference page.
    return out


def _practise_words(step: dict, vocabulary: list[str], rng: random.Random) -> list[dict]:
    items = [i for i in step.get("items", []) if i.get("de") and i.get("en")]
    if not items:
        return []
    out: list[dict] = []

    # 1. Match: the cheapest way to turn passive reading into recall.
    pairs = items[:MAX_MATCH_PAIRS]
    if len(pairs) >= 3:
        left, right = _unaligned(pairs, rng)
        out.append({"type": "match", "mode": "practise", "title": "Match them up",
                    "pairs": [{"de": p["de"], "en": p["en"]} for p in pairs],
                    "left": left, "right": right})

    # 2. Listen: audio only, choose the German. The one exercise that builds the ear.
    for item in _sample(items, LISTEN_PER_WORDS, rng):
        distractors = _pick(rng, vocabulary, item["de"], 2)
        if len(distractors) < 2:
            continue
        options = [item["de"], *distractors]
        rng.shuffle(options)
        out.append({"type": "listen", "mode": "practise", "title": "What do you hear?",
                    "audio": item["de"], "options": options, "answer": options.index(item["de"]),
                    "en": item["en"]})

    # 3. Say it: speaking is the whole point of the app, so it belongs in the lesson, not only in Talk.
    speakable = [i for i in items if 1 <= len(_words_of(i["de"])) <= 8]
    for item in _sample(speakable, 1, rng):
        out.append({"type": "speak", "mode": "practise", "title": "Say it out loud",
                    "de": item["de"], "en": item["en"]})
    return out


def _practise_grammar(step: dict, sentences: list[str], rng: random.Random) -> list[dict]:
    examples = [e for e in step.get("examples", []) if e.get("de") and e.get("en")]
    out: list[dict] = []
    usable = [e for e in examples if MIN_BUILD_WORDS <= len(_words_of(e["de"])) <= MAX_BUILD_WORDS]
    for ex in _sample(usable, BUILD_PER_GRAMMAR, rng):
        words = _words_of(ex["de"])
        # One decoy from another sentence, so word order is the thing being tested, not the word list.
        decoys = [w for s in sentences for w in _words_of(s) if w not in words]
        tiles = words + _pick(rng, decoys, "", 1)
        rng.shuffle(tiles)
        # The note disambiguates: two examples can share one English prompt ("What's your name?"
        # for both du and Sie), and then no answer is knowable from the prompt alone.
        out.append({"type": "build", "mode": "practise", "title": "Put it in order",
                    "en": ex["en"], "hint": ex.get("note"), "answer": words, "tiles": tiles})
    return out


def _unaligned(pairs: list[dict], rng: random.Random, attempts: int = 30) -> tuple[list[str], list[str]]:
    """Two shuffled columns with no row holding its own answer.

    Shuffling each side independently is not enough: with five pairs it lands on a fully aligned
    layout about once in a hundred and twenty, and then the exercise gives away every answer just by
    sitting there. Observed in the wild, hence the explicit derangement.
    """
    left = [p["de"] for p in pairs]
    right = [p["en"] for p in pairs]
    answer = {p["de"]: p["en"] for p in pairs}
    rng.shuffle(left)
    for _ in range(attempts):
        rng.shuffle(right)
        if not any(answer[l] == r for l, r in zip(left, right)):
            break
    return left, right


def _sample(items: list, n: int, rng: random.Random) -> list:
    if len(items) <= n:
        return list(items)
    return rng.sample(items, n)


def grade(exercise: dict, answer: Any) -> bool:
    """Server-side truth for an exercise. The client grades too, for instant feedback; this is what
    the progress counters trust."""
    kind = exercise.get("type")
    if kind in ("listen", "check"):
        return isinstance(answer, int) and answer == exercise.get("answer")
    if kind == "build":
        return [_clean(w) for w in (answer or [])] == list(exercise.get("answer") or [])
    if kind == "match":
        return bool(answer)
    if kind == "speak":
        return matches_spoken(exercise.get("de", ""), str(answer or ""))
    return False


def matches_spoken(expected: str, heard: str) -> bool:
    """Did he say the line? Judged generously on purpose.

    The transcriber mishears a beginner's accent constantly, and punishing that would teach him to
    stop speaking — the opposite of the point. Punctuation and case are ignored, and most of the
    words have to be there, not all of them.
    """
    strip = str.maketrans("", "", ".,!?;:—-–\"'„“")
    want = [w for w in expected.lower().translate(strip).split() if w]
    got = [w for w in heard.lower().translate(strip).split() if w]
    if not want:
        return False
    remaining = list(got)
    hit = 0
    for w in want:
        if w in remaining:
            remaining.remove(w)
            hit += 1
    return hit / len(want) >= 0.7
