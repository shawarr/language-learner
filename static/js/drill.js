/* Drill: eight short items built from the learner's own mistakes, instant feedback per item, no
   timer (docs/DESIGN.md §5). It runs in the player: the track has one segment per item and colours
   each one as it is answered, the answer comes back as the verdict panel, and the end is a score
   ring. Closing mid-drill keeps it; coming back resumes at the same item. */
import { api } from './api.js';
import { h, clear, toast, errorLine, catChip, haptic } from './ui.js';
import { katze } from './katze.js';
import { ringAround } from './rings.js';
import { icon } from './icons.js';
import { maybeCelebrate } from './moment.js';
import { focusMode, playerHead, playerFoot, katzeSays, statStrip, withGaps } from './kit.js';

const S = { root: null, listView: null, body: null, playerView: null, head: null, pbody: null, foot: null,
  drill: null, idx: 0, results: [], pending: false };
const me = () => window.dtUser || {};

export function mount(el) {
  S.root = el;
  S.body = h('div', { class: 'screen-body' });
  S.listView = h('div', { class: 'learn-view' }, h('header', { class: 'screen-head' }, h('h1', {}, 'Drill')), S.body);
  S.head = playerHead({ onClose: leave, closeLabel: 'Leave the drill' });
  S.pbody = h('div', { class: 'player-body' });
  S.foot = playerFoot();
  S.playerView = h('div', { class: 'player', hidden: true }, S.head.el, S.pbody, S.foot.el);
  clear(el).append(S.listView, S.playerView);
}

export function show() {
  if (S.drill && S.idx < S.drill.items.length) { setView(true); renderItem(); return; }
  if (!S.drill) renderIntro();
}
export function hide() {}

function setView(session) {
  S.playerView.hidden = !session;
  S.listView.hidden = session;
  focusMode(session);
  S.root.scrollTop = 0;
}

function leave() { setView(false); renderIntro(); window.dtSwitchTo('practice'); }

function renderIntro(err) {
  setView(false);
  const resume = S.drill && S.idx < S.drill.items.length;
  clear(S.body).append(h('div', { class: 'intro' },
    katzeSays('Acht kurze Fragen.', { mood: 'happy', size: 72, lang: 'de', sub: 'Eight short items built from your own recent mistakes.' }),
    h('ul', { class: 'facts' },
      h('li', {}, icon('bolt', 18), h('span', {}, 'About two minutes, and no timer')),
      h('li', {}, icon('check', 18), h('span', {}, 'A right answer retires that mistake from the tutor’s list')),
      h('li', {}, icon('sparkle', 18), h('span', {}, 'Worth 15 XP when you finish'))),
    err ? errorLine(err, startDrill) : null,
    h('button', { class: 'btn primary block lg tactile', type: 'button', onClick: resume ? () => { setView(true); renderItem(); } : startDrill },
      resume ? `Resume at item ${S.idx + 1}` : 'Start the drill'),
    resume ? h('button', { class: 'btn ghost block', type: 'button', onClick: startDrill }, 'Start a new one') : null));
}

async function startDrill() {
  clear(S.body).append(h('div', { class: 'intro' },
    katzeSays('Ich suche deine Fehler heraus…', { mood: 'thinking', size: 72, lang: 'de', sub: 'Picking items from your mistakes. This can take a few seconds…' })));
  try {
    S.drill = await api('/api/drill/new?n=8', { timeout: 90000 });
    S.idx = 0;
    S.results = [];
    setView(true);
    renderItem();
  } catch (e) {
    S.drill = null;
    renderIntro(e);
  }
}

function track() {
  const n = S.drill.items.length;
  S.head.segments(S.drill.items.map((_, i) => {
    const r = S.results[i];
    return r ? (r.correct ? 'right' : 'wrong') : (i === S.idx ? 'now' : '');
  }), `${Math.min(S.idx + 1, n)} / ${n}`);
}

function typeHint(type) {
  return { fill_blank: 'Fill the gap', choose: 'Pick the right one', reorder: 'Put the words in order', transform: 'Rewrite it as asked' }[type] || 'Your answer';
}

function renderItem() {
  const item = S.drill.items[S.idx];
  if (!item) { renderSummary(); return; }
  track();
  clear(S.pbody);
  S.foot.clear();
  S.root.scrollTop = 0;
  S.pbody.append(
    h('div', { class: 'row between' }, h('h2', { class: 'prompt-h sm' }, typeHint(item.type)), catChip(item.category)),
    h('p', { class: 'drill-sentence', lang: 'de' }, withGaps(item.prompt)));
  const options = Array.isArray(item.options) ? item.options.filter(Boolean) : [];
  if (options.length) {
    const box = h('div', { class: 'options' }, options.map((o) =>
      h('button', { class: 'option tactile', type: 'button', lang: 'de', onClick: (e) => submit(item, o, { box, chosen: e.currentTarget }) }, o)));
    S.pbody.append(box);
    S.foot.actions(h('span', { class: 'foot-hint' }, 'Pick one'));
  } else if (item.type === 'reorder' && item.prompt.includes(' / ')) {
    S.pbody.append(reorderBuilder(item));
  } else {
    const input = h('input', { class: 'input answer-input', type: 'text', name: 'answer', lang: 'de', autocapitalize: 'sentences', autocomplete: 'off',
      spellcheck: 'false', enterkeyhint: 'done', placeholder: item.type === 'transform' ? 'Write the new sentence…' : 'Your answer…', 'aria-label': 'Your answer',
      onKeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); check.click(); } } });
    const check = h('button', { class: 'btn primary lg tactile grow', type: 'button', onClick: () => submit(item, input.value, { input, check }) }, 'Check');
    S.pbody.append(input);
    S.foot.actions(check);
  }
}

