/* Talk screen: text and voice conversation with the tutor. The centrepiece (docs/DESIGN.md §4).

   Rules this screen enforces:
   - the raw transcript is shown verbatim, with a "transcribed" affordance that lets him dispute it
     ("that's not what I said") and discard the turn without polluting the mistake log
   - correction cards are amber, collapsed by default, and never move the message above them
   - the typed text / the recording is never lost: a failed turn restores the input, a failed
     upload keeps the blob in IndexedDB and retries on tap or when connectivity returns
   - the view only auto-scrolls when he was already near the bottom */
import { api, upload, audioFilename } from './api.js';
import { h, clear, toast, sheet, errorLine, prefs, tappableWords, spinner, plural, haptic, catChip, setExpanded, de } from './ui.js';
import { speak, stop as stopAudio, unlockAudio, setPlaybackListener } from './audio.js';
import { createHoldToTalk, micIcon } from './mic.js';
import { store } from './store.js';

const S = {
  screen: null, chat: null, foot: null, input: null, sendBtn: null, mic: null, composerText: null, composerMic: null,
  headScenario: null, hideBtn: null,
  session: null, scenario: null, scenarios: [], unit: null, loaded: false,
  pending: false, abort: null, hideGerman: prefs.get('hideGerman', false), mode: prefs.get('composer', 'mic'),
  playing: null,
};

/* ---- mount / show --------------------------------------------------- */
export function mount(el) {
  S.screen = el;
  const head = h('header', { class: 'screen-head' },
    h('h1', {}, 'Talk'),
    S.headScenario = h('button', { class: 'chip', type: 'button', onClick: openScenarioPicker }, 'Free conversation'),
    S.hideBtn = h('button', { class: 'btn icon ghost', type: 'button', 'aria-label': 'Hide German text', 'aria-pressed': 'false', onClick: toggleHide }, eyeIcon()),
    h('button', { class: 'btn icon ghost', type: 'button', 'aria-label': 'End session', onClick: confirmEnd }, stopIcon()));
  S.chat = h('div', { class: 'chat', id: 'chat', 'aria-live': 'polite' });
  S.foot = h('footer', { class: 'screen-foot talk-foot' });
  buildComposer();
  clear(el).append(head, S.chat, S.foot);
  syncHideButton();
  setPlaybackListener(onPlayback);
  document.addEventListener('dt:online', () => retryQueued());
  document.addEventListener('dt:viewport', (e) => { if (e.detail.keyboard) scrollToEnd(true); });
  // Placement or a passed checkpoint changed the unit: refresh the scenarios for the next session.
  document.addEventListener('dt:profile-changed', async () => { await loadScenarios(); if (!S.session) renderStart(); });
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
      if (e.offline) { renderStart(e); return; }
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
function renderLoading() {
  clear(S.chat).append(
    h('div', { class: 'msg tutor', 'aria-hidden': 'true' }, h('div', { class: 'bubble skeleton' }, h('i', { class: 'w80' }), h('i', { class: 'w60' }))),
    h('div', { class: 'msg user', 'aria-hidden': 'true' }, h('div', { class: 'bubble skeleton' }, h('i', { class: 'w40' }))));
}

function renderStart(err) {
  clear(S.chat);
  const card = h('div', { class: 'card start-card stack' },
    h('h2', {}, S.unit ? de(S.unit.title) : 'Ready when you are'),
    S.unit ? h('p', { class: 'muted small' }, (S.unit.can_do || []).slice(0, 2).join(' · ')) : null,
    h('p', {}, 'Pick a scenario or just talk. The tutor speaks first; you answer by holding the mic or typing. Mistakes are the point — say it anyway.'),
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
    h('p', {}, `Start a new conversation with "${sc.title}"? The current one is ended and summarised.`),
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
      if (lastUser) { lastUser.attach({ corrections: m.correction || [], english_help: m.english_help }); lastUser.link(m.id); lastUser = null; }
      S.chat.append(tutorBubble({ id: m.id, text: m.content }));
    }
  }
  scrollToEnd(true, 'auto');
}

