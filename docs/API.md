# API contract

Every route below lives under `/api`, needs the session cookie (`Depends(auth.require_auth)`), and
returns JSON. Errors are `{"detail": "...", "retryable": bool}`; a 503 with `retryable: true` means
"the tutor is busy, try again in a minute" and the client must keep whatever the user typed or
recorded. The frontend is written against this file; a backend change here is a contract change.

Shapes marked **(spec)** are copied from `docs/TASKS.md` verbatim.

## Foundation (exists)

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/auth/login` | `{"password"}` | `{"ok": true}` + cookie |
| POST | `/auth/logout` | — | `{"ok": true}` |
| GET | `/auth/me` | — | 200 / 401 |
| GET | `/system/status` | — | models/voices/keys present |
| GET | `/tts?text=&speed=normal|slow` | — | audio/mpeg (cached) |
| POST | `/voice/transcribe` | multipart `file`, `compare` | `{"text","provider","model"}` |

## Curriculum (C2)

- `GET /curriculum` → `{"version", "phases": [{"id","level","title","units":[unit…]}], "current": {"phase_id","unit_id","level","placement_done"}}`
- `GET /curriculum/current` → `{"phase": {"id","level","title"}, "unit": unit, "unit_index": 2, "unit_count": 5, "scenarios": [scenario…], "next_unit": unit|null, "checkpoint_available": bool}`

`unit = {"id","title","can_do":[…],"grammar":[…],"vocab_themes":[…],"scenarios":[…]}` (checkpoint
tasks are stripped). `scenario = {"id","title","setup","goal"}`.

## Talk (A2, V1)

- `POST /talk/session` `{"scenario_id": "a1.1-1-smalltalk"?}` → `{"session": session, "opening_turn": turn}`
- `POST /talk/turn` — JSON `{"session_id", "text"}` **or** multipart `session_id`, `file` → `turn`
- `POST /talk/session/{id}/end` → `{"summary": "...", "analyzed": bool}` (`analyzed: false` when the
  analyzer could not run; the session is still closed)
- `GET /talk/session/{id}` → `{"session": session, "messages": [message…]}`
- `GET /talk/sessions?limit=20` → `{"sessions": [session…]}` (newest first)

```json
turn = {"user_message_id": 41, "message_id": 42, "reply": "…", "corrections": [{"wrong","right","category","explanation"}],
        "praise": null, "english_help": {"english","german","literal"}|null,
        "new_vocab": [{"word","translation","example"}], "scenario_done": false,
        "transcript": null|"raw STT text", "transcript_provider": null|"groq"}
```
`opening_turn` has `user_message_id: null`. `session = {"id","mode","scenario_id","scenario_title","unit_id","started_at","ended_at","summary","user_turns","meta"}`.
`message = {"id","role","content","transcript_raw","input_kind","correction":[…]|null,"english_help":{…}|null,"stt_provider","llm_model","created_at"}`
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
