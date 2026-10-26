/* Placement: first launch (or a re-run from You). Four spoken tasks of rising difficulty and one
   written task, each skippable, then a conservative placement. Skippable as a whole: "start at A1.1".

   It runs in the player with the tab bar aside: a segmented track (one per task) on top, Katze asking each
   question (in German, with play), the mic in the middle, the next step in the bottom bar. */
import { api, upload, audioFilename } from './api.js';
import { h, clear, errorLine, skeleton, de } from './ui.js';
import { speak, unlockAudio } from './audio.js';
import { createHoldToTalk } from './mic.js';
import { katze } from './katze.js';
import { icon } from './icons.js';
import { focusMode, playerHead, playerFoot, katzeSays, wordMeter } from './kit.js';

const S = { root: null, head: null, body: null, foot: null, session: null, tasks: [], idx: 0, answers: {}, rerun: false, busy: false };
const me = () => window.dtUser || {};

export function mount(el) {
  S.root = el;
  S.head = playerHead({ onClose: leave, closeLabel: 'Close the placement' });
  S.body = h('div', { class: 'player-body' });
  S.foot = playerFoot();
  clear(el).append(h('div', { class: 'player' }, S.head.el, S.body, S.foot.el));
}

/* True on first launch: the shell then shows this screen instead of the tabs' default. */
export async function gate() {
  try {
    const st = await api('/api/placement/status', { timeout: 8000 });
    return !st.placement_done;
  } catch (e) {
    if (e.status === 404) {
      const tree = await api('/api/curriculum', { timeout: 8000 });
      return !(tree.current && tree.current.placement_done);
    }
    return false;
  }
}

export function show({ rerun = false } = {}) {
  S.rerun = rerun;
  focusMode(true);
  if (!S.session) renderIntro();
}
export function hide() {}

function leave() {
  if (S.session && !window.confirm('Leave the placement? Your answers so far are kept on the server; you can start again later.')) return;
  S.session = null;
  window.dtSwitchTo(S.rerun ? 'you' : 'home');
}

function track() {
  const n = S.tasks.length || 4;
  const states = Array.from({ length: n }, (_, i) => {
    const t = S.tasks[i];
    if (t && S.answers[t.id]) return 'right';
    return S.session && i === S.idx ? 'now' : '';
  });
  S.head.segments(states, S.session && S.idx < n ? `${S.idx + 1} / ${n}` : '');
}

function renderIntro(err) {
  track();
  clear(S.body).append(h('div', { class: 'intro' },
    katzeSays(S.rerun ? 'Noch einmal?' : 'Wo fangen wir an?', { mood: 'happy', size: 80, lang: 'de', sub: S.rerun ? 'Once more? Your level can only be placed again, not lost.' : 'Where do we start? Four short answers, about five minutes.' }),
    h('ul', { class: 'facts' },
      h('li', {}, icon('mic', 18), h('span', {}, 'Three spoken answers, each a little harder')),
      h('li', {}, icon('pen', 18), h('span', {}, 'One short written answer')),
      h('li', {}, icon('sparkle', 18), h('span', {}, 'Answer in German as well as you can. Mistakes are fine; they are the point.'))),
    h('p', { class: 'muted small' }, 'The tutor places conservatively: if in doubt, a step lower, so the first sessions feel doable.'),
    err ? errorLine(err, start) : null));
  S.foot.actions(
    h('button', { class: 'btn ghost', type: 'button', onClick: skip }, S.rerun ? 'Cancel' : 'Skip, start at A1.1'),
    h('button', { class: 'btn primary lg tactile grow', type: 'button', onClick: start }, 'Start'));
}

async function start() {
  clear(S.body).append(skeleton(3));
  S.foot.clear();
  try {
    const data = await api('/api/placement/start', { method: 'POST', body: {} });
    S.session = data.session_id;
    S.tasks = data.tasks || [];
    S.idx = 0;
    S.answers = {};
    renderTask();
  } catch (e) { renderIntro(e); }
}

async function skip() {
  if (S.rerun) { leave(); return; }
  clear(S.body).append(skeleton(2));
  try {
    await api('/api/placement/skip', { method: 'POST', body: {} });
    finishUp();
  } catch (e) { renderIntro(e); }
}

function say(text) { unlockAudio(); speak(text).catch(() => {}); }

function renderTask() {
  const t = S.tasks[S.idx];
  if (!t) { finish(); return; }
  track();
  clear(S.body);
  S.foot.clear();
  S.root.scrollTop = 0;
  const saved = S.answers[t.id];
  const status = h('div', { class: 'stack' });
  const speakTask = t.kind === 'speak';
  S.body.append(
    h('div', { class: 'row between' }, h('h1', { class: 'prompt-h' }, t.title),
      h('span', { class: 'pill kind' }, icon(speakTask ? 'mic' : 'pen', 14), speakTask ? 'Speak' : 'Write')),
    h('p', { class: 'prompt-lead' }, t.instruction_en),
    t.prompt_de ? h('div', { class: 'says' }, katze({ variant: me().avatar, size: 56 }),
      h('div', { class: 'says-bubble' }, h('p', { class: 'says-line', lang: 'de' }, t.prompt_de),
        h('button', { class: 'bubble-tool', type: 'button', onClick: () => say(t.prompt_de) }, icon('play', 16), 'Play'))) : null,
    status);
  if (saved) { showSaved(status, t, saved); return; }
  // Every task is optional: a beginner cannot argue a position yet, and should not have to try. The
  // grader treats a skipped task as unknown, and at least one answer is still needed to finish.
  const answered = Object.keys(S.answers).length;
  const last = S.idx + 1 >= S.tasks.length;
  if (!last || answered) {
    S.foot.actions(h('button', { class: 'btn ghost grow', type: 'button', onClick: () => { S.idx += 1; renderTask(); } },
      last ? 'Skip and finish' : 'Skip this one'));
  }
  if (speakTask) {
    const mic = createHoldToTalk({ label: 'Tap to answer, or hold', onResult: (res) => sendAudio(t, res, status) });
    const typed = h('details', { class: 'type-instead' }, h('summary', {}, 'Type instead'), textAnswer(t, status));
    status.append(mic.el, typed);
  } else {
    status.append(textAnswer(t, status));
  }
}

