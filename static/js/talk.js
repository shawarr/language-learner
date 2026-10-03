/* Talk screen: text and voice conversation with the tutor.

   Rules this screen enforces (docs/TASKS.md A4, A5, V2, V3):
   - the raw transcript is shown verbatim above the corrections, never a cleaned-up version
   - correction cards are collapsed by default and never push the conversation out of view
   - the typed text / the recording is never lost: a failed turn restores the input, a failed
     upload keeps the blob in IndexedDB and retries on tap or when connectivity returns
   - one turn = one request; the tutor's audio comes from /api/tts and autoplays */
import { api, upload, audioFilename } from './api.js';
import { h, clear, toast, sheet, errorLine, prefs, tappableWords, spinner, plural } from './ui.js';
import { speak, stop as stopAudio, unlockAudio, setPlaybackListener } from './audio.js';
import { createHoldToTalk, micIcon } from './mic.js';
import { store } from './store.js';

const S = {
  root: null, screen: null, chat: null, foot: null, input: null, sendBtn: null, mic: null,
  headScenario: null, hideBtn: null,
  session: null, scenario: null, scenarios: [], unit: null, loaded: false,
  pending: false, hideGerman: prefs.get('hideGerman', false),
  playingId: null,
};

/* ---- mount / show --------------------------------------------------- */
export function mount(el) {
  S.root = el;
  S.screen = el;
  const head = h('header', { class: 'screen-head' },
    h('h1', {}, 'Talk'),
    S.headScenario = h('button', { class: 'chip', type: 'button', onClick: openScenarioPicker }, 'Free conversation'),
    S.hideBtn = h('button', { class: 'btn icon ghost', type: 'button', 'aria-label': 'Hide German text', onClick: toggleHide },
      eyeIcon()),
    h('button', { class: 'btn icon ghost', type: 'button', 'aria-label': 'End session', onClick: confirmEnd }, stopIcon()));
  S.chat = h('div', { class: 'chat', id: 'chat' });
  S.foot = h('footer', { class: 'screen-foot talk-foot' });
  buildComposer();
  clear(el).append(head, S.chat, S.foot);
  syncHideButton();
  setPlaybackListener((st) => {
    S.playingId = st && st.playing ? st.id : null;
    for (const b of S.chat.querySelectorAll('.msg.tutor')) b.classList.toggle('playing', !!st && b.dataset.id === String(st.id));
  });
  document.addEventListener('dt:online', () => retryQueued());
}

export async function show() {
  if (!S.loaded) { S.loaded = true; await load(); }
}

export function hide() { stopAudio(); }

async function load() {
  renderLoading();
  await loadScenarios();
  const saved = prefs.get('talkSession', null);
  const queued = await store.all('recordings');
  const resumeId = (queued[0] && queued[0].sessionId) || saved;
  if (resumeId) {
    try {
      const data = await api(`/api/talk/session/${resumeId}`);
      if (data.session && !data.session.ended_at) {
        S.session = data.session;
        setScenarioFromSession(data.session);
        renderHistory(data.messages);
        await renderQueued(queued);
        return;
      }
    } catch (e) {
      if (e.status !== 404 && e.offline) { renderStart(e); return; }
    }
    prefs.set('talkSession', null);
  }
  renderStart();
  if (queued.length) await renderQueued(queued);
}

async function loadScenarios() {
  try {
    const cur = await api('/api/curriculum/current');
    S.scenarios = cur.scenarios || [];
    S.unit = cur.unit;
  } catch { S.scenarios = []; }
}

function setScenarioFromSession(session) {
  S.scenario = session.scenario_id ? { id: session.scenario_id, title: session.scenario_title || session.scenario_id } : null;
  S.headScenario.textContent = S.scenario ? S.scenario.title : 'Free conversation';
}

/* ---- rendering ------------------------------------------------------ */
function renderLoading() { clear(S.chat).append(spinner('Loading the conversation…')); }

