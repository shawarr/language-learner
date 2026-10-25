"""Turns an authored lesson into an interactive exercise sequence.

A lesson's JSON holds the *teaching* — the words, the rule, the examples. Reading that and tapping
Next is a textbook. What makes a course stick is doing something every few seconds, so each teaching
chunk is immediately followed by generated practice on exactly the material just presented:

    teach 6 greetings  ->  match them  ->  hear one, pick it  ->  say one out loud
    teach "verb second" ->  build the sentence from tiles    ->  the authored check
    teach "dem after mit" ->  fill the gap: mit ___ Bus (der / den / dem)

Generated rather than authored, because the exercises are mechanical while the explanations are the
part that needs a human. Distractors come from the same lesson, which is also the pedagogically
right place for them: confusable material, not random noise.

Deterministic for a given (lesson, seed), so a page refresh does not reshuffle mid-exercise, but a
second run through the lesson is a different order.
"""
from __future__ import annotations

import difflib
import re
import random
from typing import Any

# How much practice follows each teaching chunk. More than this and a lesson outstays its welcome.
MAX_MATCH_PAIRS = 5
LISTEN_PER_WORDS = 2
BUILD_PER_GRAMMAR = 2
GAP_PER_GRAMMAR = 1
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


def _is_list(s: str) -> bool:
    return "/" in s


def _norm(s: str) -> str:
    return "".join(ch for ch in _clean(s).lower() if ch.isalnum() or ch == " ")


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


_TWINS = ({"der", "die", "das", "den", "dem"}, {"am", "um", "im", "an"}, {"ein", "eine", "einen", "einem"},
          {"von", "vor"}, {"in", "im"})


def _confusable(rng: random.Random, target: str, pool: list[str], n: int, groups: list[set[str]] = ()) -> list[str]:
    """Distractors for a listening item that only a listening ear tells apart.

    Picking any other lesson item made the answer obvious ("eins" and "zehn" against a whole
    sentence). So the candidates are near-misses: the target with one word swapped for a similar
    word from the same lesson (Englisch -> Deutsch, Morgen -> Abend), plus the lesson's other lines,
    all ranked by how alike they look and how many words they have.
    """
    words = _words_of(target)
    tokens = list(dict.fromkeys(w.strip(".,!?") for item in pool for w in _words_of(item)))
    candidates = [c for c in dict.fromkeys(pool) if _norm(c) != _norm(target)]
    if len(words) >= 2:
        present = {w.strip(".,!?").lower() for w in words}
        # Never the first word: its capital letter is the sentence's, not the word's, so a swap there
        # produced "Arabisch komme aus Jordanien".
        for i, w in enumerate(words[1:], start=1):
            core = w.strip(".,!?")
            tail = w[len(core):] if w.startswith(core) else ""
            for t in tokens:
                if not t or t.lower() in present or t[:1].isupper() != core[:1].isupper() or "{" in t:
                    continue
                siblings = any(core.lower() in g and t.lower() in g for g in groups)
                # Articles and prepositions trade with their twins (der/die, am/um), nothing else.
                twin = any(core.lower() in g and t.lower() in g for g in _TWINS)
                if not (siblings or twin):
                    continue
                variant = " ".join(words[:i] + [t + tail] + words[i + 1:])
                if _norm(variant) != _norm(target) and _norm(variant) not in {_norm(c) for c in candidates}:
                    candidates.append(variant)

    head = (words[-1].strip(".,!?").lower() if words else "")

    def score(c: str) -> float:
        gap = abs(len(_words_of(c)) - len(words))
        cw = _words_of(c)
        sibling = bool(cw) and any(head in g and cw[-1].strip(".,!?").lower() in g for g in groups)
        return _sim(c, target) - 0.15 * gap + (0.4 if sibling else 0) + rng.random() * 0.05

    ranked = sorted(candidates, key=score, reverse=True)
    picked: list[str] = []
    for c in ranked:
        # Two distractors that differ only from each other would make the odd one out the answer.
        if all(_sim(c, p) < 0.97 for p in picked):
            picked.append(c)
        if len(picked) == n:
            break
    return picked


