# Handover — the app layer

What was built on top of the server foundation, what changed in it, what could not be verified
without a server or a real key, and what deserves a careful look. `docs/API.md` is the contract
between the frontend and the backend; `docs/TASKS.md` is the spec this implements; `docs/DESIGN.md`
is the visual and interaction spec the frontend follows.

## How it was built

The work was split by file ownership and run in parallel, with one coordinator merging:

1. The coordinator wrote the PWA shell, every screen, the base services (profile, the shared
   mistake-log merge, curriculum loader, vocab upsert, upload→transcript helper), the router
   stubs and `docs/API.md` — the contract every stream built against.
2. Three backend streams ran in isolated git worktrees with disjoint files: **talk + analyzer +
   voice turn**, **curriculum content + placement + checkpoints**, **vocab/SRS + write + drills +
   progress**. Each kept the suite green on its own; merges were conflict-free by construction.
3. The coordinator then applied `docs/DESIGN.md` to the frontend and drove every screen end to end
   in headless Chromium (360 px, 320 px light, 430 px dark, fake microphone) against the fake
   provider.

Commits are one per task (`A2: …`, `D2: …`), on the branch this was developed on.

## What exists

**Frontend (`static/`)** — vanilla ES modules, no build step, no CDN. `app.js` is the shell (auth
gate as an overlay so unsent input survives a 401, tab router, service worker registration,
`visualViewport` keyboard handling, offline banner). `js/api.js` is the one fetch helper (throws
`{status, detail, retryable}`, timeout, abort). `js/ui.js` holds the DOM helper, toast, bottom sheet
(drag-to-dismiss), skeletons, category chips, haptics. `js/audio.js` plays `/api/tts` with progress
and wraps `MediaRecorder` with a real `AnalyserNode` level meter. `js/mic.js` is the hold-to-talk
control shared by Talk, Placement and Checkpoint. `js/store.js` is IndexedDB for the two queues that
must survive a tunnel: unsent recordings and offline review ratings. One screen per file under
`js/`. `sw.js` precaches the shell (`CACHE_VERSION` — bump it on every shell change) and never
touches `/api/*`.

- **Talk**: scenario picker from the current unit, tutor bubbles with tappable words
  (translation sheet → add to deck), amber collapsible correction cards, "say it like this" card,
  praise line, new-vocab chips, replay/slow per message with a playback progress line, hide-German
  listening mode, mic/keyboard composer modes (persisted), thinking state that escalates at 6 s and
  offers cancel at 20 s, raw transcript with a "that's not what I said" dispute that discards the
  turn, recordings kept in IndexedDB until a 2xx (retry on tap and when back online, offered again
  on next launch), session resume, end-of-session summary.
- **Write**: task from the current unit (collapsible), draft saved per keystroke, live word count,
  inline amber underlines with the explanation opening under the text, improved version with a
  word-level diff, recent writings.
- **Review**: one card, tap to flip, four ratings with the next interval under each, audio on
  reveal, DE→EN and EN→DE recall directions, queue progress bar, calm end screen, deck browser with
  search and delete, offline rating queue.
- **Drill**: eight items from his own mistakes, dot progress row, big options or free text, reorder
  as tap-to-build chips, instant per-item feedback in good/amber, "that one is beaten" line.
- **Progress**: CEFR position, animated skill meters, 30-day activity strip, recurring mistakes with
  trend, vocab tiles, checkpoint call-to-action, placement re-run, thin-data honesty.
- **Placement** (first launch, skippable, re-runnable) and **Checkpoint** (speaking + writing, graded,
  the "you're now in A1.2" moment on a pass).

**Backend (`app/services/`, `app/routers/`, `app/prompts/`)** — see `docs/API.md` for every route.

- `profile.py` — the learner row; `build_context()` produces exactly the `tutor_talk` placeholders
  (six mistakes, twelve due words, `(none yet)` never `[]`); review focus rides along in the grammar
  targets so a failed checkpoint actually changes the next sessions.
