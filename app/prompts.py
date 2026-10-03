"""Prompt loader.

Every prompt lives in its own file under app/prompts/ as Markdown, so it can be tweaked
without touching code. Placeholders are `{{name}}`; `render` substitutes them and fails
loudly on a typo in either direction, because a silently-unfilled prompt produces a tutor
that quietly ignores the learner's profile.

    from .prompts import render
    system = render("tutor_talk", level="A1.2", unit_goals="...", ...)

Files are cached after first read; set RELOAD_PROMPTS=1 to re-read on every call while
you are iterating on wording.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache

from .config import settings

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


class PromptError(Exception):
    pass


@lru_cache(maxsize=64)
def _read(name: str) -> str:
    path = settings.prompts_dir / f"{name}.md"
    if not path.exists():
        raise PromptError(f"no prompt file at {path}")
    return path.read_text(encoding="utf-8")


def load(name: str) -> str:
    if os.environ.get("RELOAD_PROMPTS") == "1":
        _read.cache_clear()
    return _read(name)


def render(name: str, **values: object) -> str:
    """Substitute every {{placeholder}}. Raises on unknown or missing keys."""
    text = load(name)
    needed = set(_PLACEHOLDER.findall(text))
    given = set(values)
    if missing := needed - given:
        raise PromptError(f"prompt '{name}' needs {sorted(missing)}")
    if extra := given - needed:
        raise PromptError(f"prompt '{name}' has no placeholder for {sorted(extra)}")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), text)


def placeholders(name: str) -> set[str]:
    return set(_PLACEHOLDER.findall(load(name)))
