#!/usr/bin/env python3
"""Generate the PWA icons as flat PNGs with nothing but the standard library.

A "DE" mark in a 5x7 block font on the accent colour. No font download, no Pillow, no
external asset: the CSP forbids anything external and the Dockerfile copies static/ as is.

    .venv/bin/python scripts/make_icons.py      # writes static/icons/*.png
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "icons"

BG = (0x3B, 0x6C, 0xF6)   # accent blue, full-bleed so Android's maskable crop keeps a solid edge
FG = (0xFF, 0xFF, 0xFF)

GLYPHS = {
    "D": ["XXXX.", "X...X", "X...X", "X...X", "X...X", "X...X", "XXXX."],
    "E": ["XXXXX", "X....", "X....", "XXXX.", "X....", "X....", "XXXXX"],
}


def _png(width: int, height: int, rows: list[list[tuple[int, int, int]]]) -> bytes:
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def render(size: int) -> bytes:
    text = "DE"
    cols = 5 * len(text) + (len(text) - 1)          # one blank column between letters
    cell = size * 0.62 / cols                        # the mark covers ~62% of the width
    x0 = (size - cols * cell) / 2
    y0 = (size - 7 * cell) / 2
    rows = []
    for y in range(size):
        row = []
        gy = int((y - y0) // cell)
        for x in range(size):
            gx = int((x - x0) // cell)
            on = False
            if 0 <= gy < 7 and 0 <= gx < cols and gx % 6 != 5:
                on = GLYPHS[text[gx // 6]][gy][gx % 6] == "X"
            row.append(FG if on else BG)
        rows.append(row)
    return _png(size, size, rows)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, size in (("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)):
        (OUT / name).write_bytes(render(size))
        print(f"wrote {OUT / name} ({size}px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
