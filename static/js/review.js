/* Review: spaced repetition, one card at a time (docs/DESIGN.md §5).

   A review runs in the player like a lesson: a close button and the queue's progress on top, the
   card in the middle (German large, tap anywhere to flip, audio on reveal), and the four ratings in
   the bottom bar with the next interval under each. Ratings made offline queue in IndexedDB and
   flush when the connection is back. The deck (browse and search) and the empty and finished
   states are ordinary screens with the tab bar. */
import { api } from './api.js';
import { h, clear, toast, sheet, errorLine, prefs, skeleton, fmtDate, fmtDays, haptic, de, currentUid } from './ui.js';
import { speak, stop as stopAudio, unlockAudio } from './audio.js';
import { store } from './store.js';
import { katze } from './katze.js';
import { icon } from './icons.js';
import { maybeCelebrate } from './moment.js';
import { focusMode, playerHead, playerFoot, statStrip } from './kit.js';

const S = { root: null, listView: null, body: null, playerView: null, head: null, pbody: null, foot: null,
  queue: [], idx: 0, dueCount: 0, reviewed: 0, again: 0,
  direction: prefs.get('reviewDir', 'de-en'), revealed: false, mode: 'review' };
const me = () => window.dtUser || {};

export function mount(el) {
  S.root = el;
  S.body = h('div', { class: 'screen-body' });
  S.listView = h('div', { class: 'learn-view' },
    h('header', { class: 'screen-head' }, h('h1', {}, 'Review'), h('span', { class: 'grow' }),
      h('button', { class: 'btn small ghost', type: 'button', onClick: () => (S.mode === 'browse' ? backToReview() : browse()) }, 'Deck')),
    S.body);
  S.head = playerHead({ onClose: leaveSession, closeLabel: 'End the review' });
  S.pbody = h('div', { class: 'player-body' });
  S.foot = playerFoot();
  S.playerView = h('div', { class: 'player', hidden: true }, S.head.el, S.pbody, S.foot.el);
  clear(el).append(S.listView, S.playerView);
  document.addEventListener('dt:online', () => flushRatings());
}

export async function show() {
  await flushRatings();
  if (S.mode === 'browse') return;
  if (S.mode === 'session' && S.idx < S.queue.length) { focusMode(true); return; }
  await loadQueue();
}
export function hide() { stopAudio(); }

function setView(session) {
  S.playerView.hidden = !session;
  S.listView.hidden = session;
  focusMode(session);
  S.root.scrollTop = 0;
}

async function loadQueue() {
  S.mode = 'review';
  setView(false);
  clear(S.body).append(skeleton(1, { tall: true }), skeleton(2));
  try {
    const data = await api('/api/vocab/due?limit=20');
    S.queue = data.cards || [];
    S.dueCount = data.due_count || S.queue.length;
    S.idx = 0; S.reviewed = 0; S.again = 0; S.revealed = false;
    if (!S.queue.length) { renderEmpty(); return; }
    S.mode = 'session';
    setView(true);
    renderCard();
  } catch (e) {
    clear(S.body).append(errorLine(e, loadQueue));
  }
}

function leaveSession() {
  stopAudio();
  if (S.reviewed) { renderDone(); return; }
  S.mode = 'review';
  setView(false);
  window.dtSwitchTo('practice');
}

