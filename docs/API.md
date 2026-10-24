# API contract

Every route below lives under `/api`, needs the session cookie (`Depends(auth.require_auth)`), and
returns JSON. Errors are `{"detail": "...", "retryable": bool}`; a 503 with `retryable: true` means
"the tutor is busy, try again in a minute" and the client must keep whatever the user typed or
recorded. The frontend is written against this file; a backend change here is a contract change.

Shapes marked **(spec)** are copied from `docs/TASKS.md` verbatim.

## Foundation (exists)

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/auth/users` | — | `{"users": [{"id","username","name","gender","avatar"}], "avatars": [id…]}` — public, for the login picker; nothing secret |
| POST | `/auth/login` | `{"username", "password"}` | `{"ok": true, "user": {…}}` + cookie naming the user |
| POST | `/auth/logout` | — | `{"ok": true}` |
| GET | `/auth/me` | — | `{"ok": true, "user": {…}, "avatars": […]}` / 401 |
| POST | `/auth/avatar` | `{"avatar": "katze-3"}` | `{"ok": true, "user": {…}}`; 422 for an unknown id |
| GET | `/system/status` | — | models/voices/keys present |
| GET | `/tts?text=&speed=normal|slow` | — | audio/mpeg (cached) |
| POST | `/voice/transcribe` | multipart `file`, `compare` | `{"text","provider","model"}` |

## Curriculum (C2)

- `GET /curriculum` → `{"version", "phases": [{"id","level","title","units":[unit…]}], "current": {"phase_id","unit_id","level","placement_done"}}`
- `GET /curriculum/current` → `{"phase": {"id","level","title"}, "unit": unit, "unit_index": 2, "unit_count": 5, "scenarios": [scenario…], "next_unit": unit|null, "checkpoint_available": bool}`

`unit = {"id","title","can_do":[…],"grammar":[…],"vocab_themes":[…],"scenarios":[…]}` (checkpoint
tasks are stripped). `scenario = {"id","title","setup","goal"}`.

### Placeholders and variants

`units.json` and `lessons.json` never name a learner. Their text says `{{name}}`, `{{work}}`,
`{{role_de}}`, `{{city}}` and `{{he}}`/`{{him}}`/`{{his}}`/`{{himself}}`, which render from the
persona's gender (she/her/her/herself for Maryan); a capitalised token (`{{He}}`) capitalises the
value, and any other placeholder fails validation at startup. A scenario or checkpoint task that
only fits one kind of learner carries `"variants": {"student": {…}}`, keyed by the persona's `kind`
in `personas.json`: a scenario variant needs `title`, `setup` and `goal`; a task variant needs
`prompt` and may add `hint`. Everything above is rendered for the logged-in user — placeholders
filled, the matching variant's fields over the defaults, the `variants` key dropped — so the shapes
do not change and a scenario keeps its `id` for both learners. Lessons follow the same rules via
`curriculum.lesson_for_user`.

## Talk (A2, V1)

- `POST /talk/session` `{"scenario_id": "a1.1-1-smalltalk"?}` → `{"session": session, "opening_turn": turn}`
- `POST /talk/turn` — JSON `{"session_id", "text"}` **or** multipart `session_id`, `file` → `turn`
- `POST /talk/session/{id}/end` → `{"summary": "...", "analyzed": bool}` (`analyzed: false` when the
  analyzer could not run; the session is still closed)
- `GET /talk/session/{id}` → `{"session": session, "messages": [message…]}`
- `GET /talk/sessions?limit=20` → `{"sessions": [session…]}` (newest first)

```json
turn = {"user_message_id": 41, "message_id": 42, "reply": "…", "meaning_en": "what the reply means, in English",
        "corrections": [{"wrong","right","category","explanation"}],
        "praise": null, "english_help": {"english","german","literal"}|null,
        "new_vocab": [{"word","translation","example"}], "scenario_done": false,
        "transcript": null|"raw STT text", "transcript_provider": null|"groq"}
