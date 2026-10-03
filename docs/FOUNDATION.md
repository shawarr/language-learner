# The foundation you are building on

Everything in this file already exists, is tested (`pytest -q`, 26 tests green) and has been
verified running in Docker on the server. Treat it as the given: use these APIs, don't rebuild
them, and don't change their shape without saying so in your handover notes.

---

## 1. Provider research (October 2026) — why these models

Checked against the live Groq and Gemini docs, not from memory.

**Groq free tier.** `llama-3.1-8b-instant` and `llama-3.3-70b-versatile` left the free and
Developer tiers on 2026-08-16 and are enterprise-only now — the brief's "Groq Llama as fallback"
is no longer possible. Groq's own named replacements are `openai/gpt-oss-20b` and
`openai/gpt-oss-120b`. Free-tier limits: **30 RPM, 1 000 RPD, 8 000 TPM, 200 000 TPD** for the
gpt-oss models. Whisper: **20 RPM, 2 000 RPD, 7 200 audio-seconds/hour, 28 800 audio-seconds/day**
(= 8 hours of speech a day, far more than one learner needs). Upload cap 25 MB on free tier.

**Gemini free tier.** Google no longer publishes fixed free-tier numbers per model (they appear in
AI Studio per project and change without notice); the figures seen in the wild are ~10 RPM /
250 000 TPM / 1 500 RPD for Flash and ~15 RPM / 1 000 RPD for Flash-Lite. Free of charge on the
pricing page: `gemini-3.8-flash`, `gemini-3.7-flash`, `gemini-3.6-flash`, `gemini-3.5-flash`,
`gemini-3.5-flash-lite`, `gemini-3.1-flash-lite`, the TTS models and `gemini-3.5-transcribe`.

### Measured on the server with the real keys, 2026-10-03

Numbers, not guesses. Identical prompt and JSON schema (an A1 correction task) through both providers:

| | `groq:openai/gpt-oss-120b` | `gemini:gemini-3.8-flash` |
|---|---|---|
| Latency, JSON turn | **1.0 s** (4 runs: 1.1 / 1.0 / 1.0 / 0.8) | 2.1 – 3.2 s |
| `enum` adherence in the schema | all slugs valid | all slugs valid |
| German correction quality | correct on gender, case, aux verb, word order | same |
| Reliability | no failures observed | **503 "high demand" on 3 of 5 turns**, then 429 after 4 rapid calls |
| Free limits | 30 RPM / 1 000 RPD | ~10 RPM / ~1 500 RPD |

Both models handle A1–B1 German correction correctly, so **latency and reliability decide the
conversation path**, and there Groq wins outright. Gemini's 503s are genuine upstream capacity
("This model is currently experiencing high demand"), reproduced with a minimal request body — not
something a different request shape avoids.

**Hence three tiers instead of one primary/fallback pair** (all overridable in `.env`):

| Role | Setting | Default | Why |
|---|---|---|---|
| Conversation | `LLM_PRIMARY` | `groq:openai/gpt-oss-120b` | ~1 s is the difference between a conversation and a form; 30 RPM absorbs a talkative session |
| Fallback | `LLM_FALLBACK` | `gemini:gemini-3.8-flash` | separate quota and separate outages from Groq |
| Judgement calls | `LLM_QUALITY` | `gemini:gemini-3.8-flash` | analyzer, placement, checkpoint grading: rare, latency-tolerant, worth the stronger model. Chain: quality → primary → fallback |
| Cheap, frequent | `LLM_FAST` | `groq:openai/gpt-oss-20b` | word translation, drill grading; its own 1 000 RPD so tapping words all evening can't eat the conversation budget |
| Speech → text | `STT_PROVIDER` | `groq` (`whisper-large-v3`) | **0.35 s average**, and it preserves learner mistakes; see `STT-FINDINGS.md` |
| Text → speech | `TTS_PROVIDER` | `edge` | free, no key, no quota, ~2 s a sentence, real German neural voices |

Use the tiers from the app layer: `tier="quality"` for the analyzer, placement and checkpoint
grading; `tier="fast"` for translation and drill grading; the default for talk turns.

**Latency budget:** a talk turn is STT (0.35 s) + one LLM call (~1 s) + TTS (~2 s, cached on replay).
The analyzer runs every `ANALYZE_EVERY_TURNS` turns (default 8) and at session end — *not* every
turn, and in a background task so it never delays a reply. Keep it that way: a second LLM call per
turn would double the wait and halve the daily budget.

