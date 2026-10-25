/* Learn: the coursework, and the first thing a beginner should touch.

   The landing is the path through the current phase, Duolingo-style: units done, the one you are
   on (its lesson's progress as a ring, Katze beside it, the lesson card under it), the checkpoint
   that opens the next unit, and what is still locked.

   A lesson runs in the player: focus mode, a close button and a thick track on top, one exercise
   per screen, the action at the bottom. Teaching pages (sounds, words, grammar) are interleaved
   with practice generated from exactly what was just taught — match, listen, build from tiles, say
   it out loud — and the authored checks. A text page (a dialogue to listen to, a letter or an
   article to read) is followed by checks on what it said. Progress saves per step, and a step you have passed stays
   passed: going back never makes you answer it again to move on (you may, if you like). */
import { api, upload, audioFilename } from './api.js';
import { h, clear, toast, sheet, errorLine, skeleton, haptic, de } from './ui.js';
import { speak, prefetch, stop as stopAudio, unlockAudio } from './audio.js';
import { createHoldToTalk } from './mic.js';
import { katze } from './katze.js';
import { rings } from './rings.js';
import { icon } from './icons.js';
import { maybeCelebrate } from './moment.js';
import { focusMode, playerHead, playerFoot, katzeSays, statStrip } from './kit.js';

const S = {
  root: null, pathView: null, pathBody: null, playerView: null, head: null, body: null, foot: null,
  view: 'path', unitId: null, unitTitle: '', lesson: null, list: [], i: 0, furthest: 0,
  right: 0, asked: 0, seed: 0, scored: new Set(), finishedFirst: false,
};
const me = () => window.dtUser || {};

export function mount(el) {
  S.root = el;
  S.pathBody = h('div', { class: 'screen-body learn-path' });
  S.pathView = h('div', { class: 'learn-view' }, h('header', { class: 'screen-head' }, h('h1', {}, 'Learn')), S.pathBody);
  S.head = playerHead({ onClose: closePlayer, closeLabel: 'Close the lesson' });
  S.body = h('div', { class: 'player-body' });
  S.foot = playerFoot();
  S.playerView = h('div', { class: 'player', hidden: true }, S.head.el, S.body, S.foot.el);
  clear(el).append(S.pathView, S.playerView);
}

export async function show() {
  if (S.view === 'player') { focusMode(true); return; }
  await loadPath();
}
export function hide() { stopAudio(); }

/* Audio is a convenience: a failed fetch never breaks an exercise, and only a tap says so. */
function say(text, { speed = 'normal', quiet = false } = {}) {
  if (!text) return;
  unlockAudio();
  speak(text, speed).catch((e) => { if (!quiet) toast((e && e.detail) || 'Audio unavailable right now.', { kind: 'err' }); });
}

/* ---- the path --------------------------------------------------------- */
async function loadPath() {
  if (!S.pathBody.childElementCount || S.pathBody.querySelector('.error-line')) clear(S.pathBody).append(h('div', { class: 'card' }, skeleton(2)), skeleton(3, { tall: true }));
  try {
    const [tree, cur, lesson, overview] = await Promise.all([
      api('/api/curriculum'),
      api('/api/curriculum/current'),
      api(`/api/lesson/current?seed=${S.seed}`).catch((e) => (e.status === 404 ? null : Promise.reject(e))),
      api('/api/lesson/overview').catch(() => ({ units: [] })),
    ]);
    renderPath(tree, cur, lesson, overview.units || []);
  } catch (e) {
    clear(S.pathBody).append(errorLine(e, loadPath));
  }
}

const ZIG = [0, 64, 92, 64, 0, -64, -92, -64];

