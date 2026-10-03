"""C4 checkpoints — stub; `is_available` is the only piece other modules need before C4 lands."""
from __future__ import annotations


async def is_available(unit_id: str) -> bool:
    return False