/* ---- one card --------------------------------------------------------- */
function renderCard() {
  if (S.idx >= S.queue.length) { renderDone(); return; }
  const card = S.queue[S.idx];
  const frontDe = S.direction === 'de-en';
  const front = frontDe ? card.word : card.translation;
  const back = frontDe ? card.translation : card.word;
  S.head.set(S.idx, S.queue.length);
  clear(S.pbody);

  const dir = h('button', { class: 'dir-btn', type: 'button', 'aria-label': `Direction: ${frontDe ? 'German first' : 'English first'}. Tap to switch`, onClick: toggleDirection },
    frontDe ? 'DE → EN' : 'EN → DE');
  const meta = h('div', { class: 'card-meta' },
    h('span', { class: 'muted small' }, card.is_new ? 'New card' : `Last gap ${fmtDays(card.interval_days).replace(/^in /, '')}`), dir);
  const backEl = h('div', { class: 'fc-back', hidden: !S.revealed },
    h('div', { class: 'fc-answer', lang: frontDe ? 'en' : 'de' }, back),
    card.example ? h('p', { class: 'fc-example', lang: 'de' }, card.example) : null);
  const face = h('button', { class: `flashcard ${S.revealed ? 'flip' : ''}`, type: 'button', 'aria-expanded': String(S.revealed),
    'aria-label': S.revealed ? `${front}: ${back}` : `${front}. Tap to show the answer`, onClick: () => reveal(card) },
    h('span', { class: 'fc-front', lang: frontDe ? 'de' : 'en' }, front),
    backEl,
    S.revealed ? null : h('span', { class: 'fc-hint' }, frontDe ? 'Tap to show the meaning' : 'Say it in German, then tap'));
  const sayBtn = h('button', { class: 'fc-say', type: 'button', 'aria-label': 'Play the German', onClick: () => play(card) }, icon('speaker', 20));
  S.pbody.append(meta, h('div', { class: 'deck' }, face, sayBtn));

  if (!S.revealed) {
    S.foot.actions(h('button', { class: 'btn primary lg tactile grow', type: 'button', onClick: () => reveal(card) }, 'Show answer'));
  } else {
    const p = card.preview || {};
    S.foot.actions(h('div', { class: 'rate-grid' },
      rateBtn(1, 'Again', 'again', p.again), rateBtn(2, 'Hard', 'hard', p.hard),
      rateBtn(3, 'Good', 'good', p.good), rateBtn(4, 'Easy', 'easy', p.easy)));
  }
}

function rateBtn(rating, label, cls, days) {
  return h('button', { class: `rate tactile ${cls}`, type: 'button', onClick: () => rate(rating) },
    h('b', {}, label), h('small', { class: 'num' }, fmtDays(days)));
}

function toggleDirection() {
  S.direction = S.direction === 'de-en' ? 'en-de' : 'de-en';
  prefs.set('reviewDir', S.direction);
  S.revealed = false;
  renderCard();
}

function reveal(card) {
  if (S.revealed) return;
  S.revealed = true;
  renderCard();
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
  if (rating === 1) { S.again += 1; S.queue.push({ ...card, is_new: false }); }   // "again": once more this session
  renderCard();
  try {
    await api(`/api/vocab/${card.id}/review`, { method: 'POST', body: { rating }, timeout: 15000 });
  } catch (e) {
    if (e.status === 404) return;
    await store.add('ratings', { userId: currentUid(), vocabId: card.id, rating, at: Date.now() });
    toast('Saved on this phone. It syncs when you are back online.');
  }
}