**German edge-tts voices available** (verified from the server):
`de-DE-SeraphinaMultilingualNeural` (f, default — the most natural), `de-DE-FlorianMultilingualNeural`
(m), `de-DE-KatjaNeural` (f), `de-DE-ConradNeural` (m), `de-DE-AmalaNeural` (f),
`de-DE-KillianNeural` (m), plus `de-AT-*` (Austrian) and `de-CH-*` (Swiss).

---

## 2. Architecture decisions (and the two places I changed the brief)

The brief's architecture was followed, with two deliberate changes:

1. **Groq Llama → `openai/gpt-oss-120b`** as the fallback, because Llama is no longer on the free
   tier (above).
2. **No SDKs: plain REST via `httpx`** for both Gemini and Groq. The `google-genai` SDK has churned
   through three incompatible call shapes in a year (`generate_content` → `interactions.create`);
   the REST `generateContent` endpoint has stayed stable, and one `httpx.AsyncClient` per provider is
   less code than the SDK wrapper would be. `GeminiProvider._body` already has a compatibility retry:
   on a 400 it re-sends without the newer optional fields (`thinkingConfig`, `responseJsonSchema`) and
   puts the JSON schema in the system prompt instead, so a field being renamed upstream degrades
   instead of breaking.

Everything else is as the brief specified: FastAPI async + SQLite in a mounted volume, vanilla-JS
PWA with no build step, single-password cookie auth, Docker + compose, keys server-side only.

---

## 3. What you can call

### `app.config.settings`
Every knob, read from env once. Derived paths are plain attributes (`prompts_dir`, `static_dir`,
`curriculum_path`, `audio_dir`, `db_path`), so tests can repoint them. Add new settings here with an
env default — never read `os.environ` from a service.

### `app.db.db` — the database
```python
from .db import db, loads

row  = await db.fetchone("SELECT * FROM profile WHERE id=1")       # dict | None
rows = await db.fetchall("SELECT * FROM vocab WHERE due <= ?", (now,))
new_id = await db.execute("INSERT INTO vocab (...) VALUES (...)", (...))  # commits, returns lastrowid
await db.bump_activity("talk_turn")            # per-day counters for the progress page
await db.kv_set("key", "value"); await db.kv_get("key")
skills = loads(row["skills"], {})              # json.loads that tolerates NULL/garbage
```
Schema: `profile` (single row, id=1), `sessions`, `messages`, `mistakes`, `vocab`, `vocab_reviews`,
`translations`, `writings`, `drills`, `checkpoints`, `activity`, `kv`. Read `app/db.py` — every
column has a comment saying what belongs in it. **New columns go in `db.MIGRATIONS`**, not into the
`CREATE TABLE` text.

The `vocab` table already carries SM-2 state: `due`, `interval_days`, `ease`, `reps`, `lapses`,
`last_review`.

### `app.providers.llm.llm` — the LLM router
Walks the tier's chain, retrying once per provider on a transient failure (429 honouring
`retry-after`, or any 5xx — free-tier Gemini hands out 503s often enough that giving up on the first
one would send most turns to the fallback), then raises `LLMUnavailable`. Handles code fences, prose
around the JSON, and does one self-repair round trip if the JSON is unparseable.

```python
from .providers.base import Message
from .providers.llm import llm

data = await llm.complete_json(system_prompt, [Message("user", text)], SCHEMA)   # talk turns
data["_model"]                      # "groq:openai/gpt-oss-120b" — store it on the message row
text = await llm.complete_text(system_prompt, msgs)
judged = await llm.complete_json(sys, msgs, SCHEMA, tier="quality")  # analyzer, grading, placement
cheap  = await llm.complete_json(sys, msgs, SCHEMA, tier="fast")     # translation, drill grading
```
Verified live: an `enum` in the JSON schema is respected by both providers, so
`"category": {"enum": CATEGORY_SLUGS}` genuinely constrains the output — still run
`taxonomy.normalize()` on it, but it will rarely have to do anything.
`complete_json` returns a `dict`. **Validate it before you trust it** — a free-tier model will
occasionally return a field as a string where you asked for a list.

### `app.providers.stt.stt` — speech to text
```python
t = await stt.transcribe(audio_bytes, mime, filename)   # -> Transcript(text, provider, model)
both = await stt.transcribe_compare(audio_bytes, mime)  # -> {"groq": "...", "gemini": "..."}
```
Primary engine then the other one. Handles iOS `audio/mp4` and Android `audio/webm`; re-encodes to
16 kHz mono mp3 with ffmpeg for the Gemini path. Raises `ProviderError` when both fail — the caller
must keep the recording so the user can retry (see task V3).

