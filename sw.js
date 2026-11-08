"use strict";

const prefix = `artifact:${self.registration.scope}:`;
const shell = `${prefix}shell-v1`;
const archives = `${prefix}archives-v1`;
const core = [
  "./index.html", "./style.css", "./app.js", "./manifest.json", "./assets/icons/icon.svg",
  "./assets/icons/icon-192.png", "./assets/icons/icon-512.png", "./assets/icons/maskable-512.png",
];
const root = new URL(self.registration.scope);
const file = (path) => new URL(path, root).href;

async function cached(cacheName, request) {
  const response = await (await caches.open(cacheName)).match(request);
  if (!response || cacheName !== archives) return response;
  return new Response(response.body, {
    headers: { "Content-Type": "application/json", "X-Artifact-Cached": "1" },
  });
}

async function networkFirst(request, cacheName, fallback = request) {
  try {
    const response = await fetch(request, { signal: AbortSignal.timeout(6500), cache: "no-cache" });
    if (response.ok && (cacheName !== archives || response.headers.get("content-type")?.includes("json"))) {
      try {
        const cache = await caches.open(cacheName);
        await cache.put(fallback, response.clone());
      } catch {
        // The online response still works if browser storage is full.
      }
      return response;
    }
    return (await cached(cacheName, fallback)) || response;
  } catch {
    return (await cached(cacheName, fallback)) || Response.error();
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(shell);
    await cache.addAll(core.map(file));
    try {
      const index = await networkFirst(file("./data/index.json"), archives);
      const latest = (await index.json()).dates?.[0];
      if (typeof latest === "string" && /^\d{4}-\d{2}-\d{2}$/.test(latest)) {
        await networkFirst(file(`./data/archive/${latest}.json`), archives);
      }
    } catch {
      // Install the app shell even when the archive is unavailable.
    }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) {
      if (key.startsWith(prefix) && key !== shell && key !== archives) await caches.delete(key);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || !event.request.url.startsWith(root.href)) return;
  const relative = new URL(event.request.url).pathname.slice(root.pathname.length);
  if (event.request.mode === "navigate" && (relative === "" || relative === "index.html")) {
    event.respondWith(networkFirst(event.request, shell, file("./index.html")));
  } else if (relative === "data/index.json" || /^data\/archive\/\d{4}-\d{2}-\d{2}\.json$/.test(relative)) {
    event.respondWith(networkFirst(event.request, archives));
  } else if (core.includes(`./${relative}`)) {
    event.respondWith(networkFirst(event.request, shell, file(`./${relative}`)));
  }
});
