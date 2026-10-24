/* Milestones. Quiet lines for small wins (a toast), one full-screen Katze moment for the big
   ones: a level up, a new badge, the day's three rings closed. Level-ups are detected against the
   last level this device saw; badges come from the server's `new_badges` and are marked seen. */
import { api } from './api.js';
import { h, clear, prefs, haptic } from './ui.js';
import { katze } from './katze.js';

const ICONS = {
  mic: '<path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3z"/><path d="M19 11a7 7 0 0 1-14 0M12 18v3"/>',
  flame: '<path d="M12 3c1 3 4 4 4 8a4 4 0 0 1-8 0c0-1 .3-2 1-3 0 2 1 3 2 3 0-3-1-5 1-8z"/>',
  book: '<path d="M4 5h6a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H4z"/><path d="M20 5h-6a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h7z"/>',
  star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
  trophy: '<path d="M8 21h8M12 17v4M6 4h12v4a6 6 0 0 1-12 0z"/><path d="M6 6H3v2a3 3 0 0 0 3 3M18 6h3v2a3 3 0 0 1-3 3"/>',
  cat: '<path d="M5 9l-1-5 5 3h6l5-3-1 5a7 7 0 1 1-14 0z"/>',
};
export function badgeIcon(slug, size = 28, color = 'currentColor') {
  return h('span', { class: 'ico', style: { width: `${size}px`, height: `${size}px` },
    html: `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${ICONS[slug] || ICONS.star}</svg>` });
}

let showing = false;
const queue = [];

/* Call with /game/me's payload after any screen loads it. */
export function maybeCelebrate(game) {
  const user = window.dtUser || {};
  const key = `level:${user.id}`;
  const last = prefs.get(key, null);
  if (last != null && game.level.n > last) {
    queue.push({ kind: 'level', level: game.level, xp: game.xp_total });
  }
  prefs.set(key, game.level.n);
  for (const id of game.new_badges || []) {
    const b = (game.badges || []).find((x) => x.id === id);
    if (b) queue.push({ kind: 'badge', badge: b });
  }
  const ringsKey = `rings:${user.id}:${new Date().toISOString().slice(0, 10)}`;
  if (game.rings_closed === 3 && !prefs.get(ringsKey, false)) { prefs.set(ringsKey, true); queue.push({ kind: 'rings' }); }
  next();
}

function next() {
  if (showing || !queue.length) return;
  showing = true;
  const m = queue.shift();
  const user = window.dtUser || {};
  const root = document.getElementById('moment-root');
  const headline = m.kind === 'level' ? `Level ${m.level.n}` : m.kind === 'badge' ? m.badge.title : 'Three rings';
  const sub = m.kind === 'level' ? m.level.title : m.kind === 'badge' ? m.badge.description : 'That is a good evening.';
  const eyebrow = m.kind === 'level' ? 'Level up' : m.kind === 'badge' ? 'New badge' : 'Day complete';
  const btn = h('button', { class: 'btn primary block', type: 'button' }, 'Weiter');
  const el = h('div', { class: 'moment', role: 'dialog', 'aria-modal': 'true', 'aria-label': `${eyebrow}: ${headline}` },
    h('div', { class: 'moment-cat' }, h('div', { class: 'moment-halo', 'aria-hidden': 'true' }, h('i'), h('i'), h('i')), m.kind === 'badge' ? badgeIcon(m.badge.icon, 64, 'var(--warn)') : katze({ variant: user.avatar, mood: m.kind === 'rings' ? 'cheering' : 'proud', size: 130 })),
    h('div', { class: 'moment-text' }, h('div', { class: 'eyebrow' }, eyebrow), h('div', { class: 'moment-h' }, headline), h('div', { class: 'moment-sub' }, sub)),
    btn);
  btn.addEventListener('click', async () => {
    el.classList.remove('open');
    setTimeout(() => { el.remove(); showing = false; next(); }, 220);
    if (m.kind === 'badge') { try { await api('/api/game/seen', { method: 'POST', body: { badge_ids: [m.badge.id] } }); } catch { /* next load */ } }
  });
  clear(root).append(el);
  haptic(20);
  requestAnimationFrame(() => el.classList.add('open'));
}