function renderPath(tree, cur, lessonData, overview = []) {
  const byUnit = Object.fromEntries(overview.map((o) => [o.unit_id, o]));
  clear(S.pathBody);
  const phase = (tree.phases || []).find((p) => p.id === cur.phase.id) || { units: [] };
  const phaseIdx = (tree.phases || []).indexOf(phase);
  const nextPhase = (tree.phases || [])[phaseIdx + 1];
  const at = Math.max(0, (cur.unit_index || 1) - 1);
  const total = phase.units.length;

  S.pathBody.append(h('div', { class: 'phase-head' },
    h('div', { class: 'row between' },
      h('h2', { class: 'phase-title' }, phase.title || cur.phase.title),
      h('span', { class: 'pill' }, cur.phase.level)),
    h('div', { class: 'phase-track', role: 'img', 'aria-label': `${at} of ${total} units done` },
      phase.units.map((_, i) => h('i', { class: i < at ? 'done' : i === at ? 'now' : '' }))),
    h('p', { class: 'muted small' }, `Unit ${at + 1} of ${total}`, at ? ` · ${at} done` : '')));

  const path = h('div', { class: 'path' });
  let z = 0;
  const offset = () => ZIG[z++ % ZIG.length];
  phase.units.forEach((u, i) => {
    if (i < at) path.append(node({ u, state: 'done', x: offset() }));
    else if (i === at) {
      const x = offset();
      path.append(currentNode(u, x, lessonData), lessonCard(u, lessonData, x));
      path.append(checkpointNode(cur, offset()));
    } else {
      // Ahead of the current unit: open as soon as the lesson before it is finished.
      const o = byUnit[u.id];
      path.append(node({ u, state: o && o.open && o.has_lesson ? 'ahead' : 'locked', x: offset(), info: o }));
    }
  });
  S.pathBody.append(path);
  if (nextPhase) {
    S.pathBody.append(h('div', { class: 'next-phase' }, icon('lock', 18),
      h('span', {}, `Next: ${nextPhase.level} · ${nextPhase.title}`)));
  }
}

function node({ u, state, x, info = null }) {
  const label = { done: `${u.title}, done`, ahead: `${u.title}, open`, locked: `${u.title}, locked` }[state];
  const act = { done: () => openDoneUnit(u), ahead: () => openAhead(u),
    locked: () => toast('Finish the lesson before it to open this one.') }[state];
  const glyph = state === 'locked' ? icon('lock', 22) : state === 'done' || (info && info.completed) ? icon('check', 28) : icon('book', 26);
  const btn = h('button', { class: `node tactile ${state}`, type: 'button', 'aria-label': label, onClick: act }, glyph);
  const sub = state === 'ahead' && info && info.steps
    ? (info.completed ? 'Lesson done' : info.step ? `Step ${info.step} of ${info.steps}` : 'Lesson open') : null;
  return h('div', { class: 'node-row', style: { '--x': `${x}px` } }, btn,
    h('div', { class: `node-label ${state}`, lang: 'de' }, u.title),
    sub ? h('div', { class: 'node-sub' }, sub) : null);
}

/* A lesson further along the path, opened early because the one before it is finished. */
async function openAhead(u) {
  try {
    const data = await api(`/api/lesson/${u.id}`);
    openPlayer({ ...data, unit_title: u.title });
  } catch (e) {
    toast(e.status === 404 ? 'This unit has no written lesson yet.' : 'Could not open the lesson.', { kind: 'err' });
  }
}

function currentNode(u, x, data) {
  const p = data && data.progress;
  const total = data && data.exercises ? data.exercises.length : 0;
  const fraction = p && total ? (p.completed ? 1 : Math.min(1, (p.step || 0) / total)) : 0;
  const ring = rings([{ key: 'lesson', color: 'var(--accent)', track: 'var(--surface-2)', fraction }], 112);
  ring.classList.add('node-ring');
  const btn = h('button', { class: 'node tactile now', type: 'button', 'aria-label': `${u.title}, current unit`,
    onClick: () => (data && data.lesson ? openPlayer(data) : window.dtSwitchTo('talk')) }, icon('book', 30));
  // Katze waits on the side of the path with more room.
  const cat = h('div', { class: `node-cat ${x > 0 ? 'left' : 'right'}` }, katze({ variant: me().avatar, mood: fraction >= 1 ? 'proud' : 'happy', size: 52 }));
  return h('div', { class: 'node-row current', style: { '--x': `${x}px` } }, h('div', { class: 'node-wrap' }, ring, btn, cat));
}

