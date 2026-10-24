/* Checkpoint: one speaking task + one writing task for the current unit, graded against a rubric.
   Pass → the "you're now in A1.2" moment. Fail → review focus, retake any time, no penalty.

   Locked, it says how far off it is as a ring (conversations in this unit against the number
   needed). Open, it is two numbered parts on one screen, then one submit. */
import { api, audioFilename } from './api.js';
import { h, clear, errorLine, prefs, skeleton, de } from './ui.js';
import { createHoldToTalk } from './mic.js';
import { katze } from './katze.js';
import { ringAround } from './rings.js';
import { icon } from './icons.js';
import { maybeCelebrate } from './moment.js';
import { katzeSays, wordMeter } from './kit.js';

const S = { root: null, body: null, cp: null, recording: null, speakingText: '', busy: false };
const me = () => window.dtUser || {};

export function mount(el) {
  S.root = el;
  S.body = h('div', { class: 'screen-body' });
  clear(el).append(h('header', { class: 'screen-head' }, h('button', { class: 'btn icon ghost', type: 'button', 'aria-label': 'Back', onClick: () => window.dtSwitchTo(['learn', 'you', 'home', 'talk'].includes(window.dtBack) ? window.dtBack : 'you') }, icon('back', 22)),
    h('h1', {}, 'Checkpoint')), S.body);
}

export async function show() { await load(); }
export function hide() {}

async function load() {
  clear(S.body).append(skeleton(1, { tall: true }), skeleton(3));
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
    const done = cp.sessions_in_unit || 0;
    const need = cp.sessions_needed || 3;
    S.body.append(h('div', { class: 'finish' },
      ringAround(Math.min(1, done / need), 168, 'var(--accent)', 'var(--accent-dim)', katze({ variant: me().avatar, mood: 'sleepy', size: 88 })),
      h('h2', { class: 'finish-h' }, 'Not open yet'),
      h('p', { class: 'finish-sub' }, 'The checkpoint for ', cp.unit ? de(cp.unit.title) : 'this unit',
        ' opens after a few conversations in the unit, or when the tutor says you are ready.'),
      h('p', { class: 'muted small num' }, `${done} of ${need} conversations so far`,
        cp.last_result ? ` · last attempt ${cp.last_result.passed ? 'passed' : 'not yet'}` : ''),
      h('div', { class: 'finish-actions' },
        h('button', { class: 'btn primary block lg tactile', type: 'button', onClick: () => window.dtSwitchTo('talk') }, 'Keep talking'))));
    return;
  }
  const sp = cp.tasks.speaking, wr = cp.tasks.writing;
  const speakStatus = h('div', { class: 'stack' });
  const mic = createHoldToTalk({ label: 'Tap to answer, or hold',
    onResult: (res) => { S.recording = res; S.speakingText = ''; typedArea.value = ''; showRecorded(speakStatus, res, mic); update(); } });
  const typedArea = h('textarea', { class: 'input', name: 'spoken', rows: '4', placeholder: 'Or type what you would say…', autocapitalize: 'sentences', autocomplete: 'off', lang: 'de', 'aria-label': 'Spoken answer, typed',
    onInput: () => { S.speakingText = typedArea.value.trim(); if (S.speakingText) { S.recording = null; clear(speakStatus); } update(); } });
  const meter = wordMeter(wr.words_min || 40, wr.words_max || 80);
  const writeArea = h('textarea', { class: 'input write-area', name: 'written', rows: '7', placeholder: 'Schreib hier…', autocapitalize: 'sentences', autocomplete: 'off', lang: 'de', 'aria-label': 'Written answer',
    onInput: () => { prefs.set('cpDraft', writeArea.value); update(); } });
  writeArea.value = prefs.get('cpDraft', '');
  const submit = h('button', { class: 'btn primary block lg tactile', type: 'button', onClick: () => submitAll(writeArea.value.trim(), submit) }, 'Submit the checkpoint');
  const update = () => {
    const n = (writeArea.value.trim().match(/\S+/g) || []).length;
    meter.update(n);
    submit.disabled = S.busy || !(S.recording || S.speakingText) || n === 0;
  };
  S.body.append(
    katzeSays('Zeig, was du kannst.', { lang: 'de', size: 56, sub: `Show what you can do in ${cp.unit.title}: one spoken answer, one written. No time limit.` }),
    h('section', { class: 'cp-part' },
      h('div', { class: 'cp-part-head' }, h('span', { class: 'cp-num num', 'aria-hidden': 'true' }, '1'), h('h2', { class: 'section-h' }, 'Speaking')),
      h('p', { class: 'cp-prompt' }, sp.prompt), sp.hint ? h('p', { class: 'muted small' }, sp.hint) : null,
      speakStatus, mic.el,
      h('details', { class: 'type-instead' }, h('summary', {}, 'Type instead'), typedArea)),
    h('section', { class: 'cp-part' },
      h('div', { class: 'cp-part-head' }, h('span', { class: 'cp-num num', 'aria-hidden': 'true' }, '2'), h('h2', { class: 'section-h' }, 'Writing')),
      h('p', { class: 'cp-prompt' }, wr.prompt), wr.hint ? h('p', { class: 'muted small' }, wr.hint) : null,
      writeArea, meter.el),
    submit);
  update();
}

