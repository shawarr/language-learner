/* Learn screen: the coursework, and the first thing a beginner should touch.

   The other tabs are practice, and practice assumes you were taught. This walks a unit as a
   sequence of short exercises: teaching pages (sounds, words, grammar) interleaved with practice
   generated from exactly what was just taught — match, listen, build from tiles, say it out loud,
   and the authored multiple-choice checks.

   One thing per screen, a bar at the top, instant feedback, nothing to type. Progress saves per
   exercise, so closing the app mid-lesson costs nothing. */
import { api, upload, audioFilename } from './api.js';
import { h, clear, toast, errorLine, skeleton, haptic, de } from './ui.js';
import { speak, prefetch, stop as stopAudio, unlockAudio } from './audio.js';
import { createHoldToTalk } from './mic.js';

const S = { body: null, bar: null, headUnit: null, unitId: null, lesson: null, list: [], i: 0,
  right: 0, asked: 0, seed: 0 };

export function mount(el) {
  const head = h('header', { class: 'screen-head' },
    h('h1', {}, 'Learn'),
    S.headUnit = h('span', { class: 'head-sub' }));
  S.bar = h('div', { class: 'lesson-bar' }, h('i'));
  S.body = h('div', { class: 'screen-body lesson' });
  clear(el).append(head, S.bar, S.body);
}

export async function show() { if (!S.list.length) await load(); }
export function hide() { stopAudio(); }

async function load() {
  clear(S.body).append(skeleton(4));
  try {
    const d = await api(`/api/lesson/current?seed=${S.seed}`);
    S.unitId = d.unit_id;
    S.lesson = d.lesson;
    S.headUnit.textContent = d.unit_title || '';
    if (!d.lesson) return renderMissing(d.detail);
    S.list = d.exercises || [];
    S.i = Math.min(d.progress?.step || 0, S.list.length);
    S.right = 0; S.asked = 0;
    render();
  } catch (e) {
    clear(S.body).append(errorLine(e, load));
  }
}

function renderMissing(detail) {
  clear(S.body).append(h('div', { class: 'card empty' },
    h('h2', {}, 'No written lesson for this unit yet'),
    h('p', { class: 'muted' }, detail || 'The practice modes still work.')));
}

function render() {
  const total = S.list.length;
  S.bar.firstChild.style.width = `${Math.round((Math.min(S.i, total) / total) * 100)}%`;
  clear(S.body);
  if (S.i === 0) S.body.append(introCard());
  else if (S.i > total) S.body.append(doneCard());
  else S.body.append(exerciseCard(S.list[S.i - 1], S.i, total));
  S.body.scrollTop = 0;
  // Warm the next step's audio while he reads this one — but only when there is something to say,
  // or the TTS endpoint gets a request with an empty text and answers 422.
  const next = S.list[S.i];
  const ahead = next && (next.audio || next.de || (next.items || [])[0]?.de || (next.examples || [])[0]?.de);
  if (ahead) prefetch(ahead);
}

function introCard() {
  const l = S.lesson;
  return h('div', { class: 'card lesson-intro' },
    h('div', { class: 'eyebrow' }, 'Lesson'),
    h('h2', {}, l.title),
    h('p', { class: 'lead' }, l.intro),
    h('p', { class: 'muted small' }, `${S.list.length} short steps${l.minutes ? ` · about ${l.minutes} minutes` : ''} · nothing to type`),
    h('button', { class: 'btn primary block lg', type: 'button', onClick: () => go(1) }, 'Start'));
}

function doneCard() {
  const l = S.lesson;
  const score = S.asked ? `${S.right} of ${S.asked} right` : null;
  return h('div', { class: 'card lesson-done' },
    h('div', { class: 'big-tick' }, '✓'),
    h('h2', {}, 'Lesson finished'),
    score ? h('p', { class: 'score' }, score) : null,
    h('p', { class: 'lead' }, l.outro || 'Now use it — the practice modes are where it sticks.'),
    h('button', { class: 'btn primary block lg', type: 'button', onClick: () =>
      document.dispatchEvent(new CustomEvent('dt:go-tab', { detail: 'talk' })) }, 'Practise it in Talk'),
    h('button', { class: 'btn ghost block', type: 'button', onClick: async () => {
      // The stored step never moves backwards, so going round again needs an explicit reset —
      // otherwise this button reloads straight back onto this card.
      S.seed += 1; S.list = [];
      await api(`/api/lesson/${S.unitId}/restart`, { method: 'POST' }).catch(() => {});
      await load();
    } }, 'Do the lesson again'));
}

