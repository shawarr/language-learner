/* You: your Katze and level, the head-to-head leaderboard (totals only), badges, then the
   detailed progress (CEFR path, skills, activity, mistakes) from the existing progress screen,
   and the account actions: avatar, placement re-run, log out. */
import { api } from './api.js';
import { h, clear, toast, sheet, errorLine, skeleton, fmtDays } from './ui.js';
import { katze, VARIANTS, variantName, personColor } from './katze.js';
import { ringAround } from './rings.js';
import { badgeIcon, maybeCelebrate } from './moment.js';
import * as progress from './progress.js';

const S = { body: null, progressEl: null };

export function mount(el) {
  S.body = h('div', { class: 'screen-body' });
  S.progressEl = h('div', { class: 'you-progress' });
  clear(el).append(h('header', { class: 'screen-head' }, h('h1', {}, 'You'), h('span', { class: 'grow' }),
    h('button', { class: 'btn small ghost', type: 'button', onClick: logout }, 'Log out')), S.body);
  progress.mount(S.progressEl, { embedded: true });
}
export async function show() { await load(); }
export function hide() {}

async function load() {
  if (!S.body.childElementCount || S.body.querySelector('.error-line')) clear(S.body).append(h('div', { class: 'card' }, skeleton(2)), h('div', { class: 'card' }, skeleton(4)));
  try {
    const [game, board] = await Promise.all([api('/api/game/me'), api('/api/leaderboard')]);
    render(game, board);
    maybeCelebrate(game);
    progress.show();
  } catch (e) { clear(S.body).append(errorLine(e, load)); }
}

function render(game, board) {
  const me = window.dtUser || {};
  clear(S.body);
  S.body.append(h('div', { class: 'you-head' },
    ringAround(game.level.fraction, 92, 'var(--warn)', 'var(--warn-dim)', katze({ variant: me.avatar, mood: 'happy', size: 58 })),
    h('div', { class: 'grow' },
      h('div', { class: 'you-name' }, me.name),
      h('div', { class: 'small', style: { color: 'var(--warn)', fontWeight: 600 } }, `Level ${game.level.n} · ${game.level.title}`),
      h('div', { class: 'muted small' }, `${game.xp_total} XP · ${game.level.xp_for_next - game.level.xp_into_level} to level ${game.level.n + 1}`)),
    h('button', { class: 'btn icon', type: 'button', 'aria-label': 'Change your Katze', onClick: pickAvatar }, h('span', { class: 'ico', html: '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17.3V20h2.7L17.8 8.9l-2.7-2.7z"/><path d="M14.4 7l2.7 2.7"/></svg>' }))));

  const users = board.users || [];
  if (users.length > 1) {
    const other = users.find((u) => u.id !== board.me);
    const mine = users.find((u) => u.id === board.me);
    const left = other, right = mine;
    const col = (u, color) => h('div', { class: 'h2h-col' }, katze({ variant: u.avatar, size: 56 }), h('div', { style: { fontWeight: 600 } }, u.name),
      h('div', { class: 'h2h-xp', style: { color } }, u.xp_week), h('div', { class: 'muted xs' }, 'XP this week'));
    const stat = (a, label, b) => h('div', { class: 'h2h-row' }, h('span', { class: 'h2h-l' }, a), h('span', { class: 'muted xs h2h-m' }, label), h('span', { class: 'h2h-r' }, b));
    const daysLeft = 7 - ((new Date().getUTCDay() + 6) % 7);
    S.body.append(h('div', { class: 'card stack h2h' },
      h('div', { class: 'row between' }, h('div', { class: 'card-title' }, 'Head to head · this week'), h('span', { class: 'muted xs' }, `${daysLeft} day${daysLeft === 1 ? '' : 's'} left`)),
      h('div', { class: 'h2h-grid' }, col(left, personColor(left, users)), h('div', { class: 'muted small center' }, 'vs'), col(right, personColor(right, users))),
      h('div', { class: 'stack h2h-stats' },
        stat(days(left.streak_days), 'streak', days(right.streak_days)),
        stat(`Lv ${left.level.n} · ${left.cefr_level}`, 'level', `Lv ${right.level.n} · ${right.cefr_level}`),
        stat(left.units_passed, 'units passed', right.units_passed),
        stat(left.words_mature, 'words learned', right.words_mature),
        stat(left.xp_total, 'XP all time', right.xp_total),
        stat(left.rings_closed_today, 'rings today', right.rings_closed_today)),
      h('p', { class: 'muted xs' }, 'Totals only. Mistakes and transcripts stay private to each of you.')));
  }

  const earned = new Set((game.badges || []).map((b) => b.id));
  S.body.append(h('div', { class: 'card stack' },
    h('div', { class: 'row between' }, h('div', { class: 'card-title' }, 'Badges'), h('span', { class: 'muted xs' }, `${earned.size} of ${(game.catalogue || []).length}`)),
    h('div', { class: 'badge-grid' }, ...(game.catalogue || []).map((b) => {
      const on = earned.has(b.id);
      return h('button', { class: `badge ${on ? 'on' : ''}`, type: 'button', 'aria-label': `${b.title}${on ? '' : ', locked'}`,
        onClick: () => sheet.open(h('div', { class: 'stack center' }, badgeIcon(b.icon, 44, on ? 'var(--warn)' : 'var(--text-dim)'), h('h2', {}, b.title), h('p', { class: 'muted' }, b.description), h('p', { class: 'muted xs' }, on ? 'Earned' : 'Not yet')), { title: null }) },
        badgeIcon(b.icon, 26, on ? badgeColor(b.icon) : 'var(--text-dim)'), h('span', { class: 'xs' }, b.title));
    }))));

  S.body.append(S.progressEl);
}

function days(n) { return `${n} day${n === 1 ? '' : 's'}`; }

function badgeColor(icon) { return { mic: 'var(--accent)', flame: 'var(--warn)', book: 'var(--good)', star: 'var(--cat-gender)', trophy: 'var(--warn)', cat: 'var(--accent)' }[icon] || 'var(--warn)'; }

function pickAvatar() {
  const me = window.dtUser || {};
  const grid = h('div', { class: 'avatar-grid' });
  for (const v of VARIANTS) {
    const b = h('button', { class: `avatar-pick ${me.avatar === v ? 'active' : ''}`, type: 'button', 'aria-label': variantName(v), 'aria-pressed': String(me.avatar === v),
      onClick: async () => {
        try {
          const r = await api('/api/auth/avatar', { method: 'POST', body: { avatar: v } });
          window.dtUser = r.user;
          sheet.close();
          toast(`${variantName(v)} it is.`);
          load();
        } catch (e) { toast(e.detail || 'Could not change.', { kind: 'err' }); }
      } }, katze({ variant: v, size: 56 }));
    grid.append(b);
  }
  sheet.open(h('div', { class: 'stack' }, h('p', { class: 'muted small' }, 'Eight cats, one of you.'), grid), { title: 'Pick your Katze' });
}

async function logout() {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch { /* cookie may already be gone */ }
  location.reload();
}
