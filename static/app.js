/* Deutsch Tutor — the shell. Login picker, tabs, service worker, offline banner.
   Screens live in /js/*.js and expose mount(el) / show() / hide().

   Two learners can share a phone, so everything this device remembers (drafts, the unsent-recording
   queue, offline ratings, toggles) is keyed by user id. Modules read some of it at import time, so a
   login that changes who is using the device reloads the page once with the new id in place. */
import { api, setUnauthorizedHandler } from './js/api.js';
import { $, $$, h, clear, toast, prefs, currentUid, setCurrentUid } from './js/ui.js';
import { unlockAudio } from './js/audio.js';
import { katze } from './js/katze.js';
import * as home from './js/home.js';
import * as learn from './js/learn.js';
import * as talk from './js/talk.js';
import * as practice from './js/practice.js';
import * as you from './js/you.js';
import * as review from './js/review.js';
import * as drill from './js/drill.js';
import * as write from './js/write.js';
import * as placement from './js/placement.js';
import * as checkpoint from './js/checkpoint.js';

const screens = { home, learn, talk, practice, you, review, drill, write, placement, checkpoint };
const TABS = ['home', 'learn', 'talk', 'practice', 'you'];
// Screens reached from a tab keep that tab lit, so the bar always says where you are.
const PARENT = { review: 'practice', drill: 'practice', write: 'practice', checkpoint: 'you', placement: 'you' };
let current = null;
let mounted = false;
let picked = null;

/* ---- login picker --------------------------------------------------- */
async function showLogin({ keep = false } = {}) {
  $('#login').hidden = false;
  $('#login-error').hidden = true;
  clear($('#login-cat')).append(katze({ mood: 'proud', size: 96, label: 'Katze, the app’s cat' }));
  let list = [];
  try { list = (await api('/api/auth/users', { timeout: 8000 })).users || []; } catch { /* offline: the form still works for the last user */ }
  const box = clear($('#login-users'));
  const last = prefs.global('lastUser', null);
  for (const u of list) {
    const btn = h('button', { class: 'login-user', type: 'button', 'aria-pressed': 'false', dataset: { username: u.username } },
      katze({ variant: u.avatar, size: 72 }), h('span', { class: 'login-name' }, u.name));
    btn.addEventListener('click', () => pick(u));
    box.append(btn);
  }
  const preselect = keep && window.dtUser ? list.find((u) => u.id === window.dtUser.id) : list.find((u) => u.username === last);
  if (preselect) pick(preselect, false);
}

function pick(user, focus = true) {
  picked = user;
  for (const b of $$('.login-user')) b.setAttribute('aria-pressed', String(b.dataset.username === user.username));
  $('#login-form').hidden = false;
  $('#login-username').value = user.username;
  $('#pw-label').textContent = `Password for ${user.name}`;
  $('#login-error').hidden = true;
  if (focus) setTimeout(() => $('#pw').focus(), 30);
}

async function onLogin(e) {
  e.preventDefault();
  if (!picked) return;
  unlockAudio();
  const err = $('#login-error');
  const btn = $('#login-form button');
  btn.disabled = true;
  err.hidden = true;
  try {
    const r = await api('/api/auth/login', { method: 'POST', body: { username: picked.username, password: $('#pw').value } });
    $('#pw').value = '';
    prefs.setGlobal('lastUser', r.user.username);
    if (String(r.user.id) !== currentUid()) {
      // A different person on this device: start clean so nothing of the previous user lingers.
      setCurrentUid(r.user.id);
      location.reload();
      return;
    }
    window.dtUser = r.user;
    $('#login').hidden = true;
    await showApp();
  } catch (ex) {
    err.textContent = ex.status === 401 ? 'Wrong password.' : (ex.detail || 'Login failed.');
    err.hidden = false;
  } finally {
    btn.disabled = false;
  }
}

setUnauthorizedHandler(() => {
  // The picker sits on top of the current screen, so nothing typed or recorded is lost.
  if (!$('#login').hidden) return;
  if (mounted) toast('Session expired. Log in again.');
  showLogin({ keep: true });
});

/* ---- screens -------------------------------------------------------- */
export function switchTo(name, opts = {}) {
  if (!screens[name]) return;
  if (current && current !== name) screens[current].hide && screens[current].hide();
  // A session's focus mode (tab bar aside) belongs to the screen that set it; the next one decides.
  $('#app').classList.remove('focus');
  if (current && current !== name) window.dtBack = current;
  for (const sec of $$('.screen')) {
    const on = sec.id === `screen-${name}`;
    if (on && sec.hidden) { sec.classList.remove('enter'); void sec.offsetWidth; sec.classList.add('enter'); }
    sec.hidden = !on;
  }
  const lit = PARENT[name] || name;
  const at = TABS.indexOf(lit);
  $('#tabs').style.setProperty('--at', String(Math.max(0, at)));
  for (const tab of $$('.tab')) {
    const on = tab.dataset.tab === lit;
    tab.classList.toggle('active', on);
    if (on) tab.setAttribute('aria-current', 'page'); else tab.removeAttribute('aria-current');
  }
  current = name;
  if (TABS.includes(name)) prefs.set('tab', name);
  screens[name].show && screens[name].show(opts);
}
window.dtSwitchTo = switchTo;   // screens navigate through this without importing app.js (no cycle)

