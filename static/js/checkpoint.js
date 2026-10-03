/* Checkpoint: one speaking task + one writing task for the current unit, graded against a rubric.
   Pass → the "you're now in A1.2" moment. Fail → review focus, retake any time, no penalty. */
import { api, audioFilename } from './api.js';
import { h, clear, toast, errorLine, prefs, spinner } from './ui.js';
import { createHoldToTalk } from './mic.js';
import { speak, unlockAudio } from './audio.js';

const S = { root: null, body: null, cp: null, recording: null, speakingText: '', busy: false };

export function mount(el) {
  S.root = el;
  S.body = h('div', { class: 'screen-body' });
  clear(el).append(h('header', { class: 'screen-head' }, h('h1', {}, 'Checkpoint'), h('span', { class: 'grow' }),
    h('button', { class: 'btn small ghost', type: 'button', onClick: () => window.dtSwitchTo('progress') }, 'Back')), S.body);
}

export async function show() { await load(); }
export function hide() {}

async function load() {
  clear(S.body).append(spinner('Loading…'));
  try {
    S.cp = await api('/api/checkpoint/current');
    S.recording = null;
    render();
  } catch (e) { clear(S.body).append(errorLine(e, load)); }
}

function render() {
  const cp = S.cp;
  clear(S.body);
  if (!cp.available || !cp.checkpoint_id) {
    clear(S.body).append(h('div', { class: 'card stack' },
      h('h2', {}, `Checkpoint · ${cp.unit ? cp.unit.title : ''}`),
      h('p', {}, 'Not open yet. It unlocks after a few conversations in this unit, or when the tutor says you are ready.'),
      h('p', { class: 'muted small' }, `${cp.sessions_in_unit || 0} of ${cp.sessions_needed || '?'} sessions in this unit so far.`),
      cp.last_result ? h('p', { class: 'muted small' }, 'Last attempt: ', cp.last_result.passed ? 'passed' : 'not yet') : null,
      h('button', { class: 'btn block', type: 'button', onClick: () => window.dtSwitchTo('talk') }, 'Keep talking')));
    return;
  }
  const sp = cp.tasks.speaking, wr = cp.tasks.writing;
  const speakStatus = h('div', { class: 'stack' });
  const mic = createHoldToTalk({ onResult: (res) => { S.recording = res; S.speakingText = ''; showRecorded(speakStatus, res, mic); update(); }, label: 'Hold to answer' });
  const typedArea = h('textarea', { class: 'input', rows: '4', placeholder: 'Or type your spoken answer…', autocapitalize: 'sentences',
    onInput: () => { S.speakingText = typedArea.value.trim(); if (S.speakingText) S.recording = null; update(); } });
  const counter = h('span', { class: 'muted small' });
  const writeArea = h('textarea', { class: 'input write-area', rows: '7', placeholder: 'Schreib hier…', autocapitalize: 'sentences',
    onInput: () => { prefs.set('cpDraft', writeArea.value); update(); } });
  writeArea.value = prefs.get('cpDraft', '');
  const submit = h('button', { class: 'btn primary block', type: 'button', onClick: () => submitAll(writeArea.value.trim(), submit) }, 'Submit checkpoint');
  const update = () => {
    const n = (writeArea.value.trim().match(/\S+/g) || []).length;
    counter.textContent = `${n} words · aim for ${wr.words_min || 40}–${wr.words_max || 80}`;
    submit.disabled = S.busy || !(S.recording || S.speakingText) || n === 0;
  };
  S.body.append(
    h('p', { class: 'muted small' }, `${cp.phase ? cp.phase.level : ''} · ${cp.unit.title}`),
    h('div', { class: 'card stack' }, h('div', { class: 'card-title' }, '1 · Speaking'), h('p', {}, sp.prompt), sp.hint ? h('p', { class: 'muted small' }, sp.hint) : null,
      speakStatus, mic.el, h('details', {}, h('summary', { class: 'muted small' }, 'Type instead'), typedArea)),
    h('div', { class: 'card stack' }, h('div', { class: 'card-title' }, '2 · Writing'), h('p', {}, wr.prompt), wr.hint ? h('p', { class: 'muted small' }, wr.hint) : null,
      writeArea, counter),
    submit);
  update();
}

