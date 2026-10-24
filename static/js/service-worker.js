/* Only public resources. No authenticated pages, documents, signatures or writes. */
const CACHE = 'gg-public-v1';
const PUBLIC = new Set(['/offline/', '/static/css/app.css', '/static/js/pwa.js', '/static/icons/icon-192.png', '/static/icons/icon-512.png']);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(Array.from(PUBLIC))));
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('gg-public-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.method === 'POST' && request.mode === 'navigate') {
    // One attempt only; a lost response may follow a committed transaction.
    // Return generic guidance, never manufacture success, cache or replay the POST.
    event.respondWith(fetch(request).catch(() => caches.match('/offline/')));
    return;
  }
  if (request.method !== 'GET') return;
  if (PUBLIC.has(url.pathname) && !url.search) {
    event.respondWith(caches.open(CACHE).then(cache => cache.match(request).then(cached => cached || fetch(request))));
  } else if (request.mode === 'navigate') {
    event.respondWith(fetch(request, {cache: 'no-store'}).catch(() => caches.match('/offline/')));
  } else {
    event.respondWith(fetch(request, {cache: 'no-store'}));
  }
});
