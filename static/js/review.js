/* Review screen: spaced repetition, one card at a time.
   German → tap to reveal → four big ratings; audio on every card; a recall direction (translation
   first, say the German out loud, then reveal). Ratings made offline queue in IndexedDB and flush
   when the connection is back. */
import { api } from './api.js';
import { h, clear, toast, sheet, errorLine, prefs, spinner, fmtDate } from './ui.js';
import { speak, stop as stopAudio, unlockAudio } from './audio.js';
import { store } from './store.js';

const S = { root: null, body: null, dirBtn: null, queue: [], idx: 0, dueCount: 0, reviewed: 0,
  direction: prefs.get('reviewDir', 'de-en'), revealed: false, loading: false, mode: 'review' };

export function mount(el) {
  S.root = el;
  S.dirBtn = h('button', { class: 'chip', type: 'button', onClick: toggleDirection }, dirLabel());
  const head = h('header', { class: 'screen-head' },
    h('h1', {}, 'Review'),
    S.dirBtn,
    h('button', { class: 'btn small ghost', type: 'button', onClick: () => (S.mode === 'browse' ? backToReview() : browse()) }, 'List'));
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

function dirLabel() { return S.direction === 'de-en' ? 'DE → EN' : 'EN → DE (recall)'; }
function toggleDirection() {
  S.direction = S.direction === 'de-en' ? 'en-de' : 'de-en';
  prefs.set('reviewDir', S.direction);
  S.dirBtn.textContent = dirLabel();
  S.revealed = false;
  render();
}

async function loadQueue() {
  S.loading = true;
  clear(S.body).append(spinner('Loading cards…'));
  try {
    const data = await api('/api/vocab/due?limit=20');
    S.queue = data.cards || [];
    S.dueCount = data.due_count || S.queue.length;
    S.idx = 0;
    S.reviewed = 0;
    S.revealed = false;
    render();
  } catch (e) {
    clear(S.body).append(errorLine(e, loadQueue));
  } finally { S.loading = false; }
}

function render() {
  S.mode = 'review';
  clear(S.body);
  if (!S.queue.length) { renderEmpty(); return; }
  if (S.idx >= S.queue.length) { renderDone(); return; }
  const card = S.queue[S.idx];
  const front = S.direction === 'de-en' ? card.word : card.translation;
  const back = S.direction === 'de-en' ? card.translation : card.word;
  const progress = h('div', { class: 'row between muted small' },
    h('span', {}, `${S.idx + 1} of ${S.queue.length}`),
    h('span', {}, card.is_new ? 'new' : `interval ${Math.round(card.interval_days)} d`));
  const frontEl = h('div', { class: 'rv-front' }, front);
  const backEl = h('div', { class: 'rv-back', hidden: !S.revealed }, h('div', { class: 'rv-answer' }, back),
    card.example ? h('p', { class: 'muted rv-example' }, card.example) : null);
  const hint = h('p', { class: 'muted small center' }, S.direction === 'de-en' ? 'Tap to reveal' : 'Say it in German, then tap to reveal');
  const playBtn = h('button', { class: 'btn small ghost', type: 'button', onClick: () => play(card) }, '▶ Play');
  const cardEl = h('button', { class: 'card rv-card', type: 'button', onClick: () => reveal(card) }, frontEl, backEl, S.revealed ? null : hint);
  const ratings = h('div', { class: 'rv-ratings', hidden: !S.revealed },
    rateBtn(1, 'Again', 'again'), rateBtn(2, 'Hard', 'hard'), rateBtn(3, 'Good', 'good'), rateBtn(4, 'Easy', 'easy'));
  S.body.append(progress, cardEl, h('div', { class: 'row', style: { justifyContent: 'center' } }, playBtn), ratings);
  if (S.direction === 'de-en' && !S.revealed) play(card, true);
}

function rateBtn(rating, label, cls) {
  return h('button', { class: `btn rv-rate ${cls}`, type: 'button', onClick: () => rate(rating) }, label);
}

function reveal(card) {
  if (S.revealed) return;
  S.revealed = true;
  render();
  if (S.direction === 'en-de') play(card, true);
}

async function play(card, auto = false) {
  unlockAudio();
  try { await speak(card.word, 'normal', { id: `v${card.id}` }); } catch (e) {
    if (!auto) toast(e.detail || 'Audio unavailable.', { kind: 'err' });
  }
}

async function rate(rating) {
  const card = S.queue[S.idx];
  S.idx += 1;
  S.reviewed += 1;
  S.revealed = false;
  if (rating === 1) S.queue.push({ ...card, is_new: false });   // "again": see it once more this session
  render();
  try {
    await api(`/api/vocab/${card.id}/review`, { method: 'POST', body: { rating }, timeout: 15000 });
  } catch (e) {
    if (e.status === 404) return;
    await store.add('ratings', { vocabId: card.id, rating, at: Date.now() });
    toast('Saved offline — will sync later.');
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
  S.body.append(h('div', { class: 'card stack center' },
    h('h2', {}, 'Nothing due right now'),
    h('p', { class: 'muted' }, 'Words the tutor teaches you, and words you tap and add, come back here when they are due.'),
    h('button', { class: 'btn', type: 'button', onClick: loadQueue }, 'Check again'),
    h('button', { class: 'btn ghost', type: 'button', onClick: browse }, 'Browse all words')));
}

function renderDone() {
  const left = Math.max(0, S.dueCount - S.reviewed);
  S.body.append(h('div', { class: 'card stack center' },
    h('h2', {}, `Done — ${S.reviewed} reviewed`),
    h('p', { class: 'muted' }, left ? `${left} more due.` : 'That is everything for now.'),
    left ? h('button', { class: 'btn primary', type: 'button', onClick: loadQueue }, 'Keep going') : null,
    h('button', { class: 'btn ghost', type: 'button', onClick: browse }, 'Browse all words')));
}

/* ---- browse --------------------------------------------------------- */
async function browse() {
  S.mode = 'browse';
  clear(S.body);
  const input = h('input', { class: 'input', type: 'search', placeholder: 'Search…', enterkeyhint: 'search' });
  const list = h('div', { class: 'stack' });
  const count = h('p', { class: 'muted small' });
  let timer = null;
  const load = async () => {
    clear(list).append(spinner());
    try {
      const data = await api(`/api/vocab?q=${encodeURIComponent(input.value.trim())}&sort=due&limit=100`);
      clear(list);
      count.textContent = `${data.total} words`;
      for (const c of data.items) list.append(rowFor(c, load));
      if (!data.items.length) list.append(h('p', { class: 'muted' }, 'No words yet.'));
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
      h('div', { class: 'vocab-word' }, c.word), h('div', { class: 'muted small' }, `${c.translation} · ${due}`)),
    h('button', { class: 'btn icon ghost', type: 'button', 'aria-label': 'Play', onClick: () => play(c) }, '▶'));
}

function openWord(c, reload) {
  sheet.open(h('div', { class: 'stack' },
    h('div', { class: 'lemma' }, c.word),
    h('p', { class: 'translation' }, c.translation),
    c.example ? h('p', { class: 'muted' }, c.example) : null,
    h('p', { class: 'muted small' }, `${c.reps} reviews · ease ${Number(c.ease).toFixed(2)} · ${c.lapses} lapses · source ${c.source}`),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => play(c) }, '▶ Play'),
      h('button', { class: 'btn danger', type: 'button', onClick: async () => {
        try { await api(`/api/vocab/${c.id}`, { method: 'DELETE' }); sheet.close(); toast('Removed.'); reload(); }
        catch (e) { toast(e.detail || 'Could not remove.', { kind: 'err' }); }
      } }, 'Remove'))), { title: 'Word' });
}

function backToReview() { S.mode = 'review'; S.revealed = false; if (S.idx >= S.queue.length) loadQueue(); else render(); }
