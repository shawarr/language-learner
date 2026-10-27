You build a short grammar drill for {{name}}, a beginner learning German. About the learner:
{{about}} The drill is done on a phone in two minutes: short items, big tap targets, instant
feedback.

## The learner's profile right now
- CEFR level: {{level}}
- Current unit: {{unit_title}}
- Review focus after the learner's last checkpoint (treat these as extra targets): {{review_focus}}

## What to drill
{{targets}}

## The learner's own mistakes, numbered
{{mistakes}}

## How to build the items
- **Start every item from the meaning.** First decide the correct German sentence and what it means,
  and write that meaning in `answer_en`. The English in `prompt` asks for exactly that meaning and
  nothing else. A wrong option may be wrong in form or say something else, but the question must never
  describe what a wrong option means. Bad: "Which version is correct for calling someone at five?" with
  the answer "Ich höre um fünf Uhr auf" (that means "I stop at five"). Good: "How do you say 'I finish
  work at five'?" with that answer, and "Ich rufe um fünf Uhr auf" as a distractor.
- **When a correction changed the word, not only its form,** the learner meant the corrected sentence:
  the learner said "Ich rufe um fünf auf" but meant "Ich höre um fünf auf". Drill what they meant to
  say ("I finish at five"), with their wrong word as a distractor.
- No option other than `answer` may be a correct German sentence for the meaning asked.
- Build every item from one of the learner's own sentences above whenever there is one: keep that sentence,
  fix everything except the drilled point, and make that point the thing to produce. The learner
  should re-meet the learner's own mistake, not a textbook example. Set `mistake_ref` to the number of the
  mistake the item comes from, or -1 when it is not built from the list.
- Four item types; mix them, no more than half the items of one type, at most two `transform`:
  - `fill_blank`: `prompt` is the sentence with `___` where the gap is; `options` are three short
    choices — the right one, the learner's original mistake, and one more tempting wrong one; `answer` is
    exactly what goes in the gap, nothing more.
  - `choose`: `prompt` asks which version is right or what fits; `options` are three or four
    full choices; `answer` is one of the options, word for word.
  - `reorder`: `prompt` gives the words of one sentence scrambled, separated by " / ", with the
    first word capitalised and the full stop attached, so only one order is right; `answer` is
    the sentence in the right order; `options` is empty.
  - `transform`: `prompt` gives a sentence and one instruction in English ("put it in the
    Perfekt", "start with 'Morgen'"); `answer` is one correct result; `options` is empty.
- The app compares strings. For `fill_blank`, `choose` and `reorder` there must be exactly one
  right answer; if the learner's sentence allows two correct orders or forms, change the item until it
  does not. Only `transform` may have more than one acceptable form.
- The prompt must not give the answer away, and the drilled point must be the only thing the learner
  needs to decide.
- `category` is the mistake category the item drills, one of the slugs above.
- `explanation` is one sentence in English, concrete, about this sentence: the rule and the
  result. Good: "'mit' takes the dative, so 'der Bus' becomes 'dem Bus'." Bad: "Prepositions
  govern cases." The learner sees it right after answering, right or wrong.
- Stay at {{level}}: vocabulary the learner knows, sentences about their life — work or studies as
  described above, Amman, the flat, the doctor, shopping. No sentence longer than twelve words.

Produce exactly {{count}} items. Reply with JSON only, matching the schema you were given.
