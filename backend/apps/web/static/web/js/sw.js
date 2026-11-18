/* JETPOS service worker — uygulama kabuğunu önbellekler; API çağrıları önbelleğe alınmaz.
   Ağ yokken sipariş işlemleri IndexedDB kuyruğunda (core.js) bekler ve "mutfağa ulaştı" gösterilmez. */
const CACHE = "jetpos-shell-v3";
const SHELL = ["/waiter", "/static/web/app.css", "/static/web/js/core.js", "/static/web/js/i18n_en.js", "/static/web/js/ui.js", "/static/web/js/pages_pos.js",
  "/static/web/js/pages_mgmt.js", "/static/web/js/pages_admin.js", "/static/web/js/app.js", "/static/web/img/icon.svg",
  "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => Promise.all(SHELL.map((u) => c.add(u).catch(() => null)))).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/") || url.pathname.startsWith("/admin")) return;
  if (url.pathname.startsWith("/static/")) {
    // Önce ağ (güncellemeler hemen gelir), ağ yoksa önbellek (offline çalışma)
    e.respondWith(fetch(e.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); }
      return res;
    }).catch(() => caches.match(e.request)));
    return;
  }
  if (e.request.mode === "navigate") {
    e.respondWith(fetch(e.request).then((res) => {
      if (res.ok && !res.redirected) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(url.pathname, copy)); }
      return res;
    }).catch(() => caches.match(url.pathname).then((hit) => hit || caches.match("/waiter"))));
  }
});
