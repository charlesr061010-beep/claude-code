/* Moonshot service worker: lets the game load offline once it has been
   opened, and picks up new versions in the background (stale-while-revalidate).
   Bump VERSION when the file list changes. */
const VERSION = 'moonshot-v3';
const SHELL = [
  './',
  'index.html',
  'assets/style.css',
  'assets/app.js',
  'data/moonshot-data.js',
  'manifest.webmanifest',
  'assets/icons/icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== self.location.origin) return;
  event.respondWith((async () => {
    const cache = await caches.open(VERSION);
    const hit = await cache.match(req, { ignoreSearch: true });
    const fresh = fetch(req).then((res) => {
      if (res.ok) cache.put(req, res.clone());
      return res;
    });
    if (hit) {
      event.waitUntil(fresh.catch(() => undefined)); // refresh the cache for next time
      return hit;
    }
    return fresh;
  })());
});