function textAnswer(t, status) {
  const meter = wordMeter(t.words_min || 20, t.words_max || 60);
  const btn = h('button', { class: 'btn primary block lg tactile', type: 'button', disabled: true, onClick: () => sendText(t, area.value.trim(), status, btn) }, 'Save answer');
  const area = h('textarea', { class: 'input write-area', name: 'answer', rows: '5', placeholder: 'Auf Deutsch…', autocapitalize: 'sentences', autocomplete: 'off', lang: 'de', 'aria-label': 'Your answer',
    onInput: () => { const n = (area.value.trim().match(/\S+/g) || []).length; meter.update(n); btn.disabled = !n; } });
  meter.update(0);
  return h('div', { class: 'stack' }, area, meter.el, btn);
}

async function sendText(t, text, status, btn) {
  if (!text || S.busy) return;
  S.busy = true; btn.disabled = true; btn.textContent = 'Saving…';
  try {
    const r = await api('/api/placement/answer', { method: 'POST', body: { session_id: S.session, task_id: t.id, text } });
    S.answers[t.id] = r;
    showSaved(status, t, r);
  } catch (e) { btn.disabled = false; btn.textContent = 'Save answer'; status.prepend(errorLine(e)); }
  finally { S.busy = false; }
}

async function sendAudio(t, { blob, mime }, status) {
  if (S.busy) return;
  S.busy = true;
  const wait = h('div', { class: 'wait-line' }, katze({ variant: me().avatar, mood: 'thinking', size: 28 }), h('span', {}, 'Listening to your answer…'));
  status.prepend(wait);
  try {
    const r = await upload('/api/placement/answer', blob, audioFilename(mime), { session_id: S.session, task_id: t.id });
    S.answers[t.id] = r;
    showSaved(status, t, r);
  } catch (e) {
    wait.remove();
    status.prepend(errorLine(e, () => sendAudio(t, { blob, mime }, status)));
  } finally { S.busy = false; }
}

function showSaved(status, t, r) {
  track();
  clear(status).append(h('div', { class: 'heard-card' },
    h('div', { class: 'section-label' }, r.transcript_provider ? `What the mic heard · ${r.transcript_provider}` : 'Your answer'),
    h('p', { lang: 'de' }, r.text)));
  S.foot.actions(
    h('button', { class: 'btn ghost', type: 'button', onClick: () => { delete S.answers[t.id]; renderTask(); } }, 'Redo'),
    h('button', { class: 'btn primary lg tactile grow', type: 'button', onClick: () => { S.idx += 1; renderTask(); } }, S.idx + 1 < S.tasks.length ? 'Next' : 'Finish'));
}

async function finish() {
  track();
  S.foot.clear();
  clear(S.body).append(h('div', { class: 'intro' },
    katzeSays('Moment…', { mood: 'thinking', size: 80, lang: 'de', sub: 'Reading your answers against the CEFR descriptors. A few seconds…' }),
    skeleton(3)));
  try {
    const r = await api('/api/placement/finish', { method: 'POST', body: { session_id: S.session }, timeout: 90000 });
    renderResult(r);
  } catch (e) {
    clear(S.body).append(errorLine(e, finish));
    S.foot.actions(h('button', { class: 'btn ghost block', type: 'button', onClick: () => { S.idx = Math.max(0, S.tasks.length - 1); renderTask(); } }, 'Back'));
  }
}

function renderResult(r) {
  clear(S.body).append(h('div', { class: 'finish' },
    h('div', { class: 'finish-cat' }, katze({ variant: me().avatar, mood: 'proud', size: 110 })),
    h('div', { class: 'level-mark num' }, r.level),
    h('h2', { class: 'finish-h' }, r.phase ? r.phase.title : 'Placed'),
    r.explanation ? h('p', { class: 'finish-sub' }, r.explanation) : null,
    (r.strengths || []).length || (r.gaps || []).length ? h('div', { class: 'fb-list left' },
      ...(r.strengths || []).map((s) => h('div', { class: 'fb-row good' }, icon('check', 18), h('p', {}, s))),
      ...(r.gaps || []).map((g) => h('div', { class: 'fb-row next' }, icon('sparkle', 18), h('p', {}, g)))) : null,
    r.unit ? h('p', { class: 'muted small' }, 'Starting unit: ', de(r.unit.title)) : null));
  S.foot.actions(h('button', { class: 'btn primary lg tactile grow', type: 'button', onClick: finishUp }, 'Start learning'));
}

function finishUp() {
  S.session = null;
  document.dispatchEvent(new CustomEvent('dt:profile-changed'));
  window.dtSwitchTo('home');
}