function lessonCard(u, data, x) {
  const card = h('div', { class: 'lesson-card', style: { '--x': `${x}px` } });
  card.append(h('h3', { class: 'lesson-card-title', lang: 'de' }, u.title));
  if (!data || !data.lesson) {
    card.append(
      h('p', { class: 'muted' }, (data && data.detail) || 'No written lesson for this unit yet. Talk and practice still teach it.'),
      h('button', { class: 'btn primary block lg tactile', type: 'button', onClick: () => window.dtSwitchTo('talk') }, 'Talk about it'));
    return card;
  }
  const l = data.lesson;
  const total = data.exercises.length;
  const p = data.progress || {};
  const step = Math.min(p.step || 0, total);
  card.append(h('p', { class: 'lesson-card-intro' }, l.intro));
  if ((u.can_do || []).length) {
    card.append(h('ul', { class: 'cando-list' }, u.can_do.slice(0, 3).map((c) => h('li', {}, icon('check', 16), h('span', {}, c)))));
  }
  const meta = `${total} steps${l.minutes ? ` · about ${l.minutes} min` : ''} · nothing to type`;
  if (p.completed) {
    card.append(h('p', { class: 'muted small' }, `Finished · ${meta}`),
      h('button', { class: 'btn primary block lg tactile', type: 'button', onClick: () => window.dtSwitchTo('talk') }, 'Practise it in Talk'),
      h('button', { class: 'btn ghost block', type: 'button', onClick: () => openPlayer(data, { from: 1, review: true }) }, 'Go through it again'));
  } else if (step > 0) {
    card.append(
      h('div', { class: 'meter', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(total), 'aria-valuenow': String(step) },
        h('i', { style: { width: `${Math.round((100 * step) / total)}%`, background: 'var(--accent)' } })),
      h('p', { class: 'muted small num' }, `Step ${step} of ${total} · ${meta}`),
      h('button', { class: 'btn primary block lg tactile', type: 'button', onClick: () => openPlayer(data) }, 'Continue the lesson'));
  } else {
    card.append(h('p', { class: 'muted small' }, meta),
      h('button', { class: 'btn primary block lg tactile', type: 'button', onClick: () => openPlayer(data) }, 'Start the lesson'));
  }
  return card;
}

function checkpointNode(cur, x) {
  const open = !!cur.checkpoint_available;
  const btn = h('button', { class: `node tactile checkpoint ${open ? 'open' : 'locked'}`, type: 'button',
    'aria-label': open ? 'Checkpoint, open' : 'Checkpoint, not open yet', onClick: () => window.dtSwitchTo('checkpoint') }, icon('trophy', 26));
  return h('div', { class: 'node-row', style: { '--x': `${x}px` } }, btn,
    h('div', { class: `node-label ${open ? '' : 'locked'}` }, open ? 'Checkpoint · open' : 'Checkpoint'));
}

async function openDoneUnit(u) {
  const body = h('div', { class: 'stack' }, h('p', { class: 'muted' }, 'Passed. Going through the lesson again is a good warm-up; nothing has to be answered again.'), skeleton(1, { tall: true }));
  sheet.open(body, { title: u.title });
  try {
    const data = await api(`/api/lesson/${u.id}`);
    clear(body).append(h('p', { class: 'muted' }, 'Passed. Going through the lesson again is a good warm-up; nothing has to be answered again.'),
      h('button', { class: 'btn primary block lg tactile', type: 'button', onClick: () => { sheet.close(); openPlayer({ ...data, unit_title: u.title }, { from: 1, review: true }); } }, 'Open the lesson'));
  } catch (e) {
    clear(body).append(h('p', { class: 'muted' }, e.status === 404 ? 'This unit has no written lesson; it was taught in conversation.' : 'Could not load the lesson.'),
      h('button', { class: 'btn block', type: 'button', onClick: () => sheet.close() }, 'OK'));
  }
}

/* ---- the player ------------------------------------------------------- */
function openPlayer(data, { from = null, review = false } = {}) {
  S.unitId = data.unit_id;
  S.unitTitle = data.unit_title || '';
  S.lesson = data.lesson;
  S.list = data.exercises || [];
  const saved = Math.min((data.progress && data.progress.step) || 0, S.list.length);
  // A finished lesson, or one reopened from the path, has every step passed already.
  S.furthest = review || (data.progress && data.progress.completed) ? S.list.length + 1 : saved;
  S.i = Math.max(1, from || saved || 1);
  S.right = 0; S.asked = 0; S.scored = new Set(); S.finishedFirst = false;
  S.view = 'player';
  S.pathView.hidden = true;
  S.playerView.hidden = false;
  focusMode(true);
  render();
}

function closePlayer() {
  stopAudio();
  S.view = 'path';
  S.playerView.hidden = true;
  S.pathView.hidden = false;
  focusMode(false);
  S.root.scrollTop = 0;
  loadPath();
}

