/* Drill screen: eight short items built from his own mistakes, instant feedback per item, no timer.
   Options are big buttons; free-text items get an input and a Check button; "reorder" items whose
   prompt lists the words with " / " become tap-to-build chips. */
import { api } from './api.js';
import { h, clear, toast, errorLine, spinner } from './ui.js';

const S = { root: null, body: null, drill: null, idx: 0, results: [], pending: false };

export function mount(el) {
  S.root = el;
  const head = h('header', { class: 'screen-head' }, h('h1', {}, 'Drill'), h('span', { class: 'grow' }),
    h('button', { class: 'btn small ghost', type: 'button', onClick: () => { S.drill = null; renderIntro(); } }, 'Reset'));
  S.body = h('div', { class: 'screen-body' });
  clear(el).append(head, S.body);
}

export function show() { if (!S.drill) renderIntro(); }
export function hide() {}

function renderIntro(err) {
  clear(S.body).append(h('div', { class: 'card stack' },
    h('h2', {}, 'Quick drill'),
    h('p', { class: 'muted' }, 'Eight items built from your own recent mistakes. About two minutes, no timer. A right answer retires the mistake from the tutor’s list.'),
    err ? errorLine(err, startDrill) : null,
    h('button', { class: 'btn primary block', type: 'button', onClick: startDrill }, 'Start')));
}

async function startDrill() {
  clear(S.body).append(spinner('Building your drill…'));
  try {
    S.drill = await api('/api/drill/new?n=8', { timeout: 90000 });
    S.idx = 0;
    S.results = [];
    renderItem();
  } catch (e) {
    S.drill = null;
    renderIntro(e);
  }
}

function renderItem() {
  const d = S.drill;
  const item = d.items[S.idx];
  if (!item) { renderSummary(); return; }
  clear(S.body);
  const progress = h('div', { class: 'row between muted small' },
    h('span', {}, `${S.idx + 1} of ${d.items.length}`),
    h('span', { class: 'cat' }, (item.category || '').replace(/_/g, ' ')));
  const prompt = h('div', { class: 'card drill-prompt' }, h('p', {}, item.prompt));
  const feedback = h('div', { class: 'stack' });
  S.body.append(progress, prompt, h('p', { class: 'muted small' }, typeHint(item.type)));
  const options = Array.isArray(item.options) ? item.options.filter(Boolean) : [];
  if (options.length) {
    const row = h('div', { class: 'stack drill-options' }, options.map((o) =>
      h('button', { class: 'btn drill-option', type: 'button', onClick: (e) => submit(item, o, row, feedback, e.currentTarget) }, o)));
    S.body.append(row, feedback);
  } else if (item.type === 'reorder' && item.prompt.includes(' / ')) {
    S.body.append(reorderBuilder(item, feedback), feedback);
  } else {
    const input = h('input', { class: 'input', type: 'text', autocapitalize: 'sentences', autocomplete: 'off', enterkeyhint: 'done',
      placeholder: item.type === 'transform' ? 'Write the new sentence…' : 'Your answer…',
      onKeydown: (e) => { if (e.key === 'Enter') { e.preventDefault(); check.click(); } } });
    const check = h('button', { class: 'btn primary block', type: 'button', onClick: () => submit(item, input.value, h('div'), feedback, null, input, check) }, 'Check');
    S.body.append(input, check, feedback);
    setTimeout(() => input.focus(), 50);
  }
}

function typeHint(type) {
  return { fill_blank: 'Fill the gap.', choose: 'Pick the right one.', reorder: 'Put the words in order.', transform: 'Rewrite the sentence as asked.' }[type] || '';
}

function reorderBuilder(item, feedback) {
  const after = item.prompt.split(':').slice(1).join(':') || item.prompt;
  const tokens = after.split(' / ').map((t) => t.trim().replace(/[.?!]$/, '')).filter(Boolean);
  const chosen = [];
  const built = h('div', { class: 'card reorder-built' }, h('span', { class: 'muted' }, 'Tap the words in order'));
  const pool = h('div', { class: 'chip-row wrap' });
  const check = h('button', { class: 'btn primary block', type: 'button', disabled: true,
    onClick: () => submit(item, chosen.join(' '), pool, feedback, null, null, check) }, 'Check');
  const refresh = () => { clear(built); built.append(chosen.length ? chosen.join(' ') : h('span', { class: 'muted' }, 'Tap the words in order')); check.disabled = !chosen.length; };
  for (const tok of tokens) {
    const chip = h('button', { class: 'chip', type: 'button', onClick: () => {
      if (chip.classList.contains('used')) { chip.classList.remove('used'); chosen.splice(chosen.indexOf(tok), 1); }
      else { chip.classList.add('used'); chosen.push(tok); }
      refresh();
    } }, tok);
    pool.append(chip);
  }
  return h('div', { class: 'stack' }, built, pool, check);
}

async function submit(item, answer, optionsEl, feedback, clickedBtn, input, checkBtn) {
  if (S.pending) return;
  const given = String(answer || '').trim();
  if (!given) { toast('Type an answer first.'); return; }
  S.pending = true;
  for (const b of optionsEl.querySelectorAll('button')) b.disabled = true;
  if (checkBtn) { checkBtn.disabled = true; checkBtn.textContent = 'Checking…'; }
  if (input) input.disabled = true;
  try {
    const r = await api(`/api/drill/${S.drill.id}/answer`, { method: 'POST', body: { index: item.index, answer: given }, timeout: 60000 });
    S.results[S.idx] = r;
    if (clickedBtn) clickedBtn.classList.add(r.correct ? 'right' : 'wrong');
    clear(feedback).append(
      h('div', { class: `card feedback ${r.correct ? 'right' : 'wrong'}` },
        h('p', { class: 'feedback-head' }, r.correct ? '✓ Right' : '✗ Not quite'),
        r.correct ? null : h('p', {}, h('b', {}, r.answer)),
        r.explanation ? h('p', { class: 'muted small' }, r.explanation) : null),
      h('button', { class: 'btn primary block', type: 'button', onClick: () => { S.idx += 1; renderItem(); } }, S.idx + 1 < S.drill.items.length ? 'Next' : 'Finish'));
    feedback.querySelector('.btn').focus();
  } catch (e) {
    for (const b of optionsEl.querySelectorAll('button')) b.disabled = false;
    if (checkBtn) { checkBtn.disabled = false; checkBtn.textContent = 'Check'; }
    if (input) input.disabled = false;
    if (e.status === 404) { S.drill = null; renderIntro(e); return; }
    clear(feedback).append(errorLine(e, () => submit(item, answer, optionsEl, feedback, clickedBtn, input, checkBtn)));
  } finally { S.pending = false; }
}

function renderSummary() {
  const total = S.drill.items.length;
  const right = S.results.filter((r) => r && r.correct).length;
  clear(S.body).append(h('div', { class: 'card stack center' },
    h('h2', {}, `${right} / ${total}`),
    h('p', { class: 'muted' }, right === total ? 'Clean sheet. Those mistakes are on their way out.' : 'Every right answer retires a mistake a little further.'),
    h('div', { class: 'chip-row', style: { justifyContent: 'center' } }, (S.drill.categories || []).map((c) => h('span', { class: 'chip small' }, c.replace(/_/g, ' ')))),
    h('button', { class: 'btn primary block', type: 'button', onClick: startDrill }, 'Another drill'),
    h('button', { class: 'btn ghost block', type: 'button', onClick: () => window.dtSwitchTo('talk') }, 'Back to talking')));
  S.drill = null;
}