let flushing = false;
async function flushRatings() {
  if (flushing) return;
  flushing = true;
  try {
    const list = (await store.all('ratings')).filter((r) => String(r.userId) === currentUid());
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

/* ---- empty and finished ------------------------------------------------ */
function renderEmpty() {
  S.mode = 'review';
  setView(false);
  clear(S.body).append(h('div', { class: 'finish' },
    h('div', { class: 'finish-cat' }, katze({ variant: me().avatar, mood: 'sleepy', size: 96 })),
    h('h2', { class: 'finish-h' }, 'Nothing due right now'),
    h('p', { class: 'finish-sub' }, 'Cards come from two places: words the tutor teaches you in a conversation, and words you tap and add. They come back here when they are due.'),
    h('div', { class: 'finish-actions' },
      h('button', { class: 'btn primary block lg tactile', type: 'button', onClick: () => window.dtSwitchTo('talk') }, 'Talk and collect words'),
      h('button', { class: 'btn ghost block', type: 'button', onClick: browse }, 'Open the deck'))));
}

function renderDone() {
  S.mode = 'review';
  setView(false);
  const left = Math.max(0, S.dueCount - (S.reviewed - S.again));
  const ring = h('p', { class: 'muted small', hidden: true });
  clear(S.body).append(h('div', { class: 'finish' },
    h('div', { class: 'finish-cat' }, katze({ variant: me().avatar, mood: 'proud', size: 110 })),
    h('h2', { class: 'finish-h' }, left ? 'Good stopping point' : 'All caught up'),
    h('p', { class: 'finish-sub' }, left ? `${left} more ${left === 1 ? 'is' : 'are'} due today. Stop here or keep going; both are fine.` : 'Everything due today is done. The next ones come back on their own.'),
    statStrip([[String(S.reviewed), S.reviewed === 1 ? 'card' : 'cards'], [String(S.again), 'again'], [`+${S.reviewed * 2}`, 'XP']]),
    ring,
    h('div', { class: 'finish-actions' },
      left ? h('button', { class: 'btn primary block lg tactile', type: 'button', onClick: loadQueue }, 'Keep going') : null,
      h('button', { class: `btn ${left ? 'ghost' : 'primary lg tactile'} block`, type: 'button', onClick: () => window.dtSwitchTo('practice') }, 'Back to practice'),
      h('button', { class: 'btn ghost block', type: 'button', onClick: browse }, 'Open the deck'))));
  api('/api/game/me').then((g) => {
    const r = g.goals && g.goals.review;
    if (r) { ring.textContent = r.fraction >= 1 ? `Review ring closed: ${r.done} of ${r.target}.` : `Review ring: ${r.done} of ${r.target}.`; ring.hidden = false; }
    maybeCelebrate(g);
  }).catch(() => {});
}

/* ---- the deck --------------------------------------------------------- */
async function browse() {
  S.mode = 'browse';
  setView(false);
  clear(S.body);
  const input = h('input', { class: 'input search-input', type: 'search', name: 'q', placeholder: 'Search the deck…', enterkeyhint: 'search',
    autocomplete: 'off', spellcheck: 'false', 'aria-label': 'Search the deck' });
  const list = h('div', { class: 'deck-list' });
  const count = h('p', { class: 'muted small num' });
  let timer = null;
  const load = async () => {
    clear(list).append(skeleton(4, { tall: true }));
    try {
      const data = await api(`/api/vocab?q=${encodeURIComponent(input.value.trim())}&sort=due&limit=100`);
      clear(list);
      count.textContent = `${data.total} ${data.total === 1 ? 'word' : 'words'}`;
      for (const c of data.items) list.append(rowFor(c, load));
      if (!data.items.length) list.append(h('p', { class: 'deck-empty muted' }, input.value.trim() ? 'No word matches that.' : 'No words yet. Tap any German word in Talk to add it.'));
    } catch (e) { clear(list).append(errorLine(e, load)); }
  };
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 250); });
  S.body.append(
    h('button', { class: 'btn small ghost back-link', type: 'button', onClick: backToReview }, icon('back', 18), 'Back to review'),
    h('label', { class: 'search' }, icon('search', 18), input), count, list);
  load();
}

function rowFor(c, reload) {
  const due = c.due * 1000 <= Date.now() ? 'due now' : `due ${fmtDate(c.due)}`;
  return h('div', { class: 'deck-row' },
    h('button', { class: 'deck-main', type: 'button', onClick: () => openWord(c, reload) },
      h('span', { class: 'deck-word', lang: 'de' }, c.word), h('span', { class: 'deck-sub' }, c.translation)),
    h('span', { class: 'deck-due num' }, due),
    h('button', { class: 'btn icon ghost', type: 'button', 'aria-label': `Play ${c.word}`, onClick: () => play(c) }, icon('speaker', 20)));
}

function openWord(c, reload) {
  sheet.open(h('div', { class: 'stack' },
    de(c.word, 'lemma'),
    h('p', { class: 'translation' }, c.translation),
    c.example ? h('p', { class: 'muted', lang: 'de' }, c.example) : null,
    h('p', { class: 'muted xs num' }, `${c.reps} reviews · ease ${Number(c.ease).toFixed(2)} · ${c.lapses} lapses · from ${c.source}`),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => play(c) }, icon('speaker', 18), 'Play'),
      h('button', { class: 'btn danger', type: 'button', onClick: async () => {
        try { await api(`/api/vocab/${c.id}`, { method: 'DELETE' }); sheet.close(); toast('Removed.'); reload(); }
        catch (e) { toast(e.detail || 'Could not remove.', { kind: 'err' }); }
      } }, 'Remove'))), { title: null });
}

function backToReview() { S.mode = 'review'; S.revealed = false; loadQueue(); }