function renderStart(err) {
  clear(S.chat);
  const card = h('div', { class: 'card start-card stack' },
    h('h2', {}, S.unit ? S.unit.title : 'Ready to talk?'),
    S.unit ? h('p', { class: 'muted small' }, (S.unit.can_do || []).slice(0, 2).join(' · ')) : null,
    h('p', { class: 'muted' }, 'Pick a scenario or just talk. The tutor speaks first.'),
    scenarioChips(),
    err ? errorLine(err, () => load()) : null,
    h('button', { class: 'btn primary block', type: 'button', onClick: () => startSession() }, 'Start'));
  S.chat.append(card);
}

function scenarioChips() {
  const row = h('div', { class: 'chip-row' });
  const all = [{ id: null, title: 'Free conversation' }, ...S.scenarios];
  for (const sc of all) {
    const active = (S.scenario && S.scenario.id) === sc.id || (!S.scenario && sc.id === null);
    row.append(h('button', { class: `chip ${active ? 'active' : ''}`, type: 'button', onClick: () => {
      S.scenario = sc.id ? sc : null;
      S.headScenario.textContent = sc.title;
      for (const c of row.children) c.classList.toggle('active', c.textContent === sc.title);
    } }, sc.title));
  }
  return row;
}

function openScenarioPicker() {
  const body = h('div', { class: 'stack' });
  const all = [{ id: null, title: 'Free conversation', setup: 'No fixed goal. Talk about anything.' }, ...S.scenarios];
  for (const sc of all) {
    const active = (S.scenario ? S.scenario.id : null) === sc.id;
    body.append(h('button', { class: `card scenario-card ${active ? 'active' : ''}`, type: 'button', onClick: () => {
      sheet.close();
      if (S.session && !S.session.ended_at && (S.scenario ? S.scenario.id : null) !== sc.id) {
        confirmNewSession(sc);
      } else {
        S.scenario = sc.id ? sc : null;
        S.headScenario.textContent = sc.title;
        if (!S.session) renderStart();
      }
    } }, h('strong', {}, sc.title), sc.goal ? h('p', { class: 'muted small' }, 'Goal: ' + sc.goal) : h('p', { class: 'muted small' }, sc.setup)));
  }
  sheet.open(body, { title: S.unit ? `Scenarios · ${S.unit.title}` : 'Scenarios' });
}

function confirmNewSession(sc) {
  sheet.open(h('div', { class: 'stack' },
    h('p', {}, `Start a new conversation with "${sc.title}"? The current one will be ended and summarised.`),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => sheet.close() }, 'Cancel'),
      h('button', { class: 'btn primary', type: 'button', onClick: async () => {
        sheet.close();
        await endSession({ silent: true });
        S.scenario = sc.id ? sc : null;
        S.headScenario.textContent = sc.title;
        startSession();
      } }, 'Start new'))), { title: 'New conversation' });
}

function renderHistory(messages) {
  clear(S.chat);
  let lastUser = null;
  for (const m of messages) {
    if (m.role === 'user') {
      lastUser = userBubble({ id: m.id, text: m.content, transcript: m.input_kind === 'voice' ? (m.transcript_raw || m.content) : null,
        provider: m.stt_provider });
      S.chat.append(lastUser.el);
    } else {
      if (lastUser) { lastUser.attach({ corrections: m.correction || [], english_help: m.english_help }); lastUser = null; }
      S.chat.append(tutorBubble({ id: m.id, text: m.content }));
    }
  }
  scrollToEnd();
}