/* ---- one exercise ----------------------------------------------------- */
function exerciseCard(ex, n, total) {
  const foot = h('div', { class: 'lesson-foot' });
  const advance = (label = 'Next') => clear(foot).append(
    h('button', { class: 'btn ghost', type: 'button', onClick: () => go(n - 1) }, 'Back'),
    h('span', { class: 'muted small' }, `${n} of ${total}`),
    h('button', { class: 'btn primary', type: 'button', onClick: () => go(n + 1) }, label));
  const waiting = (hint) => clear(foot).append(
    h('button', { class: 'btn ghost', type: 'button', onClick: () => go(n - 1) }, 'Back'),
    h('span', { class: 'muted small' }, `${n} of ${total}`),
    h('span', { class: 'muted small' }, hint));

  const render = {
    sounds: soundsStep, words: wordsStep, grammar: grammarStep,
    check: (e) => choiceStep(e, e.question, e.options, e.answer, e.why, { advance, waiting }),
    listen: listenStep, match: matchStep, build: buildStep, speak: speakStep,
  }[ex.type];
  const card = render(ex, { advance, waiting, n });
  if (ex.mode === 'teach' && ex.type !== 'check') advance();
  return h('div', { class: 'stack' }, card, foot);
}

/* ---- teaching pages --------------------------------------------------- */
function sayButton(text) {
  return h('button', { class: 'btn say small ghost', type: 'button', 'aria-label': `Play "${text}"`,
    onClick: (e) => { e.stopPropagation(); unlockAudio(); haptic(10); speak(text); } }, speakerIcon());
}

function line(item) {
  return h('div', { class: 'lesson-line', onClick: () => { unlockAudio(); speak(item.de); } },
    h('div', { class: 'lesson-line-main' },
      de(item.de, 'lesson-de'),
      h('div', { class: 'lesson-en' }, item.en || ''),
      item.note ? h('div', { class: 'lesson-note' }, item.note) : null),
    sayButton(item.de));
}

function soundsStep(step) {
  return h('div', { class: 'card' },
    h('div', { class: 'eyebrow' }, 'Sounds'),
    h('h2', {}, step.title),
    step.body ? h('p', { class: 'lead' }, step.body) : null,
    h('div', { class: 'lesson-lines' }, step.items.map((s) =>
      h('div', { class: 'lesson-line', onClick: () => { unlockAudio(); speak(s.example); } },
        h('div', { class: 'lesson-line-main' },
          h('div', {}, de(s.de, 'sound-letter'), h('span', { class: 'lesson-note inline' }, s.say)),
          h('div', { class: 'lesson-en' }, de(s.example, 'lesson-de sm'), ' — ', s.en)),
        sayButton(s.example)))),
    step.note ? h('p', { class: 'muted small' }, step.note) : null);
}

function wordsStep(step) {
  return h('div', { class: 'card' },
    h('div', { class: 'eyebrow' }, 'New words'),
    h('h2', {}, step.title),
    step.body ? h('p', { class: 'lead' }, step.body) : null,
    h('div', { class: 'lesson-lines' }, step.items.map(line)),
    step.note ? h('p', { class: 'muted small' }, step.note) : null);
}

function grammarStep(step) {
  const table = step.table ? h('table', { class: 'lesson-table' },
    h('thead', {}, h('tr', {}, step.table.head.map((c) => h('th', {}, c)))),
    h('tbody', {}, step.table.rows.map((r) => h('tr', {}, r.map((c, i) =>
      h('td', { class: i === 0 ? 'de-cell' : '', lang: i === 0 ? 'de' : 'en' }, c)))))) : null;
  return h('div', { class: 'card' },
    h('div', { class: 'eyebrow' }, 'How it works'),
    h('h2', {}, step.title),
    h('p', { class: 'lead' }, step.body),
    table,
    step.examples ? h('div', { class: 'lesson-lines' }, step.examples.map(line)) : null,
    step.note ? h('p', { class: 'muted small callout' }, step.note) : null);
}

/* ---- practice --------------------------------------------------------- */
function verdict(ok, detail) {
  S.asked += 1; S.right += ok ? 1 : 0;
  haptic(ok ? 10 : 25);
  const el = h('div', { class: `verdict ${ok ? 'ok' : 'no'}` },
    h('strong', {}, ok ? 'Richtig!' : 'Not quite.'), detail ? ' ' : null, detail || null);
  record(ok);
  return el;
}

function record(correct) {
  api(`/api/lesson/${S.unitId}/check`, { method: 'POST', body: { step: S.i, correct } }).catch(() => {});
}