- `mistakes.py` — the single merge path (category + normalised pattern) used by the analyzer, the
  writing feedback and the drills. `examples` capped at 5, `resolve`/`fail` for drills.
- `curriculum.py` + `curriculum/units.json` — six phases A1.1→B1.2, 30 units, 90 scenarios written
  to Ahmad's life (standup, broken deploy, Ausländerbehörde, flat viewing, landlord, doctor,
  Packstation, delayed train, team dinner…), each unit with authored checkpoint tasks; validated at
  load; a stale `unit_id` falls back to the first unit of the level instead of crashing.
- `tutor.py` + `routers/talk.py` — sessions, turns (JSON or multipart), one LLM call per turn, all
  rows written after the model answered (a 503 leaves nothing behind), model output sanitised
  (categories normalised, caps of 3, bools coerced), analyzer every N turns in a background task,
  catch-up of sessions whose analysis failed, TTS pre-rendered in the background so the audio is
  cached before the phone asks, discard of a disputed turn.
- `analyzer.py` + `prompts/analyzer.md` — incremental from `analyzed_count`, serialised with a lock,
  `tier="quality"`, mistake aggregation through `mistakes.record`, deltas clamped to ±3,
  `rolling_summary` capped at 120 words, `unit_readiness` on `sessions.meta`. **Audio-aware**: voice
  turns are kept under `DATA_DIR/audio/turns/` (column `messages.audio_path`), concatenated with
  ffmpeg and attached to the analysis call, then deleted; a provider that rejects audio triggers one
  text-only retry.
- `speech.py` — upload → raw transcript (400 on silence, 413 over 25 MB), never cleaned up.
- `vocab.py` + `srs.py` — cache-first word translation (`tier="fast"`), upsert that never resets
  SRS state, SM-2 exactly as specified with ±10 % jitter over 7 days, due queue with new cards
  interleaved and capped, interval preview per card.
- `writing.py`, `drills.py`, `progress.py`, `placement.py`, `checkpoint.py` — as in the spec; the
  drill grades locally and only calls the fast tier for free-text transforms that differ; placement
  grades on the quality tier, caps the level at A1.2 when fewer than two tasks were answered, and
  `finish` is idempotent; the checkpoint's `passed` is enforced by code from the scores (every
  dimension ≥ 3), never half-writes, refuses (409) a stale row whose unit is no longer current, and
  a provider failure leaves the row reusable.

