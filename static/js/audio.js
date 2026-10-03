/* Audio: iOS unlock, TTS playback through /api/tts, and the MediaRecorder wrapper.

   - unlockAudio(): iOS only allows playback that started from a user gesture. Playing a silent clip
     on the first tap buys the page permission for later programmatic plays.
   - speak(text, speed): fetches (and caches by text+speed) the mp3 from the server; "slow" is a
     separate server-side render, never playbackRate, which sounds awful on phones. Playback
     progress is reported so a message can draw its thin progress line.
   - Recorder: MediaRecorder with NO forced mime type (iOS → audio/mp4, Chrome → audio/webm), plus an
     AnalyserNode level meter: a real meter, so an OS-muted mic shows as silence. */
import { api } from './api.js';

let unlocked = false;
export function unlockAudio() {
  if (unlocked) return;
  unlocked = true;
  const a = new Audio('data:audio/mp3;base64,//uQxAAAAAAAAAAAAAAAAAAAAAAAWGluZwAAAA8AAAACAAACcQCA');
  a.play().catch(() => { unlocked = false; });
}

const urlCache = new Map();   // "speed|text" -> object URL
let currentAudio = null;
let onStateChange = () => {};
export function setPlaybackListener(fn) { onStateChange = fn; }

async function fetchClip(text, speed) {
  const key = `${speed}|${text}`;
  if (urlCache.has(key)) return urlCache.get(key);
  const res = await api(`/api/tts?speed=${speed}&text=${encodeURIComponent(text)}`, { raw: true, timeout: 45000 });
  const url = URL.createObjectURL(await res.blob());
  if (urlCache.size > 60) { const first = urlCache.keys().next().value; URL.revokeObjectURL(urlCache.get(first)); urlCache.delete(first); }
  urlCache.set(key, url);
  return url;
}

export function stop() {
  if (currentAudio) { const a = currentAudio; currentAudio = null; a.pause(); a.currentTime = 0; onStateChange(null); }
}

/* Resolves when playback ends. Rejects with {name:'NotAllowedError'} when iOS refuses autoplay,
   so the caller shows a tap-to-play button rather than failing silently. */
export async function speak(text, speed = 'normal', { id } = {}) {
  const url = await fetchClip(text, speed);
  stop();
  const audio = new Audio(url);
  currentAudio = audio;
  onStateChange({ id, speed, playing: true, progress: 0 });
  audio.ontimeupdate = () => {
    if (currentAudio === audio && audio.duration) onStateChange({ id, speed, playing: true, progress: audio.currentTime / audio.duration });
  };
  await audio.play();
  await new Promise((resolve) => { audio.onended = resolve; audio.onpause = resolve; audio.onerror = resolve; });
  if (currentAudio === audio) { currentAudio = null; onStateChange(null); }
}

export function prefetch(text, speed = 'normal') { fetchClip(text, speed).catch(() => {}); }

export class Recorder {
  constructor({ onLevel, onTick } = {}) {
    this.onLevel = onLevel || (() => {});
    this.onTick = onTick || (() => {});
    this.rec = null; this.chunks = []; this.stream = null; this.ctx = null; this.startedAt = 0;
  }

  static get supported() { return !!(navigator.mediaDevices && window.MediaRecorder); }

  async start() {
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    this.rec = new MediaRecorder(this.stream);       // the browser picks the container
    this.chunks = [];
    this.rec.ondataavailable = (e) => { if (e.data && e.data.size) this.chunks.push(e.data); };
    this.rec.start(250);
    this.startedAt = Date.now();
    this._meter();
    this._timer = setInterval(() => this.onTick(Date.now() - this.startedAt), 200);
  }

  _meter() {
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new Ctx();
      const src = this.ctx.createMediaStreamSource(this.stream);
      const analyser = this.ctx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      const buf = new Uint8Array(analyser.fftSize);
      const tick = () => {
        if (!this.rec || this.rec.state !== 'recording') return;
        analyser.getByteTimeDomainData(buf);
        let sum = 0;
        for (const v of buf) { const d = (v - 128) / 128; sum += d * d; }
        this.onLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4));
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    } catch { /* no meter on this browser; recording still works */ }
  }

  _cleanup() {
    clearInterval(this._timer);
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    if (this.ctx) { this.ctx.close().catch(() => {}); this.ctx = null; }
    this.stream = null;
  }

  get durationMs() { return this.startedAt ? Date.now() - this.startedAt : 0; }

  /* Resolves to {blob, mime, durationMs}. */
  stop() {
    return new Promise((resolve) => {
      const rec = this.rec;
      if (!rec || rec.state === 'inactive') { this._cleanup(); resolve(null); return; }
      const durationMs = this.durationMs;
      rec.onstop = () => {
        const mime = rec.mimeType || 'audio/webm';
        const blob = new Blob(this.chunks, { type: mime });
        this._cleanup();
        this.rec = null;
        resolve({ blob, mime, durationMs });
      };
      rec.stop();
    });
  }

  cancel() {
    const rec = this.rec;
    this.rec = null;
    if (rec && rec.state !== 'inactive') { rec.onstop = null; rec.stop(); }
    this._cleanup();
  }
}
