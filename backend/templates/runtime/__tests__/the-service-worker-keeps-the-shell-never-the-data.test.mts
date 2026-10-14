/**
 * The SHIPPED pwa/sw.js, run under a stand-in worker global: the shell is
 * kept at install; built assets are served from the cache once fetched; an
 * API answer and anything that is not a GET are never touched; a navigation
 * goes to the network first and falls back to the offline page; a push is
 * shown as sent and opens where it points.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { ok, eqJson, done } from "./_harness.mts";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pwa/sw.js"), "utf8")
  .replaceAll("__BASE__", "").replaceAll("__VERSION__", "v1").replaceAll("__SHELL__", JSON.stringify(["/offline", "/manifest.webmanifest", "/icons/icon-192.png"]));

const handlers: Record<string, (e: any) => void> = {};
const store = new Map<string, any>();
const cacheApi = {
  async open() { return { async addAll(keys: string[]) { keys.forEach((k) => store.set(k, { url: k, cached: true })); }, async put(req: any, res: any) { store.set(typeof req === "string" ? req : req.url, res); } }; },
  async match(req: any) { const k = typeof req === "string" ? req : req.url; return store.get(k) ?? store.get(new URL(k, "http://app.test").pathname); },
  async keys() { return ["forge-shell-old"]; }, async delete() { return true; },
};
let online = true;
const fetched: string[] = [];
const shown: any[] = [];
const self: any = {
  addEventListener: (name: string, fn: any) => { handlers[name] = fn; },
  skipWaiting: async () => {}, clients: { claim: async () => {}, matchAll: async () => [], openWindow: async (u: string) => { shown.push({ opened: u }); } },
  registration: { showNotification: async (title: string, opts: any) => { shown.push({ title, ...opts }); } },
  location: { origin: "http://app.test" },
};
(globalThis as any).self = self;
(globalThis as any).caches = cacheApi;
(globalThis as any).fetch = async (req: any) => {
  const url = typeof req === "string" ? req : req.url;
  fetched.push(url);
  if (!online) throw new Error("offline");
  return { ok: true, url, clone() { return { ...this }; } };
};
new Function("self", "caches", "fetch", "Response", src)(self, cacheApi, (globalThis as any).fetch, { error: () => ({ error: true }) });

ok(handlers.install && handlers.activate && handlers.fetch && handlers.push && handlers.notificationclick, "every listener is installed");

await handlers.install({ waitUntil: (p: Promise<any>) => p });
await new Promise((r) => setTimeout(r, 0));
ok(store.has("/offline") && store.has("/manifest.webmanifest") && store.has("/icons/icon-192.png"), "install keeps the shell");

function go(method: string, path: string, mode = "cors") {
  let responded: any = null;
  const req = { method, url: "http://app.test" + path, mode };
  handlers.fetch({ request: req, respondWith: (p: any) => { responded = p; } });
  return responded;
}
ok(go("GET", "/api/data/orders") === null, "an API answer is never handled");
ok(go("POST", "/api/workflows/execute/x") === null, "nothing but a GET is handled");
ok(go("GET", "/orders", "navigate") !== null, "a navigation is handled");
fetched.length = 0;
const nav = go("GET", "/orders", "navigate");
await nav;
eqJson(fetched, ["http://app.test/orders"], "a navigation goes to the network first");
online = false;
const fallback = await go("GET", "/orders", "navigate");
ok(fallback && fallback.url === "/offline", "offline, a navigation gets the offline page");
online = true;
await go("GET", "/_next/static/chunks/a.js");
await new Promise((r) => setTimeout(r, 0));
fetched.length = 0;
const again = await go("GET", "/_next/static/chunks/a.js");
ok(again && fetched.length === 0, "a built asset is served from the cache the second time");
ok(!store.has("http://app.test/orders") && ![...store.keys()].some((k) => String(k).includes("/api/")), "no page and no API answer was ever cached");

await handlers.push({ data: { json: () => ({ title: "Shift change", body: "You are on at 6", link: "/shifts/1" }) }, waitUntil: (p: any) => p });
await new Promise((r) => setTimeout(r, 0));
eqJson({ title: shown[0].title, body: shown[0].body, link: shown[0].data.link }, { title: "Shift change", body: "You are on at 6", link: "/shifts/1" }, "a push is shown as sent");
await handlers.notificationclick({ notification: { close() {}, data: { link: "/shifts/1" } }, waitUntil: (p: any) => p });
await new Promise((r) => setTimeout(r, 0));
eqJson(shown.at(-1), { opened: "http://app.test/shifts/1" }, "a tap opens where the message points");
done();
