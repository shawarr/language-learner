#!/usr/bin/env python3
"""Summarise the clips recorded through the in-app transcription lab.

The lab is the `compare` mode of POST /api/voice/transcribe: it saves each recording plus both
engines' transcripts into DATA_DIR/stt-lab/. Record the sentences from docs/STT-FINDINGS.md §2 in
your own voice from the phone, typing what you meant to say into the "what you actually said" box,
then run this to see which engine kept your mistakes.

    .venv/bin/python scripts/stt_lab_report.py                 # DATA_DIR/stt-lab
    .venv/bin/python scripts/stt_lab_report.py path/to/stt-lab
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def words(s: str) -> list[str]:
    return re.sub(r"[^\wäöüßÄÖÜ ]", "", s.lower()).split()


def diff(said: str, got: str) -> str:
    a, b = words(said), words(got)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            out.append("-" + " ".join(a[i1:i2]))
        if tag in ("replace", "insert"):
            out.append("+" + " ".join(b[j1:j2]))
    return "  ".join(out) or "IDENTICAL"


def main() -> None:
    lab = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "stt-lab"
    samples = sorted(lab.glob("*.json"))
    if not samples:
        print(f"no samples in {lab}\n"
              "Record some: open the app, use the compare/lab recorder, and type what you said.")
        sys.exit(1)

    scores = {"groq": [0, 0], "gemini": [0, 0]}  # [verbatim, total]
    for f in samples:
        d = json.loads(f.read_text(encoding="utf-8"))
        said = (d.get("said") or "").strip()
        print(f"\n### {f.stem}   ({d.get('mime', '?')})")
        if not said:
            print("  (no reference text typed — transcripts only)")
        else:
            print(f"  said    : {said}")
        for engine in ("groq", "gemini"):
            got = d.get(engine, "")
            if not got:
                continue
            print(f"  {engine:<8}: {got}")
            if said and not got.startswith("ERROR:"):
                verdict = diff(said, got)
                print(f"  {'':<8}  {verdict}")
                scores[engine][1] += 1
                scores[engine][0] += verdict == "IDENTICAL"

    print("\n==== mistakes preserved exactly ====")
    for engine, (ok, total) in scores.items():
        if total:
            print(f"  {engine:<8} {ok}/{total}")
    print("\nA diff like '-den +dem' is the engine fixing your grammar — that is the thing to count.\n"
          "Put the outcome in docs/STT-FINDINGS.md §3 and set STT_PROVIDER accordingly.")


if __name__ == "__main__":
    main()
