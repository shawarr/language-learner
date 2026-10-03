# Handover — the app layer

What was built on top of the server foundation, what changed in it, what could not be verified
without a server or a real key, and what deserves a careful look. `docs/API.md` is the contract
between the frontend and the backend; `docs/TASKS.md` is the spec this implements.

## How it was built

The work was split across parallel agents by file ownership, with one coordinator merging:
the PWA shell and every screen, the profile/mistake/curriculum/vocab base services and the API
contract came first; then three backend streams ran in isolated worktrees (talk + analyzer + voice
turn; curriculum content + placement + checkpoints; vocab/SRS + write + drills + progress). Each
stream kept the test suite green on its own and was merged without touching another stream's files.

_(Sections below are filled in as each stream lands.)_

## What exists

## Changes to foundation files

- `app/config.py`: three settings appended at the bottom (`CHECKPOINT_MIN_SESSIONS`,
  `NEW_CARDS_PER_REVIEW`, `DRILL_ITEMS`), env-backed like the others. Nothing above them changed.
- `app/routers/__init__.py`: the new routers registered (this file is the registry by design).
- `tests/conftest.py`: one fixture added (`fresh_db`) for service-level async tests.
- `.gitignore`: `.claude/` (agent worktrees).

## Not verifiable offline

## Worth reviewing