function render() {
  const total = S.list.length;
  S.head.set(Math.min(S.i, total), total);
  clear(S.body);
  S.foot.clear();
  S.root.scrollTop = 0;
  if (S.i > total) { renderDone(); return; }
  const ex = S.list[S.i - 1];
  S.body.append(exercise(ex, S.i));
  // Warm the next step's audio while this one is read — only when there is something to say,
  // or the TTS endpoint gets an empty text and answers 422.
  const next = S.list[S.i];
  const ahead = next && (next.audio || next.de || (next.items || [])[0]?.de || (next.examples || [])[0]?.de);
  if (ahead) prefetch(ahead);
  if (next && next.type === 'text') next.lines.slice(0, 3).forEach((ln, i) => prefetch(ln.de, 'normal', voiceFor(next, i)));
}

const passed = (n) => S.furthest > n;

function backBtn(n) {
  return n > 1 ? h('button', { class: 'btn icon ghost foot-back', type: 'button', 'aria-label': 'Previous step', onClick: () => go(n - 1) }, icon('back', 22)) : null;
}
function continueBtn(n, label = 'Continue') {
  return h('button', { class: 'btn primary lg tactile grow', type: 'button', onClick: () => go(n + 1) }, label);
}

/* What the foot shows before an answer: Back, then either Continue (teaching pages, and any step
   already passed) or the exercise's own hint or button. */
function waitFoot(n, ...rest) {
  if (passed(n)) S.foot.actions(backBtn(n), continueBtn(n));
  else S.foot.actions(backBtn(n), ...rest);
}

function exercise(ex, n) {
  const make = {
    sounds: soundsStep, words: wordsStep, grammar: grammarStep, text: textStep,
    check: (e) => choiceStep(e, n, { question: e.question, options: e.options, answer: e.answer, why: e.why }),
    listen: listenStep, match: matchStep, build: buildStep, speak: speakStep,
  }[ex.type];
  const el = make ? make(ex, n) : h('p', { class: 'muted' }, 'This step type is not supported here yet.');
  if (ex.mode === 'teach' && ex.type !== 'check') S.foot.actions(backBtn(n), continueBtn(n));
  if (!make) S.foot.actions(backBtn(n), continueBtn(n));
  const wrap = h('div', { class: 'ex' });
  if (ex.mode !== 'teach' || ex.type === 'check') {
    if (passed(n)) wrap.append(h('p', { class: 'done-before' }, icon('check', 16), 'Done before. Answer again if you like, or continue.'));
  }
  wrap.append(el);
  return wrap;
}

/* ---- teaching pages --------------------------------------------------- */
function lineBtn({ main, text, label }) {
  return h('button', { class: 'line', type: 'button', 'aria-label': label || `Play “${text}”`, onClick: () => { haptic(8); say(text); } },
    h('span', { class: 'line-main' }, main), h('span', { class: 'say' }, icon('speaker', 20)));
}
function tip(note) {
  return note ? h('div', { class: 'tip' }, katze({ variant: me().avatar, mood: 'thinking', size: 28 }), h('p', {}, note)) : null;
}

function soundsStep(step) {
  return h('div', { class: 'stack-lg' },
    h('h1', { class: 'prompt-h' }, step.title),
    step.body ? h('p', { class: 'prompt-lead' }, step.body) : null,
    h('div', { class: 'lines' }, step.items.map((s) => lineBtn({ text: s.example, main: [
      h('span', { class: 'line-de' }, de(s.de, 'sound-letter'), h('span', { class: 'sound-say' }, s.say)),
      h('span', { class: 'line-en' }, de(s.example, 'line-example'), ` — ${s.en}`)] }))),
    tip(step.note));
}

function wordsStep(step) {
  return h('div', { class: 'stack-lg' },
    h('h1', { class: 'prompt-h' }, step.title),
    step.body ? h('p', { class: 'prompt-lead' }, step.body) : null,
    h('div', { class: 'lines' }, step.items.map((it) => lineBtn({ text: it.de, main: [
      de(it.de, 'line-de'), h('span', { class: 'line-en' }, it.en || ''), it.note ? h('span', { class: 'line-note' }, it.note) : null] }))),
    tip(step.note));
}

