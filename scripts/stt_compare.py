#!/usr/bin/env python3
"""Does the STT engine silently fix the learner's grammar?

Feed it German audio that contains deliberate mistakes and it prints what each engine
returned side by side, flagging the words that differ from a reference transcript.

    # one file, both engines
    .venv/bin/python scripts/stt_compare.py clip.m4a

    # with the reference text you actually said, to score mistake preservation
    .venv/bin/python scripts/stt_compare.py clip.m4a --expect "ich habe gestern in die stadt gegangen"

    # a whole directory of clips, with expectations from a sidecar .txt per clip
    .venv/bin/python scripts/stt_compare.py samples/

Needs GEMINI_API_KEY and GROQ_API_KEY in the environment (or .env, which is read if present).
Findings from the real run live in docs/STT-FINDINGS.md.
"""
from __future__ import annotations

import asyncio
import difflib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


load_dotenv(ROOT / ".env")

from app.providers.stt import normalize_mime, stt  # noqa: E402  (after dotenv)


def diff(expected: str, got: str) -> str:
    """Word-level diff: -was expected +what the engine produced."""
    e, g = expected.lower().split(), got.lower().split()
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=e, b=g).get_opcodes():
        if tag == "equal":
            continue
        if tag in ("replace", "delete"):
            out.append("-" + " ".join(e[i1:i2]))
        if tag in ("replace", "insert"):
            out.append("+" + " ".join(g[j1:j2]))
    return "  ".join(out) or "(identical)"


async def one(path: Path, expect: str | None) -> None:
    audio = path.read_bytes()
    ext, mime = normalize_mime(None, path.name)
    print(f"\n=== {path.name}  ({len(audio) / 1024:.0f} KB, sent as {mime}) ===")
    if expect:
        print(f"  said     : {expect}")
    results = await stt.transcribe_compare(audio, mime, path.name)
    for engine, text in results.items():
        print(f"  {engine:<8}: {text}")
        if expect and not text.startswith("ERROR:"):
            print(f"  {'':<8}  diff vs said: {diff(expect, text)}")


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    expect = None
    if "--expect" in sys.argv:
        expect = sys.argv[sys.argv.index("--expect") + 1]
    if not args:
        print(__doc__)
        sys.exit(1)

    target = Path(args[0])
    clips = sorted(p for p in target.iterdir() if p.suffix.lower() in
                   (".m4a", ".mp4", ".mp3", ".wav", ".webm", ".ogg", ".flac")) if target.is_dir() else [target]
    for clip in clips:
        sidecar = clip.with_suffix(".txt")
        await one(clip, expect or (sidecar.read_text().strip() if sidecar.exists() else None))

    print("\nWhichever engine keeps the mistakes wins. Put the verdict in docs/STT-FINDINGS.md")
    print("and set STT_PROVIDER in .env accordingly.")


if __name__ == "__main__":
    asyncio.run(main())
