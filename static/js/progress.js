/* Progress screen: where he is on the CEFR path, five skill meters, a 30-day activity strip,
   recurring mistakes with their trend, vocab counts, the checkpoint call-to-action, and the
   placement re-run. Honest about thin data: no curve drawn from three sessions. */
import { api } from './api.js';
import { h, clear, sheet, errorLine, spinner, fmtDate } from './ui.js';

const S = { root: null, body: null, data: null };

export function mount(el) {
  S.root = el;
  const head = h('header', { class: 'screen-head' }, h('h1', {}, 'Progress'), h('span', { class: 'grow' }),
    h('button', { class: 'btn small ghost', type: 'button', onClick: load }, 'Refresh'));
  S.body = h('div', { class: 'screen-body' });
  clear(el).append(head, S.body);
}

export async function show() { await load(); }
export function hide() {}

async function load() {
  clear(S.body).append(spinner('Loading…'));
  try {
    S.data = await api('/api/progress');
    render(S.data);
  } catch (e) {
    clear(S.body).append(errorLine(e, load));
  }
}

function render(d) {
  clear(S.body);
  const unit = d.unit || {};
  const phase = d.phase || {};
  S.body.append(
    h('div', { class: 'card stack path-card' },
      h('div', { class: 'row between' },
        h('div', {}, h('div', { class: 'level-big' }, d.profile.level), h('div', { class: 'muted small' }, phase.title || '')),
        h('div', { class: 'center' }, h('div', { class: 'unit-pos' }, `Unit ${d.unit_index} of ${d.unit_count}`), h('div', { class: 'muted small' }, unit.title || ''))),
      h('div', { class: 'meter' }, h('i', { style: { width: `${Math.round(100 * (d.unit_index - 1) / Math.max(1, d.unit_count))}%` } })),
      (unit.can_do || []).length ? h('ul', { class: 'cando' }, unit.can_do.map((c) => h('li', {}, c))) : null,
      d.checkpoint && d.checkpoint.available
        ? h('button', { class: 'btn primary block', type: 'button', onClick: () => window.dtSwitchTo('checkpoint') }, 'Take the unit checkpoint')
        : h('p', { class: 'muted small' }, 'The checkpoint opens after a few sessions in this unit, or when the tutor thinks you are ready. It is never forced.')),
    h('div', { class: 'card stack' },
      h('div', { class: 'card-title' }, 'Skills'),
      ...Object.entries(d.skills || {}).map(([k, v]) => h('div', { class: 'skill-row' },
        h('span', { class: 'skill-name' }, k), h('div', { class: 'meter grow' }, h('i', { style: { width: `${v}%` } })), h('span', { class: 'skill-val' }, v))),
      d.thin_data ? h('p', { class: 'muted small' }, 'Early days: these numbers come from only a few sessions and will move a lot.') : null),
    activityCard(d),
    mistakesCard(d),
    vocabCard(d),
    sessionsCard(d),
    h('div', { class: 'card stack' },
      h('div', { class: 'card-title' }, 'Placement'),
      h('p', { class: 'muted small' }, d.profile.placement_done ? 'Think the level is off? Re-run the placement any time.' : 'You skipped the placement. Run it to find your level.'),
      h('button', { class: 'btn block', type: 'button', onClick: () => window.dtSwitchTo('placement', { rerun: true }) }, d.profile.placement_done ? 'Re-run placement' : 'Run placement')));
}

function activityCard(d) {
  const days = d.activity || [];
  const totals = days.map((a) => (a.talk_turn || 0) + (a.review || 0) + (a.drill || 0) + (a.write || 0) + (a.checkpoint || 0));
  const max = Math.max(1, ...totals);
  const strip = h('div', { class: 'strip', role: 'img', 'aria-label': 'Activity over the last 30 days' }, days.map((a, i) =>
    h('span', { class: `bar ${totals[i] ? 'on' : ''}`, title: `${a.day}: ${totals[i]}`, style: { height: `${Math.max(totals[i] ? 14 : 4, Math.round(100 * totals[i] / max))}%` } })));
  return h('div', { class: 'card stack' },
    h('div', { class: 'row between' }, h('div', { class: 'card-title' }, 'Last 30 days'), h('span', { class: 'small' }, `${d.streak_days} day streak`)),
    strip,
    h('div', { class: 'row between muted small' }, h('span', {}, days[0] ? fmtDate(Date.parse(days[0].day) / 1000) : ''), h('span', {}, 'today')));
}

function mistakesCard(d) {
  const top = d.top_mistakes || [];
  const beaten = d.beaten_mistakes || [];
  return h('div', { class: 'card stack' },
    h('div', { class: 'card-title' }, 'Recurring mistakes'),
    top.length ? top.map((m) => {
      const ex = (m.examples || []).slice(-1)[0];
      return h('div', { class: 'mistake-row' },
        h('div', { class: 'row between' },
          h('span', { class: 'cat' }, m.category.replace(/_/g, ' ')),
          h('span', { class: `trend ${m.trend === 'improving' ? 'ok' : ''}` }, m.trend === 'improving' ? '↗ improving' : `${m.count - m.resolved} to go`)),
        h('div', {}, m.pattern),
        ex && ex.wrong ? h('div', { class: 'muted small' }, h('s', {}, ex.wrong), ' → ', ex.right) : null);
    }) : h('p', { class: 'muted small' }, 'Nothing recurring yet. The analyzer fills this after a few conversations.'),
    beaten.length ? h('details', {}, h('summary', { class: 'muted small' }, `${beaten.length} beaten`),
      h('ul', { class: 'small' }, beaten.map((m) => h('li', {}, `${m.category.replace(/_/g, ' ')}: ${m.pattern}`)))) : null,
    top.length ? h('button', { class: 'btn block', type: 'button', onClick: () => window.dtSwitchTo('drill') }, 'Drill these') : null);
}

function vocabCard(d) {
  const v = d.vocab || {};
  const tile = (n, label) => h('div', { class: 'tile' }, h('div', { class: 'tile-n' }, n ?? 0), h('div', { class: 'muted small' }, label));
  return h('div', { class: 'card stack' },
    h('div', { class: 'card-title' }, 'Vocabulary'),
    h('div', { class: 'tiles' }, tile(v.total, 'words'), tile(v.due, 'due'), tile(v.mature, 'mature'), tile(v.new, 'new')),
    v.due ? h('button', { class: 'btn block', type: 'button', onClick: () => window.dtSwitchTo('review') }, `Review ${v.due} due`) : null);
}

function sessionsCard(d) {
  const list = d.recent_sessions || [];
  return h('div', { class: 'card stack' },
    h('div', { class: 'card-title' }, 'Recent sessions'),
    list.length ? list.map((s) => h('button', { class: 'session-row', type: 'button', onClick: () => sheet.open(h('div', { class: 'stack' },
      h('p', { class: 'muted small' }, `${fmtDate(s.started_at)} · ${s.mode}${s.scenario_title ? ' · ' + s.scenario_title : ''} · ${s.user_turns || 0} turns`),
      h('p', {}, s.summary || 'No summary yet.')), { title: 'Session' }) },
      h('div', { class: 'row between' }, h('span', {}, s.scenario_title || (s.mode === 'talk' ? 'Free conversation' : s.mode)), h('span', { class: 'muted small' }, fmtDate(s.started_at))),
      h('p', { class: 'muted small clamp' }, s.summary || `${s.user_turns || 0} turns`))) : h('p', { class: 'muted small' }, 'No sessions yet.'));
}
