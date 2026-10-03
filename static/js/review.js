/* Review screen: spaced repetition, one card at a time (docs/DESIGN.md §5).
   German large, tap anywhere to flip (instant, 150 ms scale-and-fade), four rating buttons with
   the next interval underneath, audio on reveal, a queue progress bar on top. Ratings made offline
   queue in IndexedDB and flush when the connection is back. */
import { api } from './api.js';
import { h, clear, toast, sheet, errorLine, prefs, skeleton, fmtDate, fmtDays, haptic, de } from './ui.js';
import { speak, stop as stopAudio, unlockAudio } from './audio.js';
import { store } from './store.js';

const S = { body: null, dirBtn: null, queue: [], idx: 0, dueCount: 0, reviewed: 0,
  direction: prefs.get('reviewDir', 'de-en'), revealed: false, mode: 'review' };

export function mount(el) {
  S.dirBtn = h('button', { class: 'chip', type: 'button', onClick: toggleDirection }, dirLabel());
  const head = h('header', { class: 'screen-head' },
    h('h1', {}, 'Review'),
    S.dirBtn,
    h('button', { class: 'btn small ghost', type: 'button', onClick: () => (S.mode === 'browse' ? backToReview() : browse()) }, 'Deck'));
  S.body = h('div', { class: 'screen-body' });
  clear(el).append(head, S.body);
  document.addEventListener('dt:online', () => flushRatings());
}

export async function show() {
  await flushRatings();
  if (S.mode === 'browse') return;
  if (!S.queue.length || S.idx >= S.queue.length) await loadQueue();
}
export function hide() { stopAudio(); }

function dirLabel() { return S.direction === 'de-en' ? 'DE → EN' : 'EN → DE'; }
function toggleDirection() {
  S.direction = S.direction === 'de-en' ? 'en-de' : 'de-en';
  prefs.set('reviewDir', S.direction);
  S.dirBtn.textContent = dirLabel();
  S.revealed = false;
  render();
  toast(S.direction === 'de-en' ? 'German first, reveal the meaning.' : 'Meaning first: say the German, then reveal.');
}

async function loadQueue() {
  clear(S.body).append(h('div', { class: 'meter thin' }, h('i')), skeleton(1, { tall: true }), skeleton(2));
  try {
    const data = await api('/api/vocab/due?limit=20');
    S.queue = data.cards || [];
    S.dueCount = data.due_count || S.queue.length;
    S.idx = 0; S.reviewed = 0; S.revealed = false;
    render();
  } catch (e) {
    clear(S.body).append(errorLine(e, loadQueue));
  }
}

function render() {
  S.mode = 'review';
  clear(S.body);
  if (!S.queue.length) { renderEmpty(); return; }
  if (S.idx >= S.queue.length) { renderDone(); return; }
  const card = S.queue[S.idx];
  const frontDe = S.direction === 'de-en';
  const front = frontDe ? card.word : card.translation;
  const back = frontDe ? card.translation : card.word;
  const bar = h('div', { class: 'meter thin', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(S.queue.length), 'aria-valuenow': String(S.idx) }, h('i'));
  requestAnimationFrame(() => { bar.firstChild.style.width = `${Math.round(100 * S.idx / S.queue.length)}%`; });
  const frontEl = h('div', { class: 'rv-front', lang: frontDe ? 'de' : 'en' }, front);
  const backEl = h('div', { class: 'rv-back', hidden: !S.revealed }, h('div', { class: 'rv-answer', lang: frontDe ? 'en' : 'de' }, back),
    card.example ? h('p', { class: 'rv-example', lang: 'de' }, card.example) : null);
  const hint = h('p', { class: 'muted small' }, frontDe ? 'Tap to reveal' : 'Say it in German, then tap');
  const cardEl = h('button', { class: `card rv-card ${S.revealed ? 'flip' : ''}`, type: 'button', 'aria-expanded': String(S.revealed), onClick: () => reveal(card) },
    frontEl, backEl, S.revealed ? null : hint);
  const p = card.preview || {};
  const ratings = h('div', { class: 'rv-ratings', hidden: !S.revealed },
    rateBtn(1, 'Again', 'again', p.again), rateBtn(2, 'Hard', 'hard', p.hard), rateBtn(3, 'Good', 'good', p.good), rateBtn(4, 'Easy', 'easy', p.easy));
  const meta = h('div', { class: 'row between muted xs' },
    h('span', {}, `${S.idx + 1} of ${S.queue.length}`), h('span', {}, card.is_new ? 'new card' : `last interval ${Math.round(card.interval_days)} d`));
  S.body.append(bar, meta, cardEl,
    h('div', { class: 'row', style: { justifyContent: 'center' } }, h('button', { class: 'btn small ghost', type: 'button', onClick: () => play(card) }, '▶ Play')),
    ratings);
}

function rateBtn(rating, label, cls, days) {
  return h('button', { class: `btn rv-rate ${cls}`, type: 'button', onClick: () => rate(rating) }, h('b', {}, label), h('small', {}, fmtDays(days)));
}