def build(lesson: dict[str, Any], seed: int = 0) -> list[dict[str, Any]]:
    """The full sequence the Learn screen walks: teaching steps interleaved with practice."""
    rng = random.Random(f"{lesson.get('title')}:{seed}")
    steps = lesson.get("steps", [])

    # Everything sayable in this lesson, for distractors that are plausibly confusable.
    vocabulary = [i["de"] for s in steps for i in (s.get("items") or [])
                  if s.get("type") == "words" and i.get("de") and not _is_list(i["de"])]
    sentences = [e["de"] for s in steps for e in (s.get("examples") or []) if e.get("de")]
    # Words taught side by side in one list are one class (the days, the numbers, the greetings):
    # the head word of each short item, which is what a listening distractor may swap.
    # Keyed by the frame too, so "Guten ___" swaps Morgen for Abend but never for "Hallo".
    frames: dict[tuple, set[str]] = {}
    for si, s in enumerate(steps):
        if s.get("type") != "words":
            continue
        for i in s.get("items") or []:
            ws = _words_of(i.get("de", ""))
            if 1 <= len(ws) <= 2:
                frames.setdefault((si, " ".join(ws[:-1]).lower()), set()).add(ws[-1].strip(".,!?").lower())
    groups = [g for g in frames.values() if len(g) > 1]

    out: list[dict[str, Any]] = []
    for step in steps:
        kind = step.get("type")
        out.append({**step, "mode": "teach"})
        if kind == "words":
            out.extend(_practise_words(step, vocabulary + sentences, rng, groups))
        elif kind == "grammar":
            out.extend(_practise_grammar(step, sentences, rng))
        # `check` and `sounds` already are what they are: a question, and a reference page. A `text`
        # is followed by its own authored checks, which test understanding rather than recall.
    return out


def _practise_words(step: dict, vocabulary: list[str], rng: random.Random, groups: list[set[str]] = ()) -> list[dict]:
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

    # 2. Listen: audio only, choose the German. The one exercise that builds the ear. A listed pair
    # ("der Student / die Studentin") is a reference line, not one thing anybody says.
    single = [i for i in items if not _is_list(i["de"])]
    for item in _sample(single, LISTEN_PER_WORDS, rng):
        distractors = _confusable(rng, item["de"], vocabulary, 2, groups)
        if len(distractors) < 2:
            continue
        options = [item["de"], *distractors]
        rng.shuffle(options)
        out.append({"type": "listen", "mode": "practise", "title": "What do you hear?",
                    "audio": item["de"], "options": options, "answer": options.index(item["de"]),
                    "en": item["en"]})

    # 3. Say it: speaking is the whole point of the app, so it belongs in the lesson, not only in Talk.
    speakable = [i for i in single if 1 <= len(_words_of(i["de"])) <= 8]
    for item in _sample(speakable, 1, rng):
        out.append({"type": "speak", "mode": "practise", "title": "Say it out loud",
                    "de": item["de"], "en": item["en"]})
    return out