function grammarStep(step) {
  const table = step.table ? h('div', { class: 'g-table-wrap' }, h('table', { class: 'g-table' },
    h('thead', {}, h('tr', {}, step.table.head.map((c) => h('th', { scope: 'col' }, c)))),
    h('tbody', {}, step.table.rows.map((r) => h('tr', {}, r.map((c, i) =>
      h('td', { class: i === 0 ? 'de-cell' : '', lang: i === 0 ? 'de' : 'en' }, c))))))) : null;
  return h('div', { class: 'stack-lg' },
    h('h1', { class: 'prompt-h' }, step.title),
    h('p', { class: 'prompt-lead' }, step.body),
    table,
    step.examples ? h('div', { class: 'lines' }, step.examples.map((it) => lineBtn({ text: it.de, main: [
      de(it.de, 'line-de sm'), h('span', { class: 'line-en' }, it.en || ''), it.note ? h('span', { class: 'line-note' }, it.note) : null] }))) : null,
    tip(step.note));
}

/* A dialogue or a passage. Listening comes first and the text stays hidden until asked for, because
   the checks after it test the ear; a reading text is on the page from the start. Two speakers get
   two voices: by ear alone, one voice playing both sides of a phone call is a monologue. */
function voiceFor(step, i) {
  const speakers = [...new Set(step.lines.map((ln) => ln.who).filter(Boolean))];
  const who = step.lines[i].who;
  return who && speakers.indexOf(who) % 2 === 1 ? 2 : 1;
}

function textStep(step) {
  const listening = step.skill === 'listen';
  const run = { token: 0 };
  const rows = step.lines.map((ln, i) => {
    const en = h('span', { class: 'line-en', hidden: true }, ln.en);
    const btn = h('button', { class: 'line text-line', type: 'button', 'aria-label': `Play line ${i + 1}`, onClick: () => {
      haptic(8); run.token += 1; unlockAudio();
      speak(ln.de, 'normal', { voice: voiceFor(step, i) }).catch(() => toast('Audio unavailable right now.', { kind: 'err' }));
    } }, h('span', { class: 'line-main' },
      ln.who ? h('span', { class: 'line-who' }, ln.who) : null,
      de(ln.de, 'line-de sm'), en), h('span', { class: 'say' }, icon('speaker', 20)));
    return { btn, en };
  });
  const textBox = h('div', { class: 'lines text-lines', hidden: listening }, rows.map((r) => r.btn));

  async function playAll(speed) {
    const token = ++run.token;
    unlockAudio();
    playBtn.classList.add('playing');
    try {
      for (let i = 0; i < step.lines.length; i += 1) {
        if (token !== run.token || !S.body.contains(textBox)) return;
        rows.forEach((r, j) => r.btn.classList.toggle('now', j === i));
        await speak(step.lines[i].de, speed, { voice: voiceFor(step, i) });
      }
    } catch (e) {
      toast((e && e.detail) || 'Audio unavailable right now.', { kind: 'err' });
    } finally {
      if (token === run.token) { playBtn.classList.remove('playing'); rows.forEach((r) => r.btn.classList.remove('now')); }
    }
  }
  const playBtn = h('button', { class: 'btn speak-big tactile', type: 'button', 'aria-label': 'Play the whole text', onClick: () => playAll('normal') }, icon('speaker', 36));
  const slowBtn = h('button', { class: 'btn speak-slow tactile', type: 'button', 'aria-label': 'Play it slowly', onClick: () => playAll('slow') }, icon('slow', 26));

  const toggles = h('div', { class: 'row text-toggles' });
  const showText = h('button', { class: 'btn ghost small', type: 'button', onClick: () => {
    textBox.hidden = !textBox.hidden;
    showText.textContent = textBox.hidden ? 'Show the text' : 'Hide the text';
    showEn.hidden = textBox.hidden;
  } }, 'Show the text');
  const showEn = h('button', { class: 'btn ghost small', type: 'button', hidden: listening, onClick: () => {
    const on = rows[0].en.hidden;
    rows.forEach((r) => { r.en.hidden = !on; });
    showEn.textContent = on ? 'Hide English' : 'Show English';
  } }, 'Show English');
  if (listening) toggles.append(showText);
  toggles.append(showEn);

  if (listening) setTimeout(() => { if (S.body.contains(textBox)) playAll('normal'); }, 300);
  return h('div', { class: 'stack-lg' },
    h('div', { class: 'stack' },
      h('span', { class: 'pill kind' }, icon(listening ? 'speaker' : 'book', 14), listening ? 'Listen' : 'Read'),
      h('h1', { class: 'prompt-h' }, step.title)),
    step.body ? h('p', { class: 'prompt-lead' }, step.body) : null,
    listening ? h('div', { class: 'listen-row' }, playBtn, slowBtn) : null,
    toggles, textBox, tip(step.note));
}