function tutorBubble({ id, text, newVocab = [] }) {
  const sentence = h('p', { class: `bubble-text ${S.hideGerman ? 'hidden-text' : ''}` }, tappableWords(text, translateWord));
  const reveal = h('button', { class: 'btn small ghost reveal', type: 'button', hidden: !S.hideGerman, onClick: () => {
    sentence.classList.add('revealed'); reveal.hidden = true;
  } }, 'Show text');
  const slowBtn = h('button', { class: 'btn small ghost slow', type: 'button', 'aria-label': 'Play slowly', 'aria-pressed': 'false',
    onClick: () => playMessage(id, text, 'slow') }, 'Slow');
  const tools = h('div', { class: 'msg-tools' },
    h('button', { class: 'btn small ghost play', type: 'button', 'aria-label': 'Play again', onClick: () => playMessage(id, text, 'normal') }, playIcon(), 'Play'),
    slowBtn, reveal);
  const vocab = newVocab.length ? h('div', { class: 'vocab-chips' }, newVocab.map((v) =>
    h('button', { class: 'chip small', type: 'button', lang: 'de', onClick: () => translateWord(v.word.split(' (')[0].replace(/^(der|die|das)\s+/i, ''), v.example || text, v) },
      h('b', {}, v.word), ' ', h('span', { class: 'muted', lang: 'en' }, v.translation)))) : null;
  return h('div', { class: 'msg tutor', dataset: { id: String(id) } },
    h('div', { class: 'bubble' }, sentence, h('div', { class: 'audio-line', 'aria-hidden': 'true' }, h('i'))), tools, vocab);
}

function userBubble({ id, text, transcript, provider, pending = false, duration = null }) {
  const el = h('div', { class: `msg user ${pending ? 'pending' : ''}`, dataset: { id: String(id || '') } });
  const body = h('div', { class: 'bubble' });
  let assistantId = null;
  if (transcript != null) {
    body.append(h('button', { class: 'transcript-label', type: 'button', 'aria-label': 'Transcribed from your voice. Tap to dispute',
      onClick: () => disputeTranscript(id, assistantId, el) }, micIcon(), 'transcribed', provider ? ` · ${provider}` : ''));
    body.append(h('p', { class: 'bubble-text', lang: 'de' }, transcript));
  } else if (pending && duration) {
    body.append(h('div', { class: 'transcript-label' }, micIcon(), ` ${duration}`), h('p', { class: 'bubble-text muted' }, 'transcribing…'));
  } else {
    body.append(h('p', { class: 'bubble-text', lang: 'de' }, text));
  }
  el.append(body);
  const extras = h('div', { class: 'msg-extras' });
  el.append(extras);
  return {
    el,
    link(aid) { assistantId = aid; },
    attach({ corrections = [], praise = null, english_help = null }) {
      clear(extras);
      if (corrections.length) extras.append(correctionCard(corrections));
      if (praise) extras.append(h('p', { class: 'praise' }, praise));
      if (english_help) extras.append(englishHelpCard(english_help));
    },
    setPending(on) { el.classList.toggle('pending', on); },
  };
}

function correctionCard(corrections) {
  const list = h('ul', { class: 'corr-list' }, corrections.map((c) =>
    h('li', {},
      h('div', { class: 'corr-pair', lang: 'de' }, h('s', {}, c.wrong), ' → ', h('b', {}, tappableWords(c.right, translateWord))),
      h('div', { class: 'corr-expl' }, h('span', {}, c.explanation), catChip(c.category)))));
  const panel = h('div', { class: 'corr-panel', hidden: true }, list);
  const toggle = h('button', { class: 'corr-toggle', type: 'button', 'aria-expanded': 'false',
    onClick: () => setExpanded(toggle, panel, toggle.getAttribute('aria-expanded') !== 'true') },
    h('span', { class: 'dot', 'aria-hidden': 'true' }), plural(corrections.length, 'correction'), chevron());
  return h('div', { class: 'corr' }, toggle, panel);
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
    h('p', {}, h('b', {}, 'Scenario complete.'), ' Keep talking, or try the next one.'),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => card.remove() }, 'Keep going'),
      h('button', { class: 'btn primary', type: 'button', onClick: async () => { await endSession({ silent: true }); openScenarioPicker(); } }, 'New scenario')));
  return card;
}

