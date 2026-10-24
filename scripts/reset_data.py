#!/usr/bin/env python3
"""Wipe every learner's data and the caches: a genuine clean start for both accounts.

Deletes the SQLite database (and its WAL/SHM files), the TTS audio cache and the stored turn
recordings under DATA_DIR. Accounts are recreated from .env + personas.json on the next boot, so
nothing here needs to be typed back in.

    .venv/bin/python scripts/reset_data.py            # asks for confirmation
    .venv/bin/python scripts/reset_data.py --yes      # for deploy scripts

On the server: stop the container first (docker compose down), run this with DATA_DIR=./data,
then docker compose up -d and chown -R 1000:1000 data.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402  (after sys.path)


def main() -> int:
    targets = [Path(str(settings.db_path) + suffix) for suffix in ("", "-wal", "-shm")]
    dirs = [settings.audio_dir]
    print("This deletes:")
    for t in targets:
        print(f"  {t}{'' if t.exists() else '  (absent)'}")
    for d in dirs:
        print(f"  {d}/  (TTS cache and stored recordings)")
    if "--yes" not in sys.argv:
        if input("Type RESET to continue: ").strip() != "RESET":
            print("aborted")
            return 1
    for t in targets:
        t.unlink(missing_ok=True)
    for d in dirs:
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    print("done. Start the app: accounts and empty profiles are seeded on boot.")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("DATA_DIR", str(ROOT / "data"))
    sys.exit(main())
