/* Write screen: a task from the current unit, his text, inline corrections, and an improved version
   with the changes highlighted. The draft lives in localStorage until it is submitted, so a 503 or
   an expired cookie never eats a paragraph. */
import { api } from './api.js';
import { h, clear, toast, sheet, errorLine, prefs, spinner, fmtDate, tappableWords } from './ui.js';

const S = { root: null, body: null, task: prefs.get('writeTask', null), result: null, textarea: null, pending: false };

export function mount(el) {
  S.root = el;
  const head = h('header', { class: 'screen-head' }, h('h1', {}, 'Write'),
    h('span', { class: 'grow' }),
    h('button', { class: 'btn small ghost', type: 'button', onClick: () => newTask(true) }, 'New task'));
  S.body = h('div', { class: 'screen-body' });
  clear(el).append(head, S.body);
}

export async function show() {
  if (S.result) return;
  if (S.task) render(); else await newTask();
}
export function hide() {}

async function newTask(confirmDiscard = false) {
  const draft = prefs.get('writeDraft', '');
  if (confirmDiscard && draft && draft.trim() && !S.result) {
    if (!window.confirm('Discard the current draft?')) return;
  }
  S.result = null;
  prefs.set('writeDraft', '');
  clear(S.body).append(spinner('Picking a task…'));
  try {
    S.task = await api('/api/write/prompt', { timeout: 60000 });
    prefs.set('writeTask', S.task);
    render();
  } catch (e) {
    clear(S.body).append(errorLine(e, () => newTask()));
    if (S.task) S.body.append(h('button', { class: 'btn', type: 'button', onClick: render }, 'Use the previous task'));
  }
}

function words(text) { return (text.trim().match(/\S+/g) || []).length; }

function render() {
  const t = S.task;
  clear(S.body);
  const counter = h('span', { class: 'muted small' });
  S.textarea = h('textarea', { class: 'input write-area', rows: '7', placeholder: 'Schreib hier…', autocapitalize: 'sentences',
    onInput: () => { prefs.set('writeDraft', S.textarea.value); update(); } });
  S.textarea.value = prefs.get('writeDraft', '');
  const submit = h('button', { class: 'btn primary block', type: 'button', onClick: submitText }, 'Get feedback');
  const update = () => {
    const n = words(S.textarea.value);
    counter.textContent = `${n} words · aim for ${t.words_min}–${t.words_max}`;
    submit.disabled = n === 0 || S.pending;
  };
  S.body.append(
    h('div', { class: 'card stack task-card' },
      h('div', { class: 'card-title' }, 'Your task'),
      h('p', {}, t.task),
      t.to ? h('p', { class: 'muted small' }, 'To: ', t.to) : null,
      (t.must_include || []).length ? h('div', { class: 'chip-row' }, t.must_include.map((m) => h('span', { class: 'chip small' }, m))) : null),
    S.textarea, h('div', { class: 'row between' }, counter), submit,
    recentSection());
  update();
}

async function submitText() {
  const text = S.textarea.value.trim();
  if (!text || S.pending) return;
  S.pending = true;
  const btn = S.body.querySelector('.btn.primary');
  btn.disabled = true;
  btn.textContent = 'Reading…';
  try {
    S.result = await api('/api/write/submit', { method: 'POST', body: { prompt: S.task.task, text } });
    prefs.set('writeDraft', '');
    renderResult(text, S.result);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Get feedback';
    const line = errorLine(e, submitText);
    btn.before(line);
    setTimeout(() => line.remove(), 15000);
  } finally { S.pending = false; }
}

function renderResult(text, r) {
  clear(S.body);
  const stars = '★'.repeat(r.score || 0) + '☆'.repeat(5 - (r.score || 0));
  S.body.append(
    h('div', { class: 'card stack' },
      h('div', { class: 'row between' }, h('div', { class: 'card-title' }, 'Feedback'), h('span', { class: 'stars' }, stars)),
      r.strengths ? h('p', {}, h('b', {}, 'Good: '), r.strengths) : null,
      r.next_time ? h('p', {}, h('b', {}, 'Next time: '), r.next_time) : null),
    h('div', { class: 'card stack' },
      h('div', { class: 'card-title' }, r.corrections.length ? `Your text · ${r.corrections.length} corrections` : 'Your text · no corrections'),
      h('p', { class: 'write-text' }, markCorrections(text, r.corrections)),
      r.corrections.length ? h('p', { class: 'muted small' }, 'Tap a marked part to see why.') : null),
    r.improved ? h('div', { class: 'card stack' },
      h('div', { class: 'card-title' }, 'One level up'),
      h('p', { class: 'write-text' }, diffWords(text, r.improved)),
      h('p', { class: 'muted small' }, 'Highlighted: what changed. Tap any word to look it up.')) : null,
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => { S.result = null; prefs.set('writeDraft', text); render(); } }, 'Edit & resubmit'),
      h('button', { class: 'btn primary', type: 'button', onClick: () => newTask() }, 'New task')),
    recentSection());
}