function typingIndicator() {
  const note = h('div', { class: 'thinking-note', hidden: true });
  const el = h('div', { class: 'msg tutor typing-row' }, h('div', { class: 'bubble' }, h('span', { class: 'typing' }, h('i'), h('i'), h('i'))), note);
  el.note = note;
  return el;
}

function nearBottom() {
  const s = S.screen;
  return s.scrollHeight - s.scrollTop - s.clientHeight < 160;
}
function scrollToEnd(force = false, behavior = 'smooth') {
  if (!force && !nearBottom()) return;
  requestAnimationFrame(() => { S.screen.scrollTo({ top: S.screen.scrollHeight, behavior }); });
}

/* ---- audio ---------------------------------------------------------- */
function onPlayback(st) {
  S.playing = st;
  for (const m of S.chat.querySelectorAll('.msg.tutor')) {
    const on = !!st && m.dataset.id === String(st.id);
    m.classList.toggle('playing', on);
    const line = m.querySelector('.audio-line > i');
    if (line) line.style.width = on ? `${Math.round((st.progress || 0) * 100)}%` : '0%';
    const slow = m.querySelector('.btn.slow');
    if (slow) { slow.classList.toggle('active', on && st.speed === 'slow'); slow.setAttribute('aria-pressed', String(on && st.speed === 'slow')); }
  }
}

async function playMessage(id, text, speed, { auto = false } = {}) {
  if (!text) return;
  unlockAudio();
  try {
    await speak(text, speed, { id });
  } catch (e) {
    if (e && e.name === 'NotAllowedError') {
      // iOS refused autoplay: swap in a tap-to-play on that message instead of failing silently.
      const m = S.chat.querySelector(`.msg.tutor[data-id="${id}"] .msg-tools`);
      if (m && !m.querySelector('.tap-play')) {
        const b = h('button', { class: 'btn small primary tap-play', type: 'button', onClick: () => { b.remove(); playMessage(id, text, speed); } }, 'Tap to play');
        m.prepend(b);
      }
    } else if (!auto) {
      toast(e.detail || 'Audio unavailable right now.', { kind: 'err' });
    }
  }
}

