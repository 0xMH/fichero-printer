const CACHE_NAME = "pwa-cache-v1";
const urlsToCache = [
    "/",
    "/index.html",
    "/manifest.json"
];

// install: cache files
self.addEventListener("install", event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
              .then(cache => cache.addAll(urlsToCache))
    );
});

// fetch: serve cached version if offline
self.addEventListener("fetch", event => {
    event.respondWith(
        caches.match(event.request)
              .then(response => response || fetch(event.request))
    );
});