function choiceStep(ex, question, options, answer, why, { advance, waiting }, { eyebrow = 'Check', audio = null } = {}) {
  const feedback = h('div', { class: 'check-feedback', hidden: true });
  const opts = h('div', { class: 'check-options' });
  let done = false;
  options.forEach((text, i) => {
    opts.append(h('button', { class: 'check-option', type: 'button', lang: audio ? 'de' : undefined, onClick: () => {
      if (done) return;
      done = true;
      const ok = i === answer;
      for (const [j, b] of [...opts.children].entries()) {
        b.disabled = true;
        if (j === answer) b.classList.add('right');
        else if (j === i) b.classList.add('wrong');
      }
      clear(feedback).append(verdict(ok, why || (ok ? '' : `It was “${options[answer]}”.`)));
      feedback.hidden = false;
      advance('Continue');
    } }, text));
  });
  waiting('Pick one');
  return h('div', { class: 'card' },
    h('div', { class: 'eyebrow' }, eyebrow),
    audio ? null : h('h2', { lang: 'en' }, question),
    audio ? h('div', { class: 'listen-head' },
      h('h2', {}, question),
      h('button', { class: 'btn play-big', type: 'button', 'aria-label': 'Play again',
        onClick: () => { unlockAudio(); speak(audio); } }, speakerIcon())) : null,
    opts, feedback);
}

function listenStep(ex, ctx) {
  // Play on arrival: the exercise is the audio, so making him tap first is a wasted step.
  setTimeout(() => { unlockAudio(); speak(ex.audio); }, 180);
  return choiceStep(ex, 'What do you hear?', ex.options, ex.answer,
    ex.en ? `“${ex.options[ex.answer]}” — ${ex.en}` : '', ctx, { eyebrow: 'Listen', audio: ex.audio });
}

function matchStep(ex, { advance, waiting }) {
  const feedback = h('div', { class: 'check-feedback', hidden: true });
  const pairFor = Object.fromEntries(ex.pairs.map((p) => [p.de, p.en]));
  let picked = null, solved = 0, wrong = 0;
  const leftCol = h('div', { class: 'match-col' });
  const rightCol = h('div', { class: 'match-col' });

  function tap(btn, side, value) {
    if (btn.classList.contains('done')) return;
    if (!picked) {
      clearSelection();
      picked = { btn, side, value };
      btn.classList.add('sel');
      if (side === 'de') { unlockAudio(); speak(value); }
      return;
    }
    if (picked.side === side) { clearSelection(); picked = { btn, side, value }; btn.classList.add('sel'); return; }
    const deWord = side === 'de' ? value : picked.value;
    const enWord = side === 'en' ? value : picked.value;
    if (pairFor[deWord] === enWord) {
      for (const b of [btn, picked.btn]) { b.classList.remove('sel'); b.classList.add('done'); b.disabled = true; }
      haptic(8);
      solved += 1;
      if (solved === ex.pairs.length) {
        clear(feedback).append(verdict(wrong === 0, wrong ? `${wrong} mix-up${wrong > 1 ? 's' : ''} on the way.` : ''));
        feedback.hidden = false;
        advance('Continue');
      }
    } else {
      wrong += 1;
      haptic(25);
      for (const b of [btn, picked.btn]) {
        b.classList.add('miss');
        setTimeout(() => b.classList.remove('miss'), 400);
      }
    }
    picked = null;
    clearSelection();
  }
  function clearSelection() { for (const b of [...leftCol.children, ...rightCol.children]) b.classList.remove('sel'); }

  for (const word of ex.left) leftCol.append(h('button', { class: 'match-tile', lang: 'de', type: 'button',
    onClick: (e) => tap(e.currentTarget, 'de', word) }, word));
  for (const word of ex.right) rightCol.append(h('button', { class: 'match-tile en', type: 'button',
    onClick: (e) => tap(e.currentTarget, 'en', word) }, word));

  waiting('Tap the pairs');
  return h('div', { class: 'card' },
    h('div', { class: 'eyebrow' }, 'Match'),
    h('h2', {}, 'Tap a German word, then its meaning'),
    h('div', { class: 'match-grid' }, leftCol, rightCol), feedback);
}