/* ---- session lifecycle ---------------------------------------------- */
async function startSession() {
  if (S.pending) return;
  setPending(true);
  const wasNear = true;
  clear(S.chat).append(typingIndicator());
  try {
    const data = await api('/api/talk/session', { method: 'POST', body: { scenario_id: S.scenario ? S.scenario.id : null } });
    S.session = data.session;
    prefs.set('talkSession', S.session.id);
    setScenarioFromSession(S.session);
    clear(S.chat);
    renderTurn(data.opening_turn, null, wasNear);
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
  if (!silent) clear(S.chat).append(h('div', { class: 'card stack' }, h('div', { class: 'card-title' }, 'Session summary'), spinner('Summarising…')));
  try {
    const res = await api(`/api/talk/session/${id}/end`, { method: 'POST', timeout: 90000 });
    if (!silent) {
      clear(S.chat).append(h('div', { class: 'card stack' },
        h('div', { class: 'card-title' }, 'Session summary'),
        h('p', {}, res.summary || (res.analyzed ? 'Nothing new to summarise.' : 'Saved. The analysis runs later — the tutor was busy.')),
        h('button', { class: 'btn primary block', type: 'button', onClick: () => renderStart() }, 'New conversation')));
    } else if (!res.analyzed) {
      toast('Session saved; analysis postponed.');
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

function renderTurn(turn, userHandle, wasNear) {
  if (userHandle) {
    userHandle.setPending(false);
    userHandle.link(turn.message_id);
    userHandle.attach({ corrections: turn.corrections || [], praise: turn.praise, english_help: turn.english_help });
  }
  const bubble = tutorBubble({ id: turn.message_id, text: turn.reply, newVocab: turn.new_vocab || [] });
  S.chat.append(bubble);
  if (turn.scenario_done) S.chat.append(scenarioDoneCard());
  scrollToEnd(wasNear);
  playMessage(turn.message_id, turn.reply, 'normal', { auto: true });
}

async function sendText() {
  const text = S.input.value.trim();
  if (!text || S.pending) return;
  if (!S.session) { await startSession(); if (!S.session) return; }
  haptic(20);
  await doTurn({ text }, (signal) => api('/api/talk/turn', { method: 'POST', body: { session_id: S.session.id, text }, signal }));
}

/* Runs one turn with the pending UI; `run(signal)` performs the request. Restores the input on
   error. Escalates the thinking state at 6 s and offers cancel at 20 s. */
async function doTurn({ text, transcript = null, duration = null, retry = null }, run) {
  setPending(true);
  stopAudio();
  const wasNear = nearBottom();
  const handle = userBubble({ text: text || 'voice message', transcript, pending: true, duration });
  S.chat.append(handle.el);
  const typing = typingIndicator();
  S.chat.append(typing);
  S.input.value = '';
  autosize();
  scrollToEnd(wasNear);
  S.abort = new AbortController();
  const t6 = setTimeout(() => { typing.note.textContent = 'still thinking…'; typing.note.hidden = false; }, 6000);
  const t20 = setTimeout(() => {
    clear(typing.note).append('taking longer than usual · ', h('button', { class: 'btn small ghost', type: 'button', onClick: () => S.abort && S.abort.abort() }, 'Cancel'));
  }, 20000);
  try {
    const turn = await run(S.abort.signal);
    typing.remove();
    if (turn.transcript != null) {
      // Replace the placeholder with the raw transcript, exactly as the engine returned it.
      const real = userBubble({ id: turn.user_message_id, text: turn.transcript, transcript: turn.transcript, provider: turn.transcript_provider });
      handle.el.replaceWith(real.el);
      renderTurn(turn, real, wasNear);
    } else {
      handle.el.dataset.id = String(turn.user_message_id || '');
      renderTurn(turn, handle, wasNear);
    }
    return true;
  } catch (e) {
    typing.remove();
    handle.el.remove();
    if (text) S.input.value = text;
    autosize();
    if (e.cancelled) { toast('Cancelled.'); resync(); return false; }
    if (e.status === 409) { toast('That conversation has ended. Starting a new one.'); S.session = null; prefs.set('talkSession', null); renderStart(); return false; }
    showError(e, retry || (text ? sendText : null));
    return false;
  } finally {
    clearTimeout(t6); clearTimeout(t20);
    S.abort = null;
    setPending(false);
  }
}

/* After a cancel the server may still have completed the turn: reload the session to stay in sync. */
async function resync() {
  if (!S.session) return;
  try { const data = await api(`/api/talk/session/${S.session.id}`); renderHistory(data.messages); } catch { /* next load fixes it */ }
}

let errorEl = null;
function showError(e, retry) {
  if (errorEl) errorEl.remove();
  errorEl = errorLine(e, retry ? () => { errorEl.remove(); errorEl = null; retry(); } : null);
  S.foot.prepend(errorEl);
  setTimeout(() => { if (errorEl) { errorEl.remove(); errorEl = null; } }, 15000);
}

/* "That's not what I said": discard the turn so the transcriber's error never reaches the log. */
function disputeTranscript(userId, assistantId, el) {
  if (!userId || !S.session) return;
  sheet.open(h('div', { class: 'stack' },
    h('p', {}, 'If the transcriber got this wrong, discard the turn. Nothing from it goes into your mistake log, and you can say it again.'),
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => sheet.close() }, 'Keep it'),
      h('button', { class: 'btn primary', type: 'button', onClick: async () => {
        sheet.close();
        try {
          await api(`/api/talk/session/${S.session.id}/discard`, { method: 'POST', body: { user_message_id: Number(userId) } });
          const next = el.nextElementSibling;
          if (next && next.classList.contains('tutor') && (!assistantId || next.dataset.id === String(assistantId))) next.remove();
          el.remove();
          stopAudio();
          toast('Turn discarded. Say it again when you are ready.');
        } catch (e) { toast(e.detail || 'Could not discard.', { kind: 'err' }); }
      } }, "That's not what I said"))), { title: 'Transcript' });
}

/* ---- composer + mic ------------------------------------------------- */
function buildComposer() {
  S.input = h('textarea', { class: 'input composer-input', rows: '1', placeholder: 'Schreib auf Deutsch…', enterkeyhint: 'send', lang: 'de',
    autocapitalize: 'sentences', autocomplete: 'off', 'aria-label': 'Your message', onInput: autosize,
    onKeydown: (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendText(); } } });
  S.sendBtn = h('button', { class: 'btn icon primary', type: 'button', 'aria-label': 'Send', onClick: sendText }, sendIcon());
  const toMic = h('button', { class: 'btn icon ghost', type: 'button', 'aria-label': 'Switch to voice', onClick: () => setMode('mic') }, micIcon());
  S.composerText = h('div', { class: 'composer', hidden: true }, toMic, S.input, S.sendBtn);
  const toText = h('button', { class: 'btn icon ghost', type: 'button', 'aria-label': 'Switch to typing', onClick: () => setMode('text') }, keyboardIcon());
  S.mic = createHoldToTalk({
    onStart: async () => { if (S.pending) return false; if (!S.session) { await startSession(); } return !!S.session; },
    onResult: (result) => sendRecording(result),
    side: toText,
  });
  S.composerMic = S.mic.el;
  S.foot.append(S.composerText, S.composerMic);
  setMode(S.mode, false);
}

