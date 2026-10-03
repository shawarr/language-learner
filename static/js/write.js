/* Write screen (docs/DESIGN.md §5): the task pinned at the top (collapsible), a generous textarea,
   a live word count against the target. On submit his text is re-rendered with the wrong spans
   underlined in amber — tapping one reveals the explanation inline — and the improved version sits
   below with the changed words highlighted. The draft is saved on every keystroke. */
import { api } from './api.js';
import { h, clear, toast, sheet, errorLine, prefs, skeleton, fmtDate, tappableWords, catChip, setExpanded } from './ui.js';

const S = { body: null, task: prefs.get('writeTask', null), result: null, textarea: null, pending: false };

export function mount(el) {
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
  clear(S.body).append(h('div', { class: 'card' }, skeleton(3)), skeleton(1, { tall: true }));
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

function taskCard(t, open = true) {
  const panel = h('div', { class: 'corr-panel', hidden: !open, style: { height: open ? 'auto' : '0px' } },
    h('div', { class: 'stack', style: { paddingTop: '8px' } },
      h('p', {}, t.task),
      t.to ? h('p', { class: 'muted small' }, 'To: ', t.to) : null,
      (t.must_include || []).length ? h('div', { class: 'chip-row wrap' }, t.must_include.map((m) => h('span', { class: 'chip small' }, m))) : null,
      h('p', { class: 'muted xs' }, `${t.words_min}–${t.words_max} words`)));
  const toggle = h('button', { class: 'task-toggle', type: 'button', 'aria-expanded': String(open),
    onClick: () => setExpanded(toggle, panel, toggle.getAttribute('aria-expanded') !== 'true') },
    h('span', { class: 'card-title' }, 'Your task'), h('span', { class: 'muted xs' }, 'show / hide'));
  return h('div', { class: 'card task-card' }, toggle, panel);
}

function render() {
  const t = S.task;
  clear(S.body);
  const counter = h('span', { class: 'muted xs' });
  S.textarea = h('textarea', { class: 'input write-area', rows: '8', placeholder: 'Schreib hier…', autocapitalize: 'sentences', lang: 'de', 'aria-label': 'Your text',
    onInput: () => { prefs.set('writeDraft', S.textarea.value); update(); } });
  S.textarea.value = prefs.get('writeDraft', '');
  const submit = h('button', { class: 'btn primary block', type: 'button', onClick: submitText }, 'Get feedback');
  const update = () => {
    const n = words(S.textarea.value);
    counter.textContent = `${n} words · aim for ${t.words_min}–${t.words_max}`;
    submit.disabled = n === 0 || S.pending;
  };
  S.body.append(taskCard(t, true), S.textarea, h('div', { class: 'row between' }, counter), submit, recentSection());
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
  const corrections = r.corrections || [];
  const stars = '★'.repeat(r.score || 0) + '☆'.repeat(5 - (r.score || 0));
  const expl = h('div', { class: 'stack' });
  S.body.append(
    h('div', { class: 'card stack' },
      h('div', { class: 'row between' }, h('div', { class: 'card-title' }, 'Feedback'), h('span', { class: 'stars', 'aria-label': `${r.score} of 5` }, stars)),
      r.strengths ? h('p', {}, h('b', {}, 'Good: '), r.strengths) : null,
      r.next_time ? h('p', {}, h('b', {}, 'Next time: '), r.next_time) : null),
    h('div', { class: 'card stack' },
      h('div', { class: 'card-title' }, corrections.length ? `Your text · ${corrections.length} to look at` : 'Your text · nothing to correct'),
      h('p', { class: 'write-text', lang: 'de' }, markCorrections(text, corrections, expl)),
      expl,
      corrections.length ? h('p', { class: 'muted xs' }, 'Tap an underlined part to see why.') : null),
    r.improved ? h('div', { class: 'card stack' },
      h('div', { class: 'card-title' }, 'One level up'),
      h('p', { class: 'write-text', lang: 'de' }, diffWords(text, r.improved)),
      h('p', { class: 'muted xs' }, 'Highlighted: what changed. Tap any word to look it up.')) : null,
    h('div', { class: 'btn-row' },
      h('button', { class: 'btn', type: 'button', onClick: () => { S.result = null; prefs.set('writeDraft', text); render(); } }, 'Edit & resubmit'),
      h('button', { class: 'btn primary', type: 'button', onClick: () => newTask() }, 'New task')),
    recentSection());
}

/* Wrap each correction's `wrong` span (first unmarked occurrence) in a tappable amber mark; the
   explanation opens inline under the text, one at a time. */
function markCorrections(text, corrections, explEl) {
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
  let openMark = null;
  const explain = (mark, c) => {
    const same = openMark === mark;
    if (openMark) openMark.classList.remove('open');
    clear(explEl);
    openMark = null;
    if (same) return;
    openMark = mark;
    mark.classList.add('open');
    explEl.append(h('div', { class: 'inline-expl' },
      h('div', { class: 'corr-pair', lang: 'de' }, h('s', {}, c.wrong), ' → ', h('b', {}, c.right)),
      h('div', { class: 'corr-expl' }, h('span', {}, c.explanation || ''), catChip(c.category))));
  };
  for (const s of spans) {
    if (s.start > pos) frag.append(document.createTextNode(text.slice(pos, s.start)));
    const mark = h('mark', { class: 'wrong', role: 'button', tabindex: '0', 'aria-label': `Correction: ${s.c.right}` }, text.slice(s.start, s.end));
    mark.addEventListener('click', () => explain(mark, s.c));
    mark.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); explain(mark, s.c); } });
    frag.append(mark);
    pos = s.end;
  }
  if (pos < text.length) frag.append(document.createTextNode(text.slice(pos)));
  const unplaced = corrections.filter((c) => !spans.some((s) => s.c === c));
  if (unplaced.length) {
    frag.append(h('div', { class: 'chip-row wrap', style: { marginTop: '8px' } }, unplaced.map((c) => {
      const chip = h('button', { class: 'chip small', type: 'button', lang: 'de' }, `${c.wrong} → ${c.right}`);
      chip.addEventListener('click', () => explain(chip, c));
      return chip;
    })));
  }
  return frag;
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
    const node = tappableWords(w, (word) => lookup(word, after));
    frag.append(keep.has(k) ? node : h('mark', { class: 'better' }, node), document.createTextNode(' '));
  });
  return frag;
}