async function showApp() {
  $('#app').hidden = false;
  if (!mounted) {
    mounted = true;
    for (const name of Object.keys(screens)) screens[name].mount($(`#screen-${name}`));
  }
  // First launch: the placement flow takes over until it is done or skipped.
  const gated = await placement.gate().catch(() => false);
  if (gated) { switchTo('placement'); return; }
  if (!current || current === 'placement') switchTo('home');
}

/* ---- boot ----------------------------------------------------------- */
async function boot() {
  $('#login-form').addEventListener('submit', onLogin);
  for (const tab of $$('.tab')) tab.addEventListener('click', () => { unlockAudio(); switchTo(tab.dataset.tab); });
  document.addEventListener('dt:go-tab', (e) => switchTo(e.detail));
  document.addEventListener('pointerdown', unlockAudio, { once: true, passive: true });
  // iOS Safari only applies :active press states when the page listens for touches; without this
  // every button's press feedback silently does nothing, which is what made taps feel dead.
  document.addEventListener('touchstart', () => {}, { passive: true });

  // iOS keeps the layout viewport under the keyboard; size #app to the visual viewport so the
  // composer stays glued above the keys and the last message stays visible (DESIGN.md §3).
  // When the keyboard goes, everything must return exactly: iOS fires its last resize mid-animation
  // and can leave the page scrolled, which left the shell short and the tab bar floating above a
  // gap. So: re-measure after the keyboard settles, never size the shell when no keyboard is up
  // (CSS `inset: 0` does that), and scroll the window back to the top.
  const vv = window.visualViewport;
  const app = $('#app');
  const editing = () => {
    const a = document.activeElement;
    return !!a && (a.tagName === 'TEXTAREA' || (a.tagName === 'INPUT' && !/^(button|checkbox|radio|range|submit)$/.test(a.type)) || a.isContentEditable);
  };
  const coarse = window.matchMedia('(pointer: coarse)').matches;
  let wasKeyboard = false;
  const syncViewport = () => {
    const kb = vv ? Math.max(0, window.innerHeight - vv.height - vv.offsetTop) : 0;
    const sized = kb > 80;
    // Android resizes the layout viewport itself (interactive-widget=resizes-content), so there the
    // keyboard shows up only as a focused field.
    const keyboard = sized || (coarse && editing());
    app.style.height = sized ? `${vv.height}px` : '';
    app.style.top = sized ? `${vv.offsetTop}px` : '';
    app.style.bottom = sized ? 'auto' : '';
    if (keyboard !== wasKeyboard) {
      wasKeyboard = keyboard;
      app.classList.toggle('keyboard', keyboard);
      document.dispatchEvent(new CustomEvent('dt:viewport', { detail: { keyboard } }));
    }
    if (!sized && (window.scrollY || document.documentElement.scrollTop)) window.scrollTo(0, 0);
  };
  const settle = () => { syncViewport(); for (const ms of [60, 250, 500, 900]) setTimeout(syncViewport, ms); };
  if (vv) { vv.addEventListener('resize', syncViewport); vv.addEventListener('scroll', syncViewport); }
  window.addEventListener('resize', settle);
  window.addEventListener('orientationchange', settle);
  window.addEventListener('pageshow', settle);
  document.addEventListener('focusin', settle);
  // Not at once on blur: tapping Send blurs the field first, and moving the layout under the finger
  // in that instant made the tap miss. The keyboard animation takes about this long anyway.
  document.addEventListener('focusout', () => { for (const ms of [250, 500, 900]) setTimeout(syncViewport, ms); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) settle(); });

  const offline = $('#offline');
  const sync = () => { offline.hidden = navigator.onLine !== false; };
  window.addEventListener('online', () => { sync(); document.dispatchEvent(new CustomEvent('dt:online')); });
  window.addEventListener('offline', sync);
  sync();

  if ('serviceWorker' in navigator) {
    // When a new version takes over, reload once: this page's modules are the old version, and
    // mixing them with new ones is how screens broke after an update.
    const hadController = !!navigator.serviceWorker.controller;
    let reloading = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (!hadController || reloading) return;
      reloading = true;
      location.reload();
    });
    navigator.serviceWorker.register('/sw.js').then((reg) => reg.update().catch(() => {})).catch(() => {});
  }

  try {
    const me = await api('/api/auth/me', { timeout: 8000 });
    window.dtUser = me.user;
    if (String(me.user.id) !== currentUid()) { setCurrentUid(me.user.id); location.reload(); return; }
    await showApp();
  } catch (e) {
    if (e.status === 401) { showLogin(); return; }
    // Offline or server down: open the shell for the last user; every call surfaces its own error.
    window.dtUser = prefs.get('me', null);
    await showApp();
  }
  if (window.dtUser) prefs.set('me', window.dtUser);
}

boot();
