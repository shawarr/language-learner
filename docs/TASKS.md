# Build spec — German tutor app layer

You are building the application on top of a finished, tested server foundation.
**Read `docs/FOUNDATION.md` first**, then `CLAUDE.md`, then `app/db.py` and
`app/prompts/tutor_talk.md`. You need no server, no API keys and no network: the `fake` LLM
provider answers every call offline (`LLM_PRIMARY=fake:fake`).

> **`docs/DESIGN.md` is not optional.** Ahmad's requirement is that the frontend be genuinely
> polished — native-app quality, not "functional". DESIGN.md is the binding spec for the visual
> system, the Talk screen's interactions, motion, states and accessibility, with concrete numbers.
> Read it before writing a line of CSS, and treat its final checklist as part of the definition of
> done for every screen.

## Rules of engagement

1. **Do not modify these files** — they are deployed and verified, and changing them makes the
   merge painful:
   `app/config.py` (add settings at the bottom only), `app/db.py` (new columns go in `MIGRATIONS`),
   `app/auth.py`, `app/taxonomy.py`, `app/prompts.py`, `app/providers/*`, `app/main.py`,
   `Dockerfile`, `docker-compose.yml`, `deploy/*`, `requirements.txt`.
   If you are convinced one of them must change, make the change small, isolated in its own commit,
   and explain why in `docs/HANDOVER.md`.
2. **Build in order.** Each phase works — manually exercised in a browser, with tests — before the
   next one starts. A half-built phase blocks the merge.
3. **Tests stay green and offline.** `.venv/bin/python -m pytest -q`. Add tests per service; mock
   STT/TTS the way `tests/test_foundation.py` does. No test may need a key or the network.
4. **One commit per task**, message `phase/task: what changed` (e.g. `A2: talk turn endpoint`).
   Push to `main`.
5. **Write `docs/HANDOVER.md` as you go**: what you built, anything you changed in the foundation,
   anything you could not verify without a server or a real key, and anything you want checked.
   This is what the review reads first.
6. **Mobile is the only target that matters.** Assume a phone held in one hand, in portrait, on a
   mediocre connection. If a control needs two hands or a hover, it is wrong.
7. **Every model call costs quota.** One talk turn = one LLM call + one TTS call. If you find
   yourself adding a second LLM call to a turn, find another way.

## Definition of done, per task

- The endpoint or screen works when driven by hand with `LLM_PRIMARY=fake:fake`.
- Tests cover the logic that isn't the model's judgement (scheduling maths, state transitions,
  validation of model output, error paths).
- Bad model output cannot corrupt the DB or 500 the request.
- `pytest -q` green.

---

# Phase F0 — the PWA shell

**Files:** `static/index.html`, `static/styles.css`, `static/app.js`, `static/sw.js`,
`static/manifest.webmanifest`, `static/icons/icon-192.png`, `static/icons/icon-512.png`,
`static/icons/apple-touch-icon.png`

The current `static/index.html` is a placeholder diagnostic page. Replace it. Keep its two useful
tricks: the `unlockAudio()` silent-clip-on-first-tap, and letting `MediaRecorder` pick its own mime.

- Single-page app, hash-free, **no build step, no framework, no bundler, no CDN**. Plain ES modules
  (`<script type="module">`) are fine; the CSP allows `'self'` scripts only.
- Bottom tab bar: **Talk · Write · Drill · Review · Progress**. Thumb-reachable, 56 px targets,
  safe-area insets honoured (`env(safe-area-inset-bottom)`).
- Dark mode by default, light via `prefers-color-scheme`. Colour tokens on `:root`, nothing
  hardcoded per component.
- Auth gate: probe `GET /api/auth/me`; on 401 show the password screen. A 401 from any later call
  returns to it without losing unsent input.
- One `api()` helper: `credentials: 'same-origin'`, throws an object carrying `detail` and
  `retryable` from the server's error body, so every screen can show a real message and a retry
  button.
- Service worker: cache the shell (`/`, css, js, icons) for offline start-up, **never cache `/api/*`
  or `/sw.js`**. Bump a `CACHE_VERSION` const so an updated shell actually replaces the old one.
- `manifest.webmanifest`: `display: standalone`, `theme_color`, portrait, the three icons.
  Installable to the iOS and Android home screen.
