# Does the transcriber silently fix my German?

**Run on the server with live keys, 2026-10-03. Verdict: `STT_PROVIDER=groq`.**
The pitfall is real, but much narrower than feared — and the part that does leak through has a
mitigation that costs nothing.

## 1. Why this matters

Whisper is trained to produce fluent, well-formed text. Fed a learner saying
*"ich habe gestern in die Stadt gegangen"*, it is perfectly capable of writing
*"ich bin gestern in die Stadt gegangen"* — the right German, and the wrong transcript. If that
happens, the mistake never reaches the analyzer, never reaches the mistake log, never reaches a
drill, and the app quietly stops teaching the one thing it exists to teach. The learner also sees a
corrected sentence and concludes he said it correctly.

Two things in the foundation hedge against it:

- `WHISPER_PROMPT` is **empty by default** and a test asserts it
  (`test_whisper_prompt_is_empty_by_default`). A Whisper `prompt` is a style example: a prompt
  written in clean German is an instruction to produce clean German. Leave it empty.
- `temperature=0`, `language="de"`, `response_format=json` — no creative latitude, no language
  guessing (auto-detection on broken German sometimes lands on Dutch).

## 2. Method

11 clips of German, each containing one deliberate, unambiguous error (plus one correct control),
synthesised with four different edge-tts voices at `-15%` rate, then put through both engines and
diffed word-by-word against the exact text spoken.

```bash
.venv/bin/python scripts/make_stt_clips.py     # -> samples/*.mp3 + .txt + .category sidecars
.venv/bin/python scripts/stt_compare.py samples/
```

### Re-running it with a real voice (3 minutes, from the phone)

The app has a transcription lab at **`/lab.html`** so this does not require recording voice memos
and moving files to the server. Log in to the app, open `/lab.html`, type the sentence you are about
to say, hold to record, read it aloud — it tells you per engine whether the transcript came back
verbatim. The eight sentences are listed on the page. Each sample is saved with both transcripts to `DATA_DIR/stt-lab/`, then:

```bash
.venv/bin/python scripts/stt_lab_report.py data/stt-lab
```

It prints the word-level diff per engine and a "mistakes preserved exactly" tally. Read the eight
sentences in the table below in your own voice and the caveat under it goes away.

**Caveat, stated plainly:** synthesised speech is not Ahmad's accent. What this design *does* test
cleanly is the thing we actually fear — the words are unambiguous in the audio, so any difference in
the transcript is the engine editing rather than mishearing. Accent robustness still needs real
recordings; re-run `stt_compare.py` against his own voice once there are a few sessions' worth, and
append the results here.

## 3. Results — Groq `whisper-large-v3`, no prompt, `language=de`

**8 of 11 clips transcribed exactly as spoken. Average latency 0.35 s.**

| Clip | Category | Said | Transcribed | Preserved? |
|---|---|---|---|---|
| 01 | verb_conjugation | Ich **habe** gestern in die Stadt gegangen. | identical | ✅ |
| 02 | case | Ich fahre mit **den** Bus zur Arbeit. | mit **dem** Bus | ❌ **fixed** |
| 03 | gender | **Das** Termin ist am Montag. | identical | ✅ |
| 04 | case | Ich habe ein Problem mit **die** Heizung. | identical | ✅ |
| 05 | word_order | **Gestern ich habe** viel gearbeitet. | identical | ✅ |
| 06 | word_order | …weil **ich bin müde**. | identical | ✅ |
| 07 | fillers | …Deutsch, **ähm**, ich lerne noch. | identical | ✅ |
| 08 | vocabulary | …es war ein **outage**. | ein "**Autage**" | ⚠️ misheard, not corrected |
| 09 | adjective_ending | in **eine klein** Wohnung | in **einer Klein**wohnung | ❌ **fixed** |
| 10 | negation | Ich habe **nicht** Zeit heute Abend. | identical | ✅ |
| 11 | *control: correct German* | Ich arbeite als DevOps-Ingenieur… | identical | ✅ no invented error |

### The pattern, and it is a sharp one

Whisper **does not restructure sentences**. Every structural error survived: the wrong auxiliary
(`habe gegangen`), wrong gender (`das Termin`), inverted word order (`Gestern ich habe`), the
un-inverted subordinate clause (`weil ich bin müde`), wrong negation, and the filler `ähm`. It also
invented nothing on the correct control.