function buildStep(ex, { advance, waiting }) {
  const feedback = h('div', { class: 'check-feedback', hidden: true });
  const slot = h('div', { class: 'build-slot' });
  const bank = h('div', { class: 'build-bank' });
  const chosen = [];
  let done = false;

  const check = h('button', { class: 'btn primary block', type: 'button', disabled: true, onClick: () => {
    if (done || !chosen.length) return;
    done = true;
    const ok = chosen.join(' ') === ex.answer.join(' ');
    slot.classList.add(ok ? 'right' : 'wrong');
    clear(feedback).append(verdict(ok, ok ? '' : h('span', {}, 'It was ', de(ex.answer.join(' ')))));
    feedback.hidden = false;
    for (const b of bank.children) b.disabled = true;
    if (!ok) { unlockAudio(); speak(ex.answer.join(' ')); }
    advance('Continue');
  } }, 'Check');

  function sync() { check.disabled = chosen.length === 0 || done; }

  ex.tiles.forEach((word, i) => {
    const tile = h('button', { class: 'tile', lang: 'de', type: 'button', dataset: { i: String(i) }, onClick: () => {
      if (done) return;
      tile.hidden = true;
      chosen.push(word);
      const placed = h('button', { class: 'tile placed', lang: 'de', type: 'button', onClick: () => {
        if (done) return;
        placed.remove(); tile.hidden = false;
        chosen.splice(chosen.indexOf(word), 1);
        sync();
      } }, word);
      slot.append(placed);
      haptic(6);
      sync();
    } }, word);
    bank.append(tile);
  });

  waiting('Build the sentence');
  return h('div', { class: 'card' },
    h('div', { class: 'eyebrow' }, 'Build it'),
    h('h2', { lang: 'en' }, ex.en),
    ex.hint ? h('p', { class: 'muted small' }, ex.hint) : null,
    slot, bank, check, feedback);
}

function speakStep(ex, { advance, waiting }) {
  const feedback = h('div', { class: 'check-feedback', hidden: true });
  const heard = h('p', { class: 'heard', hidden: true });
  let done = false;

  const mic = createHoldToTalk({
    label: 'Hold and say it',
    onResult: async ({ blob, mime }) => {
      if (done) return;
      clear(feedback).append(h('span', { class: 'muted' }, 'listening…'));
      feedback.hidden = false;
      try {
        const res = await upload('/api/voice/transcribe', blob, audioFilename(mime));
        const said = res.text || '';
        heard.textContent = said ? `You said: ${said}` : 'Nothing came through.';
        heard.hidden = false;
        const ok = matches(ex.de, said);
        done = true;
        clear(feedback).append(verdict(ok, ok ? '' : 'Tap the speaker and try once more — close is fine.'));
        advance('Continue');
      } catch (e) {
        // Never block the lesson on the transcriber: speaking practice still happened.
        clear(feedback).append(h('span', { class: 'muted' }, 'Could not hear that one — carry on.'));
        advance('Skip');
      }
    },
  });

  waiting('Hold the button');
  return h('div', { class: 'card speak-card' },
    h('div', { class: 'eyebrow' }, 'Say it'),
    h('h2', {}, 'Say this out loud'),
    h('div', { class: 'speak-line' }, de(ex.de, 'lesson-de big'), h('div', { class: 'lesson-en' }, ex.en),
      h('button', { class: 'btn say small ghost', type: 'button', 'aria-label': 'Hear it',
        onClick: () => { unlockAudio(); speak(ex.de); } }, speakerIcon())),
    mic.el, heard, feedback);
}

/* Same generous rule as the server: a beginner's accent gets misheard constantly, and punishing
   that teaches him to stop speaking. */
function matches(expected, saidText) {
  const norm = (s) => s.toLowerCase().replace(/[.,!?;:—–"'„“]/g, '').split(/\s+/).filter(Boolean);
  const want = norm(expected), got = norm(saidText);
  if (!want.length) return false;
  const pool = [...got];
  let hit = 0;
  for (const w of want) { const i = pool.indexOf(w); if (i > -1) { pool.splice(i, 1); hit += 1; } }
  return hit / want.length >= 0.7;
}

/* ---- navigation ------------------------------------------------------- */
async function go(n) {
  const total = S.list.length;
  S.i = Math.max(0, Math.min(n, total + 1));
  stopAudio();
  render();
  try {
    if (S.i > total) {
      await api(`/api/lesson/${S.unitId}/complete`, { method: 'POST' });
      document.dispatchEvent(new CustomEvent('dt:lesson-done', { detail: S.unitId }));
    } else {
      await api(`/api/lesson/${S.unitId}/progress`, { method: 'POST', body: { step: S.i } });
    }
  } catch { /* progress is a convenience; never block the lesson on it */ }
}

function speakerIcon() {
  return h('span', { class: 'ico', html: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4zm13.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4zM15 3.2v2.1a6.8 6.8 0 0 1 0 13.4v2.1a8.9 8.9 0 0 0 0-17.6z"/></svg>' });
}
