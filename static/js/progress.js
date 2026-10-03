/* Progress screen: where he is on the CEFR path, five skill meters (animate from 0 on first paint),
   a 30-day activity strip, recurring mistakes with their trend, vocab counts, the checkpoint
   call-to-action and the placement re-run. Honest about thin data (docs/DESIGN.md §5). */
import { api } from './api.js';
import { h, clear, sheet, errorLine, skeleton, fmtDate, catChip, de } from './ui.js';

const S = { body: null, data: null };

export function mount(el) {
  const head = h('header', { class: 'screen-head' }, h('h1', {}, 'Progress'), h('span', { class: 'grow' }),
    h('button', { class: 'btn small ghost', type: 'button', onClick: load }, 'Refresh'));
  S.body = h('div', { class: 'screen-body' });
  clear(el).append(head, S.body);
}

export async function show() { await load(); }
export function hide() {}

async function load() {
  clear(S.body).append(h('div', { class: 'card' }, skeleton(3)), h('div', { class: 'card' }, skeleton(5)), h('div', { class: 'card' }, skeleton(2)));
  try {
    S.data = await api('/api/progress');
    render(S.data);
  } catch (e) {
    clear(S.body).append(errorLine(e, load));
  }
}

/* Meters start at 0 and fill on the next frame, so the CSS transition animates them on first paint. */
function meter(pct, cls = '') {
  const bar = h('div', { class: `meter ${cls}` }, h('i', { style: { width: '0%' } }));
  requestAnimationFrame(() => requestAnimationFrame(() => { bar.firstChild.style.width = `${Math.max(0, Math.min(100, pct))}%`; }));
  return bar;
}

function render(d) {
  clear(S.body);
  const unit = d.unit || {};
  const phase = d.phase || {};
  const cp = d.checkpoint || {};
  S.body.append(
    h('div', { class: 'card stack path-card' },
      h('div', { class: 'row between' },
        h('div', {}, h('div', { class: 'level-big' }, d.profile.level), h('div', { class: 'muted small' }, phase.title || '')),
        h('div', { class: 'center' }, h('div', { class: 'unit-pos' }, `Unit ${d.unit_index} of ${d.unit_count}`), de(unit.title || '', 'muted small'))),
      meter(100 * (d.unit_index - 1) / Math.max(1, d.unit_count)),
      (unit.can_do || []).length ? h('ul', { class: 'cando' }, unit.can_do.map((c) => h('li', {}, c))) : null,
      cp.available
        ? h('button', { class: 'btn primary block', type: 'button', onClick: () => window.dtSwitchTo('checkpoint') }, 'Take the unit checkpoint')
        : h('p', { class: 'muted small' }, cp.sessions_needed
          ? `Checkpoint after ${cp.sessions_needed} conversations in this unit (${cp.sessions_in_unit || 0} so far), or sooner if the tutor thinks you are ready. Never forced.`
          : 'The checkpoint opens after a few conversations in this unit, or when the tutor thinks you are ready. It is never forced.')),
    h('div', { class: 'card stack' },
      h('div', { class: 'card-title' }, 'Skills'),
      ...Object.entries(d.skills || {}).map(([k, v]) => h('div', { class: 'skill-row' },
        h('span', { class: 'skill-name' }, k), h('div', { class: 'grow' }, meter(v)), h('span', { class: 'skill-val' }, v))),
      d.thin_data ? h('p', { class: 'muted small' }, 'Not enough sessions yet for these to mean much — they settle after a week or two.') : null),
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
  const bars = days.map((a, i) => h('span', { class: `bar ${totals[i] ? 'on' : ''}`, title: `${a.day}: ${totals[i]}`, style: { height: '4px' } }));
  requestAnimationFrame(() => requestAnimationFrame(() => bars.forEach((b, i) => { b.style.height = `${Math.max(totals[i] ? 14 : 4, Math.round(100 * totals[i] / max))}%`; })));
  const strip = h('div', { class: 'strip', role: 'img', 'aria-label': `Activity over the last 30 days, ${d.streak_days} day streak` }, bars);
  return h('div', { class: 'card stack' },
    h('div', { class: 'row between' }, h('div', { class: 'card-title' }, 'Last 30 days'), h('span', { class: 'small' }, d.streak_days ? `${d.streak_days}-day streak` : 'no streak yet')),
    strip,
    h('div', { class: 'row between muted xs' }, h('span', {}, days[0] ? fmtDate(Date.parse(days[0].day) / 1000) : ''), h('span', {}, 'today')));
}

function mistakesCard(d) {
  const top = d.top_mistakes || [];
  const beaten = d.beaten_mistakes || [];
  return h('div', { class: 'card stack' },
    h('div', { class: 'card-title' }, 'Recurring mistakes'),
    top.length ? top.map((m) => {
      const ex = (m.examples || []).slice(-1)[0];
      return h('div', { class: 'mistake-row' },
        h('div', { class: 'row between' }, catChip(m.category),
          h('span', { class: `trend ${m.trend === 'improving' ? 'ok' : ''}` }, m.trend === 'improving' ? '↗ improving' : `${m.count - m.resolved} to go`)),
        h('div', {}, m.pattern),
        ex && ex.wrong ? h('div', { class: 'muted small', lang: 'de' }, h('s', {}, ex.wrong), ' → ', ex.right) : null);
    }) : h('p', { class: 'muted small' }, 'Nothing recurring yet. The analyzer fills this in after a few conversations.'),
    beaten.length ? h('details', {}, h('summary', { class: 'muted small' }, `${beaten.length} beaten`),
      h('ul', { class: 'small' }, beaten.map((m) => h('li', {}, `${m.category.replace(/_/g, ' ')}: ${m.pattern}`)))) : null,
    top.length ? h('button', { class: 'btn block', type: 'button', onClick: () => window.dtSwitchTo('drill') }, 'Drill these') : null);
}

function vocabCard(d) {
  const v = d.vocab || {};
  const tile = (n, label) => h('div', { class: 'tile' }, h('div', { class: 'tile-n' }, n ?? 0), h('div', { class: 'muted xs' }, label));
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
      h('p', { class: 'muted xs' }, `${fmtDate(s.started_at)} · ${s.mode}${s.scenario_title ? ' · ' + s.scenario_title : ''} · ${s.user_turns || 0} turns`),
      h('p', {}, s.summary || 'No summary yet.')), { title: 'Session' }) },
      h('div', { class: 'row between' }, h('span', {}, s.scenario_title || (s.mode === 'talk' ? 'Free conversation' : s.mode)), h('span', { class: 'muted xs' }, fmtDate(s.started_at))),
      h('p', { class: 'muted small clamp' }, s.summary || `${s.user_turns || 0} turns`))) : h('p', { class: 'muted small' }, 'No sessions yet. The first conversation shows up here.'));
}