### `app.providers.tts` — text to speech
```python
path = await tts.synthesize(text, speed="normal")   # or "slow"; cached on disk by content hash
```
Already exposed as `GET /api/tts?text=...&speed=normal|slow`. The frontend should use the endpoint,
not the function.

### `app.prompts.render` — prompts
```python
system = render("tutor_talk", level="A1.2", unit_title=..., ...)   # {{placeholder}} substitution
```
Raises `PromptError` on a missing *or* unexpected key, so a prompt and its caller can never drift
apart silently. `RELOAD_PROMPTS=1` re-reads the file on every call while you iterate on wording.
`app/prompts/tutor_talk.md` is written — read it; it is the quality bar and the house style for the
other prompt files.

### `app.taxonomy` — mistake categories
14 fixed slugs (`gender`, `case`, `word_order`, …). Use `normalize()` on anything a model returns
and `describe_for_prompt()` to put the list into a prompt, so the DB and the prompts can't drift.

### `app.auth`
`Depends(auth.require_auth)` on every router you add. Login/logout/me already exist.

### Errors
Raise `ProviderError` or `LLMUnavailable`; `main.py` converts them to
`{"detail": "...", "retryable": true}` with status 503. The frontend shows `detail` and offers a
retry when `retryable`. Don't catch these just to return a 200 with an apology in German.

---

## 4. Endpoints that already exist

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/health` | no | container healthcheck |
| POST | `/api/auth/login` | no | `{"password": "..."}` → sets `dt_session` cookie |
| POST | `/api/auth/logout` | no | clears the cookie |
| GET | `/api/auth/me` | yes | 200/401 — the frontend's "am I logged in" probe |
| GET | `/api/system/status` | yes | configured models/voices and which keys are present (never the keys) |
| GET | `/api/tts?text=&speed=` | yes | audio/mpeg or audio/wav, cached |
| POST | `/api/voice/transcribe` | yes | multipart `file`, optional `compare=true` → both engines |

`static/` is mounted at `/` and currently holds a **placeholder diagnostic page** that logs in and
exercises TTS/STT from a phone. Task F1 replaces it wholesale.

---

## 5. Server facts (you have no access to this; here's what it looks like)

- Repo lives at `/opt/language-learner`, deployed with `docker compose` as container
  `german-tutor`, image `german-tutor:latest`, bound to **127.0.0.1:9003** (9001 and 9002 are
  taken by other apps on the box).
- `./data` is bind-mounted to `/data`: `tutor.db` plus `audio/` for the TTS cache.
- **The container runs as uid 1000.** If the host `data/` dir is root-owned, every write fails with
  `attempt to write a readonly database` while reads keep working — a silent, confusing failure that
  has bitten this server before. `deploy/deploy.sh` chowns it on every deploy.
- nginx terminates TLS and proxies to 9003; `deploy/nginx.conf` + `deploy/snippets/` + rate-limit
  zones (`5r/m` on login, `2r/s` on the API). `client_max_body_size 26m` for audio uploads,
  `proxy_read_timeout 120s` because an LLM turn plus TTS is slow. CSP allows `media-src blob:` for
  MediaRecorder playback and nothing external at all — **no CDN, no Google Fonts; if you add one the
  CSP will block it.**
- ffmpeg is installed in the image (verified). `/api/system/status` reports `"ffmpeg": true`.
- Backups: `deploy/backup.sh` uses the sqlite backup API (not `cp`, which can tear a WAL database),
  gzips, keeps 30, runs from cron.
- Verified working on the server: login → cookie, `GET /api/tts` → 21 KB mp3 in ~2 s (German,
  Seraphina), slow variant cached separately, 401 for anonymous requests, 503 + `retryable` when a
  provider is missing its key, all 13 tables created on first boot.

---

## 6. How to work without the server

You do not need a server, a key or a network:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q                      # 26 tests, all offline

# run the app with no API keys at all — the `fake` provider answers every LLM call
DATA_DIR=./data APP_PASSWORD=dev COOKIE_SECURE=0 LLM_PRIMARY=fake:fake LLM_FALLBACK= \
  .venv/bin/uvicorn app.main:app --reload --port 8000
```

`app/providers/fake.py` inspects whatever JSON schema it is handed and returns a valid object for
it, so services and the whole frontend can be driven end to end offline. Set
`FakeProvider.canned = {...}` in a test to pin the reply exactly. TTS and STT still need the
network/keys — mock them in tests the way `tests/test_foundation.py` does.