function tutorBubble({ id, text, newVocab = [] }) {
  const sentence = h('p', { class: `bubble-text ${S.hideGerman ? 'hidden-text' : ''}` }, tappableWords(text, translateWord));
  const reveal = h('button', { class: 'btn small ghost reveal', type: 'button', hidden: !S.hideGerman, onClick: () => {
    sentence.classList.add('revealed'); reveal.hidden = true;
  } }, 'Show text');
  const tools = h('div', { class: 'msg-tools' },
    h('button', { class: 'btn small ghost', type: 'button', 'aria-label': 'Play', onClick: () => playMessage(id, text, 'normal') }, playIcon(), 'Play'),
    h('button', { class: 'btn small ghost', type: 'button', 'aria-label': 'Play slowly', onClick: () => playMessage(id, text, 'slow') }, 'Slow'),
    reveal);
  const vocab = newVocab.length ? h('div', { class: 'vocab-chips' }, newVocab.map((v) =>
    h('button', { class: 'chip small', type: 'button', onClick: () => translateWord(v.word.split(' (')[0].replace(/^(der|die|das)\s+/i, ''), v.example || text, v) },
      h('b', {}, v.word), ' ', h('span', { class: 'muted' }, v.translation)))) : null;
  return h('div', { class: 'msg tutor', dataset: { id: String(id) } }, h('div', { class: 'bubble' }, sentence), tools, vocab);
}

function userBubble({ id, text, transcript, provider, pending = false }) {
  const el = h('div', { class: `msg user ${pending ? 'pending' : ''}`, dataset: { id: String(id || '') } });
  const body = h('div', { class: 'bubble' });
  if (transcript != null) {
    body.append(h('div', { class: 'transcript-label' }, micIcon(), ' transcript', provider ? h('span', { class: 'muted' }, ` · ${provider}`) : null));
    body.append(h('p', { class: 'bubble-text' }, transcript));
  } else {
    body.append(h('p', { class: 'bubble-text' }, text));
  }
  el.append(body);
  const extras = h('div', { class: 'msg-extras' });
  el.append(extras);
  return {
    el,
    attach({ corrections = [], praise = null, english_help = null }) {
      clear(extras);
      if (corrections.length) extras.append(correctionCard(corrections));
      if (praise) extras.append(h('p', { class: 'praise' }, '★ ', praise));
      if (english_help) extras.append(englishHelpCard(english_help));
    },
    setPending(on) { el.classList.toggle('pending', on); },
  };
}

function correctionCard(corrections) {
  const list = h('ul', { class: 'corr-list' }, corrections.map((c) =>
    h('li', {},
      h('div', { class: 'corr-pair' }, h('s', {}, c.wrong), ' → ', h('b', {}, tappableWords(c.right, translateWord))),
      h('div', { class: 'corr-expl muted small' }, c.explanation, c.category ? h('span', { class: 'cat' }, c.category.replace(/_/g, ' ')) : null))));
  return h('details', { class: 'corr' },
    h('summary', {}, h('span', { class: 'badge' }, corrections.length), ' ', plural(corrections.length, 'correction')),
    list);
}

function englishHelpCard(eh) {
  const german = eh.german || '';
  return h('div', { class: 'card help-card' },
    h('div', { class: 'card-title' }, 'Say it like this'),
    h('p', { class: 'help-german' }, tappableWords(german, translateWord),
      h('button', { class: 'btn small ghost', type: 'button', 'aria-label': 'Play', onClick: () => playMessage('help', german, 'normal') }, playIcon())),
    eh.literal ? h('p', { class: 'muted small' }, eh.literal) : null,
    eh.english ? h('p', { class: 'small' }, '“', eh.english, '”') : null);
}

function scenarioDoneCard() {
  const card = h('div', { class: 'card done-card stack' },
    h('p', {}, h('b', {}, 'Scenario complete.'), ' Nice. Keep talking or try the next one.'),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => card.remove() }, 'Keep going'),
      h('button', { class: 'btn primary', type: 'button', onClick: async () => { await endSession({ silent: true }); openScenarioPicker(); } }, 'New scenario')));
  return card;
}

function typingIndicator() {
  return h('div', { class: 'msg tutor typing-row' }, h('div', { class: 'bubble' }, h('span', { class: 'typing' }, h('i'), h('i'), h('i'))));
}

function scrollToEnd() {
  requestAnimationFrame(() => { S.screen.scrollTo({ top: S.screen.scrollHeight, behavior: 'smooth' }); });
}

