/* The learning flows' shared parts (Learn, Review, Drill, Placement, Checkpoint, Talk).

   A session runs like a level in a game: focus mode moves the tab bar aside, the player head puts a
   close button and a thick progress track on top, and the action sits in a bar at the bottom, where
   the thumb is. An answer turns that bar into a verdict panel with Katze in it. */
import { h, clear } from './ui.js';
import { katze } from './katze.js';
import { icon } from './icons.js';

const me = () => window.dtUser || {};

/* The tab bar steps aside while a session runs; the shell clears this on every screen switch. */
export function focusMode(on) {
  const app = document.getElementById('app');
  if (app) app.classList.toggle('focus', !!on);
}

/* Close button, progress track, count. `set(value, total)` fills a continuous bar;
   `segments(states, label)` draws one segment per item ('right' | 'wrong' | 'now' | ''). */
export function playerHead({ onClose, closeLabel = 'Close' } = {}) {
  const track = h('div', { class: 'track', role: 'progressbar', 'aria-valuemin': '0', 'aria-label': 'Progress' });
  const count = h('span', { class: 'track-count num' });
  const el = h('header', { class: 'player-head' },
    h('button', { class: 'btn icon ghost', type: 'button', 'aria-label': closeLabel, onClick: onClose }, icon('close', 22)),
    track, count);
  let fill = null;
  return {
    el,
    set(value, total) {
      if (!fill || track.classList.contains('segmented')) {
        track.classList.remove('segmented');
        fill = h('i');
        clear(track).append(fill);
      }
      const f = total ? Math.max(0, Math.min(1, value / total)) : 0;
      // Set on the next frame so the bar visibly moves rather than appearing at its new length.
      requestAnimationFrame(() => { fill.style.width = `${(f * 100).toFixed(1)}%`; });
      track.setAttribute('aria-valuemax', String(total));
      track.setAttribute('aria-valuenow', String(Math.min(value, total)));
      count.textContent = total ? `${Math.min(value, total)} / ${total}` : '';
    },
    segments(states, label) {
      track.classList.add('segmented');
      clear(track).append(...states.map((s) => h('i', { class: s || '' })));
      track.setAttribute('aria-valuemax', String(states.length));
      track.setAttribute('aria-valuenow', String(states.filter(Boolean).length));
      count.textContent = label || '';
    },
  };
}

/* The bottom bar of a session. `actions(...nodes)` shows buttons; `verdict({...})` turns it into
   the answer panel and resolves when Continue is pressed. */
export function playerFoot() {
  const el = h('footer', { class: 'player-foot' });
  return {
    el,
    actions(...nodes) {
      el.className = 'player-foot';
      clear(el).append(...nodes.flat().filter(Boolean));
    },
    verdict({ ok, title, detail = null, cta = 'Continue', onContinue }) {
      el.className = `player-foot ${ok ? 'ok' : 'no'}`;
      const btn = h('button', { class: `btn block lg tactile ${ok ? 'good' : 'warn'}`, type: 'button', onClick: onContinue }, cta);
      clear(el).append(
        h('div', { class: 'verdict', role: 'status' },
          katze({ variant: me().avatar, mood: ok ? 'proud' : 'thinking', size: 44 }),
          h('div', { class: 'grow' },
            h('div', { class: 'verdict-title' }, title || (ok ? 'Richtig' : 'Not quite')),
            detail ? h('div', { class: 'verdict-detail' }, detail) : null)),
        btn);
      setTimeout(() => btn.focus({ preventScroll: true }), 60);
      return btn;
    },
    clear() { el.className = 'player-foot'; clear(el); },
  };
}

/* Katze with a speech bubble. The first line is the remark, `sub` its translation or a note. */
export function katzeSays(text, { mood = 'happy', size = 56, sub = null, lang = null } = {}) {
  return h('div', { class: 'says' },
    katze({ variant: me().avatar, mood, size }),
    h('div', { class: 'says-bubble' }, h('p', { class: 'says-line', lang }, text), sub ? h('p', { class: 'says-sub' }, sub) : null));
}

/* Words written against a target range: the band is the range, the fill the count. */
export function wordMeter(min, max) {
  const scale = Math.max(max * 1.25, max + 10);
  const fill = h('i', { class: 'wm-fill' });
  const label = h('span', { class: 'wm-label num' });
  const el = h('div', { class: 'word-meter' },
    h('div', { class: 'wm-track', 'aria-hidden': 'true' },
      h('i', { class: 'wm-band', style: { left: `${(100 * min) / scale}%`, width: `${(100 * (max - min)) / scale}%` } }), fill),
    label);
  return {
    el,
    update(n) {
      fill.style.width = `${Math.min(100, (100 * n) / scale)}%`;
      const state = n === 0 ? 'empty' : n < min ? 'under' : n <= max ? 'in' : 'over';
      el.dataset.state = state;
      const tail = state === 'in' ? 'in range' : state === 'over' ? `over ${max}, fine if it flows` : `aim for ${min}–${max}`;
      label.textContent = `${n} ${n === 1 ? 'word' : 'words'} · ${tail}`;
    },
  };
}

/* A divided strip of figures: [[value, label], …]. */
export function statStrip(items) {
  return h('div', { class: 'stat-strip' }, items.map(([n, label]) =>
    h('div', {}, h('span', { class: 'stat-n num' }, n), h('span', { class: 'stat-l' }, label))));
}

/* Sentence with its gaps drawn as blanks: "Ich ___ aus Jordanien." */
export function withGaps(text) {
  const parts = String(text).split(/(_{2,}|…{1,}|\.{3,})/);
  return parts.map((p) => (/^(_{2,}|…+|\.{3,})$/.test(p) ? h('span', { class: 'gap', 'aria-label': 'blank' }) : p));
}
