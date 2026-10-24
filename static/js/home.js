/* Home: today in one screen. Greeting with your Katze, the three daily rings, the plan for
   tonight (lesson → talk → review), and the week's race against the other learner. One payload
   from /game/me plus the lesson, curriculum and leaderboard calls, all cheap and cached server-side. */
import { api } from './api.js';
import { h, clear, errorLine, skeleton, toast } from './ui.js';
import { katze, says, personColor } from './katze.js';
import { rings } from './rings.js';
import { maybeCelebrate } from './moment.js';

const S = { body: null, user: null };

export function mount(el) {
  S.body = h('div', { class: 'screen-body home' });
  clear(el).append(S.body);
}

export async function show() {
  S.user = window.dtUser || null;
  await load();
}
export function hide() {}

async function load() {
  clear(S.body).append(h('div', { class: 'card' }, skeleton(2)), h('div', { class: 'card' }, skeleton(3)), h('div', { class: 'card' }, skeleton(2)));
  try {
    const [game, lesson, cur, board, due] = await Promise.all([
      api('/api/game/me'),
      api('/api/lesson/status').catch(() => null),
      api('/api/curriculum/current').catch(() => null),
      api('/api/leaderboard').catch(() => null),
      api('/api/vocab/due?limit=1').catch(() => ({ due_count: 0 })),
    ]);
    render({ game, lesson, cur, board, due });
    maybeCelebrate(game);
  } catch (e) {
    clear(S.body).append(errorLine(e, load));
  }
}

function greeting() {
  const hr = new Date().getHours();
  if (hr < 11) return 'Guten Morgen';
  if (hr < 18) return 'Guten Tag';
  return 'Guten Abend';
}

function render({ game, lesson, cur, board, due }) {
  clear(S.body);
  const me = S.user || {};
  const g = game.goals || {};
  const mood = game.rings_closed === 3 ? 'cheering' : (game.streak_days === 0 ? 'sleepy' : 'happy');

  S.body.append(h('div', { class: 'home-head' },
    h('button', { class: 'avatar-btn', type: 'button', 'aria-label': 'Your profile', onClick: () => window.dtSwitchTo('you') }, katze({ variant: me.avatar, mood, size: 40 })),
    h('div', { class: 'grow' },
      h('div', { class: 'home-greet', lang: 'de' }, `${greeting()}, ${me.name || ''}`),
      h('div', { class: 'muted small row', style: { gap: '6px' } }, flame(), `${game.streak_days}-day streak`)),
    h('span', { class: 'pill xp' }, `Lv ${game.level.n} · ${game.xp_total} XP`)));

  const ringsEl = rings([
    { key: 'speak', color: 'var(--accent)', track: 'var(--accent-dim)', fraction: g.speak?.fraction || 0 },
    { key: 'review', color: 'var(--good)', track: 'var(--good-dim)', fraction: g.review?.fraction || 0 },
    { key: 'study', color: 'var(--warn)', track: 'var(--warn-dim)', fraction: g.study?.fraction || 0 },
  ], 140);
  S.body.append(h('div', { class: 'card rings-card' }, ringsEl,
    h('div', { class: 'stack', style: { gap: '10px', flex: '1' } },
      legend('Speak', 'var(--accent)', `${g.speak?.done || 0} of ${g.speak?.target || 5} turns`, g.speak?.fraction >= 1),
      legend('Review', 'var(--good)', `${g.review?.done || 0} of ${g.review?.target || 10} cards`, g.review?.fraction >= 1),
      legend('Study', 'var(--warn)', `${g.study?.done || 0} of ${g.study?.target || 1} · lesson, drill or writing`, g.study?.fraction >= 1))));

  const plan = h('div', { class: 'stack' }, h('div', { class: 'card-title' }, 'Today’s plan'));
  if (lesson && lesson.has_lesson && !lesson.completed) {
    plan.append(planCard('book', 'var(--warn)', 'var(--warn-dim)', `Lesson · ${lesson.title || ''}`,
      `Step ${(lesson.step || 0)} of ${lesson.steps || '?'} · about ${lesson.minutes || 6} min`, 'Continue', () => window.dtSwitchTo('learn'), true));
  }
  const sc = cur && cur.scenarios && cur.scenarios[0];
  plan.append(planCard('mic', 'var(--accent)', 'var(--accent-dim)', sc ? `Talk · ${sc.title}` : 'Talk', sc ? sc.goal : 'A conversation with the tutor', 'Start', () => window.dtSwitchTo('talk'), !lesson || lesson.completed));
  const n = due ? due.due_count || 0 : 0;
  plan.append(planCard('cards', 'var(--good)', 'var(--good-dim)', n ? `Review · ${n} cards due` : 'Review', n ? says('due', { n }) : 'Nothing due yet; cards come from conversations', n ? 'Go' : 'Open', () => window.dtSwitchTo('review'), false));
  S.body.append(plan);

  if (board && board.users && board.users.length > 1) {
    const mine = board.users.find((u) => u.id === board.me);
    const other = board.users.find((u) => u.id !== board.me);
    const top = Math.max(1, ...board.users.map((u) => u.xp_week));
    const gap = (other?.xp_week || 0) - (mine?.xp_week || 0);
    const line = gap > 0 ? says('behind', { otherName: other.name, gap }) : gap < 0 ? says('ahead', { otherName: other.name, gap: -gap }) : says('tied', { otherName: other.name });
    S.body.append(h('button', { class: 'card race', type: 'button', onClick: () => window.dtSwitchTo('you') },
      h('div', { class: 'row between' }, h('div', { class: 'card-title' }, 'This week'), h('span', { class: 'muted xs' }, 'resets Monday')),
      ...board.users.map((u) => h('div', { class: 'race-row' },
        h('span', { class: 'race-name' }, u.name),
        h('div', { class: 'meter' }, h('i', { style: { width: `${Math.round(100 * u.xp_week / top)}%`, background: personColor(u, board.users) } })),
        h('span', { class: 'race-xp muted small' }, `${u.xp_week} XP`))),
      h('div', { class: 'row', style: { gap: '8px' } }, katze({ variant: me.avatar, mood: 'thinking', size: 24 }), h('span', { class: 'muted small' }, line))));
  }
}