/* ---- session lifecycle ---------------------------------------------- */
async function startSession() {
  if (S.pending) return;
  setPending(true);
  clear(S.chat).append(typingIndicator());
  try {
    const data = await api('/api/talk/session', { method: 'POST', body: { scenario_id: S.scenario ? S.scenario.id : null } });
    S.session = data.session;
    prefs.set('talkSession', S.session.id);
    setScenarioFromSession(S.session);
    clear(S.chat);
    renderTurn(data.opening_turn, null);
  } catch (e) {
    clear(S.chat);
    renderStart(e);
  } finally {
    setPending(false);
  }
}

function confirmEnd() {
  if (!S.session) { toast('No conversation running.'); return; }
  sheet.open(h('div', { class: 'stack' },
    h('p', {}, 'End this conversation? The tutor writes a short summary and updates your profile.'),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => sheet.close() }, 'Keep talking'),
      h('button', { class: 'btn primary', type: 'button', onClick: () => { sheet.close(); endSession(); } }, 'End'))), { title: 'End session' });
}

async function endSession({ silent = false } = {}) {
  if (!S.session) return;
  const id = S.session.id;
  S.session = null;
  prefs.set('talkSession', null);
  stopAudio();
  if (!silent) clear(S.chat).append(spinner('Summarising…'));
  try {
    const res = await api(`/api/talk/session/${id}/end`, { method: 'POST', timeout: 90000 });
    if (!silent) {
      clear(S.chat).append(h('div', { class: 'card stack' },
        h('div', { class: 'card-title' }, 'Session summary'),
        h('p', {}, res.summary || (res.analyzed ? 'Nothing new to summarise.' : 'Saved. The analysis will run later — the tutor was busy.')),
        h('button', { class: 'btn primary block', type: 'button', onClick: () => renderStart() }, 'New conversation')));
    } else if (!res.analyzed) {
      toast('Session saved; analysis postponed (tutor busy).');
    }
  } catch (e) {
    if (!silent) { clear(S.chat); renderStart(e); }
    toast(e.detail || 'Could not end the session.', { kind: 'err' });
  }
}

/* ---- turns ---------------------------------------------------------- */
function setPending(on) {
  S.pending = on;
  S.input.disabled = on;
  S.sendBtn.disabled = on;
  S.mic.setDisabled(on);
}

function renderTurn(turn, userHandle) {
  if (userHandle) {
    userHandle.setPending(false);
    userHandle.attach({ corrections: turn.corrections || [], praise: turn.praise, english_help: turn.english_help });
  }
  const bubble = tutorBubble({ id: turn.message_id, text: turn.reply, newVocab: turn.new_vocab || [] });
  S.chat.append(bubble);
  if (turn.scenario_done) S.chat.append(scenarioDoneCard());
  scrollToEnd();
  playMessage(turn.message_id, turn.reply, 'normal', { auto: true });
}

async function playMessage(id, text, speed, { auto = false } = {}) {
  if (!text) return;
  unlockAudio();
  try {
    await speak(text, speed, { id });
  } catch (e) {
    if (e && e.name === 'NotAllowedError') {
      // iOS refused autoplay: offer a tap-to-play instead of failing silently.
      if (auto) toast('Tap to hear the tutor.', { action: 'Play', onAction: () => playMessage(id, text, speed) });
    } else if (!auto) {
      toast(e.detail || 'Audio unavailable right now.', { kind: 'err' });
    }
  }
}

async function sendText() {
  const text = S.input.value.trim();
  if (!text || S.pending) return;
  if (!S.session) { await startSession(); if (!S.session) return; }
  await doTurn({ text }, () => api('/api/talk/turn', { method: 'POST', body: { session_id: S.session.id, text } }));
}