def _practise_grammar(step: dict, sentences: list[str], rng: random.Random) -> list[dict]:
    examples = [e for e in step.get("examples", []) if e.get("de") and e.get("en")]
    out: list[dict] = []
    usable = [e for e in examples if MIN_BUILD_WORDS <= len(_words_of(e["de"])) <= MAX_BUILD_WORDS]
    builds = _sample(usable, BUILD_PER_GRAMMAR, rng)
    for ex in builds:
        words = _words_of(ex["de"])
        # One decoy from another sentence, so word order is the thing being tested, not the word list.
        decoys = [w for s in sentences for w in _words_of(s) if w not in words]
        tiles = words + _pick(rng, decoys, "", 1)
        rng.shuffle(tiles)
        # The note disambiguates: two examples can share one English prompt ("What's your name?"
        # for both du and Sie), and then no answer is knowable from the prompt alone.
        out.append({"type": "build", "mode": "practise", "title": "Put it in order",
                    "en": ex["en"], "hint": ex.get("note"), "answer": words, "tiles": tiles})
    # Building tests word order; the gap tests the form itself (den or dem, mich or mir, -en or -em),
    # which is what most grammar points are about. Prefer an example the tiles did not just show.
    rest = [e for e in examples if e not in builds] or examples
    gaps = [g for g in (_gap(e, rng) for e in rest) if g]
    gaps.sort(key=lambda g: -g.pop("_weight"))
    out.extend(gaps[:GAP_PER_GRAMMAR])
    return out


# Forms a learner picks between. A gap blanks one of these and offers its siblings, so the choice is
# always between real German words that differ in exactly the way the grammar step is about.
_FAMILIES = [
    ["der", "die", "das", "den", "dem", "des"],
    ["ein", "eine", "einen", "einem", "einer", "eines"],
    ["kein", "keine", "keinen", "keinem", "keiner"],
    *[[s, s + "e", s + "en", s + "em", s + "er"] for s in ("mein", "dein", "sein", "unser", "euer")],
    ["mich", "mir", "ich"], ["dich", "dir", "du"], ["ihn", "ihm", "er"], ["uns", "wir", "unser"],
    ["bin", "bist", "ist", "sind", "seid"], ["habe", "hast", "hat", "haben", "habt"],
    ["war", "warst", "waren"], ["hatte", "hattest", "hatten"],
    ["im", "am", "um", "zum", "zur", "beim", "vom"],
    ["als", "wenn", "wann", "ob"], ["dass", "weil", "obwohl", "damit"],
    ["deshalb", "trotzdem", "denn"], ["wurde", "wird", "worden", "werden"],
    ["dessen", "deren", "denen"],
]
# The genitive arrives at B1; before that "des" is noise, not a plausible mistake.
_GENITIVE = {"des", "eines"}
_FAMILY_OF = {w: fam for fam in _FAMILIES for w in fam}
# Which gap a grammar step gets when an example offers several: the rarer form wins, because an
# example only contains "dessen" or "obwohl" when that is what the step is teaching.
_ADVANCED = {w for fam in _FAMILIES if fam[0] in ("war", "hatte", "als", "dass", "deshalb", "wurde", "dessen") for w in fam}
_BASIC = {"ich", "du", "er", "wir", "bin", "bist", "ist", "sind", "seid", "habe", "hast", "hat", "haben", "habt"}
_ARTICLE_LIKE = {w for fam in _FAMILIES[:8] for w in fam}
_ENDINGS = ("en", "em", "er", "es", "e")


