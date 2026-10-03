/* Service worker: caches the shell for offline start-up. Never caches /api/* or itself.
   Bump CACHE_VERSION whenever a shell file changes, or phones keep the old one forever. */
const CACHE_VERSION = 'v11';
const CACHE = `tutor-shell-${CACHE_VERSION}`;
const SHELL = [
  '/', '/index.html', '/styles.css', '/app.js',
  '/js/api.js', '/js/ui.js', '/js/audio.js', '/js/store.js', '/js/mic.js',
  '/js/learn.js', '/js/talk.js', '/js/write.js', '/js/drill.js', '/js/review.js', '/js/progress.js',
  '/js/placement.js', '/js/checkpoint.js',
  '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png', '/icons/apple-touch-icon.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/sw.js') return;   // always live
  // Shell: cache first, so the app opens in a tunnel. A new CACHE_VERSION replaces it wholesale.
  e.respondWith(
    caches.match(e.request, { ignoreSearch: true }).then((hit) => hit || fetch(e.request).then((res) => {
      if (res.ok && SHELL.includes(url.pathname)) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
      }
      return res;
    })),
  );
});