function showRecorded(status, res, mic) {
  const s = Math.round(res.durationMs / 1000);
  clear(status).append(h('div', { class: 'recorded' },
    icon('check', 18),
    h('span', { class: 'grow num' }, `Recorded · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`),
    h('button', { class: 'btn small ghost', type: 'button', onClick: () => { S.recording = null; clear(status); mic.setLabel('Tap to answer, or hold'); } }, 'Discard')));
  mic.setLabel('Record again to replace it');
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
    api('/api/game/me').then(maybeCelebrate).catch(() => {});
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Submit the checkpoint';
    btn.before(errorLine(e, () => submitAll(writingText, btn)));
  } finally { S.busy = false; }
}

function renderResult(r) {
  clear(S.body);
  S.root.scrollTop = 0;
  const adv = r.advanced_to;
  if (r.passed) {
    S.body.append(h('div', { class: 'finish' },
      h('div', { class: 'finish-cat' }, katze({ variant: me().avatar, mood: 'cheering', size: 110 })),
      adv && adv.phase_changed && adv.phase ? h('div', { class: 'level-mark num' }, adv.phase.level) : null,
      h('h2', { class: 'finish-h' }, r.finished_curriculum ? 'You finished the whole path' : adv && adv.phase_changed ? `You're now in ${adv.phase.level}` : 'Unit passed'),
      adv && adv.unit ? h('p', { class: 'finish-sub' }, 'Next: ', de(adv.unit.title)) : null));
  } else {
    S.body.append(h('div', { class: 'finish' },
      h('div', { class: 'finish-cat' }, katze({ variant: me().avatar, mood: 'thinking', size: 96 })),
      h('h2', { class: 'finish-h' }, 'Not yet, and that is fine'),
      h('p', { class: 'finish-sub' }, 'The next sessions target the gaps below. Retake it any time.')));
  }
  const dims = [['task_completion', 'Task'], ['range', 'Range'], ['accuracy', 'Accuracy'], ['fluency', 'Fluency']];
  S.body.append(
    h('section', { class: 'text-card' }, h('h2', { class: 'section-h' }, 'Scores'),
      h('div', { class: 'scores' }, dims.map(([k, label]) => {
        const d = (r.scores || {})[k] || {};
        const n = Math.max(0, Math.min(5, d.score || 0));
        return h('div', { class: 'score' },
          h('div', { class: 'row between' }, h('b', {}, label), h('span', { class: 'muted small num' }, d.score == null ? '—' : `${d.score} / 5`)),
          h('div', { class: 'score-bar', role: 'img', 'aria-label': `${label}: ${d.score ?? 'no'} of 5` }, Array.from({ length: 5 }, (_, i) => h('i', { class: i < n ? 'on' : '' }))),
          d.comment ? h('p', { class: 'muted small' }, d.comment) : null);
      })),
      r.summary ? h('p', {}, r.summary) : null),
    (r.review_focus || []).length ? h('section', { class: 'text-card' }, h('h2', { class: 'section-h' }, 'What to work on next'),
      h('div', { class: 'chip-row wrap' }, r.review_focus.map((f) => h('span', { class: 'chip small' }, f)))) : null,
    r.speaking_transcript ? h('details', { class: 'type-instead' }, h('summary', {}, 'What the mic heard'), h('p', { class: 'small', lang: 'de' }, r.speaking_transcript)) : null,
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn lg', type: 'button', onClick: () => window.dtSwitchTo('you') }, 'Your progress'),
      h('button', { class: 'btn primary lg tactile', type: 'button', onClick: () => window.dtSwitchTo('talk') }, 'Talk')));
}