- Generate the icons as flat PNGs (a plain "DE" mark on the theme colour is fine) — no external
  asset, no font download.

**Acceptance:** loads as a standalone app from the home screen; login works; tabs switch; shell
starts with the network off; nothing in DevTools' console.

---

# Phase A — text chat, profile injection, analyzer

This is the core. Get it genuinely good before touching voice.

## A1 — `app/services/profile.py`

```python
async def get_profile() -> dict          # parsed: skills/facts/review_focus as objects
async def update_profile(**fields) -> None   # whitelisted columns only, bumps updated_at
async def apply_skill_deltas(deltas: dict[str, int]) -> dict  # clamp each skill to 0..100
async def add_facts(facts: list[str]) -> None    # dedupe case-insensitively, cap at 40
async def top_mistakes(limit: int = 6) -> list[dict]
async def build_context(unit: dict) -> dict      # everything the tutor prompt needs
```

- `top_mistakes` ranks by `count - resolved`, then recency. Mistakes whose `resolved >= count` are
  considered beaten and drop out — otherwise a mistake from week one haunts the prompt forever.
- `build_context` returns exactly the keys `app/prompts/tutor_talk.md` declares (check with
  `prompts.placeholders("tutor_talk")`; a mismatch raises, which is the point). Formatting rules:
  - `top_mistakes` → `"case: 'mit dem Bus' not 'mit den Bus' (4×)"`, newline-separated, max 6.
  - `due_vocab` → words only, comma-separated, **max 12** — a longer list makes the tutor stuff them
    all into one unnatural sentence.
  - empty values render as `"(none yet)"`, never as `"[]"` or `"None"`.
- **Keep the prompt small.** `rolling_summary` is capped at ~120 words by the analyzer; don't paste
  raw transcripts in.

**Tests:** skill clamping at both ends; beaten mistakes excluded; fact dedupe; `build_context`
satisfies `placeholders("tutor_talk")` exactly; truncation limits hold.

## A2 — `app/services/tutor.py` + `app/routers/talk.py`