What it *does* repair is **unstressed inflection where the wrong and right forms are nearly
homophonous**: `den`→`dem`, `eine klein`→`einer Klein`. In fast speech those differ by a single
reduced vowel, so the model resolves the acoustic ambiguity using its prior — which is correct
German. It is not "fixing grammar"; it is guessing a mumbled syllable and guessing it right.

That is a narrow leak, but an awkward one: case and adjective endings are exactly where a beginner
lives. Hence the mitigation in §5.

Clip 08 is worth noting separately: the English word "outage" came back as "Autage". Not a
correction — a genuine mishearing of English inside German audio, with `language=de` set. Expect
English technical words in Ahmad's speech (he's a DevOps engineer) to come back mangled. That is a
transcription artefact and must never be logged as a vocabulary mistake; the prompt in
`app/prompts/tutor_talk.md` already says to ignore obvious speech-to-text noise.

## 4. Results — Gemini verbatim transcription

Where it ran, the strict verbatim instruction worked **perfectly** — 4 for 4, including the one
clip Whisper repaired:

| Clip | Said | Gemini wrote | |
|---|---|---|---|
| 01 | Ich **habe** … gegangen | identical | ✅ |
| 05 | **Gestern ich habe** viel gearbeitet | identical | ✅ |
| 01 (re-probe) | Ich **habe** … gegangen | identical | ✅ |
| 02 | Ich fahre mit **den** Bus | mit **den** Bus — **kept, where Whisper wrote "dem"** | ✅ |

So on faithfulness Gemini is the better engine, and the reason is structural rather than lucky: it
has no acoustic guess to make. Whisper decodes phonemes and resolves a mumbled `den`/`dem` with a
prior trained on correct German; Gemini reads the utterance as a whole. That is also why it is the
right engine for the §5 mitigation — it is specifically good at the thing Whisper is specifically
bad at.

It is nonetheless **unusable as the primary engine**, for two measured reasons:

- **4.5 – 8.6 s per clip** against Groq's 0.35 s. That is more than ten times slower, on the one
  call sitting directly between the learner releasing the mic and the tutor answering.
- **Free-tier quota makes it unreliable at conversation rate.** A full 11-clip pass could not
  complete: every clip returned 429 even with 20-second backoffs between attempts, because
  `gemini-3.8-flash`'s free allowance turns out to be **20 requests per day** (confirmed from the
  429 body: `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, `quotaValue: "20"`,
  `retryDelay: 75941s`). `GEMINI_STT_MODEL` was moved to `gemini-3.5-flash-lite`, which has a
  usable allowance and transcribed clip 01 verbatim and correctly.

So Gemini stays where its strengths pay and its weaknesses don't: the automatic STT fallback, and
the audio-aware analysis path in §5 — a call that happens once every eight turns, not once a turn.

## 5. The mitigation — audio-aware analysis, at no extra cost

Since the leak is confined to endings that Whisper can't hear reliably, the fix is to let the
analyzer hear the original audio rather than only the transcript:

Direct evidence for this, from the lab: on the clip where Whisper wrote `mit dem Bus`, Gemini
returned `mit den Bus` from the same audio. The error is recoverable — it just needs the engine
that can hear it.

- `LLMRequest(audio=..., audio_mime=...)` is already wired, and `complete_json` accepts
  `audio`/`audio_mime`. The Gemini path re-encodes browser recordings to 16 kHz mono mp3 with ffmpeg
  automatically.
- The analyzer runs once every 8 turns, not per turn, so attaching audio costs **no extra request** —
  it is the same call, and latency there is invisible to the conversation.
- The transcript stays what the learner sees; the audio is the ground truth for endings and
  pronunciation.

Specified as a requirement for the analyzer in `docs/TASKS.md` task A3.

## 6. Settings this produced

```bash
STT_PROVIDER=groq              # 0.35s, preserves structural errors, invents nothing
GROQ_STT_MODEL=whisper-large-v3
WHISPER_PROMPT=                # must stay empty
GEMINI_STT_MODEL=gemini-3.5-flash-lite   # fallback + audio-aware analysis (NOT 3.8-flash: 20/day)
```

And one product rule that follows from clip 02 and clip 08 together: **the app always shows the raw
transcript**, so when the transcriber is the one at fault it is visible as such and never silently
becomes "Ahmad's German". The Talk screen also gives him a way to say "that's not what I said" and
discard the turn (`docs/DESIGN.md` §4).
