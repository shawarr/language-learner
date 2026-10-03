# Deutsch Tutor

A personal German tutor web app for one user: spoken conversation practice with a tutor that
remembers your level, your recurring mistakes and your vocabulary across sessions, plus writing
practice, targeted drills and spaced-repetition review. Mobile-first PWA, installable to the home
screen, free to run on free-tier model providers.

**Status: foundation and app layer built** — `docs/FOUNDATION.md` describes the server layer,
`docs/TASKS.md` the app-layer spec, `docs/DESIGN.md` the frontend spec, `docs/API.md` the endpoint
contract, and `docs/HANDOVER.md` what was built, what changed and what still needs a real phone.

- Talk (voice or text) with a tutor that remembers your level, recurring mistakes and due
  vocabulary; raw transcripts you can dispute; corrections as collapsible cards; replay and slow audio.
- Write with inline corrections and a one-level-up rewrite; Review with SM-2 spaced repetition and
  audio on every card; Drill built from your own mistakes; Progress with the CEFR path.
- A placement flow on first launch, a checkpoint at the end of each unit, and an analyzer that runs
  in the background every few turns — and listens to the recordings, because the transcriber
  quietly fixes endings.
- Installable PWA, offline-tolerant (the shell starts without network; recordings and ratings queue).

---

## Stack

| Piece | Choice | Why |
|---|---|---|
| Backend | FastAPI, async, SQLite in a mounted volume | one process, one file to back up |
| Frontend | vanilla-JS PWA, no build step | nothing to rebuild in a year's time |
| Conversation | Groq `openai/gpt-oss-120b` | ~1 s a turn on the free tier |
| Analyzer, grading | Gemini Flash, structured JSON output | spots recurring patterns Groq misses |
| Any other provider | one OpenAI-compatible class + a registry | swapping is a key and a model string, not code |
| Speech → text | Groq `whisper-large-v3` (Gemini audio as fallback) | free tier, 8 h/day |
| Text → speech | edge-tts, German neural voices | free, no key, no quota |
| Auth | one password → long-lived httpOnly cookie | single user, no accounts |
| Deploy | Docker + compose behind nginx | matches the rest of the box |

Every model, voice and provider is an env var. Nothing is hardcoded — see `.env.example`.

## Requirements

Docker and docker-compose, or Python 3.12+ for local development. ffmpeg is installed inside the
image (used to re-encode phone recordings for the Gemini transcription path).

## Getting the API keys

Both are free and need no credit card.

1. **Groq** — <https://console.groq.com/keys>. Sign in, *Create API Key*, copy it immediately (it is
   shown once). Free tier: 30 req/min and 1 000/day on the gpt-oss models, and 8 hours of Whisper
   audio per day. This is the conversation path and the transcriber.
2. **Gemini** — <https://aistudio.google.com/apikey>. Sign in, *Create API key*, pick or create a
   project. Used for the analyzer, grading and as the fallback. Your live quota is at
   <https://aistudio.google.com/rate-limit>.

Paste both into `.env`. They are only ever used server-side; the frontend never sees them.

> **Watch the Gemini per-model day limit.** It is per model and unpublished, and some newer models
> are tiny — `gemini-3.8-flash` allows **20 requests a day** on the free tier, which is why the
> defaults don't use it. `.venv/bin/python scripts/check_providers.py` shows which configured model
> is actually alive, and `--all` probes the other free Gemini models if you need a replacement.

**Not married to these two.** Every OpenAI-compatible endpoint works with the same code, so any
provider that is good and free drops in: set its key (`OPENROUTER_API_KEY`, `MISTRAL_API_KEY`,
`TOGETHER_API_KEY`, `CEREBRAS_API_KEY`, or `CUSTOM_LLM_BASE_URL` for anything else including a local
vLLM/Ollama) and point a tier at it, e.g. `LLM_PRIMARY=openrouter:some-model:free`.

## Environment variables

Copy `.env.example` to `.env` and fill it in. The ones that matter:

