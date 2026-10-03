#!/usr/bin/env python3
"""Generate German audio clips containing deliberate learner mistakes, for the STT pitfall test.

Synthesised speech is not a learner's accent, so this does not replace recording Ahmad's own voice
(see docs/STT-FINDINGS.md). What it does test, and test cleanly, is the thing we actually fear: given
audio that unambiguously contains wrong German, does the transcriber write down the wrong German or
quietly repair it? The words are unambiguous here, so any difference in the transcript is the engine
editing, not mishearing.

    .venv/bin/python scripts/make_stt_clips.py          # -> samples/*.m4a + *.txt sidecars
    .venv/bin/python scripts/stt_compare.py samples/
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# (slug, error category, sentence as a learner would say it wrong)
CLIPS: list[tuple[str, str, str]] = [
    ("01-aux-verb", "verb_conjugation", "Ich habe gestern in die Stadt gegangen."),
    ("02-case-mit", "case", "Ich fahre mit den Bus zur Arbeit."),
    ("03-gender", "gender", "Das Termin ist am Montag."),
    ("04-case-article", "case", "Ich habe ein Problem mit die Heizung."),
    ("05-word-order", "word_order", "Gestern ich habe viel gearbeitet."),
    ("06-subclause", "word_order", "Ich muss nach Hause gehen, weil ich bin müde."),
    ("07-fillers", "fillers", "Ich spreche nicht gut Deutsch, ähm, ich lerne noch."),
    ("08-english-word", "vocabulary", "Ich habe das Deployment gemacht, es war ein outage."),
    ("09-adj-ending", "adjective_ending", "Ich wohne in eine klein Wohnung in Amman."),
    ("10-negation", "negation", "Ich habe nicht Zeit heute Abend."),
    # Control: correct German. If an engine "finds" an error here, it is inventing them.
    ("11-control-correct", "none", "Ich arbeite als DevOps-Ingenieur für eine deutsche Firma."),
]

# Vary the voice so the result is not an artefact of one speaker.
VOICES = ["de-DE-SeraphinaMultilingualNeural", "de-DE-FlorianMultilingualNeural",
          "de-DE-KatjaNeural", "de-DE-ConradNeural"]


async def main() -> None:
    import edge_tts

    out = ROOT / "samples"
    out.mkdir(exist_ok=True)
    for i, (slug, category, text) in enumerate(CLIPS):
        voice = VOICES[i % len(VOICES)]
        mp3 = out / f"{slug}.mp3"
        # A slightly slow, conversational rate: closer to how a learner speaks than the default.
        await edge_tts.Communicate(text, voice, rate="-15%").save(str(mp3))
        (out / f"{slug}.txt").write_text(text + "\n", encoding="utf-8")
        (out / f"{slug}.category").write_text(category + "\n", encoding="utf-8")
        print(f"{mp3.name:<26} {voice:<36} {category:<18} {text}")
    print(f"\n{len(CLIPS)} clips in {out}\nNow: .venv/bin/python scripts/stt_compare.py samples/")


if __name__ == "__main__":
    asyncio.run(main())