function legend(name, color, text, closed) {
  return h('div', {}, h('div', { class: 'row', style: { gap: '8px', fontWeight: 600, fontSize: '15px' } }, h('span', { class: 'dot', style: { background: color } }), name),
    h('div', { class: `small ${closed ? 'ok' : 'muted'}`, style: { paddingLeft: '18px' } }, closed ? `${text} · closed` : text));
}

function planCard(icon, color, bg, title, sub, cta, go, primary) {
  return h('button', { class: 'card plan', type: 'button', onClick: go },
    h('span', { class: 'plan-icon', style: { background: bg, color } }, icons[icon]()),
    h('span', { class: 'grow', style: { textAlign: 'left' } }, h('span', { class: 'plan-title' }, title), h('span', { class: 'muted small' }, sub)),
    h('span', { class: `chip small ${primary ? 'active' : ''}` }, cta));
}

function flame() { return h('span', { class: 'ico', html: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="var(--warn)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3c1 3 4 4 4 8a4 4 0 0 1-8 0c0-1 .3-2 1-3 0 2 1 3 2 3 0-3-1-5 1-8z"/></svg>' }); }
const icons = {
  book: () => h('span', { class: 'ico', html: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 5h6a3 3 0 0 1 3 3v12a2 2 0 0 0-2-2H4z"/><path d="M20 5h-6a3 3 0 0 0-3 3v12a2 2 0 0 1 2-2h7z"/></svg>' }),
  mic: () => h('span', { class: 'ico', html: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 14a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3z"/><path d="M19 11a7 7 0 0 1-14 0M12 18v3"/></svg>' }),
  cards: () => h('span', { class: 'ico', html: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="7" width="13" height="13" rx="2"/><path d="M8 4h11a2 2 0 0 1 2 2v11"/></svg>' }),
};