/* ---- practice --------------------------------------------------------- */
/* Shows the verdict in the foot. Only a first pass counts toward the score and the server's tally. */
function verdict(n, ok, detail, { cta = 'Continue' } = {}) {
  if (!passed(n) && !S.scored.has(n)) {
    S.scored.add(n);
    S.asked += 1; S.right += ok ? 1 : 0;
    api(`/api/lesson/${S.unitId}/check`, { method: 'POST', body: { step: n, correct: ok } }).catch(() => {});
  }
  haptic(ok ? 10 : 25);
  S.foot.verdict({ ok, title: ok ? 'Richtig' : 'Not quite', detail, cta, onContinue: () => go(n + 1) });
}

function choiceStep(ex, n, { question, options, answer, why, audio = null, title = null }) {
  const opts = h('div', { class: 'options' });
  let done = false;
  options.forEach((text, i) => {
    opts.append(h('button', { class: 'option tactile', type: 'button', lang: audio ? 'de' : undefined, onClick: () => {
      if (done) return;
      done = true;
      const ok = i === answer;
      for (const [j, b] of [...opts.children].entries()) {
        b.disabled = true;
        if (j === answer) b.classList.add('right');
        else if (j === i) b.classList.add('wrong');
      }
      verdict(n, ok, why || (ok ? null : `It was “${options[answer]}”.`));
    } }, text));
  });
  waitFoot(n, h('span', { class: 'foot-hint' }, 'Pick one'));
  return h('div', { class: 'stack-lg' },
    audio ? listenControls(audio, title) : h('h1', { class: 'prompt-h', lang: 'en' }, question),
    opts);
}

function listenControls(audio, title) {
  return h('div', { class: 'stack' },
    h('h1', { class: 'prompt-h' }, title || 'What do you hear?'),
    h('div', { class: 'listen-row' },
      h('button', { class: 'btn speak-big tactile', type: 'button', 'aria-label': 'Play it again', onClick: () => say(audio) }, icon('speaker', 36)),
      h('button', { class: 'btn speak-slow tactile', type: 'button', 'aria-label': 'Play it slowly', onClick: () => say(audio, { speed: 'slow' }) }, icon('slow', 26))));
}

function listenStep(ex, n) {
  // Play on arrival: the exercise is the audio, so making the learner tap first is a wasted step.
  setTimeout(() => say(ex.audio, { quiet: true }), 200);
  return choiceStep(ex, n, { options: ex.options, answer: ex.answer,
    why: ex.en ? `“${ex.options[ex.answer]}” means ${ex.en}.` : '', audio: ex.audio });
}

function matchStep(ex, n) {
  const pairFor = Object.fromEntries(ex.pairs.map((p) => [p.de, p.en]));
  let picked = null, solved = 0, wrong = 0;
  const leftCol = h('div', { class: 'match-col' });
  const rightCol = h('div', { class: 'match-col' });
  const all = () => [...leftCol.children, ...rightCol.children];
  const unselect = () => all().forEach((b) => b.classList.remove('sel'));

  function tap(btn, side, value) {
    if (btn.classList.contains('done')) return;
    if (!picked || picked.side === side) {
      unselect();
      picked = { btn, side, value };
      btn.classList.add('sel');
      if (side === 'de') say(value, { quiet: true });
      return;
    }
    const deWord = side === 'de' ? value : picked.value;
    const enWord = side === 'en' ? value : picked.value;
    const other = picked.btn;
    picked = null;
    unselect();
    if (pairFor[deWord] === enWord) {
      for (const b of [btn, other]) { b.classList.add('done', 'hit'); b.disabled = true; }
      haptic(8);
      solved += 1;
      if (solved === ex.pairs.length) verdict(n, wrong === 0, wrong ? `${wrong} mix-up${wrong > 1 ? 's' : ''} on the way.` : 'Every pair first time.');
    } else {
      wrong += 1;
      haptic(25);
      for (const b of [btn, other]) { b.classList.add('miss'); setTimeout(() => b.classList.remove('miss'), 420); }
    }
  }
  for (const word of ex.left) leftCol.append(h('button', { class: 'match-tile tactile', lang: 'de', type: 'button', onClick: (e) => tap(e.currentTarget, 'de', word) }, word));
  for (const word of ex.right) rightCol.append(h('button', { class: 'match-tile tactile en', type: 'button', onClick: (e) => tap(e.currentTarget, 'en', word) }, word));
  waitFoot(n, h('span', { class: 'foot-hint' }, 'Tap a word, then its meaning'));
  return h('div', { class: 'stack-lg' },
    h('h1', { class: 'prompt-h' }, 'Match the pairs'),
    h('div', { class: 'match-grid' }, leftCol, rightCol));
}

