/* Placement: first launch (or a re-run from Progress). Three spoken tasks of rising difficulty and
   one written task, then a conservative placement. Skippable: "start at A1.1". */
import { api, upload, audioFilename } from './api.js';
import { h, clear, toast, errorLine, spinner, skeleton, de } from './ui.js';
import { speak, unlockAudio } from './audio.js';
import { createHoldToTalk } from './mic.js';

const S = { root: null, body: null, session: null, tasks: [], idx: 0, answers: {}, rerun: false, busy: false };

export function mount(el) {
  S.root = el;
  S.body = h('div', { class: 'screen-body' });
  clear(el).append(h('header', { class: 'screen-head' }, h('h1', {}, 'Placement'), h('span', { class: 'grow' }),
    h('button', { class: 'btn small ghost', type: 'button', onClick: leave }, 'Close')), S.body);
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
  if (!S.session) renderIntro();
}
export function hide() {}

function leave() {
  if (S.session && !window.confirm('Leave the placement? Your answers so far are kept on the server; you can start again later.')) return;
  S.session = null;
  window.dtSwitchTo(S.rerun ? 'progress' : 'talk');
}

function renderIntro(err) {
  clear(S.body).append(h('div', { class: 'card stack' },
    h('h2', {}, S.rerun ? 'Re-run the placement' : 'Where do we start?'),
    h('p', {}, 'Three short spoken tasks, one short written one — about five minutes. Answer in German as well as you can; mistakes are fine, they are the point.'),
    h('p', { class: 'muted small' }, 'The tutor places conservatively: if in doubt, a step lower, so the first sessions feel doable.'),
    err ? errorLine(err, start) : null,
    h('button', { class: 'btn primary block', type: 'button', onClick: start }, 'Start'),
    h('button', { class: 'btn ghost block', type: 'button', onClick: skip }, S.rerun ? 'Cancel' : 'Skip — start at A1.1')));
}

async function start() {
  clear(S.body).append(h('div', { class: 'card' }, skeleton(3)));
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
  clear(S.body).append(h('div', { class: 'card' }, skeleton(2)));
  try {
    await api('/api/placement/skip', { method: 'POST', body: {} });
    finishUp();
  } catch (e) { renderIntro(e); }
}

function renderTask() {
  const t = S.tasks[S.idx];
  if (!t) { finish(); return; }
  clear(S.body);
  const saved = S.answers[t.id];
  const status = h('div', { class: 'stack' });
  const promptDe = t.prompt_de ? h('p', { class: 'help-german' }, de(t.prompt_de),
    h('button', { class: 'btn small ghost', type: 'button', onClick: () => { unlockAudio(); speak(t.prompt_de).catch(() => {}); } }, '▶')) : null;
  S.body.append(
    h('div', { class: 'row between muted small' }, h('span', {}, `Task ${S.idx + 1} of ${S.tasks.length}`), h('span', { class: 'cat' }, t.kind === 'speak' ? 'speak' : 'write')),
    h('div', { class: 'card stack' }, h('h2', {}, t.title), h('p', {}, t.instruction_en), promptDe),
    status);
  if (saved) { showSaved(status, t, saved); return; }
  if (t.kind === 'speak') {
    const typed = h('details', {}, h('summary', { class: 'muted small' }, 'Type instead'),
      textAnswer(t, status));
    const mic = createHoldToTalk({ onResult: (res) => sendAudio(t, res, status) });
    status.append(mic.el, typed);
  } else {
    status.append(textAnswer(t, status));
  }
}

function textAnswer(t, status) {
  const area = h('textarea', { class: 'input', rows: '5', placeholder: 'Auf Deutsch…', autocapitalize: 'sentences', lang: 'de', 'aria-label': 'Your answer' });
  const btn = h('button', { class: 'btn primary block', type: 'button', onClick: () => sendText(t, area.value.trim(), status, btn) }, 'Save answer');
  return h('div', { class: 'stack' }, area, btn);
}

async function sendText(t, text, status, btn) {
  if (!text || S.busy) return;
  S.busy = true; btn.disabled = true;
  try {
    const r = await api('/api/placement/answer', { method: 'POST', body: { session_id: S.session, task_id: t.id, text } });
    S.answers[t.id] = r;
    showSaved(status, t, r);
  } catch (e) { btn.disabled = false; status.prepend(errorLine(e)); }
  finally { S.busy = false; }
}

async function sendAudio(t, { blob, mime }, status) {
  if (S.busy) return;
  S.busy = true;
  const sp = spinner('Transcribing…');
  status.prepend(sp);
  try {
    const r = await upload('/api/placement/answer', blob, audioFilename(mime), { session_id: S.session, task_id: t.id });
    S.answers[t.id] = r;
    showSaved(status, t, r);
  } catch (e) {
    sp.remove();
    status.prepend(errorLine(e, () => sendAudio(t, { blob, mime }, status)));
  } finally { S.busy = false; }
}

function showSaved(status, t, r) {
  clear(status).append(
    h('div', { class: 'card subtle stack' },
      h('div', { class: 'transcript-label' }, r.transcript_provider ? `transcript · ${r.transcript_provider}` : 'your answer'),
      h('p', { lang: 'de' }, r.text)),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => { delete S.answers[t.id]; renderTask(); } }, 'Redo'),
      h('button', { class: 'btn primary', type: 'button', onClick: () => { S.idx += 1; renderTask(); } }, S.idx + 1 < S.tasks.length ? 'Next' : 'Finish')));
}

async function finish() {
  clear(S.body).append(h('div', { class: 'card stack' }, h('h2', {}, 'Placing you'), h('p', { class: 'muted' }, 'Reading your four answers against the CEFR descriptors. A few seconds.'), spinner('Grading…')));
  try {
    const r = await api('/api/placement/finish', { method: 'POST', body: { session_id: S.session }, timeout: 90000 });
    renderResult(r);
  } catch (e) {
    clear(S.body).append(errorLine(e, finish), h('button', { class: 'btn ghost block', type: 'button', onClick: () => { S.idx = Math.max(0, S.tasks.length - 1); renderTask(); } }, 'Back'));
  }
}

function renderResult(r) {
  clear(S.body).append(h('div', { class: 'card stack center' },
    h('div', { class: 'level-big' }, r.level),
    h('p', { class: 'muted' }, r.phase ? r.phase.title : ''),
    h('p', {}, r.explanation || ''),
    (r.strengths || []).length ? h('p', { class: 'small' }, h('b', {}, 'Strengths: '), r.strengths.join(' · ')) : null,
    (r.gaps || []).length ? h('p', { class: 'small' }, h('b', {}, 'To work on: '), r.gaps.join(' · ')) : null,
    h('p', { class: 'muted small' }, r.unit ? `Starting unit: ${r.unit.title}` : ''),
    h('button', { class: 'btn primary block', type: 'button', onClick: finishUp }, 'Start learning')));
}

function finishUp() {
  S.session = null;
  document.dispatchEvent(new CustomEvent('dt:profile-changed'));
  window.dtSwitchTo('talk');
}