| Variable | Default | Notes |
|---|---|---|
| `APP_PASSWORD` | — | **required.** The only thing between the internet and your API quota. Make it long and random. |
| `SESSION_SECRET` | auto | Optional. Unset: generated once and stored in the DB. Set it to keep sessions alive across a DB restore. |
| `COOKIE_SECURE` | `1` | `0` only for local `http://` development. |
| `GEMINI_API_KEY` / `GROQ_API_KEY` | — | see above |
| `LLM_PRIMARY` | `groq:openai/gpt-oss-120b` | `provider:model`, the conversation path. Swap freely. |
| `LLM_FALLBACK` | `gemini:gemini-3.5-flash-lite` | used on a rate limit or an outage |
| `LLM_QUALITY` | `gemini:gemini-3.5-flash` | analyzer, placement, checkpoint grading |
| `LLM_FAST` | `groq:openai/gpt-oss-20b` | cheap calls (word translation, drill grading) |
| `STT_PROVIDER` | `groq` | `groq` (0.35 s) or `gemini` (~6 s); the other is the automatic fallback |
| `WHISPER_PROMPT` | *(empty)* | **leave empty.** A prompt in clean German makes Whisper fix your grammar — see `docs/STT-FINDINGS.md`. |
| `TTS_VOICE` | `de-DE-SeraphinaMultilingualNeural` | also Florian (m), Katja (f), Conrad (m), `de-AT-*`, `de-CH-*` |
| `TTS_RATE_SLOW` | `-30%` | the "slow" replay speed |
| `ANALYZE_EVERY_TURNS` | `8` | how often the analyzer runs inside a long session |
| `DATA_DIR` | `/data` | holds `tutor.db` and the TTS cache |

## Running locally

```bash
git clone git@github.com:shawarr/language-learner.git && cd language-learner
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # set APP_PASSWORD, COOKIE_SECURE=0, and your keys

DATA_DIR=./data .venv/bin/uvicorn app.main:app --reload --port 8000
# http://localhost:8000
```

Without any API keys, use the offline provider — every LLM call returns a valid dummy answer, so the
UI is fully navigable:

```bash
LLM_PRIMARY=fake:fake LLM_FALLBACK= DATA_DIR=./data APP_PASSWORD=dev COOKIE_SECURE=0 \
  .venv/bin/uvicorn app.main:app --reload --port 8000
```

Tests (offline, no keys needed):

```bash
.venv/bin/python -m pytest -q
```

Iterating on the tutor's wording — prompts live in `app/prompts/*.md` and `RELOAD_PROMPTS=1` re-reads
them on every request, so you can edit a prompt and send the next message without a restart:

```bash
RELOAD_PROMPTS=1 .venv/bin/uvicorn app.main:app --reload
```

## Deploying

On the server, as root:

```bash
cd /opt/language-learner
git pull
cp .env.example .env && $EDITOR .env        # first time only
bash deploy/deploy.sh                       # build, restart, wait for health
```

`deploy.sh` builds the image, recreates the container (bound to `127.0.0.1:9003`), chowns `data/` to
uid 1000 and blocks until `/api/health` answers, dumping the last 50 log lines if it doesn't.

First time, for the public hostname:

```bash
DOMAIN=german.shawar.xyz bash deploy/install-nginx.sh   # vhost + snippets + rate limits
certbot --nginx -d german.shawar.xyz                    # TLS
```

Logs and status:

```bash
docker compose logs -f --tail 100
docker compose ps
curl -s localhost:9003/api/health
```

> **The one trap on this server:** the container runs as uid 1000. If `data/` ends up root-owned,
> every write fails with `attempt to write a readonly database` while reads keep working — the app
> looks fine and silently saves nothing. `deploy.sh` fixes the ownership on every run; if you create
> the directory by hand, `chown -R 1000:1000 data`.

## Backing up the database

