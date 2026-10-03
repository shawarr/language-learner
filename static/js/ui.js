/* Tiny DOM helpers. No framework: `h()` builds elements, `toast()` and `sheet` are the two global
   surfaces every screen uses. Numbers and motion follow docs/DESIGN.md. */
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'html') el.innerHTML = v;   // only for trusted, app-generated markup
    else if (typeof v === 'boolean') { if (v) el.setAttribute(k, ''); if (k in el) el[k] = v; }
    else el.setAttribute(k, v);
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }

/* German text: lang="de" so screen readers and the OS pronounce it right (DESIGN.md §8). */
export function de(text, cls = '') { return h('span', { lang: 'de', class: cls }, text); }

/* Haptics: Android only, iOS ignores it. 12 ms mic press, 20 ms send, 10 ms rating — nothing else. */
export function haptic(ms) { try { if (navigator.vibrate) navigator.vibrate(ms); } catch { /* not available */ } }

/* ---- toast ------------------------------------------------------------- */
let toastTimer = null;
export function toast(message, { action, onAction, duration = 3500, kind = '' } = {}) {
  const root = $('#toast-root');
  clear(root);
  const dismiss = () => { el.remove(); };
  const el = h('div', { class: `toast ${kind}`, role: 'status' }, h('span', {}, message));
  if (action) el.append(h('button', { class: 'toast-action', type: 'button', onClick: () => { dismiss(); onAction && onAction(); } }, action));
  root.append(el);
  clearTimeout(toastTimer);
  if (duration > 0) toastTimer = setTimeout(dismiss, duration);
  return dismiss;
}

/* A human sentence for an ApiError, with a retry button that actually retries. */
export function errorText(err) {
  if (!err) return 'Something went wrong.';
  if (err.offline) return err.detail || 'You are offline.';
  if (err.status === 429 || err.status === 503) return 'The tutor is busy — try again in a minute.';
  return err.detail || err.message || 'Something went wrong.';
}
export function errorLine(err, retry) {
  const el = h('div', { class: 'error-line', role: 'alert' }, h('span', {}, errorText(err)));
  if (retry) el.append(h('button', { class: 'btn small', type: 'button', onClick: retry }, 'Retry'));
  return el;
}

/* Loading placeholders shaped like the content, instead of a spinner as the primary content. */
export function skeleton(rows = 3, { tall = false } = {}) {
  const widths = ['w80', 'w60', 'w40', 'w80', 'w60'];
  return h('div', { class: 'skeleton', 'aria-hidden': 'true' },
    Array.from({ length: rows }, (_, i) => h('i', { class: tall ? 'tall' : widths[i % widths.length] })));
}

export function spinner(label = 'Loading…') {
  return h('div', { class: 'spinner-row' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), h('span', {}, label));
}

/* Category chip: one hue per mistake category, everywhere. */
export function catChip(category) {
  const slug = String(category || 'other');
  return h('span', { class: 'cat', style: { '--cat-color': `var(--cat-${slug}, var(--cat-other))` } }, slug.replace(/_/g, ' '));
}

/* ---- bottom sheet ------------------------------------------------------ */
export const sheet = {
  open(content, { title } = {}) {
    this.close();
    const root = $('#sheet-root');
    const panel = h('div', { class: 'sheet', role: 'dialog', 'aria-modal': 'true' },
      h('div', { class: 'sheet-grip', 'aria-hidden': 'true' }),
      title ? h('h2', { class: 'sheet-title' }, title) : null,
      h('div', { class: 'sheet-body' }, content));
    const back = h('div', { class: 'sheet-backdrop', onClick: () => this.close() }, panel);
    panel.addEventListener('click', (e) => e.stopPropagation());
    this._drag(panel);
    root.append(back);
    requestAnimationFrame(() => back.classList.add('open'));
    document.body.classList.add('sheet-open');
    this._el = back;
    return panel;
  },
  /* Drag down to dismiss, like a native sheet. Only when the sheet itself is scrolled to the top. */
  _drag(panel) {
    let y0 = null, dy = 0;
    panel.addEventListener('pointerdown', (e) => { if (panel.scrollTop > 0) return; y0 = e.clientY; dy = 0; });
    panel.addEventListener('pointermove', (e) => {
      if (y0 == null) return;
      dy = Math.max(0, e.clientY - y0);
      if (dy > 6) { panel.classList.add('dragging'); panel.style.transform = `translateY(${dy}px)`; }
    });
    const end = () => {
      if (y0 == null) return;
      panel.classList.remove('dragging');
      if (dy > 80) this.close(); else panel.style.transform = '';
      y0 = null;
    };
    panel.addEventListener('pointerup', end);
    panel.addEventListener('pointercancel', end);
  },
  close() {
    const el = this._el;
    if (!el) return;
    this._el = null;
    el.classList.remove('open');
    document.body.classList.remove('sheet-open');
    setTimeout(() => el.remove(), 200);
  },
  get isOpen() { return !!this._el; },
};

/* ---- small formatters -------------------------------------------------- */
export function fmtDate(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}
export function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}
export function fmtDays(days) {
  if (days == null) return '';
  if (days < 0.04) return 'in 10 min';
  if (days < 1) return 'in a day';
  const d = Math.round(days);
  if (d < 30) return `in ${d} day${d === 1 ? '' : 's'}`;
  if (d < 365) return `in ${Math.round(d / 30)} mo`;
  return `in ${(d / 365).toFixed(1)} y`;
}
export function plural(n, one, many) { return `${n} ${n === 1 ? one : many || one + 's'}`; }

/* Persisted per-device preferences (never anything the server needs to know). */
export const prefs = {
  get(key, fallback) {
    try { const v = localStorage.getItem(`dt:${key}`); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(`dt:${key}`, JSON.stringify(value)); } catch { /* private mode */ } },
};

/* Split German text into tappable word spans (lang="de"). Tap targets are whole words; punctuation
   is stripped for the lookup but displayed as typed. */
export function tappableWords(text, onTap) {
  const frag = h('span', { lang: 'de' });
  const parts = String(text).split(/(\s+)/);
  for (const part of parts) {
    if (!part) continue;
    if (/^\s+$/.test(part)) { frag.append(document.createTextNode(part)); continue; }
    const core = part.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '');
    if (!core) { frag.append(document.createTextNode(part)); continue; }
    frag.append(h('span', { class: 'word', role: 'button', tabindex: '0',
      onClick: () => onTap(core, text),
      onKeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onTap(core, text); } } }, part));
  }
  return frag;
}

/* Animated expand/collapse of a panel whose CSS sets height: 0 + transition. */
export function setExpanded(toggle, panel, open) {
  toggle.setAttribute('aria-expanded', String(open));
  if (open) {
    panel.hidden = false;
    panel.style.height = panel.scrollHeight + 'px';
    const done = () => { panel.style.height = 'auto'; panel.removeEventListener('transitionend', done); };
    panel.addEventListener('transitionend', done);
  } else {
    panel.style.height = panel.scrollHeight + 'px';
    requestAnimationFrame(() => { panel.style.height = '0px'; });
  }
}
