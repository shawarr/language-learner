/* Katze's voice: a purr, a "mrrp", a "mrr?" and a "me-ow", made on the phone with Web Audio.

   No sound files: the CSP allows no external assets, and a synthesised cat is a few lines. The
   voice is a buzzy oscillator through two moving formants (the "m-ee-ow" vowel), the rolled r of a
   "mrrp" is that voice switched on and off about thirty times a second, and a purr is low noise
   pulsed at the same rate. Sounds play only on the learner's own actions (an answer, a tap, a
   finished lesson), never on a timer, and the switch on the You screen turns them off. */
import { prefs } from './ui.js';

let ctx = null;
function ac() {
  if (!ctx) {
    const C = window.AudioContext || window.webkitAudioContext;
    if (!C) return null;
    ctx = new C();
  }
  if (ctx.state === 'suspended') ctx.resume().catch(() => {});
  return ctx;
}

/* iOS only lets audio start inside a tap. The first tap anywhere opens the context, so a sound that
   comes later (after a transcription, say) can still play. */
document.addEventListener('pointerdown', () => { if (soundOn()) ac(); }, { once: true, capture: true });

export const soundOn = () => prefs.get('katzeSound', true) !== false;
export function setSound(on) { prefs.set('katzeSound', !!on); if (on) ac(); }

function mew({ pitch, formants, dur, vol = .2, trill = 0, at = 0 }) {
  const c = ac();
  if (!c) return;
  const t = c.currentTime + .02 + at;
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

function purr(dur = 2.2, vol = .5) {
  const c = ac();
  if (!c) return;
  const t = c.currentTime + .02;
  const len = Math.floor(c.sampleRate * dur);
  const buf = c.createBuffer(1, len, c.sampleRate);
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

const SOUNDS = {
  // Richtig: a short, rising, rolled "mrrp".
  right: () => mew({ pitch: [[0, 520], [.6, 820], [1, 760]], formants: [[700, 1100, 1000], [1700, 2300, 2100]], dur: .26, trill: 32, vol: .18 }),
  // Not quite: a soft, questioning "mrr?". Curious, never a sad sound.
  wrong: () => mew({ pitch: [[0, 430], [1, 560]], formants: [[600, 650, 800], [1400, 1500, 1700]], dur: .22, trill: 30, vol: .1 }),
  // A finished lesson or a passed checkpoint: a proper "me-ow", then a happy chirp.
  party: () => {
    mew({ pitch: [[0, 560], [.35, 900], [1, 520]], formants: [[500, 1100, 600], [1800, 2400, 1300]], dur: .75, vol: .22 });
    mew({ pitch: [[0, 650], [1, 950]], formants: [[800, 1200, 1100], [2000, 2500, 2300]], dur: .2, trill: 34, vol: .15, at: .85 });
  },
  pet: () => purr(),
};

/* Play one of Katze's sounds, if the learner has them on. Never throws: a sound is a garnish. */
export function meow(kind) {
  if (!soundOn() || !SOUNDS[kind]) return;
  try { SOUNDS[kind](); } catch { /* no Web Audio here; the animation still runs */ }
}