function buildStep(ex, n) {
  const slot = h('div', { class: 'build-slot', 'aria-live': 'polite' });
  const bank = h('div', { class: 'build-bank' });
  const chosen = [];
  let done = false;
  const check = h('button', { class: 'btn primary lg tactile grow', type: 'button', disabled: true, onClick: () => {
    if (done || !chosen.length) return;
    done = true;
    const ok = chosen.map((c) => c.word).join(' ') === ex.answer.join(' ');
    slot.classList.add(ok ? 'right' : 'wrong');
    for (const b of [...bank.children, ...slot.children]) b.disabled = true;
    if (!ok) say(ex.answer.join(' '), { quiet: true });
    verdict(n, ok, ok ? null : h('span', {}, 'It was ', de(ex.answer.join(' '), 'strong'), '.'));
  } }, 'Check');
  const sync = () => { check.disabled = done || chosen.length === 0; };

  ex.tiles.forEach((word) => {
    const tile = h('button', { class: 'word-tile tactile', lang: 'de', type: 'button', onClick: () => {
      if (done || tile.classList.contains('used')) return;
      tile.classList.add('used');
      tile.setAttribute('aria-hidden', 'true');
      const placed = h('button', { class: 'word-tile tactile', lang: 'de', type: 'button', onClick: () => {
        if (done) return;
        placed.remove();
        tile.classList.remove('used');
        tile.removeAttribute('aria-hidden');
        chosen.splice(chosen.findIndex((c) => c.el === placed), 1);
        sync();
      } }, word);
      chosen.push({ word, el: placed });
      slot.append(placed);
      haptic(6);
      sync();
    } }, word);
    bank.append(tile);
  });
  if (passed(n)) S.foot.actions(backBtn(n), continueBtn(n));
  else S.foot.actions(backBtn(n), check);
  return h('div', { class: 'stack-lg' },
    h('h1', { class: 'prompt-h' }, 'Build it in German'),
    katzeSays(ex.en, { mood: 'happy', size: 64, sub: ex.hint || null, lang: 'en' }),
    slot, bank,
    passed(n) ? h('div', { class: 'row' }, check) : null);
}

function speakStep(ex, n) {
  const heard = h('p', { class: 'heard', hidden: true, 'aria-live': 'polite' });
  let tries = 0;
  const mic = createHoldToTalk({
    label: 'Tap and say it, or hold',
    onResult: async ({ blob, mime }) => {
      // Every attempt counts: a wrong first try is followed by another one, never ignored.
      tries += 1;
      heard.hidden = false;
      heard.textContent = 'Listening…';
      try {
        const res = await upload('/api/voice/transcribe', blob, audioFilename(mime));
        const said = (res.text || '').trim();
        if (!said) {
          // A silent clip is the microphone's fault, not the learner's: no verdict, try again.
          tries -= 1;
          heard.textContent = 'Nothing was heard in that recording. Check the microphone is not muted, then try again.';
          return;
        }
        heard.textContent = `Heard: “${said}”`;
        const ok = matches(ex.de, said);
        verdict(n, ok, ok ? (tries > 1 ? 'Got it that time.' : null)
          : tries === 1 ? 'Close is fine. Say it once more with the mic, or continue.' : 'Listen once more and try again, or continue.');
      } catch {
        // Never block the lesson on the transcriber: the speaking practice still happened.
        heard.textContent = 'Could not hear that one. Try again, or continue.';
        S.foot.actions(backBtn(n), continueBtn(n));
      }
    },
  });
  waitFoot(n, h('button', { class: 'btn ghost', type: 'button', onClick: () => go(n + 1) }, 'Can’t speak now'));
  return h('div', { class: 'stack-lg' },
    h('h1', { class: 'prompt-h' }, 'Say this out loud'),
    h('div', { class: 'say-card' },
      h('div', { class: 'grow' }, de(ex.de, 'say-de'), h('p', { class: 'line-en' }, ex.en)),
      h('button', { class: 'btn speak-big sm tactile', type: 'button', 'aria-label': 'Hear it', onClick: () => say(ex.de) }, icon('speaker', 28))),
    mic.el, heard);
}

