/* Learn screen: the coursework, and the first thing a beginner should touch.

   The other four tabs are practice, and practice assumes you were taught. This walks one unit's
   lesson a step at a time — sounds, words, grammar, and a check between them — with every German
   line playable. One idea per screen, a progress bar at the top, and nothing to type.

   Progress is saved on every step, so closing the app mid-lesson costs nothing. */
import { api } from './api.js';
import { h, clear, toast, errorLine, skeleton, haptic, de } from './ui.js';
import { speak, prefetch, stop as stopAudio, unlockAudio } from './audio.js';

const S = { body: null, bar: null, head: null, unitId: null, lesson: null, i: 0, answered: null };

export function mount(el) {
  S.head = h('header', { class: 'screen-head' }, h('h1', {}, 'Learn'), S.headUnit = h('span', { class: 'head-sub' }));
  S.bar = h('div', { class: 'lesson-bar' }, h('i'));
  S.body = h('div', { class: 'screen-body lesson' });
  clear(el).append(S.head, S.bar, S.body);
}

export async function show() { if (!S.lesson) await load(); }
export function hide() { stopAudio(); }

async function load() {
  clear(S.body).append(skeleton(4));
  try {
    const d = await api('/api/lesson/current');
    S.unitId = d.unit_id;
    S.lesson = d.lesson;
    S.headUnit.textContent = d.unit_title || '';
    if (!d.lesson) return renderMissing(d.detail);
    // Resume where he stopped, but never on the "finished" card — that would hide the lesson.
    S.i = Math.min(d.progress?.step || 0, d.lesson.steps.length);
    if (d.progress?.completed && S.i >= d.lesson.steps.length) S.i = d.lesson.steps.length;
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
  const total = S.lesson.steps.length;
  S.bar.firstChild.style.width = `${Math.round((Math.min(S.i, total) / total) * 100)}%`;
  S.answered = null;
  clear(S.body);
  if (S.i === 0) S.body.append(introCard());
  else if (S.i > total) S.body.append(doneCard());
  else S.body.append(stepCard(S.lesson.steps[S.i - 1], S.i, total));
  S.body.scrollTop = 0;
  prefetchNext();
}

/* Speaking the next step's first line while he reads this one: by the time he taps, it is cached. */
function prefetchNext() {
  const next = S.lesson.steps[S.i];
  if (!next) return;
  const first = (next.items || []).find((x) => x.de) || (next.examples || []).find((x) => x.de);
  if (first) prefetch(first.de);
}

function introCard() {
  const l = S.lesson;
  return h('div', { class: 'card lesson-intro' },
    h('div', { class: 'eyebrow' }, 'Lesson'),
    h('h2', {}, l.title),
    h('p', { class: 'lead' }, l.intro),
    h('p', { class: 'muted small' }, `${l.steps.length} short pages${l.minutes ? ` · about ${l.minutes} minutes` : ''} · nothing to type`),
    h('button', { class: 'btn primary block lg', type: 'button', onClick: () => go(1) }, 'Start the lesson'));
}

function doneCard() {
  const l = S.lesson;
  return h('div', { class: 'card lesson-done' },
    h('div', { class: 'big-tick' }, '✓'),
    h('h2', {}, 'Lesson finished'),
    h('p', { class: 'lead' }, l.outro || 'Now use it — the practice modes are where it sticks.'),
    h('button', { class: 'btn primary block lg', type: 'button', onClick: () => {
      document.dispatchEvent(new CustomEvent('dt:go-tab', { detail: 'talk' }));
    } }, 'Practise it in Talk'),
    h('button', { class: 'btn ghost block', type: 'button', onClick: () => go(1) }, 'Read the lesson again'));
}

function stepCard(step, n, total) {
  const foot = h('div', { class: 'lesson-foot' },
    h('button', { class: 'btn ghost', type: 'button', onClick: () => go(n - 1) }, 'Back'),
    h('span', { class: 'muted small' }, `${n} of ${total}`),
    step.type === 'check'
      ? h('span', { class: 'muted small' }, 'Pick one')
      : h('button', { class: 'btn primary', type: 'button', onClick: () => go(n + 1) }, 'Next'));

  const body = { sounds: soundsStep, words: wordsStep, grammar: grammarStep, check: checkStep }[step.type];
  // The footer is always attached: a check replaces its contents with Continue once answered, and
  // writing into a detached node would silently lose the only way forward.
  return h('div', { class: 'stack' }, body(step, n, foot), foot);
}

/* ---- step bodies ------------------------------------------------------ */
function sayButton(text, { big = false } = {}) {
  return h('button', {
    class: `btn say ${big ? 'lg' : 'small'} ghost`, type: 'button', 'aria-label': `Play "${text}"`,
    onClick: (e) => { e.stopPropagation(); unlockAudio(); haptic(10); speak(text); },
  }, speakerIcon());
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
    h('div', { class: 'eyebrow' }, 'Words'),
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

function checkStep(step, n, foot) {
  const feedback = h('div', { class: 'check-feedback', hidden: true });
  const opts = h('div', { class: 'check-options' });
  step.options.forEach((text, i) => {
    const btn = h('button', { class: 'check-option', type: 'button', onClick: () => {
      if (S.answered !== null) return;
      S.answered = i;
      const right = i === step.answer;
      haptic(right ? 10 : 20);
      for (const [j, b] of [...opts.children].entries()) {
        b.disabled = true;
        if (j === step.answer) b.classList.add('right');
        else if (j === i) b.classList.add('wrong');
      }
      clear(feedback).append(
        h('strong', { class: right ? 'good' : 'warn' }, right ? 'Yes.' : 'Not quite.'),
        ' ', step.why || '');
      feedback.hidden = false;
      clear(foot).append(h('button', { class: 'btn primary block lg', type: 'button',
        onClick: () => go(n + 1) }, 'Continue'));
      api(`/api/lesson/${S.unitId}/check`, { method: 'POST', body: { step: n, correct: right } }).catch(() => {});
    } }, text);
    opts.append(btn);
  });
  return h('div', { class: 'card' },
    h('div', { class: 'eyebrow' }, 'Check'),
    h('h2', { lang: 'en' }, step.question),
    opts, feedback);
}

/* ---- navigation ------------------------------------------------------- */
async function go(n) {
  const total = S.lesson.steps.length;
  S.i = Math.max(0, Math.min(n, total + 1));
  stopAudio();
  render();
  try {
    if (S.i > total) {
      await api(`/api/lesson/${S.unitId}/complete`, { method: 'POST' });
      document.dispatchEvent(new CustomEvent('dt:lesson-done', { detail: S.unitId }));
      toast('Lesson finished.');
    } else {
      await api(`/api/lesson/${S.unitId}/progress`, { method: 'POST', body: { step: S.i } });
    }
  } catch { /* progress is a convenience; never block the lesson on it */ }
}

function speakerIcon() {
  return h('span', { class: 'ico', html: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9v6h4l5 4V5L8 9H4zm13.5 3a4.5 4.5 0 0 0-2.5-4v8a4.5 4.5 0 0 0 2.5-4zM15 3.2v2.1a6.8 6.8 0 0 1 0 13.4v2.1a8.9 8.9 0 0 0 0-17.6z"/></svg>' });
}