/* Runs one turn with the pending UI; `run` performs the request. Restores the input on error. */
async function doTurn({ text, transcript = null, retry = null }, run) {
  setPending(true);
  stopAudio();
  const handle = userBubble({ text: text || 'voice message', transcript, pending: true });
  S.chat.append(handle.el);
  const typing = typingIndicator();
  S.chat.append(typing);
  S.input.value = '';
  autosize();
  scrollToEnd();
  try {
    const turn = await run();
    typing.remove();
    if (turn.transcript != null) {
      // Replace the placeholder with the raw transcript, exactly as the engine returned it.
      const real = userBubble({ id: turn.user_message_id, text: turn.transcript, transcript: turn.transcript, provider: turn.transcript_provider });
      handle.el.replaceWith(real.el);
      renderTurn(turn, real);
    } else {
      handle.el.dataset.id = String(turn.user_message_id || '');
      renderTurn(turn, handle);
    }
    return true;
  } catch (e) {
    typing.remove();
    handle.el.remove();
    if (text) S.input.value = text;
    autosize();
    if (e.status === 409) { toast('That conversation has ended. Starting a new one.'); S.session = null; prefs.set('talkSession', null); renderStart(); return false; }
    showError(e, retry || (text ? sendText : null));
    return false;
  } finally {
    setPending(false);
  }
}

let errorEl = null;
function showError(e, retry) {
  if (errorEl) errorEl.remove();
  errorEl = errorLine(e, retry ? () => { errorEl.remove(); errorEl = null; retry(); } : null);
  S.foot.prepend(errorEl);
  setTimeout(() => { if (errorEl) { errorEl.remove(); errorEl = null; } }, 15000);
}

/* ---- composer + mic ------------------------------------------------- */
function buildComposer() {
  S.input = h('textarea', { class: 'input composer-input', rows: '1', placeholder: 'Schreib auf Deutsch…', enterkeyhint: 'send',
    autocapitalize: 'sentences', autocomplete: 'off', onInput: autosize,
    onKeydown: (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendText(); } } });
  S.sendBtn = h('button', { class: 'btn icon primary', type: 'button', 'aria-label': 'Send', onClick: sendText }, sendIcon());
  S.mic = createHoldToTalk({
    onStart: async () => { if (S.pending) return false; if (!S.session) { await startSession(); } return !!S.session; },
    onResult: (result) => sendRecording(result),
  });
  S.foot.append(h('div', { class: 'composer' }, S.input, S.sendBtn), S.mic.el);
}

function autosize() {
  const el = S.input;
  el.style.height = 'auto';
  el.style.height = Math.min(120, el.scrollHeight) + 'px';
}

/* V3: the blob goes into IndexedDB before the upload and is deleted only after a 2xx. */
async function sendRecording({ blob, mime }) {
  const sessionId = S.session.id;
  const stored = await store.add('recordings', { sessionId, blob, mime, createdAt: Date.now() });
  await uploadRecording({ id: stored, sessionId, blob, mime });
}

async function uploadRecording(rec) {
  const run = () => upload('/api/talk/turn', rec.blob, audioFilename(rec.mime), { session_id: rec.sessionId });
  const ok = await doTurn({ text: null, transcript: '…', retry: () => uploadRecording(rec) }, run);
  if (ok) { if (rec.id != null) await store.remove('recordings', rec.id); return; }
  // Keep it: show it as an unsent message with a retry, and retry automatically when back online.
  showQueued(rec);
}

function showQueued(rec) {
  if (S.chat.querySelector(`.queued[data-rec="${rec.id}"]`)) return;
  const el = h('div', { class: 'msg user queued', dataset: { rec: String(rec.id) } },
    h('div', { class: 'bubble' }, h('p', { class: 'bubble-text' }, micIcon(), ' Voice message — not sent'),
      h('div', { class: 'btn-row' },
        h('button', { class: 'btn small primary', type: 'button', onClick: () => { el.remove(); uploadRecording(rec); } }, 'Retry'),
        h('button', { class: 'btn small ghost', type: 'button', onClick: async () => { await store.remove('recordings', rec.id); el.remove(); } }, 'Discard'))));
  S.chat.append(el);
  scrollToEnd();
}

