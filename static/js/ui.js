/* Tiny DOM helpers. No framework: `h()` builds elements, `toast()` and `sheet` are the two global
   surfaces every screen uses. Everything is keyboard- and thumb-friendly by construction. */
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

/* ---- toast ------------------------------------------------------------- */
let toastTimer = null;
export function toast(message, { action, onAction, duration = 3500, kind = '' } = {}) {
  const root = $('#toast-root');
  clear(root);
  const el = h('div', { class: `toast ${kind}`, role: 'status' }, h('span', {}, message));
  if (action) el.append(h('button', { class: 'toast-action', type: 'button', onClick: () => { dismiss(); onAction && onAction(); } }, action));
  root.append(el);
  clearTimeout(toastTimer);
  const dismiss = () => { el.remove(); };
  if (duration > 0) toastTimer = setTimeout(dismiss, duration);
  return dismiss;
}

/* A friendly line for an ApiError, with a retry button when it makes sense. */
export function errorLine(err, retry) {
  const msg = err && err.retryable && err.status === 503
    ? 'The tutor is busy. Try again in a minute.'
    : (err && (err.detail || err.message)) || 'Something went wrong.';
  const el = h('div', { class: 'error-line', role: 'alert' }, h('span', {}, msg));
  if (retry) el.append(h('button', { class: 'btn small', type: 'button', onClick: retry }, 'Retry'));
  return el;
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
    root.append(back);
    requestAnimationFrame(() => back.classList.add('open'));
    document.body.classList.add('sheet-open');
    this._el = back;
    return panel;
  },
  close() {
    if (this._el) { this._el.remove(); this._el = null; }
    document.body.classList.remove('sheet-open');
  },
  get isOpen() { return !!this._el; },
};

/* ---- small formatters -------------------------------------------------- */
export function fmtDate(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}
export function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}
export function plural(n, one, many) { return `${n} ${n === 1 ? one : many || one + 's'}`; }

export function spinner(label = 'Loading…') {
  return h('div', { class: 'spinner-row' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), h('span', {}, label));
}

/* Persisted per-device preferences (never anything the server needs to know). */
export const prefs = {
  get(key, fallback) {
    try { const v = localStorage.getItem(`dt:${key}`); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(`dt:${key}`, JSON.stringify(value)); } catch { /* private mode */ } },
};

/* Split a German sentence into tappable word spans. Tap targets are words, not letters. */
export function tappableWords(text, onTap) {
  const frag = document.createDocumentFragment();
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
