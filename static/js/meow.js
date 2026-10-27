/* Katze's voice: a purr, a "mrrp", a "mrr?" and a "me-ow", made on the phone.

   No sound files: the CSP allows no external assets, and a synthesised cat is a few lines. The
   voice is a buzzy oscillator through two moving formants (the "m-ee-ow" vowel), the rolled r of a
   "mrrp" is that voice switched on and off about thirty times a second, and a purr is low noise
   pulsed at the same rate.

   Each sound is rendered once, offline, into a WAV clip and played through an <audio> element, the
   same way the tutor's voice plays. Played live through Web Audio instead, it was silent on an
   iPhone: iOS mutes Web Audio with the ring/silent switch (the tutor's voice ignores the switch),
   and only some taps unlock it. Sounds play only on the learner's own actions (an answer, a tap, a
   finished lesson), never on a timer, and the switch on the You screen turns them off. */
import { prefs } from './ui.js';

const RATE = 44100;

export const soundOn = () => prefs.get('katzeSound', true) !== false;
export function setSound(on) { prefs.set('katzeSound', !!on); if (on) prepare(); }

function mew(c, { pitch, formants, dur, vol = .2, trill = 0, at = 0 }) {
  const t = .02 + at;
  const osc = c.createOscillator();
  osc.type = 'sawtooth';
  pitch.forEach(([time, f], i) => (i ? osc.frequency.exponentialRampToValueAtTime(f, t + time * dur) : osc.frequency.setValueAtTime(f, t)));
  const vib = c.createOscillator();
  vib.frequency.value = 6;
  const vibDepth = c.createGain();
  vibDepth.gain.value = 9;
  vib.connect(vibDepth).connect(osc.frequency);
  const out = c.createGain();
  out.gain.setValueAtTime(0, t);
  out.gain.linearRampToValueAtTime(vol, t + Math.min(.06, dur * .15));
  out.gain.setValueAtTime(vol, t + dur * .6);
  out.gain.exponentialRampToValueAtTime(.0008, t + dur);
  let src = osc;
  if (trill) {
    const am = c.createGain();
    am.gain.value = .5;
    const lfo = c.createOscillator();
    lfo.type = 'square';
    lfo.frequency.value = trill;
    const depth = c.createGain();
    depth.gain.value = .5;
    lfo.connect(depth).connect(am.gain);
    osc.connect(am);
    src = am;
    lfo.start(t);
    lfo.stop(t + dur);
  }
  formants.forEach(([f0, f1, f2], k) => {
    const bp = c.createBiquadFilter();
    bp.type = 'bandpass';
    bp.Q.value = 7;
    bp.frequency.setValueAtTime(f0, t);
    bp.frequency.linearRampToValueAtTime(f1, t + dur * .4);
    bp.frequency.linearRampToValueAtTime(f2, t + dur);
    const g = c.createGain();
    g.gain.value = k ? .6 : 1;
    src.connect(bp).connect(g).connect(out);
  });
  out.connect(c.destination);
  osc.start(t); vib.start(t);
  osc.stop(t + dur + .05); vib.stop(t + dur + .05);
}

function purr(c, dur = 2.2, vol = .5) {
  const t = .02;
  const len = Math.floor(RATE * dur);
  const buf = c.createBuffer(1, len, RATE);
  const d = buf.getChannelData(0);
  let last = 0;
  for (let i = 0; i < len; i++) { last = (last + .02 * (Math.random() * 2 - 1)) / 1.02; d[i] = last * 3.5; }   // brown noise
  const noise = c.createBufferSource();
  noise.buffer = buf;
  const lp = c.createBiquadFilter();
  lp.type = 'lowpass';
  lp.frequency.value = 380;
  const pulse = c.createGain();
  pulse.gain.value = .4;
  const lfo = c.createOscillator();
  lfo.frequency.setValueAtTime(23, t);
  lfo.frequency.linearRampToValueAtTime(27, t + dur);
  const depth = c.createGain();
  depth.gain.value = .6;
  lfo.connect(depth).connect(pulse.gain);
  const out = c.createGain();
  out.gain.setValueAtTime(0, t);
  out.gain.linearRampToValueAtTime(vol, t + .4);
  out.gain.setValueAtTime(vol, t + dur - .6);
  out.gain.linearRampToValueAtTime(0, t + dur);
  noise.connect(lp).connect(pulse).connect(out).connect(c.destination);
  noise.start(t); lfo.start(t);
  noise.stop(t + dur); lfo.stop(t + dur);
}

