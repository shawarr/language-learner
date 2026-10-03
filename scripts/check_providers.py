#!/usr/bin/env python3
"""Is every model this app is configured to use actually reachable right now?

Gemini's free per-day quota is **per model** and is published nowhere: some of the newest models
allow as few as 20 requests a day (gemini-3.8-flash, confirmed from a 429 body). When the tutor
suddenly feels slow or keeps falling back, run this first — it says which configured model is
alive, which is quota-walled, and what the wall actually is.

    .venv/bin/python scripts/check_providers.py          # the configured models
    .venv/bin/python scripts/check_providers.py --all    # plus the other free Gemini models

Costs one tiny request per model, so it eats a little of the quota it is measuring. Don't loop it.
"""
from __future__ import annotations

import asyncio
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
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


load_dotenv(ROOT / ".env")
# .env points DATA_DIR at the container's /data, which does not exist on the host. The health
# check only needs a throwaway TTS cache, so give it one rather than requiring a writable /data.
if not os.access(os.environ.get("DATA_DIR", "/data"), os.W_OK):
    os.environ["DATA_DIR"] = str(ROOT / ".cache-probe")

from app.config import settings  # noqa: E402
from app.providers.base import LLMRequest, Message, ProviderError  # noqa: E402
from app.providers.llm import llm  # noqa: E402

OTHER_GEMINI = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash",
                "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-2.5-flash",
                "gemini-2.5-flash-lite"]

# Not a tiny budget: Gemini spends output tokens on thinking before it writes anything, so a
# 16-token probe comes back empty with finishReason=MAX_TOKENS and looks like a failure.
PROBE = LLMRequest(system="Antworte mit einem Wort.", messages=[Message("user", "Sag Hallo")], max_tokens=64)


async def probe(spec: str, role: str) -> None:
    provider, _, model = spec.partition(":")
    p = {"gemini": llm.gemini, "groq": llm.groq, "fake": llm.fake}.get(provider)
    if p is None:
        print(f"  {role:<10} {spec:<34} UNKNOWN PROVIDER")
        return
    import time
    st = time.time()
    try:
        await p.complete(model, PROBE)
        print(f"  {role:<10} {spec:<34} ok      {time.time() - st:.1f}s")
    except ProviderError as e:
        print(f"  {role:<10} {spec:<34} FAIL    {e}")


async def main() -> None:
    print(f"keys: gemini={'set' if settings.gemini_api_key else 'MISSING'} "
          f"groq={'set' if settings.groq_api_key else 'MISSING'}\n")
    print("configured models:")
    for role, spec in (("primary", settings.llm_primary), ("fallback", settings.llm_fallback),
                       ("quality", settings.llm_quality), ("fast", settings.llm_fast)):
        if spec:
            await probe(spec, role)

    print("\nspeech:")
    clip = ROOT / "samples" / "11-control-correct.mp3"
    if clip.exists():
        try:
            t = await llm.groq.transcribe(settings.groq_stt_model, clip.read_bytes(), "c.mp3", "audio/mpeg")
            print(f"  stt        groq:{settings.groq_stt_model:<29} ok      {t[:48]!r}")
        except ProviderError as e:
            print(f"  stt        groq:{settings.groq_stt_model:<29} FAIL    {e}")
    else:
        print("  stt        (run scripts/make_stt_clips.py first to probe transcription)")
    try:
        from app.providers import tts
        path = await tts.synthesize("Hallo, das ist ein Test.", "normal")
        print(f"  tts        {settings.tts_provider}:{settings.tts_voice[:28]:<28} ok      "
              f"{path.stat().st_size // 1024} KB")
    except ProviderError as e:
        print(f"  tts        {settings.tts_provider:<34} FAIL    {e}")

    if "--all" in sys.argv:
        print("\nother free gemini models (for picking a replacement):")
        for m in OTHER_GEMINI:
            await probe(f"gemini:{m}", "")
            await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