async function renderQueued(list) {
  for (const rec of list) {
    if (S.session && rec.sessionId !== S.session.id) {
      // Belongs to another (ended) session: offer once, then let the user decide.
      showQueued({ ...rec, sessionId: S.session.id });
    } else if (S.session) {
      showQueued(rec);
    } else {
      toast('An unsent recording is waiting.', { action: 'Send', duration: 0, onAction: async () => { await startSession(); if (S.session) uploadRecording({ ...rec, sessionId: S.session.id }); } });
    }
  }
}

async function retryQueued() {
  if (!S.session || S.pending) return;
  const list = await store.all('recordings');
  for (const rec of list) {
    const el = S.chat.querySelector(`.queued[data-rec="${rec.id}"]`);
    if (el) el.remove();
    await uploadRecording({ ...rec, sessionId: S.session.id });
  }
}

/* ---- hide German ---------------------------------------------------- */
function toggleHide() {
  S.hideGerman = !S.hideGerman;
  prefs.set('hideGerman', S.hideGerman);
  syncHideButton();
  for (const t of S.chat.querySelectorAll('.msg.tutor .bubble-text')) {
    t.classList.toggle('hidden-text', S.hideGerman);
    t.classList.remove('revealed');
  }
  for (const r of S.chat.querySelectorAll('.msg.tutor .reveal')) r.hidden = !S.hideGerman;
  toast(S.hideGerman ? 'Listening mode: German text hidden.' : 'German text shown.');
}
function syncHideButton() {
  S.hideBtn.classList.toggle('active', S.hideGerman);
  S.hideBtn.setAttribute('aria-pressed', String(S.hideGerman));
}

/* ---- tap a word → translation sheet --------------------------------- */
async function translateWord(word, sentence, known = null) {
  const body = h('div', { class: 'stack' }, spinner('Looking up…'));
  sheet.open(body, { title: word });
  let data;
  try {
    data = known
      ? { word, lemma: known.word, translation: known.translation, pos: '', note: known.example || '', in_vocab: true }
      : await api('/api/vocab/translate', { method: 'POST', body: { word, context: sentence || '' }, timeout: 30000 });
  } catch (e) {
    clear(body).append(errorLine(e, () => translateWord(word, sentence, known)));
    return;
  }
  const addBtn = h('button', { class: 'btn primary block', type: 'button', disabled: data.in_vocab, onClick: async () => {
    addBtn.disabled = true;
    try {
      await api('/api/vocab', { method: 'POST', body: { word: data.lemma || word, translation: data.translation, example: sentence || '', source: 'manual' } });
      addBtn.textContent = 'In your vocab';
      toast('Added to vocab.', { kind: 'ok' });
    } catch (e) { addBtn.disabled = false; toast(e.detail || 'Could not add.', { kind: 'err' }); }
  } }, data.in_vocab ? 'In your vocab' : 'Add to vocab');
  clear(body).append(
    h('div', { class: 'row between' },
      h('div', {}, h('div', { class: 'lemma' }, data.lemma || word), h('div', { class: 'muted small' }, data.pos || '')),
      h('button', { class: 'btn icon', type: 'button', 'aria-label': 'Hear it', onClick: () => playMessage('w', data.lemma || word, 'normal') }, playIcon())),
    h('p', { class: 'translation' }, data.translation || '—'),
    data.note ? h('p', { class: 'muted small' }, data.note) : null,
    addBtn);
}

/* ---- icons (inline SVG keeps the CSP happy; no icon font) ----------- */
function svg(d, extra = '') { return h('span', { class: 'ico', html: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/>${extra}</svg>` }); }
function playIcon() { return svg('M8 5v14l11-7z'); }
function sendIcon() { return svg('M3 11.5 21 3l-7 18-2.5-7.5z'); }
function eyeIcon() { return svg('M12 5c5 0 9 4.5 10 7-1 2.5-5 7-10 7S3 14.5 2 12c1-2.5 5-7 10-7zm0 3.5A3.5 3.5 0 1 0 12 15.5 3.5 3.5 0 0 0 12 8.5z'); }
function stopIcon() { return svg('M6 6h12v12H6z'); }