def _gap(example: dict, rng: random.Random) -> dict | None:
    words = _words_of(example["de"])
    if not 3 <= len(words) <= 14:
        return None
    candidates = []
    for i, raw in enumerate(words):
        core = raw.strip(".,!?;:„“\"'()")
        if not core or core != raw.rstrip(".,!?;:“\"')") or "{{" in core:
            continue
        low = core.lower()
        nxt = words[i + 1] if i + 1 < len(words) else ""
        prev = words[i - 1].lower() if i else ""
        # An adjective between an article and its noun: the ending is the whole point of A2.2.
        ending = next((e for e in _ENDINGS if low.endswith(e) and len(low) - len(e) >= 3), None)
        if ending and prev in _ARTICLE_LIKE and nxt[:1].isupper() and core[:1].islower():
            stem = core[: -len(ending)]
            options = [core] + [stem + e for e in _ENDINGS if e != ending]
            candidates.append((4, i, raw, core, options))
        elif low in _FAMILY_OF:
            # An article only counts in front of its noun (or adjective + noun): "Das ist gut" is a
            # pronoun, and "Der ist gut" would be right too.
            after = words[i + 2] if i + 2 < len(words) else ""
            if low in _ARTICLE_LIKE and not (nxt[:1].isupper() or (nxt[:1].islower() and after[:1].isupper())):
                continue
            options = [w for w in _FAMILY_OF[low] if w != low and (low in _GENITIVE or w not in _GENITIVE)]
            if core[:1].isupper():
                options = [w[:1].upper() + w[1:] for w in options]
            weight = 3 if low in _ADVANCED else 1 if low in _BASIC else 2
            candidates.append((weight, i, raw, core, [core] + options))
    if not candidates:
        return None
    weight, i, raw, core, options = max(candidates, key=lambda c: (c[0], rng.random()))
    picked = [core] + rng.sample(options[1:], min(2, len(options) - 1))
    if len(picked) < 3:
        return None
    rng.shuffle(picked)
    tail = raw[len(core):]
    return {"type": "gap", "mode": "practise", "title": "Fill the gap", "_weight": weight,
            "before": " ".join(words[:i]), "after": (tail + " " + " ".join(words[i + 1:])).strip(),
            "options": picked, "answer": picked.index(core), "de": example["de"], "en": example["en"]}


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
    if kind in ("listen", "check", "gap"):
        return isinstance(answer, int) and answer == exercise.get("answer")
    if kind == "build":
        return [_clean(w) for w in (answer or [])] == list(exercise.get("answer") or [])
    if kind == "match":
        return bool(answer)
    if kind == "speak":
        return matches_spoken(exercise.get("de", ""), str(answer or ""))
    return False


_ONES = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf",
         "zwölf", "dreizehn", "vierzehn", "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn"]
_TENS = ["", "", "zwanzig", "dreißig", "vierzig", "fünfzig", "sechzig", "siebzig", "achtzig", "neunzig"]


def german_number(n: int) -> str:
    """0..999999 as one German word: 21 -> einundzwanzig, 101 -> hunderteins, 2500 -> zweitausendfünfhundert."""
    if n < 20:
        return _ONES[n]
    if n < 100:
        unit = n % 10
        return (("ein" if unit == 1 else _ONES[unit]) + "und" if unit else "") + _TENS[n // 10]
    if n < 1000:
        head = "" if n // 100 == 1 else _ONES[n // 100]
        return head + "hundert" + (german_number(n % 100) if n % 100 else "")
    k = n // 1000
    head = "" if k == 1 else german_number(k).removesuffix("s") if german_number(k).endswith("eins") else german_number(k)
    return head + "tausend" + (german_number(n % 1000) if n % 1000 else "")


def spoken_words(text: str) -> list[str]:
    """Words for comparing what was said: lower case, no punctuation, ß as ss, numbers as words.

    Whisper writes a spoken number as digits ("fünf" -> "5", "drei Uhr" -> "3 Uhr"), so digits
    become German words before anything is compared; "eins" and "ein" count as one word."""
    t = text.lower().replace("ß", "ss")
    t = re.sub(r"(\d)[:.](\d)", r"\1 \2", t)            # 14:30, 3.20 -> two numbers
    t = re.sub(r"[^\w\s]", " ", t)
    out: list[str] = []
    for w in t.split():
        if w.isdigit() and len(w) <= 6:
            w = german_number(int(w)).replace("ß", "ss")
        out.append("ein" if w == "eins" else w)
    return out


def matches_spoken(expected: str, heard: str) -> bool:
    """Did he say the line? Judged generously on purpose.

    The transcriber mishears a beginner's accent constantly, and punishing that would teach him to
    stop speaking — the opposite of the point. Punctuation, case and how a number is written are
    ignored, and most of the words have to be there, not all of them.
    """
    want, got = spoken_words(expected), spoken_words(heard)
    if not want:
        return False
    remaining = list(got)
    hit = 0
    for w in want:
        if w in remaining:
            remaining.remove(w)
            hit += 1
    return hit / len(want) >= 0.7