function reorderBuilder(item) {
  const after = item.prompt.split(':').slice(1).join(':') || item.prompt;
  const tokens = after.split(' / ').map((t) => t.trim().replace(/[.?!]$/, '')).filter(Boolean);
  const chosen = [];
  const slot = h('div', { class: 'build-slot', 'aria-live': 'polite' });
  const bank = h('div', { class: 'build-bank' });
  const check = h('button', { class: 'btn primary lg tactile grow', type: 'button', disabled: true,
    onClick: () => submit(item, chosen.map((c) => c.word).join(' '), { box: bank, check, slot }) }, 'Check');
  const sync = () => { check.disabled = !chosen.length; };
  for (const word of tokens) {
    const tile = h('button', { class: 'word-tile tactile', type: 'button', lang: 'de', onClick: () => {
      if (tile.classList.contains('used') || S.pending) return;
      tile.classList.add('used');
      const placed = h('button', { class: 'word-tile tactile', type: 'button', lang: 'de', onClick: () => {
        if (S.pending) return;
        placed.remove(); tile.classList.remove('used');
        chosen.splice(chosen.findIndex((c) => c.el === placed), 1);
        sync();
      } }, word);
      chosen.push({ word, el: placed });
      slot.append(placed);
      haptic(6);
      sync();
    } }, word);
    bank.append(tile);
  }
  S.foot.actions(check);
  return h('div', { class: 'stack' }, slot, bank);
}

async function submit(item, answer, { box = null, chosen = null, input = null, check = null, slot = null } = {}) {
  if (S.pending) return;
  const given = String(answer || '').trim();
  if (!given) { toast('Type an answer first.'); return; }
  S.pending = true;
  const lock = (on) => {
    if (box) for (const b of box.querySelectorAll('button')) b.disabled = on;
    if (slot) for (const b of slot.querySelectorAll('button')) b.disabled = on;
    if (input) input.disabled = on;
    if (check) { check.disabled = on; check.textContent = on ? 'Checking…' : 'Check'; }
  };
  lock(true);
  if (chosen) chosen.classList.add('sel');
  try {
    const r = await api(`/api/drill/${S.drill.id}/answer`, { method: 'POST', body: { index: item.index, answer: given }, timeout: 60000 });
    S.results[S.idx] = r;
    if (chosen) { chosen.classList.remove('sel'); chosen.classList.add(r.correct ? 'right' : 'wrong'); }
    if (slot) slot.classList.add(r.correct ? 'right' : 'wrong');
    track();
    haptic(r.correct ? 10 : 25);
    const last = S.idx + 1 >= S.drill.items.length;
    S.foot.verdict({
      ok: r.correct,
      title: r.correct ? 'Richtig' : 'Not quite',
      detail: h('span', {},
        r.correct ? null : h('span', { class: 'block' }, 'Answer: ', h('b', { lang: 'de' }, r.answer)),
        r.explanation ? h('span', { class: 'block' }, r.explanation) : null,
        r.beaten ? h('span', { class: 'block' }, 'That one is beaten: it leaves the tutor’s list.') : null),
      cta: last ? 'See how it went' : 'Next',
      onContinue: () => { S.idx += 1; renderItem(); },
    });
  } catch (e) {
    lock(false);
    if (chosen) chosen.classList.remove('sel');
    if (e.status === 404) { S.drill = null; renderIntro(e); return; }
    S.pbody.append(errorLine(e, () => { S.pbody.lastChild.remove(); submit(item, answer, { box, chosen, input, check, slot }); }));
  } finally { S.pending = false; }
}

function renderSummary() {
  const total = S.drill.items.length;
  const right = S.results.filter((r) => r && r.correct).length;
  const beaten = S.results.filter((r) => r && r.beaten).length;
  const cats = S.drill.categories || [];
  setView(false);
  clear(S.body).append(h('div', { class: 'finish' },
    ringAround(total ? right / total : 0, 168, 'var(--good)', 'var(--good-dim)',
      katze({ variant: me().avatar, mood: right === total ? 'cheering' : 'proud', size: 92 })),
    h('h2', { class: 'finish-h num' }, `${right} of ${total} right`),
    h('p', { class: 'finish-sub' }, right === total ? 'Clean sheet. Those mistakes are on their way out.' : 'Every right answer retires a mistake a little further.'),
    statStrip([[String(beaten), beaten === 1 ? 'mistake retired' : 'mistakes retired'], ['+15', 'XP']]),
    cats.length ? h('div', { class: 'chip-row wrap center-row' }, cats.map((c) => catChip(c))) : null,
    h('div', { class: 'finish-actions' },
      h('button', { class: 'btn primary block lg tactile', type: 'button', onClick: startDrill }, 'Another drill'),
      h('button', { class: 'btn ghost block', type: 'button', onClick: () => window.dtSwitchTo('talk') }, 'Back to talking'))));
  S.drill = null;
  api('/api/game/me').then(maybeCelebrate).catch(() => {});
}