/* Same generous rule as the server (exercises.matches_spoken): a beginner's accent gets misheard
   constantly, and punishing that teaches the learner to stop speaking. The transcriber writes a
   spoken number as digits ("fünf" comes back as "5"), so digits become German words first. */
const ONES = ['null', 'eins', 'zwei', 'drei', 'vier', 'fünf', 'sechs', 'sieben', 'acht', 'neun', 'zehn', 'elf',
  'zwölf', 'dreizehn', 'vierzehn', 'fünfzehn', 'sechzehn', 'siebzehn', 'achtzehn', 'neunzehn'];
const TENS = ['', '', 'zwanzig', 'dreißig', 'vierzig', 'fünfzig', 'sechzig', 'siebzig', 'achtzig', 'neunzig'];
function germanNumber(n) {
  if (n < 20) return ONES[n];
  if (n < 100) { const u = n % 10; return (u ? (u === 1 ? 'ein' : ONES[u]) + 'und' : '') + TENS[Math.floor(n / 10)]; }
  if (n < 1000) { const h = Math.floor(n / 100); return (h === 1 ? '' : ONES[h]) + 'hundert' + (n % 100 ? germanNumber(n % 100) : ''); }
  const k = Math.floor(n / 1000);
  const head = k === 1 ? '' : germanNumber(k).replace(/eins$/, 'ein');
  return head + 'tausend' + (n % 1000 ? germanNumber(n % 1000) : '');
}
function spokenWords(text) {
  return String(text).toLowerCase().replace(/ß/g, 'ss')
    .replace(/(\d)[:.](\d)/g, '$1 $2')
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split(/\s+/).filter(Boolean)
    .map((w) => (/^\d{1,6}$/.test(w) ? germanNumber(Number(w)).replace(/ß/g, 'ss') : w))
    .map((w) => (w === 'eins' ? 'ein' : w));
}
function matches(expected, saidText) {
  const want = spokenWords(expected), got = spokenWords(saidText);
  if (!want.length) return false;
  const pool = [...got];
  let hit = 0;
  for (const w of want) { const i = pool.indexOf(w); if (i > -1) { pool.splice(i, 1); hit += 1; } }
  return hit / want.length >= 0.7;
}

/* ---- the end of a lesson ---------------------------------------------- */
function renderDone() {
  const l = S.lesson || {};
  S.head.set(S.list.length, S.list.length);
  const stats = [[String(S.list.length), 'steps']];
  if (S.asked) stats.push([`${S.right}/${S.asked}`, 'right first time']);
  if (S.finishedFirst) stats.push(['+40', 'XP']);
  S.body.append(h('div', { class: 'finish' },
    h('div', { class: 'finish-cat' }, katze({ variant: me().avatar, mood: 'proud', size: 120 })),
    h('h2', { class: 'finish-h' }, 'Lesson finished'),
    h('p', { class: 'finish-sub' }, l.outro || 'Now use it: the conversation is where it sticks.'),
    statStrip(stats)));
  S.foot.actions(
    h('button', { class: 'btn ghost', type: 'button', onClick: closePlayer }, 'Done'),
    h('button', { class: 'btn primary lg tactile grow', type: 'button', onClick: () => { closePlayer(); window.dtSwitchTo('talk'); } }, 'Practise in Talk'));
}

/* ---- navigation ------------------------------------------------------- */
async function go(n) {
  const total = S.list.length;
  const forward = n > S.i;
  S.i = Math.max(1, Math.min(n, total + 1));
  const first = S.i > S.furthest;
  S.furthest = Math.max(S.furthest, S.i);
  S.finishedFirst = forward && first && S.i > total;
  stopAudio();
  render();
  if (!forward || !first) return;   // going back, or re-walking passed steps, changes nothing stored
  try {
    if (S.i > total) {
      await api(`/api/lesson/${S.unitId}/complete`, { method: 'POST' });
      document.dispatchEvent(new CustomEvent('dt:lesson-done', { detail: S.unitId }));
      api('/api/game/me').then(maybeCelebrate).catch(() => {});
    } else {
      await api(`/api/lesson/${S.unitId}/progress`, { method: 'POST', body: { step: S.i } });
    }
  } catch { /* progress is a convenience; never block the lesson on it */ }
}