function reveal(card) {
  if (S.revealed) return;
  S.revealed = true;
  render();
  play(card, true);
}

async function play(card, auto = false) {
  unlockAudio();
  try { await speak(card.word, 'normal', { id: `v${card.id}` }); } catch (e) {
    if (!auto) toast(e.detail || 'Audio unavailable.', { kind: 'err' });
  }
}

async function rate(rating) {
  haptic(10);
  const card = S.queue[S.idx];
  S.idx += 1;
  S.reviewed += 1;
  S.revealed = false;
  if (rating === 1) S.queue.push({ ...card, is_new: false });   // "again": once more this session
  render();
  try {
    await api(`/api/vocab/${card.id}/review`, { method: 'POST', body: { rating }, timeout: 15000 });
  } catch (e) {
    if (e.status === 404) return;
    await store.add('ratings', { vocabId: card.id, rating, at: Date.now() });
    toast('Saved on this phone — syncs when you are back online.');
  }
}

let flushing = false;
async function flushRatings() {
  if (flushing) return;
  flushing = true;
  try {
    const list = await store.all('ratings');
    for (const r of list) {
      try {
        await api(`/api/vocab/${r.vocabId}/review`, { method: 'POST', body: { rating: r.rating }, timeout: 15000 });
        await store.remove('ratings', r.id);
      } catch (e) {
        if (e.status === 404 || e.status === 422) { await store.remove('ratings', r.id); continue; }
        break;   // still offline: try again later
      }
    }
  } finally { flushing = false; }
}

function renderEmpty() {
  S.body.append(h('div', { class: 'card empty' },
    h('h2', {}, 'Nothing due right now'),
    h('p', {}, 'Cards come from two places: words the tutor teaches you in a conversation, and words you tap and add. They return here when they are due.'),
    h('button', { class: 'btn', type: 'button', onClick: loadQueue }, 'Check again'),
    h('button', { class: 'btn ghost', type: 'button', onClick: browse }, 'Open the deck')));
}

function renderDone() {
  const left = Math.max(0, S.dueCount - S.reviewed);
  S.body.append(h('div', { class: 'card empty' },
    h('h2', {}, `${S.reviewed} reviewed`),
    h('p', {}, left ? `${left} more are due today. Stop here or keep going — both are fine.` : 'That is everything for today.'),
    left ? h('button', { class: 'btn primary', type: 'button', onClick: loadQueue }, 'Keep going') : null,
    h('button', { class: 'btn ghost', type: 'button', onClick: browse }, 'Open the deck')));
}

/* ---- browse --------------------------------------------------------- */
async function browse() {
  S.mode = 'browse';
  clear(S.body);
  const input = h('input', { class: 'input', type: 'search', placeholder: 'Search the deck…', enterkeyhint: 'search', 'aria-label': 'Search' });
  const list = h('div', { class: 'stack' });
  const count = h('p', { class: 'muted xs' });
  let timer = null;
  const load = async () => {
    clear(list).append(skeleton(4, { tall: true }));
    try {
      const data = await api(`/api/vocab?q=${encodeURIComponent(input.value.trim())}&sort=due&limit=100`);
      clear(list);
      count.textContent = `${data.total} words`;
      for (const c of data.items) list.append(rowFor(c, load));
      if (!data.items.length) list.append(h('p', { class: 'muted small' }, 'No words yet.'));
    } catch (e) { clear(list).append(errorLine(e, load)); }
  };
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 250); });
  S.body.append(h('button', { class: 'btn small ghost', type: 'button', onClick: backToReview }, '← Back to review'), input, count, list);
  load();
}

function rowFor(c, reload) {
  const due = c.due * 1000 <= Date.now() ? 'due' : `due ${fmtDate(c.due)}`;
  return h('div', { class: 'card row between vocab-row' },
    h('button', { class: 'grow vocab-main', type: 'button', onClick: () => openWord(c, reload) },
      h('div', { class: 'vocab-word', lang: 'de' }, c.word), h('div', { class: 'muted xs' }, `${c.translation} · ${due}`)),
    h('button', { class: 'btn icon ghost', type: 'button', 'aria-label': 'Play', onClick: () => play(c) }, '▶'));
}

function openWord(c, reload) {
  sheet.open(h('div', { class: 'stack' },
    de(c.word, 'lemma'),
    h('p', { class: 'translation' }, c.translation),
    c.example ? h('p', { class: 'muted', lang: 'de' }, c.example) : null,
    h('p', { class: 'muted xs' }, `${c.reps} reviews · ease ${Number(c.ease).toFixed(2)} · ${c.lapses} lapses · from ${c.source}`),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => play(c) }, '▶ Play'),
      h('button', { class: 'btn danger', type: 'button', onClick: async () => {
        try { await api(`/api/vocab/${c.id}`, { method: 'DELETE' }); sheet.close(); toast('Removed.'); reload(); }
        catch (e) { toast(e.detail || 'Could not remove.', { kind: 'err' }); }
      } }, 'Remove'))), { title: null });
}

function backToReview() { S.mode = 'review'; S.revealed = false; if (S.idx >= S.queue.length) loadQueue(); else render(); }