Prompts: `analyzer.md`, `placement.md`, `checkpoint_grade.md`, `translate.md`, `write_prompt.md`,
`write_feedback.md`, `drill_generate.md`, `drill_grade.md` (plus the foundation's `tutor_talk.md`).

Tests: `.venv/bin/python -m pytest -q` — 189 tests, all offline, fake provider, STT/TTS/ffmpeg mocked.
`tests/test_static.py` additionally asserts every `/api` route carries `auth.require_auth`, every
module the shell imports is in the service worker's precache list, nothing in `static/` references
an external URL, and no API key pattern is in the tree.

## Changes to foundation files

Kept to the minimum the spec allows; each is isolated and small.

- `app/config.py`: three settings appended at the bottom (`CHECKPOINT_MIN_SESSIONS`,
  `NEW_CARDS_PER_REVIEW`, `DRILL_ITEMS`). Nothing above them changed.
- `app/db.py`: one line in `MIGRATIONS` — `("messages", "audio_path", "TEXT")` — for the stored
  recordings the analyzer listens to. Exactly what `MIGRATIONS` exists for.
- `app/providers/fake.py`: `_dummy` returns three entries for an `"items"` array (one everywhere
  else), so the drill generator (needs ≥ 3 usable items) can be driven offline. Nothing else.
- `app/routers/__init__.py`: the new routers registered (the registry by design).
- `tests/conftest.py`: `LLM_QUALITY=""` added to the offline environment and one fixture
  (`fresh_db`) for service-level async tests.
- `.gitignore`: `.claude/` (agent worktrees).

Not changed, deliberately: `app/main.py` — `HTTPException` bodies carry no `retryable` key; the
frontend treats a missing key as `false`, so no handler was needed.

## Not verifiable offline

- Real model output for every prompt: lemma/plural accuracy in `translate.md`, whether drill items
  really reuse his sentences, the analyzer's pattern wording staying stable enough to merge, the
  placement landing conservatively, grading leniency on free-text transforms. Every path validates
  defensively, so a bad reply can only produce a 503 (retryable) or a dropped item, never a 500 or
  a partial write.
- Gemini with inline mp3 audio from real phone recordings, and ffmpeg concat of real `.m4a`/`.webm`
  clips (the command shapes are asserted in tests; ffmpeg itself is mocked).
- edge-tts from this sandbox (its TLS is intercepted here); the foundation verified it on the server.
  The frontend's audio paths were exercised with a server that returned 503 for `/api/tts`, which
  is also what they must survive.
- iOS Safari specifics: autoplay refusal → tap-to-play, `audio/mp4` uploads, `visualViewport`
  keyboard behaviour, home-screen install. Built to the spec; needs a real phone.
- Haptics (`navigator.vibrate`, Android only).

## Worth reviewing

- `app/prompts/analyzer.md` and `app/prompts/drill_generate.md` are the two prompts that decide
  whether the memory system works (merging) and whether drills feel personal. Read them with a
  real transcript in hand.
- The analyzer attaches the concatenated audio of a slice; with `ANALYZE_EVERY_TURNS=8` that is up
  to eight short clips. If Gemini's inline limit bites on long sessions, lower the turn count or
  raise `MAX_AUDIO_BYTES` handling in `analyzer.py`.
- `static/js/talk.js` is the biggest file (the Talk screen is the app); the pending/queued recording
  state machine is in `doTurn` / `uploadRecording` / `showQueued`.
- `docs/DESIGN.md` §9 checklist: everything verifiable in headless Chromium passes (no horizontal
  scroll at 320/430, dark and light, keyboard-less flows). The items that need a real phone are
  listed above.

## Ideas not built (and why)

Listed in `README.md` under "Ideas not built yet". The one most worth doing next: streaming the
tutor's text so the first sentence is spoken while the rest is still being written.


---

# Review notes (server session, 2026-10-03)

Merged into `main` and deployed to https://german.shawar.xyz. What the review checked, what it
found, and what it changed on top.

## Verified before merging

- 189 offline tests green; 195 after the additions below.
- **Every one of the 35 documented `/api` operations returns 401 without a cookie** — checked by
  calling each one anonymously, not by introspecting dependencies (FastAPI 0.142 nests included
  routers, so introspection quietly reported zero routes).
- No key material and no external URL anywhere in the tracked tree.
- The four foundation files touched are each minimal and justified.
- `services/srs.py` matches the SM-2 spec exactly, jitter and ease bounds included.
- One merge path for the mistake log, and `analyzer.md` is fed the open patterns and told to reuse
  their wording verbatim — the thing that stops semantic drift from making nothing look recurring.

## Verified live, with real keys

A real conversation, a real voice turn and every other mode, against Groq and Gemini:

- Voice turn end to end over HTTPS in **1.1 s** (upload → Whisper → tutor → stored recording).
- The memory loop genuinely closes: two sessions produced the log rows
  `verb_conjugation / perfekt with sein for movement verbs` and `preposition / dative after in for
  location`, each `count=1` — **no double-counting**, because the analyzer is the single writer.
  Skills moved 10→11/9, facts came out as "Works remotely for a German company", and the drill then
  built a `reorder` item from his own sentence.
- Write produced a landlord/broken-heating task with `must_include` and word bounds, and graded a
  real message correctly (`zu das Meeting → zum Meeting`, `weil ich bin krank → weil ich krank bin`).

## Fixed on top of the branch

1. **Abandoned sessions were never analysed and leaked their recordings.** A session is only ended
   by an explicit tap, and `analyzer.catch_up()` filters on `ended_at IS NOT NULL` — but on a phone
   the normal exit is switching apps. Reproduced: a week-old open session with three voice turns,
   `catch_up()` returned 0 and all three clips were still on disk. Added
   `tutor.close_stale_sessions()` (reusing `end_session`, so an abandoned session takes the tidy
   path) and `tutor.sweep_orphan_audio()`, both behind the existing new-session hook, plus
   `SESSION_STALE_MINUTES` (45). Six tests in `tests/test_abandoned_sessions.py`.
2. **The tutor re-corrected earlier turns.** An English question came back with corrections for the
   *previous* message. Display-only (the analyzer owns the log) but it reads as not listening.
   `tutor_talk.md` now scopes corrections to the latest message. Verified: the same turn now returns
   zero corrections.
3. **The English escape hatch bypassed `english_help`.** The tutor answered inside `reply`, so the
   "say it like this" card never rendered and the phrase was spoken instead of shown. The prompt now
   says `reply` is spoken aloud and the phrase belongs in `english_help`. Verified: it now returns
   `english_help` with the German and a literal gloss.
4. **Two category pairs in `taxonomy.py` overlapped** (`gender`/`article`, `case`/`preposition`), so
   one recurring error could split across two rows and never look recurring — my own bug in the
   foundation. The boundaries are now explicit, and `tutor_talk.md` carries the one-line
   disambiguation, since the tutor only ever saw the slug names.
5. **`test_no_secret_in_the_repo_tree` scanned the working tree**, so it failed on the real `.env` —
   a test that always fails on the server gets disabled and then protects nothing. Rescoped to
   `git ls-files`, which is where the actual risk lives.
6. The placeholder shell was replaced by the real one, as intended; the transcription lab moved to
   **`/lab.html`** (a dev tool, not precached, not linked from the UI).

The database was reset after testing: the conversations above had written real sessions, mistakes,
vocab and personal facts into the learner profile, and Ahmad has to start from a genuine placement.
The pre-reset state is in `backups/`.

## Still unverified

Everything in the branch's "Not verifiable offline" list that needs a real phone: iOS autoplay,
`audio/mp4` uploads, home-screen install, `visualViewport` behaviour, haptics. Also the
audio-aware analysis path against real phone recordings — it was exercised here with an mp3 upload,
not with a multi-clip ffmpeg concat from a real session.


---

# Learn mode (server session, 2026-10-03)

Ahmad, after the first real session: *"i need it to actually teach me like a coursework then i can
use these write and text things, i know nothing about german"*. He was right, and it was the biggest
gap in the product.

Everything built so far is **practice** — talk, write, drill, review — and practice assumes someone
taught you. `units.json` is a syllabus: `"sein in the singular (ich bin / du bist …)"` is a note a
teacher writes for themselves, not something a learner can use. Nothing in the app ever explained
anything.

So there is now a **Learn** tab, first in the bar, and it wins the landing screen whenever the
current unit's lesson is unfinished.

- `app/curriculum/lessons.json` — hand-written coursework per unit. Not model-generated on purpose:
  a beginner's first contact with the language should be identical every time, correct, and free of
  quota. A1.1 units 1–2 are written; the rest report "not ready yet" instead of 404-ing.
- Step types: `sounds` (a pronunciation primer — five rules that make German readable), `words`
  (each line tappable to hear), `grammar` (explained in English, with a table and examples), `check`
  (one question, graded on the device, wrong answers explained).
- `app/services/lessons.py` + `app/routers/lesson.py` + the `lesson_progress` table. Progress never
  moves backwards, completion is idempotent, and the next step's audio is prefetched while he reads
  the current one.
- `static/js/learn.js` + the Learn styles.

Two layout bugs came in with it and are fixed: `#tabs` had `repeat(5, 1fr)` hardcoded, so the sixth
tab (Progress) fell off the right edge, and `.screen-body` had no gutter for the fixed tab bar, so a
screen without its own sticky footer hid its last control behind it.

**Still to write:** lessons for a1.1-3 through a1.1-5 and everything above A1.1 — 28 units. The
shape is set by the two that exist; follow their density and keep every explanation shorter than it
wants to be.
