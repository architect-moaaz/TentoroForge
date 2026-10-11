/* The application's service worker — the SHELL only, never the data.
 *
 * Installed, the app opens from the home screen and still opens with no
 * network: the offline page, the manifest and the icons are kept from
 * install, and built assets (`/_next/static/…`, fingerprinted, immutable)
 * are kept as they are first fetched. Nothing else is: a page's HTML and
 * every `/api/**` answer carry a person's records, scoped to who asked,
 * and a cache that served one person's answer to another — or yesterday's
 * answer today — would be a leak and a lie. Navigations go to the network
 * first and fall back to the offline page only when it cannot be reached.
 *
 * BASE is the path the app is served under (empty at the root; the preview's
 * prefix behind the platform), SHELL what install keeps — both filled in by
 * the Blueprint projection (project_pwa); edit the Blueprint, not this file.
 */
const BASE = "__BASE__";
const VERSION = "__VERSION__";
const SHELL = __SHELL__;
const CACHE = `forge-shell-${VERSION}`;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

/** Built assets are fingerprinted: once fetched they never change. */
function isStatic(url) {
  return url.pathname.startsWith(`${BASE}/_next/static/`);
}

/** A person's data, never kept: every API answer, and anything not a GET. */
function isData(request, url) {
  return request.method !== "GET" || url.pathname.startsWith(`${BASE}/api/`);
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || isData(request, url)) return;
  if (isStatic(url)) {
    event.respondWith(
      caches.match(request).then((hit) => hit || fetch(request).then((res) => {
        if (res.ok) caches.open(CACHE).then((c) => c.put(request, res.clone()));
        return res;
      })),
    );
    return;
  }
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request).catch(() => caches.match(`${BASE}/offline`).then((hit) => hit || Response.error())),
    );
    return;
  }
  if (SHELL.includes(url.pathname)) {
    event.respondWith(caches.match(request).then((hit) => hit || fetch(request)));
  }
});

/** A push from the application: shown as it was sent, opened where it points. */
self.addEventListener("push", (event) => {
  let data = { title: "Notification", body: "", link: null };
  try { data = { ...data, ...event.data.json() }; } catch { if (event.data) data.body = event.data.text(); }
  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body, icon: `${BASE}/icons/icon-192.png`, badge: `${BASE}/icons/icon-192.png`,
    data: { link: data.link }, tag: data.tag || undefined,
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const link = (event.notification.data && event.notification.data.link) || `${BASE}/`;
  const target = link.startsWith("http") ? link : `${self.location.origin}${link.startsWith(BASE) ? "" : BASE}${link}`;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    for (const w of wins) { if ("focus" in w) { w.navigate(target); return w.focus(); } }
    return self.clients.openWindow(target);
  }));
});
