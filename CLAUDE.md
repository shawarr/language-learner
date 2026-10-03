# German tutor — working notes for agents

A personal German tutor PWA for one user (Ahmad: DevOps engineer in Amman, remote for a German
company, beginner, learning for daily life and a possible move to Germany, uses it on his phone).
Speaking is the primary mode; writing practice is required too.

## Ground rules

- **Free tiers only.** Gemini and Groq free tiers, edge-tts for speech. Never add a paid dependency,
  and keep the number of model calls per interaction down — the free limits are the real budget
  (see `docs/FOUNDATION.md` for the numbers).
- **Simple stack, maintainable by one person.** FastAPI + SQLite + vanilla JS, no build step, no
  framework, no bundler, no CDN. Ahmad knows Python, Docker, Kubernetes and vanilla JS; keep it at
  that level.
- **A solid app beats a feature pile.** Each layer works before the next one starts.
- **Mobile first, one-handed.** Every control thumb-reachable, dark mode, no hover-only affordance.
  iOS Safari and Android Chrome both matter.
- **API keys never reach the frontend.** They live in env vars, used server-side only.
- **Secrets never get committed.** `.env` is gitignored; `.env.example` carries the shape.
- **Prompts live in files**, one per file under `app/prompts/`, loaded via `app.prompts.render`.
  Never inline a prompt string in a service.
- **Never show the learner a cleaned-up version of what he said.** The raw transcript is the point
  (see the Whisper pitfall in `docs/STT-FINDINGS.md`).

## Layout

```
app/
  config.py        env-var settings, every model/voice swappable            [foundation]
  db.py            schema + aiosqlite helpers; MIGRATIONS for new columns   [foundation]
  auth.py          single-password cookie session                          [foundation]
  taxonomy.py      the canonical mistake categories                        [foundation]
  prompts.py       prompt loader ({{placeholder}} substitution)            [foundation]
  prompts/*.md     one prompt per file
  providers/       gemini, groq, fake; llm router, stt, tts                [foundation]
  routers/         FastAPI routers, registered in routers/__init__.py
  services/        the app logic (tutor, analyzer, srs, curriculum, ...)
  curriculum/      units.json
static/            the PWA: index.html, app.js, styles.css, sw.js, manifest
deploy/            nginx conf, deploy.sh, backup.sh                        [foundation]
docs/              FOUNDATION.md (what exists), TASKS.md (what to build)
tests/             pytest, offline (fake provider), no API keys needed
```

## Conventions

- Async everywhere. Never block the event loop; `edge-tts` and `httpx` are already async, and
  `ffmpeg` is invoked through `asyncio.create_subprocess_exec`.
- Routers are thin: parse, call a service, return. Logic lives in `app/services/`.
- Every `/api` route except `/api/health` and `/api/auth/login` depends on `auth.require_auth`.
- Schema changes go in `db.MIGRATIONS` as idempotent `ALTER TABLE`s. `CREATE TABLE IF NOT EXISTS`
  never adds a column to an existing table, and the live DB has real history in it.
- All LLM calls go through `app.providers.llm.llm` so rate limits, fallback and JSON repair are
  handled in one place. Ask for JSON with a schema (`complete_json`), never parse prose.
- Raise `ProviderError`/`LLMUnavailable` and let `main.py`'s handlers turn them into a
  `{"detail", "retryable"}` 503. Never swallow a provider failure into a fake tutor reply.
- Comments explain *why*, at the density of the existing files. No comment that restates the code.
- Tests must pass with no API keys and no network: `LLM_PRIMARY=fake:fake`.

## Commands

```bash
.venv/bin/python -m pytest -q          # the suite; must stay green
RELOAD_PROMPTS=1 .venv/bin/uvicorn app.main:app --reload   # iterate on prompts
bash deploy/deploy.sh                  # build + restart the container (server only)
```
