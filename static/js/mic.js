/* The mic, shared by Talk, Learn, Placement and Checkpoint (docs/DESIGN.md §4 "The mic").

   Two ways to use it, both always available:
   - Tap: recording starts; tap again to send. A cancel button sits beside it while it runs.
   - Hold: recording starts on the press and is sent on release; slide ≥ 80 px away to cancel.
   A press shorter than HOLD_MS is a tap. Recording starts on the press either way, so the first
   syllable is never lost, and a release before the microphone has even opened keeps it running
   (as a tap would) instead of throwing the attempt away.

   iOS decides on its long-press text loupe and "Copy / Look Up" callout from the touch itself,
   before any pointer event fires, so the button cancels touchstart (non-passive) as well as the
   pointer default, and the dock around it is unselectable. Pointer capture keeps a hold on the
   button when the thumb drifts. */
import { h, toast, sheet, haptic } from './ui.js';
import { Recorder, unlockAudio, stop as stopAudio } from './audio.js';
import { icon } from './icons.js';

const HOLD_MS = 350;
const MAX_MS = 120000;     // a forgotten tap-recording should not run all evening
const BARS = 28;

let explained = false;

/* While the thumb is down, the page is being gestured on, not read: suppress text selection and the
   iOS long-press callout document-wide, and drop any selection that already started. Released on
   every exit path, including a cancelled or failed recording, so the page never stays unselectable. */
function setRecordingGesture(on) {
  document.documentElement.classList.toggle('recording', on);
  if (!on) return;
  try { window.getSelection()?.removeAllRanges(); } catch { /* fine */ }
}

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

/* onStart (optional, async) runs before recording and may return false to abort (e.g. no session).
   The name is historical: holding is now one of two ways to use it. */
