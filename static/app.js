/* Deutsch Tutor — the shell. Auth gate, tabs, service worker, offline banner.
   Screens live in /js/*.js and expose mount(el) / show() / hide(). */
import { api, setUnauthorizedHandler } from './js/api.js';
import { $, $$, toast, prefs } from './js/ui.js';
import { unlockAudio } from './js/audio.js';
import * as talk from './js/talk.js';
import * as write from './js/write.js';
import * as drill from './js/drill.js';
import * as review from './js/review.js';
import * as progress from './js/progress.js';
import * as placement from './js/placement.js';
import * as checkpoint from './js/checkpoint.js';

const screens = { talk, write, drill, review, progress, placement, checkpoint };
const TABS = ['talk', 'write', 'drill', 'review', 'progress'];
let current = null;
let mounted = false;
let pendingAfterLogin = null;

/* ---- auth gate ------------------------------------------------------ */
function showLogin() {
  $('#login').hidden = false;
  $('#login-error').hidden = true;
  setTimeout(() => $('#pw').focus(), 50);
}

async function onLogin(e) {
  e.preventDefault();
  unlockAudio();
  const err = $('#login-error');
  const btn = $('#login-form button');
  btn.disabled = true;
  err.hidden = true;
  try {
    await api('/api/auth/login', { method: 'POST', body: { password: $('#pw').value } });
    $('#pw').value = '';
    $('#login').hidden = true;
    await showApp();
    if (pendingAfterLogin) { const fn = pendingAfterLogin; pendingAfterLogin = null; fn(); }
  } catch (ex) {
    err.textContent = ex.status === 401 ? 'Wrong password.' : (ex.detail || 'Login failed.');
    err.hidden = false;
  } finally {
    btn.disabled = false;
  }
}

setUnauthorizedHandler(() => {
  // The login overlay sits on top of the current screen, so nothing typed or recorded is lost.
  if (!$('#login').hidden) return;
  if (mounted) toast('Session expired. Log in again.');
  showLogin();
});

/* ---- screens -------------------------------------------------------- */
export function switchTo(name, opts = {}) {
  if (!screens[name]) return;
  if (current && current !== name) screens[current].hide && screens[current].hide();
  for (const sec of $$('.screen')) sec.hidden = sec.id !== `screen-${name}`;
  for (const tab of $$('.tab')) tab.classList.toggle('active', tab.dataset.tab === name);
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
  if (!current || current === 'placement') switchTo(prefs.get('tab', 'talk'));
}

/* ---- boot ----------------------------------------------------------- */
async function boot() {
  $('#login-form').addEventListener('submit', onLogin);
  for (const tab of $$('.tab')) tab.addEventListener('click', () => { unlockAudio(); switchTo(tab.dataset.tab); });
  document.addEventListener('pointerdown', unlockAudio, { once: true, passive: true });

  const offline = $('#offline');
  const sync = () => { offline.hidden = navigator.onLine !== false; };
  window.addEventListener('online', () => { sync(); document.dispatchEvent(new CustomEvent('dt:online')); });
  window.addEventListener('offline', sync);
  sync();

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').then((reg) => {
      reg.addEventListener('updatefound', () => {
        const sw = reg.installing;
        sw && sw.addEventListener('statechange', () => {
          if (sw.state === 'installed' && navigator.serviceWorker.controller) {
            toast('Update ready.', { action: 'Reload', onAction: () => location.reload(), duration: 0 });
          }
        });
      });
    }).catch(() => {});
  }

  try {
    await api('/api/auth/me', { timeout: 8000 });
    await showApp();
  } catch (e) {
    if (e.status === 401) { showLogin(); return; }
    // Offline or server down: open the shell anyway; every call will surface its own error.
    await showApp();
  }
}

boot();