function setMode(mode, focus = true) {
  S.mode = mode;
  prefs.set('composer', mode);
  S.composerText.hidden = mode !== 'text';
  S.composerMic.hidden = mode !== 'mic';
  if (mode === 'text' && focus) setTimeout(() => S.input.focus(), 30);
}

function autosize() {
  const el = S.input;
  el.style.height = 'auto';
  el.style.height = Math.min(120, el.scrollHeight) + 'px';
}

/* V3: the blob goes into IndexedDB before the upload and is deleted only after a 2xx. */
async function sendRecording({ blob, mime, durationMs }) {
  const sessionId = S.session.id;
  const stored = await store.add('recordings', { sessionId, blob, mime, createdAt: Date.now(), durationMs });
  await uploadRecording({ id: stored, sessionId, blob, mime, durationMs });
}

function fmtDuration(ms) { const s = Math.round((ms || 0) / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }

async function uploadRecording(rec) {
  const run = (signal) => upload('/api/talk/turn', rec.blob, audioFilename(rec.mime), { session_id: rec.sessionId }, { signal });
  const ok = await doTurn({ text: null, duration: fmtDuration(rec.durationMs), retry: () => uploadRecording(rec) }, run);
  if (ok) { if (rec.id != null) await store.remove('recordings', rec.id); return; }
  // Keep it: show it as an unsent message with a retry, and retry automatically when back online.
  showQueued(rec);
}

function showQueued(rec) {
  if (S.chat.querySelector(`.queued[data-rec="${rec.id}"]`)) return;
  const el = h('div', { class: 'msg user queued', dataset: { rec: String(rec.id) } },
    h('div', { class: 'bubble' }, h('p', { class: 'bubble-text' }, micIcon(), ` Voice message ${fmtDuration(rec.durationMs)} — not sent yet`),
      h('div', { class: 'btn-row' },
        h('button', { class: 'btn small primary', type: 'button', onClick: () => { el.remove(); uploadRecording(rec); } }, 'Retry'),
        h('button', { class: 'btn small ghost', type: 'button', onClick: async () => { await store.remove('recordings', rec.id); el.remove(); } }, 'Discard'))));
  S.chat.append(el);
  scrollToEnd(true);
}

async function renderQueued(list) {
  for (const rec of list) {
    if (S.session) showQueued({ ...rec, sessionId: S.session.id });
    else toast('An unsent recording is waiting.', { action: 'Send', duration: 0, onAction: async () => { await startSession(); if (S.session) uploadRecording({ ...rec, sessionId: S.session.id }); } });
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
  // The sheet opens instantly with the word; the translation fills in when it arrives.
  const lemma = h('div', { class: 'lemma', lang: 'de' }, known ? known.word : word);
  const pos = h('div', { class: 'muted small' }, '');
  const translation = h('p', { class: 'translation' }, known ? known.translation : '');
  const note = h('p', { class: 'lookup-note' }, known ? (known.example || '') : 'looking up…');
  const addBtn = h('button', { class: 'btn primary block', type: 'button', disabled: true }, 'Add to vocab');
  const body = h('div', { class: 'stack' },
    h('div', { class: 'row between' }, h('div', {}, lemma, pos),
      h('button', { class: 'btn icon', type: 'button', 'aria-label': 'Hear it', onClick: () => playMessage('w', lemma.textContent, 'normal') }, playIcon())),
    translation, note, addBtn);
  sheet.open(body, { title: null });
  let data;
  try {
    data = known
      ? { word, lemma: known.word, translation: known.translation, pos: '', note: known.example || '', in_vocab: true }
      : await api('/api/vocab/translate', { method: 'POST', body: { word, context: sentence || '' }, timeout: 30000 });
  } catch (e) {
    clear(note).append(errorLine(e, () => translateWord(word, sentence, known)));
    return;
  }
  lemma.textContent = data.lemma || word;
  pos.textContent = data.pos || '';
  translation.textContent = data.translation || '—';
  note.textContent = data.note || '';
  addBtn.disabled = !!data.in_vocab;
  addBtn.textContent = data.in_vocab ? 'In your deck' : 'Add to vocab';
  addBtn.addEventListener('click', async () => {
    addBtn.disabled = true;
    try {
      await api('/api/vocab', { method: 'POST', body: { word: data.lemma || word, translation: data.translation, example: sentence || '', source: 'manual' } });
      addBtn.textContent = 'In your deck';
      toast('Added to your deck.', { kind: 'ok' });
    } catch (e) { addBtn.disabled = false; toast(e.detail || 'Could not add.', { kind: 'err' }); }
  });
}

/* ---- icons (inline SVG keeps the CSP happy; no icon font) ----------- */
function svg(d) { return h('span', { class: 'ico', html: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg>` }); }
function playIcon() { return svg('M8 5v14l11-7z'); }
function sendIcon() { return svg('M3 11.5 21 3l-7 18-2.5-7.5z'); }
function eyeIcon() { return svg('M12 5c5 0 9 4.5 10 7-1 2.5-5 7-10 7S3 14.5 2 12c1-2.5 5-7 10-7zm0 3.5A3.5 3.5 0 1 0 12 15.5 3.5 3.5 0 0 0 12 8.5z'); }
function stopIcon() { return svg('M6 6h12v12H6z'); }
function keyboardIcon() { return svg('M3 6h18a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1zm2 3v2h2V9zm4 0v2h2V9zm4 0v2h2V9zm4 0v2h2V9zM5 13v2h2v-2zm4 0v2h6v-2zm8 0v2h2v-2z'); }
function chevron() { return h('span', { class: 'ico chev', html: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6z"/></svg>' }); }
