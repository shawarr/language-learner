# Does the transcriber silently fix my German?

**Status: method ready, verdict pending real keys and real audio of Ahmad's voice.**
Run on the server (the only place with the keys), then fill in §3 and set `STT_PROVIDER` in `.env`.

## 1. Why this matters

Whisper is trained to produce fluent, well-formed text. Fed a learner saying
*"ich habe gestern in die Stadt gegangen"*, it is perfectly capable of writing
*"ich bin gestern in die Stadt gegangen"* — the right German, and the wrong transcript. If that
happens, the mistake never reaches the analyzer, never reaches the mistake log, never reaches a
drill, and the app quietly stops teaching the one thing it exists to teach. The learner also sees a
corrected sentence and concludes he said it correctly.

Two things in the foundation hedge against it:

- `WHISPER_PROMPT` is **empty by default** and a test asserts it (`test_whisper_prompt_is_empty_by_default`).
  A Whisper `prompt` is a style example: a prompt written in clean German is an instruction to
  produce clean German. Leave it empty.
- `temperature=0`, `language="de"`, `response_format=json` — no creative latitude, no language
  guessing (language auto-detection on broken German sometimes lands on Dutch).

## 2. The method

```bash
# on the server, with GROQ_API_KEY and GEMINI_API_KEY in .env
.venv/bin/python scripts/stt_compare.py clip.m4a --expect "ich habe gestern in die stadt gegangen"
.venv/bin/python scripts/stt_compare.py samples/      # a directory, with a sidecar clip.txt per clip
```

It runs both engines on the same audio and prints a word-level diff against what you actually said:
`-expected  +what the engine produced`. Anything the engine "improved" shows up as a diff pair.

Record **at least 8 clips in Ahmad's own voice**, each containing a deliberate, specific error, and
write the exact words said into the sidecar `.txt`. Suggested set — one per common category, because
engines fix some error types far more eagerly than others:

| # | Say (deliberately wrong) | Error type | What a "fixing" engine would write |
|---|---|---|---|
| 1 | ich habe gestern in die Stadt gegangen | verb_conjugation (haben/sein) | ich **bin** gestern … |
| 2 | ich fahre mit den Bus zur Arbeit | case after `mit` | mit **dem** Bus |
| 3 | das Termin ist am Montag | gender | **der** Termin |
| 4 | ich habe ein Problem mit die Heizung | case/article | mit **der** Heizung |
| 5 | gestern ich habe viel gearbeitet | word_order | gestern **habe ich** … |
| 6 | ich muss nach Hause gehen weil ich bin müde | subordinate word order | … weil ich müde **bin** |
| 7 | ich spreche nicht gut Deutsch, ähm, ich lerne noch | fillers | (ähm dropped) |
| 8 | ich habe das Deployment gemacht, es war ein outage | English word mid-sentence | translated or dropped |

Also record one clip at normal conversational speed with a mild accent and no deliberate error, to
check the engines aren't inventing errors (a false positive is just as damaging: the app would drill
a mistake he never made).

Judge on: **mistakes preserved** (the main criterion), fillers preserved, English words left as
English, no invented errors, latency, and quota cost.

## 3. Results

_To fill in after the run:_

| Clip | Error type | Groq `whisper-large-v3` | Gemini verbatim | Preserved? |
|---|---|---|---|---|
| 1 | | | | |

**Verdict:** _which engine preserves mistakes better, and the `STT_PROVIDER` value set as a result._

**Latency:** _measured seconds per 10 s clip, both engines._

**Notes:** _anything surprising — e.g. one engine strong on word order but keen to fix articles._

## 4. If both engines turn out to fix grammar

Fallbacks, in order of preference:

1. Keep the better engine and let the **analyzer judge the audio**, not the transcript: Gemini Flash
   accepts inline audio (already wired — `LLMRequest.audio`), so the analysis call can hear the
   original. Costs no extra request; the transcript stays what the learner sees.
2. Ask the transcriber for both: a verbatim transcript *and* its own corrected version, and keep the
   divergence as a mistake signal.
3. Accept the loss on pronunciation/endings and rely on the Write and Drill modes for the grammar
   signal — the weakest option, and the one to argue against.

Whatever the outcome: **the app always shows the raw transcript**, so a transcription artefact is
visible as such and never silently becomes "Ahmad's German".