// Each sound: its length in seconds, how to draw it into a context, and how loud it ends up (peak,
// 0–1). The synthesis comes out around -30 dB, which a phone speaker barely plays; every clip is
// scaled to its peak after rendering, the "mrr?" for a wrong answer deliberately the softest.
export const LOUDNESS = { right: .6, wrong: .4, party: .7, pet: .6 };
export const SOUNDS = {
  // Richtig: a short, rising, rolled "mrrp".
  right: [.35, (c) => mew(c, { pitch: [[0, 520], [.6, 820], [1, 760]], formants: [[700, 1100, 1000], [1700, 2300, 2100]], dur: .26, trill: 32, vol: .18 })],
  // Not quite: a soft, questioning "mrr?". Curious, never a sad sound.
  wrong: [.3, (c) => mew(c, { pitch: [[0, 430], [1, 560]], formants: [[600, 650, 800], [1400, 1500, 1700]], dur: .22, trill: 30, vol: .1 })],
  // A finished lesson or a passed checkpoint: a proper "me-ow", then a happy chirp.
  party: [1.15, (c) => {
    mew(c, { pitch: [[0, 560], [.35, 900], [1, 520]], formants: [[500, 1100, 600], [1800, 2400, 1300]], dur: .75, vol: .22 });
    mew(c, { pitch: [[0, 650], [1, 950]], formants: [[800, 1200, 1100], [2000, 2500, 2300]], dur: .2, trill: 34, vol: .15, at: .85 });
  }],
  pet: [2.3, (c) => purr(c)],
};

/* Renders one sound into PCM samples. Resolves to a Float32Array, or null where the browser has no
   offline audio. */
export function render(kind) {
  const [dur, draw] = SOUNDS[kind];
  const Off = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  if (!Off) return Promise.resolve(null);
  const c = new Off(1, Math.ceil(RATE * dur), RATE);
  draw(c);
  return new Promise((resolve) => {
    // Old Safari only has the event; new browsers return a promise. Either way, once.
    let done = false;
    const finish = (buf) => { if (!done) { done = true; resolve(buf ? normalise(buf.getChannelData(0), LOUDNESS[kind]) : null); } };
    c.oncomplete = (e) => finish(e.renderedBuffer);
    const p = c.startRendering();
    if (p && p.then) p.then(finish, () => finish(null));
  });
}

function normalise(samples, target) {
  let peak = 0;
  for (const v of samples) peak = Math.max(peak, Math.abs(v));
  if (peak > 0) { const k = target / peak; for (let i = 0; i < samples.length; i++) samples[i] *= k; }
  return samples;
}

/* 16-bit mono WAV: what every phone's <audio> plays. */
export function wav(samples) {
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const str = (o, s) => { for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i)); };
  str(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); str(8, 'WAVE');
  str(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, RATE, true); view.setUint32(28, RATE * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  str(36, 'data'); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 0x7fff, true);
  return new Blob([view], { type: 'audio/wav' });
}

const clips = {};   // kind -> Promise<object URL | null>
function clip(kind) {
  if (!clips[kind]) clips[kind] = render(kind).then((s) => (s ? URL.createObjectURL(wav(s)) : null)).catch(() => null);
  return clips[kind];
}
/* Render every clip ahead, so the first "mrrp" plays the moment the answer is tapped. */
export function prepare() { for (const k of Object.keys(SOUNDS)) clip(k); }
document.addEventListener('pointerdown', () => { if (soundOn()) prepare(); }, { once: true, capture: true });

/* Play one of Katze's sounds, if the learner has them on. Never throws: a sound is a garnish. */
export function meow(kind) {
  if (!soundOn() || !SOUNDS[kind]) return;
  clip(kind).then((url) => {
    if (!url) return;
    const a = new Audio(url);
    a.play().catch(() => { /* blocked or interrupted: the animation still runs */ });
  });
}
