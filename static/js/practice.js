/* Practice hub: Review, Drill and Write in one place, with Katze's note on what to work on. The
   three modes keep their own screens; this is the door. */
import { api } from './api.js';
import { h, clear, errorLine, skeleton, fmtDate } from './ui.js';
import { katze } from './katze.js';

const S = { body: null };

export function mount(el) {
  S.body = h('div', { class: 'screen-body' });
  clear(el).append(h('header', { class: 'screen-head' }, h('h1', {}, 'Practice')), S.body);
}
export async function show() { await load(); }
export function hide() {}

async function load() {
  if (!S.body.childElementCount || S.body.querySelector('.error-line')) clear(S.body).append(skeleton(3, { tall: true }));
  try {
    const [due, prog, game] = await Promise.all([
      api('/api/vocab/due?limit=1').catch(() => ({ due_count: 0 })),
      api('/api/progress').catch(() => null),
      api('/api/game/me').catch(() => null),
    ]);
    render(due.due_count || 0, prog, game);
  } catch (e) { clear(S.body).append(errorLine(e, load)); }
}

function render(due, prog, game) {
  clear(S.body);
  if (game) S.body.append(h('p', { class: 'muted small' }, `Study ring: ${game.goals.study.done} of ${game.goals.study.target}`));
  S.body.append(
    hubCard('cards', 'var(--ring-2)', 'var(--surface-2)', 'Review', due ? `${due} card${due === 1 ? '' : 's'} due · about ${Math.max(1, Math.round(due / 4))} min` : 'Nothing due right now', due ? h('span', { class: 'count' }, due) : null, () => window.dtSwitchTo('review')),
    hubCard('bolt', 'var(--warn)', 'var(--warn-dim)', 'Drill', 'Eight items from your own mistakes · 2 min', null, () => window.dtSwitchTo('drill')),
    hubCard('pen', 'var(--accent)', 'var(--accent-dim)', 'Write', 'A short task from your unit, with corrections', null, () => window.dtSwitchTo('write')));
  const top = prog && prog.top_mistakes && prog.top_mistakes[0];
  if (top) {
    const ex = (top.examples || []).slice(-1)[0];
    S.body.append(h('div', { class: 'card stack' }, h('div', { class: 'card-title' }, 'Katze noticed'),
      h('div', { class: 'row', style: { alignItems: 'flex-start' } }, katze({ variant: (window.dtUser || {}).avatar, mood: 'thinking', size: 44 }),
        h('p', { class: 'small' }, ex && ex.right ? `“${ex.right}” has come up ${top.count} times. The next drill leans on it; beat it ${Math.max(1, top.count - top.resolved)} more and it leaves the tutor’s list.` : `${top.pattern} keeps coming back. The next drill leans on it.`))));
  }
  const recent = (prog && prog.recent_sessions || []).slice(0, 3);
  if (recent.length) {
    S.body.append(h('div', { class: 'stack' }, h('div', { class: 'card-title' }, 'Recent'), ...recent.map((s) =>
      h('div', { class: 'card row between', style: { padding: '12px 14px' } }, h('span', { class: 'small' }, s.scenario_title || (s.mode === 'talk' ? 'Free conversation' : s.mode[0].toUpperCase() + s.mode.slice(1))), h('span', { class: 'muted xs' }, fmtDate(s.started_at))))));
  }
}

const ICONS = {
  cards: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="7" width="13" height="13" rx="2"/><path d="M8 4h11a2 2 0 0 1 2 2v11"/></svg>',
  bolt: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M13 2 4.5 13.5h6L10 22l8.5-11.5h-6z"/></svg>',
  pen: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17.3V20h2.7L17.8 8.9l-2.7-2.7z"/><path d="M14.4 7l2.7 2.7"/></svg>',
};
function hubCard(icon, color, bg, title, sub, tail, go) {
  return h('button', { class: 'card hub', type: 'button', onClick: go },
    h('span', { class: 'hub-icon', style: { color }, html: ICONS[icon] }),
    h('span', { class: 'grow', style: { textAlign: 'left' } }, h('span', { class: 'hub-title' }, title), h('span', { class: 'muted small' }, sub)),
    tail || h('span', { class: 'ico muted', html: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>' }));
}