```
`opening_turn` has `user_message_id: null`. `session = {"id","mode","scenario_id","scenario_title","unit_id","started_at","ended_at","summary","user_turns","meta"}`.
`message = {"id","role","content","meaning_en","transcript_raw","input_kind","correction":[…]|null,"english_help":{…}|null,"stt_provider","llm_model","created_at"}`
(`meaning_en` is the English meaning of a tutor reply, rendered under the bubble and never spoken.
It is null on user rows and on replies stored before it existed, so treat it as optional.)
(`correction` on an assistant row holds the corrections of the user message before it; the client
renders them under that user message). The client shows `transcript` **verbatim**, never a cleaned
version. An empty transcript → `400`, no rows written.

## Vocab (A5, D2)

- `POST /vocab/translate` `{"word", "context"}` → `{"word","lemma","translation","pos","note","in_vocab": bool}` **(spec)** — cached by lowercase surface form, `tier="fast"`.
- `POST /vocab` `{"word","translation","example"?,"source"?}` → `{"id","word","created": bool}` (upsert, `due = now`, never resets SRS state)
- `GET /vocab/due?limit=20` → `{"cards": [card…], "due_count": n}` — oldest due first, new cards interleaved, ≤10 new per queue
- `POST /vocab/{id}/review` `{"rating": 1|2|3|4}` → `card` (new state)
- `GET /vocab?q=&sort=due|word|created&limit=` → `{"items": [card…], "total": n}`
- `DELETE /vocab/{id}` → `{"ok": true}`

`card = {"id","word","translation","example","notes","source","due","interval_days","ease","reps","lapses","last_review","created_at","is_new": bool}`

## Placement (C3)

- `POST /placement/start` → `{"session_id", "tasks": [task…]}`; `task = {"id","kind":"speak"|"write","title","instruction_en","prompt_de"}` (3 speaking tasks of rising difficulty, then 1 written)
- `POST /placement/answer` — JSON `{"session_id","task_id","text"}` or multipart `session_id`,`task_id`,`file` → `{"task_id","text","transcript_provider": null|"groq"}` (the text is the raw transcript)
- `POST /placement/finish` `{"session_id"}` → `placement_result`; idempotent (a second call returns the stored result, writes nothing)
- `POST /placement/skip` → `placement_result` with level `A1.1`

```json
placement_result = {"level": "A1.2", "unit": unit, "phase": {"id","level","title"}, "skills": {"speaking":…},
                    "explanation": "English, where he landed and why", "strengths": [str], "gaps": [str], "skipped": bool}
```

## Checkpoint (C4)

- `GET /checkpoint/current` → `{"available": bool, "reason": "ready"|"sessions"|"not_yet", "unit": unit, "phase": {…}, "checkpoint_id": int|null, "tasks": {"speaking": {"prompt","hint"?}, "writing": {"prompt","hint"?,"words_min","words_max"}}, "sessions_in_unit": n, "sessions_needed": n, "last_result": result|null}`
  (`checkpoint_id` is set only when available: an unfinished row is created or reused)
- `POST /checkpoint/{id}/submit` — multipart `writing_text` + (`file` speaking audio **or** `speaking_text`) → `result`

```json
result = {"passed": bool, "scores": {"task_completion": {"score": 1-5, "comment"}, "range": {…}, "accuracy": {…}, "fluency": {…}},
          "summary": "English, two sentences", "review_focus": [str], "speaking_transcript": "raw",
          "advanced_to": {"phase": {…}, "unit": unit, "phase_changed": bool}|null, "finished_curriculum": bool}
```

## Write (D1)

- `GET /write/prompt` → `{"task": "English instructions incl. who it's to and what it must achieve", "to": "…", "must_include": [str], "words_min": 40, "words_max": 80, "unit_id"}`
- `POST /write/submit` `{"prompt": "<the task text>", "text"}` → `{"id","corrections": [{"wrong","right","category","explanation"}], "improved", "score": 1-5, "strengths", "next_time"}` **(spec)**
- `GET /write/recent?limit=10` → `{"items": [{"id","prompt","text","feedback","score","created_at"}]}`

## Drill (D3)

- `GET /drill/new?n=8` → `{"id", "categories": [slug…], "items": [{"index","type":"fill_blank"|"choose"|"reorder"|"transform","prompt","options": [str]|null,"category"}]}` — answers and explanations withheld
- `POST /drill/{id}/answer` `{"index","answer"}` → `{"index","correct": bool,"answer": "the right one","your_answer","explanation","finished": bool,"score": n|null,"total": n}` — instant per-item feedback; grades locally when exact, model (`tier="fast"`) only for free-text `transform` items
- `POST /drill/{id}/submit` `{"answers": [str|null…]}` → `{"results": [{"index","correct","answer","your_answer","explanation"}], "score", "total"}`

A correct answer bumps `mistakes.resolved` for the item's source mistake; a wrong one bumps `count`.

## Progress (E)

- `GET /progress` → **(spec)** plus a few honesty fields:

```json
{"profile": {"name","level","unit_id","placement_done","rolling_summary"}, "phase": {…}, "unit": unit, "unit_index": 3, "unit_count": 5,
 "skills": {"speaking": 0-100, …}, "streak_days": 7, "activity": [{"day": "2026-10-01", "talk_turn": 14, "review": 20, …}],
 "top_mistakes": [{"id","category","pattern","count","resolved","examples","trend": "improving"|"not_yet"}],
 "beaten_mistakes": [{…}], "vocab": {"total": 210, "due": 18, "mature": 90, "new": 12},
 "recent_sessions": [session…], "checkpoint": {"available": bool, "unit_id": "a1.1-4", "reason": "…"},
 "sessions_total": n, "thin_data": bool}