export function createHoldToTalk({ onResult, onStart, label = 'Tap to talk, or hold', side = null } = {}) {
  const btn = h('button', { class: 'mic-btn', type: 'button', 'aria-label': 'Start recording', 'aria-pressed': 'false' }, icon('mic', 30));
  const timerEl = h('span', { class: 'mic-timer num' }, '0:00');
  const wave = h('div', { class: 'mic-wave', 'aria-hidden': 'true' }, Array.from({ length: BARS }, () => h('i')));
  const status = h('div', { class: 'mic-status', hidden: true }, h('span', { class: 'mic-dot', 'aria-hidden': 'true' }), timerEl, wave);
  const cancelBtn = h('button', { class: 'btn icon mic-cancel', type: 'button', 'aria-label': 'Cancel recording', hidden: true,
    onClick: () => finish(true) }, icon('trash', 20));
  const labelEl = h('div', { class: 'mic-label', 'aria-live': 'polite' }, label);
  const el = h('div', { class: 'mic-wrap' }, status,
    h('div', { class: 'mic-row' }, h('div', { class: 'mic-side' }, side, cancelBtn), btn, h('div', { class: 'mic-side' })),
    labelEl);

  let rec = null;          // the Recorder while one runs or is opening
  let mode = 'idle';       // idle | hold | latched
  let press = null;        // the pointer that is down on the button: { id, x, y, at, stop }
  let cancelArmed = false, busy = false, maxTimer = null, idleLabel = label, lastBar = 0;
  const levels = new Array(BARS).fill(0);

  function setUi(state) {   // idle | hold | latched | cancel
    const on = state !== 'idle';
    btn.classList.toggle('on', on);
    btn.classList.toggle('latched', state === 'latched');
    btn.setAttribute('aria-pressed', String(on));
    btn.setAttribute('aria-label', on ? 'Stop and send' : 'Start recording');
    clearIcon(on ? 'send' : 'mic');
    status.hidden = !on;
    status.classList.toggle('cancel', state === 'cancel');
    cancelBtn.hidden = state !== 'latched';
    if (side) side.hidden = on;
    labelEl.textContent = { idle: idleLabel, hold: 'Release to send · slide away to cancel', latched: 'Tap to send', cancel: 'Release to cancel' }[state];
    labelEl.classList.toggle('warn', state === 'cancel');
    if (on) { timerEl.textContent = '0:00'; levels.fill(0); drawWave(); }
  }
  function clearIcon(name) {
    if (btn.dataset.icon === name) return;
    btn.dataset.icon = name;
    btn.replaceChildren(icon(name === 'send' ? 'send' : 'mic', 30));
  }
  function drawWave() {
    [...wave.children].forEach((bar, i) => { bar.style.transform = `scaleY(${(0.14 + levels[i] * 0.86).toFixed(3)})`; });
  }

  function reset() {
    rec = null; mode = 'idle'; press = null;
    clearTimeout(maxTimer);
    setRecordingGesture(false);
    setUi('idle');
  }

  async function start() {
    if (!Recorder.supported) { reset(); toast('This browser cannot record audio. Type instead.'); return; }
    if (onStart && (await onStart()) === false) { reset(); return; }
    if (mode === 'idle') return;   // cancelled while onStart ran
    const r = new Recorder({
      onLevel: (v) => {
        const now = performance.now();
        if (now - lastBar < 70) return;
        lastBar = now;
        levels.shift(); levels.push(v);
        drawWave();
      },
      onTick: (ms) => { const s = Math.floor(ms / 1000); timerEl.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; },
    });
    rec = r;
    try { await r.start(); } catch (e) { if (rec === r) reset(); explainMicDenied(e); return; }
    if (rec !== r) { r.cancel(); return; }   // stopped or cancelled before the microphone opened
    clearTimeout(maxTimer);
    maxTimer = setTimeout(() => { if (rec === r) { toast('Two minutes is the limit, so that one was sent.'); finish(false); } }, MAX_MS);
  }

  async function finish(doCancel) {
    const r = rec;
    reset();
    if (!r) return;
    if (doCancel) { r.cancel(); return; }
    const tooShort = r.durationMs < 500;
    const result = await r.stop();
    if (!result || !result.blob.size || tooShort) { toast('Too short to hear. Tap the mic, speak, then tap again.'); return; }
    haptic(20);
    onResult && onResult(result);
  }

  // Gesture, not text: no loupe, no callout, no selection, no context menu (see the header).
  btn.addEventListener('touchstart', (e) => { if (e.cancelable) e.preventDefault(); }, { passive: false });
  el.addEventListener('contextmenu', (e) => e.preventDefault());
  el.addEventListener('selectstart', (e) => e.preventDefault());

  btn.addEventListener('pointerdown', (e) => {
    if (busy || e.button > 0) return;
    e.preventDefault();
    if (mode === 'latched') {   // the tap that sends
      press = { id: e.pointerId, stop: true };
      try { btn.setPointerCapture(e.pointerId); } catch { /* fine */ }
      return;
    }
    if (mode !== 'idle') return;
    unlockAudio();
    stopAudio();
    haptic(12);
    setRecordingGesture(true);   // before getUserMedia: the callout can appear during that await
    try { btn.setPointerCapture(e.pointerId); } catch { /* fine */ }
    press = { id: e.pointerId, x: e.clientX, y: e.clientY, at: performance.now() };
    cancelArmed = false;
    mode = 'hold';
    setUi('hold');
    start();
  });
  btn.addEventListener('pointermove', (e) => {
    if (!press || press.stop || mode !== 'hold' || e.pointerId !== press.id) return;
    if (performance.now() - press.at < HOLD_MS) return;   // a tap wobbles; only a hold slides to cancel
    cancelArmed = Math.hypot(e.clientX - press.x, e.clientY - press.y) >= 80;
    setUi(cancelArmed ? 'cancel' : 'hold');
  });
  const release = (interrupted) => (e) => {
    if (!press || e.pointerId !== press.id) return;
    const p = press;
    press = null;
    setRecordingGesture(false);
    if (p.stop) { if (!interrupted) finish(false); return; }
    if (mode !== 'hold') return;
    const held = performance.now() - p.at >= HOLD_MS;
    const recording = !!(rec && rec.startedAt);
    if (held && cancelArmed) { finish(true); return; }
    // A tap, a release while the microphone was still opening, or the system taking the touch
    // away (pointercancel): keep recording until the next tap rather than losing the attempt.
    if (!held || !recording || interrupted) { mode = 'latched'; setUi('latched'); return; }
    finish(false);
  };
  btn.addEventListener('pointerup', release(false));
  btn.addEventListener('pointercancel', release(true));
  btn.addEventListener('lostpointercapture', release(true));   // after pointerup `press` is already null
  // Keyboard (Enter / Space) arrives as a click with no pointer: it toggles, like a tap.
  btn.addEventListener('click', (e) => {
    if (e.detail !== 0 || busy) return;
    if (mode === 'latched') { finish(false); return; }
    if (mode !== 'idle') return;
    unlockAudio(); stopAudio();
    mode = 'latched';
    setUi('latched');
    start();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && mode !== 'idle' && el.isConnected) finish(true); });
  // Backgrounding the app mid-recording: stop cleanly rather than leaving a dangling stream.
  document.addEventListener('visibilitychange', () => { if (document.hidden && mode !== 'idle') { setRecordingGesture(false); finish(true); } });

  return {
    el,
    button: btn,
    setDisabled(on) { busy = on; btn.disabled = on; },
    setLabel(text) { idleLabel = text; if (mode === 'idle') labelEl.textContent = text; },
    get recording() { return mode !== 'idle'; },
  };
}

export function micIcon(size = 14) { return icon('mic', size); }
