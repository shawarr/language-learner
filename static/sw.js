/* Service worker: keeps the shell for offline start-up. Never caches /api/* or itself.

   Network first: online, every shell file comes from the server (revalidated, so usually a 304), and
   the cache is only the fallback for a tunnel. Cache-first mixed versions after an update — new
   modules next to old ones, which is what broke the Talk screen on an iPhone. Install downloads with
   cache: 'reload' so the browser's own HTTP cache cannot slip an old file into a new version.
   Still bump CACHE_VERSION with each release, so the old cache is dropped. */
const CACHE_VERSION = 'v13-one-piece-audio';
const CACHE = `tutor-shell-${CACHE_VERSION}`;
const SHELL = [
  '/', '/index.html', '/styles.css', '/app.js', '/js/api.js', '/js/ui.js', '/js/audio.js',
  '/js/store.js', '/js/mic.js', '/js/learn.js', '/js/talk.js', '/js/write.js', '/js/drill.js',
  '/js/review.js', '/js/progress.js', '/js/placement.js', '/js/checkpoint.js',
  '/manifest.webmanifest', '/icons/icon-192.png', '/icons/icon-512.png',
  '/icons/apple-touch-icon.png', '/js/home.js', '/js/katze.js', '/js/moment.js', '/js/practice.js',
  '/js/rings.js', '/js/you.js', '/js/icons.js', '/js/kit.js',
  '/fonts/instrument-sans-latin.woff2', '/fonts/instrument-sans-latin-ext.woff2', '/fonts/instrument-serif-latin.woff2'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE)
    .then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: 'reload' }))))
    .then(() => self.skipWaiting()));
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
  e.respondWith(fromNetwork(e.request, url).catch(() =>
    caches.match(e.request, { ignoreSearch: true }).then((hit) => hit || Response.error())));
});

/* The network, with a time limit so a dead connection falls back to the cache quickly. */
function fromNetwork(request, url) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('slow')), 4000);
    fetch(request, { cache: 'no-cache' }).then((res) => {
      clearTimeout(timer);
      if (res.ok && (SHELL.includes(url.pathname) || url.pathname === '/')) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(request, copy));
      }
      resolve(res);
    }, (err) => { clearTimeout(timer); reject(err); });
  });
}
