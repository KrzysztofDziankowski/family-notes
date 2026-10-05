{% autoescape off %}/*
 * FamilyNotes service worker (S-06).
 *
 * A minimal shell for installability and an offline fallback page. It never
 * stores family data: non-GET requests are ignored (they go straight to the
 * network), navigations are network-only with the precached offline page as
 * the fallback, and nothing is written to the cache at runtime. The cache
 * holds only the explicit precache list below.
 */
'use strict';

var CACHE_NAME = {{ cache_name|safe }};
var CACHE_PREFIX = {{ cache_prefix|safe }};
var OFFLINE_URL = {{ offline_url|safe }};
var PRECACHE_URLS = {{ precache_urls|safe }};

self.addEventListener('install', function (event) {
    event.waitUntil(
        caches.open(CACHE_NAME).then(function (cache) {
            // Anonymous, uncached fetches: the offline page is never personal.
            return cache.addAll(PRECACHE_URLS.map(function (url) {
                return new Request(url, {cache: 'reload', credentials: 'omit'});
            }));
        }).then(function () {
            return self.skipWaiting();
        })
    );
});

self.addEventListener('activate', function (event) {
    event.waitUntil(
        caches.keys().then(function (names) {
            return Promise.all(names.filter(function (name) {
                return name.indexOf(CACHE_PREFIX) === 0 && name !== CACHE_NAME;
            }).map(function (name) {
                return caches.delete(name);
            }));
        }).then(function () {
            return self.clients.claim();
        })
    );
});

function fromCache(url) {
    return caches.open(CACHE_NAME).then(function (cache) {
        return cache.match(url);
    }).then(function (response) {
        return response || Response.error();
    });
}

self.addEventListener('fetch', function (event) {
    var request = event.request;
    if (request.method !== 'GET') {
        // Form posts (classification, saves, sign-in) bypass the worker.
        return;
    }
    if (request.mode === 'navigate') {
        // The network response is returned as-is and never stored.
        event.respondWith(fetch(request).catch(function () {
            return fromCache(OFFLINE_URL);
        }));
        return;
    }
    var url = new URL(request.url);
    if (url.origin !== self.location.origin || PRECACHE_URLS.indexOf(url.pathname) === -1) {
        return;
    }
    event.respondWith(fetch(request).catch(function () {
        return fromCache(url.pathname);
    }));
});
{% endautoescape %}