function showRecorded(status, res, mic) {
  const s = Math.round(res.durationMs / 1000);
  clear(status).append(h('div', { class: 'card subtle row between' },
    h('span', {}, `Recorded · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`),
    h('button', { class: 'btn small ghost', type: 'button', onClick: () => { S.recording = null; clear(status); mic.setLabel('Hold to answer'); } }, 'Re-record')));
  mic.setLabel('Hold to re-record');
}

async function submitAll(writingText, btn) {
  if (S.busy) return;
  S.busy = true;
  btn.disabled = true;
  btn.textContent = 'Grading…';
  const fd = new FormData();
  fd.append('writing_text', writingText);
  if (S.recording) fd.append('file', S.recording.blob, audioFilename(S.recording.mime));
  else fd.append('speaking_text', S.speakingText);
  try {
    const r = await api(`/api/checkpoint/${S.cp.checkpoint_id}/submit`, { method: 'POST', body: fd, timeout: 120000 });
    prefs.set('cpDraft', '');
    renderResult(r);
    document.dispatchEvent(new CustomEvent('dt:profile-changed'));
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Submit checkpoint';
    const line = errorLine(e, () => submitAll(writingText, btn));
    btn.before(line);
  } finally { S.busy = false; }
}

function renderResult(r) {
  clear(S.body);
  const adv = r.advanced_to;
  if (r.passed) {
    S.body.append(h('div', { class: 'card stack center pass-card' },
      h('div', { class: 'level-big' }, adv && adv.phase ? adv.phase.level : '✓'),
      h('h2', {}, r.finished_curriculum ? 'You finished the whole path.' : adv && adv.phase_changed ? `You're now in ${adv.phase.level}` : 'Unit passed'),
      adv && adv.unit ? h('p', { class: 'muted' }, `Next: ${adv.unit.title}`) : null));
  } else {
    S.body.append(h('div', { class: 'card stack center' }, h('h2', {}, 'Not yet — and that is fine'), h('p', { class: 'muted' }, 'The next sessions will target the gaps below. Retake any time.')));
  }
  const dims = [['task_completion', 'Task'], ['range', 'Range'], ['accuracy', 'Accuracy'], ['fluency', 'Fluency']];
  S.body.append(
    h('div', { class: 'card stack' }, h('div', { class: 'card-title' }, 'Scores'),
      dims.map(([k, label]) => { const d = (r.scores || {})[k] || {}; return h('div', { class: 'score-row' },
        h('div', { class: 'row between' }, h('b', {}, label), h('span', {}, `${d.score ?? '–'} / 5`)),
        h('div', { class: 'meter' }, h('i', { style: { width: `${((d.score || 0) / 5) * 100}%` } })),
        d.comment ? h('p', { class: 'muted small' }, d.comment) : null); }),
      r.summary ? h('p', {}, r.summary) : null),
    (r.review_focus || []).length ? h('div', { class: 'card stack' }, h('div', { class: 'card-title' }, 'Review focus'),
      h('div', { class: 'chip-row wrap' }, r.review_focus.map((f) => h('span', { class: 'chip small' }, f)))) : null,
    r.speaking_transcript ? h('details', {}, h('summary', { class: 'muted small' }, 'What the transcriber heard'), h('p', { class: 'small' }, r.speaking_transcript)) : null,
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => window.dtSwitchTo('progress') }, 'Progress'),
      h('button', { class: 'btn primary', type: 'button', onClick: () => window.dtSwitchTo('talk') }, 'Talk')));
}