/* Wrap each correction's `wrong` span in his text (first unmarked occurrence) in a tappable mark. */
function markCorrections(text, corrections) {
  const frag = document.createDocumentFragment();
  const spans = [];
  for (const c of corrections) {
    if (!c.wrong) continue;
    let from = 0, found = -1;
    while (from <= text.length) {
      const i = text.toLowerCase().indexOf(c.wrong.toLowerCase(), from);
      if (i === -1) break;
      if (!spans.some((s) => i < s.end && i + c.wrong.length > s.start)) { found = i; break; }
      from = i + 1;
    }
    if (found >= 0) spans.push({ start: found, end: found + c.wrong.length, c });
  }
  spans.sort((a, b) => a.start - b.start);
  let pos = 0;
  for (const s of spans) {
    if (s.start > pos) frag.append(document.createTextNode(text.slice(pos, s.start)));
    frag.append(h('mark', { class: 'wrong', role: 'button', tabindex: '0', onClick: () => explain(s.c) }, text.slice(s.start, s.end)));
    pos = s.end;
  }
  if (pos < text.length) frag.append(document.createTextNode(text.slice(pos)));
  const unplaced = corrections.filter((c) => !spans.some((s) => s.c === c));
  if (unplaced.length) {
    frag.append(h('div', { class: 'stack', style: { marginTop: '8px' } }, unplaced.map((c) =>
      h('button', { class: 'btn small ghost', type: 'button', onClick: () => explain(c) }, `“${c.wrong}” → “${c.right}”`))));
  }
  return frag;
}

function explain(c) {
  sheet.open(h('div', { class: 'stack' },
    h('div', { class: 'corr-pair' }, h('s', {}, c.wrong), ' → ', h('b', {}, c.right)),
    h('p', {}, c.explanation || ''),
    c.category ? h('span', { class: 'cat' }, c.category.replace(/_/g, ' ')) : null), { title: 'Correction' });
}

/* Word-level LCS diff: words of `after` that are not in the common subsequence get highlighted. */
function diffWords(before, after) {
  const a = before.split(/\s+/).filter(Boolean), b = after.split(/\s+/).filter(Boolean);
  const norm = (w) => w.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
  const n = a.length, m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) {
    dp[i][j] = norm(a[i]) === norm(b[j]) ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  }
  const keep = new Set();
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (norm(a[i]) === norm(b[j])) { keep.add(j); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) i++;
    else j++;
  }
  const frag = document.createDocumentFragment();
  b.forEach((w, k) => {
    const node = tappableWords(w, (word, sentence) => lookup(word, after));
    frag.append(keep.has(k) ? node : h('mark', { class: 'better' }, node), document.createTextNode(' '));
  });
  return frag;
}

async function lookup(word, sentence) {
  const body = h('div', { class: 'stack' }, spinner('Looking up…'));
  sheet.open(body, { title: word });
  try {
    const d = await api('/api/vocab/translate', { method: 'POST', body: { word, context: sentence }, timeout: 30000 });
    const add = h('button', { class: 'btn primary block', type: 'button', disabled: d.in_vocab, onClick: async () => {
      add.disabled = true;
      try { await api('/api/vocab', { method: 'POST', body: { word: d.lemma || word, translation: d.translation, example: sentence, source: 'manual' } }); add.textContent = 'In your vocab'; }
      catch (e) { add.disabled = false; toast(e.detail || 'Could not add.', { kind: 'err' }); }
    } }, d.in_vocab ? 'In your vocab' : 'Add to vocab');
    clear(body).append(h('div', { class: 'lemma' }, d.lemma || word), h('p', { class: 'translation' }, d.translation), d.note ? h('p', { class: 'muted small' }, d.note) : null, add);
  } catch (e) { clear(body).append(errorLine(e)); }
}

function recentSection() {
  const list = h('div', { class: 'stack' });
  const det = h('details', { class: 'recent' }, h('summary', {}, 'Recent writings'), list);
  det.addEventListener('toggle', async () => {
    if (!det.open || list.childElementCount) return;
    list.append(spinner());
    try {
      const data = await api('/api/write/recent?limit=10');
      clear(list);
      if (!data.items.length) list.append(h('p', { class: 'muted small' }, 'Nothing yet.'));
      for (const w of data.items) {
        list.append(h('button', { class: 'card recent-row', type: 'button', onClick: () => renderResult(w.text, w.feedback || { corrections: [] }) },
          h('div', { class: 'row between' }, h('span', { class: 'small' }, fmtDate(w.created_at)), h('span', { class: 'stars small' }, '★'.repeat(w.score || 0))),
          h('p', { class: 'muted small clamp' }, w.prompt)));
      }
    } catch (e) { clear(list).append(errorLine(e)); }
  });
  return det;
}
