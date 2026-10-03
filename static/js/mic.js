/* Hold-to-talk control, shared by Talk, Placement and Checkpoint.

   Press and hold → record (timer + level meter visible), release → onResult({blob, mime, durationMs}),
   slide up or sideways → cancel, like a voice note. Pointer capture keeps the gesture on the button
   even when the thumb drifts. Recordings under 600 ms are treated as an accidental tap. */
import { h, toast, sheet } from './ui.js';
import { Recorder, unlockAudio, stop as stopAudio } from './audio.js';

let explained = false;

export function explainMicDenied(e) {
  const denied = e && (e.name === 'NotAllowedError' || e.name === 'SecurityError');
  if (denied && !explained) {
    explained = true;
    sheet.open(h('div', { class: 'stack' },
      h('p', {}, 'The microphone is blocked for this site. Speaking is the main way to practise, so it is worth allowing it: Settings → Safari (or Chrome) → Microphone.'),
      h('p', { class: 'muted small' }, 'Until then you can type instead.'),
      h('button', { class: 'btn primary block', type: 'button', onClick: () => sheet.close() }, 'OK')), { title: 'Microphone blocked' });
  } else {
    toast(denied ? 'Microphone blocked. Typing still works.' : 'Could not start recording.', { kind: 'err' });
  }
}

/* onStart (optional, async) runs before recording and may return false to abort (e.g. no session). */
export function createHoldToTalk({ onResult, onStart, label = 'Hold to talk' } = {}) {
  const btn = h('button', { class: 'mic-btn', type: 'button', 'aria-label': label }, micIcon());
  const timerEl = h('div', { class: 'mic-timer' }, '0:00');
  const level = h('i');
  const hint = h('div', { class: 'mic-hint muted small' }, 'Release to send · slide up to cancel');
  const panel = h('div', { class: 'mic-panel', hidden: true }, timerEl, h('div', { class: 'meter mic-level' }, level), hint);
  const labelEl = h('span', { class: 'mic-label muted small' }, label);
  const el = h('div', { class: 'mic-wrap' }, panel, h('div', { class: 'mic-row' }, btn, labelEl));
  let rec = null, startX = 0, startY = 0, cancel = false, busy = false;

  async function start() {
    if (!Recorder.supported) { toast('This browser cannot record audio. Type instead.'); return; }
    if (onStart && (await onStart()) === false) return;
    const r = new Recorder({
      onLevel: (v) => { level.style.width = Math.round(v * 100) + '%'; },
      onTick: (ms) => { const s = Math.floor(ms / 1000); timerEl.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; },
    });
    rec = r;
    try { await r.start(); } catch (e) { rec = null; explainMicDenied(e); return; }
    if (rec !== r) { r.cancel(); return; }   // released before getUserMedia resolved
    btn.classList.add('on');
    panel.hidden = false;
    panel.classList.remove('cancel');
    timerEl.textContent = '0:00';
  }

  async function finish(doCancel) {
    const r = rec;
    rec = null;
    btn.classList.remove('on');
    panel.hidden = true;
    if (!r) return;
    const tooShort = r.durationMs < 600;
    if (doCancel) { r.cancel(); return; }
    const result = await r.stop();
    if (!result || !result.blob.size || tooShort) { toast('Hold the button while you speak.'); return; }
    onResult && onResult(result);
  }

  btn.addEventListener('contextmenu', (e) => e.preventDefault());
  btn.addEventListener('pointerdown', (e) => {
    if (busy || rec) return;
    e.preventDefault();
    unlockAudio();
    stopAudio();
    try { btn.setPointerCapture(e.pointerId); } catch { /* fine */ }
    startX = e.clientX; startY = e.clientY; cancel = false;
    start();
  });
  btn.addEventListener('pointermove', (e) => {
    if (!rec) return;
    cancel = (startY - e.clientY) > 70 || Math.abs(e.clientX - startX) > 90;
    panel.classList.toggle('cancel', cancel);
    hint.textContent = cancel ? 'Release to cancel' : 'Release to send · slide up to cancel';
  });
  btn.addEventListener('pointerup', () => finish(cancel));
  btn.addEventListener('pointercancel', () => finish(true));
  btn.addEventListener('lostpointercapture', () => { if (rec) finish(cancel); });

  return {
    el,
    button: btn,
    setDisabled(on) { busy = on; btn.disabled = on; },
    setLabel(text) { labelEl.textContent = text; },
  };
}

export function micIcon() {
  return h('span', { class: 'ico', html: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.9V21h2v-3.1A7 7 0 0 0 19 11z"/></svg>' });
}