```
`thin_data` is true under four sessions — the UI says "not enough data yet" instead of drawing a curve.
`activity` covers the last 30 days, oldest first, one entry per day (zeros included).


## Learn (coursework)

The teaching, before any practice mode. Lessons are hand-written in `app/curriculum/lessons.json`,
keyed by unit id — never model-generated, so a beginner's first contact with German is identical
every time, correct, and free of quota.

- `GET /lesson/current?seed=0` → `{"unit_id","unit_title","lesson",{…}|null,"exercises":[…],"progress","detail"?}` —
  `exercises` is what the client walks: the authored teaching with generated practice interleaved.
  Same `seed` gives the same sequence (a refresh must not reshuffle mid-exercise); a different seed
  is a different run. —
  `lesson: null` with a `detail` when that unit's coursework is not written yet; the tab says so
  rather than 404-ing.
- `GET /lesson/status` → `{"has_lesson","completed","step","steps","title","minutes"}` — what the
  shell uses to decide the landing tab.
- `GET /lesson/{unit_id}` → `{"unit_id","lesson","progress"}` (404 if none)
- `POST /lesson/{unit_id}/progress` `{"step"}` → progress. Never moves backwards: re-reading an
  earlier page is not losing progress.
- `POST /lesson/{unit_id}/check` `{"step","correct"}` → progress (counts only; the answer is graded
  on the device)
- `POST /lesson/{unit_id}/restart` → progress with `step: 0`, keeping `completed`. Needed because
  `progress` never moves backwards, so "do the lesson again" would otherwise reload onto the
  finished card.
- `POST /lesson/{unit_id}/complete` → progress. Idempotent; keeps the first completion time.

```
exercise = teaching step (mode "teach") or one of, all mode "practise":
  match   {"pairs":[{"de","en"}],"left":[de…],"right":[en…]}   columns deranged: no row holds its own answer
  listen  {"audio","options":[de…],"answer": <index>,"en"}      plays on arrival
  build   {"en","hint","answer":[word…],"tiles":[word…]}        tiles = the sentence plus one decoy
  speak   {"de","en"}                                           graded via /voice/transcribe, 70% of words
```

```
lesson = {"title","intro","outro","minutes","steps": [step…]}
step   = {"type": "sounds"|"words"|"grammar"|"check", …}
  sounds  {"title","body","items":[{"de","say","example","en"}],"note"}
  words   {"title","body","items":[{"de","en","note"}],"note"}
  grammar {"title","body","table":{"head":[…],"rows":[[…]]},"examples":[{"de","en","note"}],"note"}
  check   {"question","options":[…],"answer": <index>,"why"}
```

## Game and leaderboard (M3)

XP is derived from the `activity` counters every mode already bumps, so nothing new is written when
a learner earns points. Points per count: talk_turn 10, review 2, drill 15, write 25, checkpoint 60,
lesson 40. Level n starts at 100·n·(n−1)/2 XP (1 at 0, 2 at 100, 3 at 300, 4 at 600, 5 at 1000…);
titles: 1 Newcomer, 2–3 Tourist, 4–5 Neighbour, 6–7 Colleague, 8–9 Local, 10+ Fluent-ish. Days and
weeks are UTC; the week starts Monday 00:00. The three rings per day: `speak` (talk turns, 5),
`review` (reviews, 10), `study` (lesson + drill + write + checkpoint, 1). The streak rule is the
progress page's: consecutive days ending today, or yesterday when today is still empty. Only the
`badges` table is written to, by `/game/me`.

- `GET /game/me` → evaluates badges first, so one earned by the last action is already in
  `new_badges` when the page opens.
  ```
  {"xp_total": 130, "xp_today": 30, "xp_week": 90,
   "level": {"n": 2, "title": "Tourist", "xp_into_level": 30, "xp_for_next": 200, "fraction": 0.15},
   "streak_days": 3,
   "goals": {"speak": {"done": 3, "target": 5, "fraction": 0.6},
             "review": {"done": 10, "target": 10, "fraction": 1.0},
             "study": {"done": 0, "target": 1, "fraction": 0.0}},
   "rings_closed": 1,
   "badges": [{"id": "first_talk", "title": "First words", "description": "…", "icon": "mic",
               "earned_at": 1761048000.0, "seen": 0}],          // earned only, oldest first
   "new_badges": ["first_talk"],                                // earned and not yet shown
   "catalogue": [{"id", "title", "description", "icon"}…]}     // every badge, for the locked grid
  ```
  `fraction` is capped at 1. Icons are slugs the client maps to SVGs: mic, flame, book, star,
  trophy, cat. Badges: first_talk, first_lesson, streak_3, streak_7, streak_30, xp_500, xp_2000,
  words_50, words_200 (vocab with interval ≥ 21 days), checkpoint_first, units_5 (passed
  checkpoints), drill_clean (a finished drill with every item right), early_week (all three rings
  on one day). A badge is never taken away.
- `POST /game/seen` `{"badge_ids": ["first_talk"]}` → `{"ok": true}` — the client has shown the
  full-screen moment once; small wins are quiet lines (docs/DESIGN.md).
- `GET /leaderboard` → every learner, totals only, never a mistake or a transcript. Sorted by
  `xp_week` desc, then `xp_total` desc.
  ```
  {"week_start": "2026-10-19", "me": 1,
   "users": [{"id": 2, "name": "Maryan", "avatar": "katze-1", "gender": "f",
              "xp_week": 80, "xp_total": 80, "level": {"n": 1, "title": "Newcomer"},
              "streak_days": 1, "cefr_level": "A1.2", "units_passed": 1, "words_mature": 0,
              "rings_closed_today": 2, "badges_count": 1}, …]}
  ```