Schema for the tutor turn (copy this; it is also the frontend's contract):

```python
TUTOR_TURN_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "German only. 1-3 short sentences, ends with one question. Spoken aloud verbatim."},
        "corrections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "wrong": {"type": "string"},
                    "right": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORY_SLUGS},
                    "explanation": {"type": "string", "description": "One sentence, English."},
                },
                "required": ["wrong", "right", "category", "explanation"],
            },
        },
        "praise": {"type": ["string", "null"], "description": "Only when he did something new or hard."},
        "english_help": {
            "type": ["object", "null"],
            "properties": {"english": {"type": "string"}, "german": {"type": "string"},
                           "literal": {"type": "string", "description": "Word-by-word gloss, so he sees the structure."}},
            "required": ["english", "german", "literal"],
        },
        "new_vocab": {
            "type": "array",
            "items": {"type": "object",
                      "properties": {"word": {"type": "string", "description": "Nouns with article and plural: 'der Termin (die Termine)'"},
                                     "translation": {"type": "string"}, "example": {"type": "string"}},
                      "required": ["word", "translation"]},
        },
        "scenario_done": {"type": "boolean", "description": "True when the scenario's goal has been reached."},
    },
    "required": ["reply", "corrections", "new_vocab", "scenario_done"],
}
```

Service:
```python
async def start_session(mode="talk", scenario_id=None) -> dict   # row + opening tutor turn
async def take_turn(session_id: int, text: str, *, input_kind="text",
                    transcript_raw: str | None = None) -> dict
async def end_session(session_id: int) -> dict                   # triggers the analyzer, returns the summary
```

- History sent to the model: the last `settings.history_window` messages (default 14) of this
  session; everything older is represented by `profile.rolling_summary`.
- Persist in one place: the user message (with `transcript_raw` and `input_kind`), then the
  assistant message with `correction`/`english_help` as JSON and `llm_model` from `data["_model"]`.
- Store `corrections` on the **assistant** row (the schema comment says so): the card renders under
  the user's message but is produced by the tutor's turn.
- `new_vocab` → upsert into `vocab` with `source='tutor'` and `due = now` (first review today).
  Never overwrite an existing row's SRS state.
- Validate before writing: `taxonomy.normalize()` every category; drop a correction missing `wrong`
  or `right`; cap `corrections` at 3 and `new_vocab` at 3 even if the model returns more; coerce
  `scenario_done` to a bool.
- `bump_activity("talk_turn")`; increment `sessions.user_turns`.
- Trigger the analyzer when `user_turns % settings.analyze_every_turns == 0` — in the background
  (`asyncio.create_task`), never blocking the reply. Log and swallow its failures; a failed analyzer
  must not break a conversation.

Routes (all `Depends(auth.require_auth)`, registered in `app/routers/__init__.py`):

| Method | Path | Body / params | Returns |
|---|---|---|---|
| POST | `/api/talk/session` | `{"scenario_id": "..."?}` | `{session, opening_turn}` |
| POST | `/api/talk/turn` | `{"session_id", "text"}` | the turn (below) |
| POST | `/api/talk/session/{id}/end` | — | `{"summary": "..."}` |
| GET | `/api/talk/session/{id}` | — | `{session, messages}` for resuming |
| GET | `/api/talk/sessions` | `?limit=20` | recent sessions for the progress page |

Turn response shape — fixed, voice adds to it in V1:
```json
{"user_message_id": 41, "message_id": 42, "reply": "...", "corrections": [...],
 "praise": null, "english_help": null, "new_vocab": [...], "scenario_done": false,
 "transcript": null, "transcript_provider": null}
```

**Tests:** turn persists both rows; over-long corrections/vocab truncated; unknown category
normalised to `other`; a correction missing `right` dropped; analyzer fires on turn 8 and not on 7;
analyzer exception doesn't fail the turn; `LLMUnavailable` → 503 with `retryable` and **no** partial
rows left behind.

## A3 — `app/services/analyzer.py` + `app/prompts/analyzer.md`

Reads the messages of a session from `sessions.analyzed_count` onward, returns updates, writes them,
advances `analyzed_count`. Runs on every Nth turn and at session end — so it must be idempotent and
incremental.

```python
ANALYSIS_SCHEMA = {
  "type": "object",
  "properties": {
    "session_summary": {"type": "string", "description": "2-3 sentences, English: what he practised and how it went."},
    "rolling_summary": {"type": "string", "description": "Rewritten cumulative picture of the learner, max 120 words."},
    "mistakes": {"type": "array", "items": {"type": "object", "properties": {
        "category": {"type": "string", "enum": CATEGORY_SLUGS},
        "pattern": {"type": "string", "description": "The recurring error in a few words, not this one instance."},
        "wrong": {"type": "string"}, "right": {"type": "string"}, "note": {"type": "string"}},
        "required": ["category", "pattern", "wrong", "right"]}},
    "new_vocab": {"type": "array", "items": {"type": "object", "properties": {
        "word": {"type": "string"}, "translation": {"type": "string"}, "example": {"type": "string"}},
        "required": ["word", "translation"]}},
    "skill_deltas": {"type": "object", "properties": {
        "speaking": {"type": "integer"}, "listening": {"type": "integer"}, "writing": {"type": "integer"},
        "grammar": {"type": "integer"}, "vocab": {"type": "integer"}},
        "description": "Change for this session only, each between -3 and +3."},
    "facts": {"type": "array", "items": {"type": "string"},
              "description": "New durable personal facts worth using as conversation material later."},
    "unit_readiness": {"type": "string", "enum": ["not_yet", "almost", "ready"],
                       "description": "Is he ready for this unit's checkpoint?"}
  },
  "required": ["session_summary", "rolling_summary", "mistakes", "new_vocab", "skill_deltas", "unit_readiness"]
}
```

- **Mistake aggregation is the heart of the memory.** Merge on `(category, pattern)` with a
  normalised pattern key (lowercase, collapse whitespace): bump `count`, append to `examples`
  (keep the newest 5), update `last_seen`. Do not insert a near-duplicate row per session — if that
  happens, nothing ever reaches a count of 3 and the drills have nothing to aim at.
- Clamp `skill_deltas` to ±3 each before applying.
- `unit_readiness == "ready"` → surface the checkpoint in the UI (phase C4). Store it on
  `sessions.meta`.
- The prompt must include `taxonomy.describe_for_prompt()` so the slugs match the DB, and must say:
  judge the learner's German from the **raw transcript**, ignoring transcription noise, and never
  invent a mistake to fill the list.
- Use `tier="quality"` for this call — it runs once every 8 turns, so it can afford the stronger
  model and a few seconds.

**Audio-aware analysis (do this, it is not optional).** The transcription test
(`docs/STT-FINDINGS.md`) found that Whisper reliably preserves structural errors but silently
repairs *unstressed inflection* — it turned "mit **den** Bus" into "mit **dem** Bus" and
"in **eine klein** Wohnung" into "in **einer Klein**wohnung". Those are case and adjective-ending
errors: precisely a beginner's most common mistakes. Judging them from the transcript alone would
miss them systematically.

So when the slice being analysed contains voice turns, attach the audio to the analyzer call:
`LLMRequest(audio=..., audio_mime=...)` is already wired (`complete_json` takes `audio`/`audio_mime`),
and the Gemini path re-encodes to mp3 with ffmpeg automatically. Store the recordings for the session
under `DATA_DIR/audio/turns/` (add a column via `db.MIGRATIONS` for the path) and delete them once
the session has been analysed — they are only needed until then, and keeping every recording forever
would grow the volume without a reason. The prompt should say that the audio is the ground truth for
pronunciation and endings, and the transcript is what the learner saw.

This costs **no extra request** — it is the same analyzer call, with audio attached.

**Tests:** two sessions with the same pattern produce one `mistakes` row with `count=2`; examples
capped at 5; deltas clamped; `analyzed_count` advances and a second run re-analyses nothing; a model
reply with `mistakes` as a string instead of a list is rejected without touching the DB.

## A4 — Talk screen (text first)

- Chat transcript, newest at the bottom, tutor turns and user turns visually distinct.
- Under a user message: a **collapsible correction card**, collapsed by default, showing a count
  badge ("2 corrections"). Never auto-expands, never pushes the conversation out of view.
  `praise` shows as a small inline note, not a card.
- Text input with a send button; `enterkeyhint="send"`. The input keeps its content if the request
  fails.
- `english_help` renders as a distinct "say it like this" card: German, then the literal gloss.
- Scenario picker at the top (phase C2 fills it from the curriculum; until then a static list).
- Pending state on the turn: a typing indicator, input disabled, nothing lost on error.
- `scenario_done: true` → a quiet "scenario complete" affordance offering a new one or "keep going".

## A5 — tap a word → translation + add to vocab

- `POST /api/vocab/translate` `{"word": "...", "context": "the sentence it was in"}` →
  `{"word", "lemma", "translation", "pos", "note", "in_vocab": bool}`. Cache in the `translations`
  table keyed on lowercase surface form; **serve the cache before calling the model** (this fires on
  every tap). Use `tier="fast"`.
  `lemma` is the dictionary form with article and plural for nouns — that's what gets added to vocab.
- `POST /api/vocab` `{"word", "translation", "example"?, "source": "manual"}` → upsert, `due = now`.
- Frontend: tapping any word in a tutor reply opens a small bottom sheet with the translation and an
  **Add to vocab** button. Tap targets are words, not letters — split on whitespace, strip
  punctuation, keep the original word for display.

---

# Phase V — voice

## V1 — audio in the talk turn

`POST /api/talk/turn` also accepts `multipart/form-data`: `session_id`, `file` (the recording),
optional `scenario_id`. Flow: `stt.transcribe()` → the transcript becomes the user's text →
the same `take_turn` path → response additionally carries
`{"transcript": "...", "transcript_provider": "groq", "transcript_raw": "..."}`.

- **Always show the transcript**, exactly as the engine returned it, before/above the corrections.
  Never substitute a corrected version. The learner must be able to see that he said
  "ich habe gegangen".
- Store it in `messages.transcript_raw` and `stt_provider`.
- An empty transcript (silence, mic failure) → `400` with a clear message, and **no** session rows
  written.
- Keep one LLM call: do not add a "clean up the transcript" call.

## V2 — hold-to-talk UI

- Big mic button, bottom centre, hold to record, release to send; a visible timer and a level
  meter so it's obvious recording is live. Cancel by sliding away (like a voice note).
- `MediaRecorder` with **no** forced mime type — iOS Safari gives `audio/mp4`, Chrome `audio/webm`;
  the server handles both. Send the right file extension (`.m4a` / `.webm`).
- Tutor replies: autoplay the audio from `/api/tts`, with **replay** and **slow (0.7×)** buttons
  per message. Slow fetches `speed=slow` (a separate server-side render, not `playbackRate`, which
  sounds awful on mobile).
- iOS autoplay: call the silent-clip unlock on the first user gesture (the placeholder page shows
  how). If a play still rejects, show a tap-to-play button rather than failing silently.
- **Hide German text** toggle (listening practice): tutor text blurred/hidden with a per-message
  reveal. The setting persists in `localStorage`.
- Mic permission denied → explain it once, keep text input working.

## V3 — never lose a recording

- Hold the blob in memory *and* in IndexedDB before the upload starts; delete it only after a 2xx.
- On failure (offline, 429, 503, timeout): keep it, show "not sent — retry", retry on tap and
  automatically when connectivity returns.
- On app start, if an unsent recording exists, offer to send it.
- Surface `retryable` errors as "the tutor is busy, try again in a minute", not a stack trace.

## V4 — the Whisper pitfall test *(server-side: do not do this one)*

`scripts/stt_compare.py` and `docs/STT-FINDINGS.md` exist for it; it needs real keys and real audio
of Ahmad's voice, so it runs on the server. Build V1/V2 against whatever `STT_PROVIDER` says and
don't hardcode an engine.

---

# Phase C — curriculum, placement, checkpoints

## C1 — `app/curriculum/units.json`

Six phases: **A1.1 → A1.2 → A2.1 → A2.2 → B1.1 → B1.2** (B2 later), 4–6 units each.

```json
{
  "version": 1,
  "phases": [
    {"id": "a1.1", "level": "A1.1", "title": "First contact",
     "units": [
       {"id": "a1.1-1", "title": "Hallo und Tschüss",
        "can_do": ["greet someone and say goodbye", "say my name, where I'm from and where I live"],
        "grammar": ["sein (ich bin / du bist / er ist)", "W-questions: wie, wo, woher", "personal pronouns sg."],
        "vocab_themes": ["greetings", "countries and languages", "numbers 0-20"],
        "scenarios": [
          {"id": "a1.1-1-smalltalk", "title": "Meeting a neighbour",
           "setup": "You are Frau Keller, Ahmad's new neighbour in the stairwell. Introduce yourself and ask who he is.",
           "goal": "He introduces himself and asks one question back."}
        ]}
     ]}
  ]
}
```

Content rules — this is pedagogy, not filler, so put real thought in:
- `can_do` statements are CEFR-style and testable ("order food and ask what a dish contains"), not
  "learn the dative".
- Order grammar so each unit needs only what came before. Perfekt before Präteritum (spoken German);
  accusative before dative; `weil`/`dass` word order before relative clauses; separable verbs early
  (they're everywhere in speech).
- **Bias the whole thing to Ahmad's actual life**: a remote DevOps engineer in Amman working for a
  German company who may move to Germany. Scenarios he'll really face — work standup, a 1:1,
  explaining a deploy that broke, the Ausländerbehörde, a flat viewing, a landlord about the heating,
  the doctor, Anmeldung, phone contracts, a parcel at the Packstation, small talk about Amman with
  German colleagues. Not "at the museum".
- Each unit: 2–4 scenarios, each with a `goal` the tutor can judge as reached (feeding
  `scenario_done`).
- B1.1/B1.2 shift toward opinions, narration, complaints, and work talk at length.

**Test:** the JSON loads; ids unique and matching `^[a-z0-9.\-]+$`; every unit has non-empty
`can_do`/`grammar`/`vocab_themes` and ≥2 scenarios; phase order is exactly the six above.

## C2 — `app/services/curriculum.py` + `app/routers/curriculum.py`

```python
def load() -> dict                      # cached, validated at import
def unit(unit_id) -> dict | None
def phase_of(unit_id) -> dict
def next_unit(unit_id) -> dict | None
def scenarios_for(unit_id) -> list[dict]
async def advance() -> dict             # move profile to the next unit, clear review_focus
```
- `GET /api/curriculum` → the whole tree plus the current position (for the progress page).
- `GET /api/curriculum/current` → `{phase, unit, scenarios, checkpoint_available: bool}`.
- A `unit_id` in the DB that no longer exists in the JSON must not crash the app — fall back to the
  first unit of the profile's level and log it.

## C3 — placement test

First launch (`profile.placement_done == 0`) → a short placement flow, not a quiz:
1. two or three spoken tasks of rising difficulty (introduce yourself / describe your work day /
   tell me about a problem you solved last week),
2. one short written task,
3. a graded result → sets `level`, `unit_id`, initial `skills`, `facts` gathered on the way,
   `placement_done = 1`.

- `POST /api/placement/start` → tasks. `POST /api/placement/answer` → per-task capture (audio or
  text, reusing `stt`). `POST /api/placement/finish` → grading, writes the profile, returns the
  placement with an explanation of where he landed and why.
- `app/prompts/placement.md` grades against CEFR descriptors and must **place conservatively**: a
  beginner put at A2.2 gets drowned and quits. Ties go to the lower level.
- Skippable ("start at A1.1") — and re-runnable later from the progress page.
- `POST /api/placement/finish` must be idempotent; a double tap can't double-write.

## C4 — checkpoints

End of each unit: **one speaking task + one writing task**, graded against a rubric.

- `GET /api/checkpoint/current` → `{available, unit, tasks}`; available when the unit's
  `unit_readiness == "ready"` or he's had enough sessions in the unit, and offered — never forced.
- `POST /api/checkpoint/{id}/submit` → speaking audio + written text → `app/prompts/checkpoint_grade.md`
  grades per rubric dimension (task completion, range, accuracy, fluency/coherence) 1–5 with one
  concrete sentence each, plus `passed` and `review_focus`.
- Pass → `curriculum.advance()`, a visible "you're now in A1.2" moment.
  Fail → write `review_focus` into the profile; the tutor prompt and the drill generator read it, so
  the next sessions actually target the gap. Retakeable any time, no penalty, no streak-breaking.
- Store everything in `checkpoints`. Grading must never half-write: one transaction at the end.

---

# Phase D — write, SRS, drills

## D1 — Write mode

- `GET /api/write/prompt` → a writing task from the current unit (`app/prompts/write_prompt.md`):
  an email to a colleague, a message to the landlord, a journal entry, a standup update. 40–80 words
  at A1, more later. Include who it's to and what it must achieve.
- `POST /api/write/submit` `{"prompt", "text"}` → `app/prompts/write_feedback.md` returns:
  ```json
  {"corrections": [{"wrong","right","category","explanation"}],
   "improved": "his text, rewritten at one level above his own — recognisably his, not a new text",
   "score": 1-5, "strengths": "one sentence", "next_time": "one concrete thing to try"}
  ```
- Render corrections **inline** in his text (the wrong span marked, tap to see the explanation), then
  the improved version below with a diff-style highlight of what changed.
- Store in `writings`; feed the corrections into the mistake log through the same aggregation path as
  the analyzer (reuse the function — do not write a second, divergent merge).
- `bump_activity("write")`.

## D2 — SRS vocab + Review mode

`app/services/srs.py` — **SM-2**, four ratings (1 again, 2 hard, 3 good, 4 easy):

```
again:  reps = 0, lapses += 1, interval = 0 (due in 10 minutes), ease = max(1.3, ease - 0.20)
hard:   interval = max(1, interval * 1.2),  ease = max(1.3, ease - 0.15)
good:   interval = 1 if reps == 0 else (6 if reps == 1 else interval * ease)
easy:   as good, then × 1.3,                ease = min(2.8, ease + 0.15)
```
Then `reps += 1`, `due = now + interval_days`, `last_review = now`, and log the row in
`vocab_reviews`. Add ±10 % jitter to intervals over 7 days so a big day doesn't recur as a big day
forever.

- `GET /api/vocab/due?limit=20` → due cards (oldest due first, new cards interleaved, cap new ones at
  10 per session so a chatty day doesn't create a 60-card queue).
- `POST /api/vocab/{id}/review` `{"rating": 1-4}` → the new state.
- `GET /api/vocab?q=&sort=&limit=` for browsing; `DELETE /api/vocab/{id}`.
- Review UI: one card at a time, German → tap to reveal translation + example, four big rating
  buttons, **audio on every card** (`/api/tts`, autoplay the German), swipe or tap, progress counter.
  Also a "German → Arabic/English recall" direction: show translation first, he says the German out
  loud, then reveals. Offline-tolerant: queue ratings in IndexedDB and flush when back online.
- `bump_activity("review", n)`.

## D3 — Drill mode

- `GET /api/drill/new?n=8` → `app/services/drills.py` picks his 2–3 weakest mistake categories
  (`profile.top_mistakes` + `review_focus`) and generates targeted items via
  `app/prompts/drill_generate.md`:
  ```json
  {"items": [{"type": "fill_blank|choose|reorder|transform",
              "prompt": "Ich fahre ___ Bus zur Arbeit.", "options": ["mit dem","mit den","mit der"],
              "answer": "mit dem", "category": "case",
              "explanation": "'mit' takes the dative, and 'der Bus' becomes 'dem Bus'."}]}
  ```
  Items must be **built from his own mistakes** — reuse the stored `examples` so he re-meets his own
  sentences, not generic textbook ones.
- `POST /api/drill/{id}/submit` `{"answers": [...]}` → grade locally where the answer is exact
  (string compare, whitespace/case-normalised); only call the model (`tier="fast"`) for free-text
  transform items. Return per-item right/wrong with the explanation.
- A correct answer increments `mistakes.resolved` for that category/pattern — that's what retires a
  beaten mistake from the prompt. A wrong answer increments `count`.
- Keep it short: 8 items, under two minutes, big tap targets, instant feedback per item (not at the
  end), no timer.
- `bump_activity("drill")`.

---

# Phase E — progress page

`GET /api/progress` → one payload, one call:
```json
{"profile": {...}, "phase": {...}, "unit": {...}, "unit_index": 3, "unit_count": 5,
 "skills": {...}, "streak_days": 7, "activity": [{"day": "2026-10-01", "talk_turn": 14, "review": 20}],
 "top_mistakes": [...], "beaten_mistakes": [...], "vocab": {"total": 210, "due": 18, "mature": 90},
 "recent_sessions": [...], "checkpoint": {"available": true, "unit_id": "a1.1-4"}}
```
Screen: where he is in the CEFR path (phase + unit, with what's left in the unit), five skill meters,
a 30-day activity strip, top recurring mistakes **with their trend** (improving / not yet), vocab
counts, the checkpoint call-to-action when available, and a link to re-run placement.

Keep it honest: if a number is thin (three sessions), say so rather than drawing a confident curve.
No chart library — inline SVG or CSS bars. Readable at 360 px wide.

---

# Phase G — use it, then improve it

Once D and E work, **use the app as a learner for a while** on a phone-sized viewport, then think
hard about pedagogy, UX, latency and reliability. Implement what's clearly worth it; list the rest in
the README under "Ideas not built yet". Things worth weighing:

- **Latency.** The turn is STT → LLM → TTS, serial. Can the tutor's first sentence be synthesised
  while the rest is still being written? Is streaming the text worth the complexity on a phone?
- **Pedagogy.** Does the tutor actually recycle due vocab, or just mention it? Does it recover when
  he's silent? Does it ever explain the same thing twice because the mistake log didn't merge?
  Is the correction load right — two per turn can still be two too many when he's struggling?
- **Session shape.** A 5-minute "daily" flow (2 reviews + 1 scenario + 1 drill) may beat an open
  chat window for someone tired after work.
- **Reliability.** What happens mid-turn on a train, in a tunnel, on a 429, on an expired cookie?
- **Honesty.** Make it obvious when the transcript, not his German, was the problem.

---

# Checklist before handing back

- [ ] `pytest -q` green, no test needs a key or the network
- [ ] every phase exercised by hand with `LLM_PRIMARY=fake:fake`
- [ ] no API key, password or secret anywhere in the repo or in `static/`
- [ ] no new runtime dependency outside `requirements.txt` (and nothing paid)
- [ ] no CDN, no external font, no bundler — the CSP blocks all of it
- [ ] every new `/api` route has `Depends(auth.require_auth)`
- [ ] every new prompt is a file under `app/prompts/`, loaded with `render()`
- [ ] new columns are in `db.MIGRATIONS`, not edited into `CREATE TABLE`
- [ ] works at 360 px wide, one-handed, in dark mode
- [ ] `docs/HANDOVER.md` written: what you built, what you changed in the foundation, what you
      couldn't verify, what you want reviewed