Everything the tutor remembers is in one SQLite file: `data/tutor.db`. The TTS cache in
`data/audio/` is disposable — it regenerates.

```bash
bash deploy/backup.sh          # -> backups/tutor-YYYYmmdd-HHMMSS.db.gz, keeps the last 30
```

It uses the SQLite backup API rather than `cp`, because the app runs in WAL mode: copying the `.db`
file while the app is writing can capture a torn database that's missing the most recent sessions.

Nightly cron:

```cron
17 3 * * * /opt/language-learner/deploy/backup.sh >> /var/log/tutor-backup.log 2>&1
```

Restore:

```bash
docker compose down
gunzip -c backups/tutor-20261003-031700.db.gz > data/tutor.db
rm -f data/tutor.db-wal data/tutor.db-shm      # stale WAL would fight the restored file
chown -R 1000:1000 data
docker compose up -d
```

Copy a backup off the box now and then — a gzipped DB is small enough to keep anywhere.

The restore path above is **tested, not assumed**: a backup was gunzipped into a throwaway
container on a spare port, which booted, logged in, reported all 13 tables and passed
`PRAGMA integrity_check`. Worth repeating occasionally — an untested backup is a guess:

```bash
# drill: restore the newest backup into a scratch container, leaving the live one alone
S=$(mktemp -d) && mkdir -p "$S/data"
gunzip -c "$(ls -1t backups/tutor-*.db.gz | head -1)" > "$S/data/tutor.db"
chown -R 1000:1000 "$S/data"
docker run --rm -d --name tutor-drill -p 127.0.0.1:9099:8000 -v "$S/data:/data" \
  -e DATA_DIR=/data -e APP_PASSWORD=drill -e COOKIE_SECURE=0 -e LLM_PRIMARY=fake:fake \
  german-tutor:latest
sleep 6 && curl -s localhost:9099/api/health && docker stop tutor-drill
```

## Project layout

```
app/
  config.py  db.py  auth.py  taxonomy.py  prompts.py   # foundation
  prompts/            one prompt per file, {{placeholders}}
  providers/          gemini, groq, fake; llm router, stt, tts
  routers/            FastAPI routers
  services/           app logic
  curriculum/         units.json (A1.1 → B1.2)
static/               the PWA
deploy/               nginx conf, deploy.sh, backup.sh
docs/                 FOUNDATION.md, TASKS.md, STT-FINDINGS.md
tests/                pytest, fully offline
```

`CLAUDE.md` holds the conventions for anyone (human or agent) working in the repo. `docs/` holds the
foundation contract, the app-layer build spec, the frontend design spec and the transcription
findings.

## Checking the providers

```bash
.venv/bin/python scripts/check_providers.py          # every configured model + STT + TTS
.venv/bin/python scripts/check_providers.py --all    # also probe the other free Gemini models
```

Run this first when the tutor feels slow or keeps falling back — it distinguishes "quota wall" from
"outage" and prints the actual quota from the error body.

## Ideas not built yet

Deliberately left out for now; revisit once the core is in daily use.

- A "that's not what I said" that re-transcribes with the other engine instead of discarding — the
  discard exists; a one-tap second opinion would cost one STT call.
- A 5-minute "daily" flow as a screen of its own: the Talk start card already shows what is due and
  the streak, but a guided review → scenario → drill loop would suit tired evenings better.
- Keeping the tutor's corrections (not only the analyzer's) in the mistake log — they overlap
  today, and double counting was worse than missing a few.

- Streaming the tutor's reply, and synthesising the first sentence while the rest is still being
  written, to cut the perceived turn latency.
- A 5-minute "daily" flow: two reviews, one scenario, one drill, done — better than an open chat
  window when you're tired after work.
- Pronunciation feedback (the transcript already hints at it, but real feedback needs phoneme-level
  scoring, which no free tier offers).
- Export of the vocabulary deck to Anki.
- Shadowing mode: hear a sentence, repeat it, compare.
- Multi-week retention stats per grammar point, not just per vocabulary item.