async function lookup(word, sentence) {
  const lemma = h('div', { class: 'lemma', lang: 'de' }, word);
  const tr = h('p', { class: 'translation' }, '');
  const note = h('p', { class: 'lookup-note' }, 'looking up…');
  const add = h('button', { class: 'btn primary block', type: 'button', disabled: true }, 'Add to vocab');
  sheet.open(h('div', { class: 'stack' }, lemma, tr, note, add), { title: null });
  try {
    const d = await api('/api/vocab/translate', { method: 'POST', body: { word, context: sentence }, timeout: 30000 });
    lemma.textContent = d.lemma || word; tr.textContent = d.translation || '—'; note.textContent = d.note || '';
    add.disabled = !!d.in_vocab; add.textContent = d.in_vocab ? 'In your deck' : 'Add to vocab';
    add.addEventListener('click', async () => {
      add.disabled = true;
      try { await api('/api/vocab', { method: 'POST', body: { word: d.lemma || word, translation: d.translation, example: sentence, source: 'manual' } }); add.textContent = 'In your deck'; }
      catch (e) { add.disabled = false; toast(e.detail || 'Could not add.', { kind: 'err' }); }
    });
  } catch (e) { clear(note).append(errorLine(e)); }
}

function recentSection() {
  const list = h('div', { class: 'stack' });
  const det = h('details', { class: 'recent' }, h('summary', {}, 'Recent writings'), list);
  det.addEventListener('toggle', async () => {
    if (!det.open || list.childElementCount) return;
    list.append(skeleton(3, { tall: true }));
    try {
      const data = await api('/api/write/recent?limit=10');
      clear(list);
      if (!data.items.length) list.append(h('p', { class: 'muted small' }, 'Nothing yet. Your first piece lands here.'));
      for (const w of data.items) {
        list.append(h('button', { class: 'card recent-row', type: 'button', onClick: () => renderResult(w.text, w.feedback || { corrections: [] }) },
          h('div', { class: 'row between' }, h('span', { class: 'small' }, fmtDate(w.created_at)), h('span', { class: 'stars small' }, '★'.repeat(w.score || 0))),
          h('p', { class: 'muted small clamp' }, w.prompt)));
      }
    } catch (e) { clear(list).append(errorLine(e)); }
  });
  return det;
}
