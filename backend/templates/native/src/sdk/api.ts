// The app SDK (native) — the connection to the generated app's own API.
//
// THE APP IS THE BACKEND. A native screen never reaches a database: it calls the
// same HTTP routes the web pages' own code calls (`/api/read/*`,
// `/api/workflows/<id>/execute`, `/api/files/upload`, `/api/auth/*`), signed in
// with the same next-auth cookie. Rules, access and workflows stay single-sourced.
//
// WHERE THE APP IS: `EXPO_PUBLIC_APP_URL` (set per EAS build profile, or in a
// local `.env`) wins, else `extra.appUrl` of app.json (the deployed URL the
// scaffold wrote). The base path (`EXPO_PUBLIC_BASE_PATH`, empty for a published
// app; a preview is served under one) is the web SDK's `apiPath` prefix.
//
// THE COOKIES are kept in secure storage (the keychain / keystore) so a
// restart is still signed in. See cookies.ts for why the SDK keeps its own jar
// beside the platform's.
//
// `apiFetch` is the raw call (a `Response`); `apiJson` never throws and never
// hands a screen a stack trace. Most screens use the hooks (`useList`,
// `useWorkflow`) and never touch either.

import Constants from "expo-constants";
import * as SecureStore from "expo-secure-store";
import { CookieJar, chunkedStore, type KeyValue } from "./cookies";
import { createClient, type ApiResult, type Client, type JsonInit } from "./http";
import { signedOut } from "./events";

/** A configured value, or "": the scaffold leaves `__DEPLOYED_URL__` in place
 *  until the app is deployed, and that is not an address. */
function configured(value: unknown): string {
  const s = typeof value === "string" ? value.trim() : "";
  return s && !s.startsWith("__") ? s : "";
}

const extra = (Constants.expoConfig?.extra ?? {}) as Record<string, unknown>;

/** The deployed app's origin (no trailing slash), or "" when none is configured. */
const APP_URL: string = (configured(process.env.EXPO_PUBLIC_APP_URL) || configured(extra.appUrl)).replace(/\/+$/, "");

/** The app's base path ("" for a published app). */
const BASE_PATH: string = configured(process.env.EXPO_PUBLIC_BASE_PATH).replace(/\/+$/, "");

/** False until the app knows where its backend is — the login screen says so. */
export const appConfigured: boolean = APP_URL !== "";

/** Secure storage as the jar's key-value store. A platform without it (the web
 *  preview) just does not persist: every call is guarded. */
const secure: KeyValue = {
  async get(key) { try { return await SecureStore.getItemAsync(key); } catch { return null; } },
  async set(key, value) { try { await SecureStore.setItemAsync(key, value); } catch { /* not persisted */ } },
  async remove(key) { try { await SecureStore.deleteItemAsync(key); } catch { /* nothing to remove */ } },
};
const store = chunkedStore(secure, "forge.jar");

export const jar = new CookieJar();

// Writes are queued: two changes close together must land in order.
let writing: Promise<unknown> = Promise.resolve();
function persist(): void {
  const text = jar.toJSON();
  writing = writing.then(() => (jar.size ? store.write(text) : store.remove())).catch(() => undefined);
}

const raw = createClient({
  baseUrl: APP_URL,
  basePath: BASE_PATH,
  fetch: (url, init) => fetch(url, init),
  jar,
  onJarChange: persist,
  onSignedOut: () => signedOut.emit(),
});

let restoring: Promise<void> | null = null;

/** Read the saved cookies into the jar, once. Every call below waits for it, so
 *  the first request of a launch carries the session. */
export function restoreCookies(): Promise<void> {
  restoring ??= store.read().then((text) => { jar.load(text); });
  return restoring;
}

/** The client the protocol functions (signin.ts, reads.ts, run.ts) take: the
 *  connection above, every call waiting for the saved cookies first. */
export const client: Client = {
  jar,
  url: raw.url,
  async request(path, init) { await restoreCookies(); return raw.request(path, init); },
  async json<T>(path: string, init?: JsonInit) { await restoreCookies(); return raw.json<T>(path, init); },
};

/** The raw call, `credentials` and cookies handled. `path` is the app's: "/api/…". */
export function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return client.request(path, init);
}

/** A JSON call that never throws: see `ApiResult`. */
export function apiJson<T = Record<string, unknown>>(path: string, init?: JsonInit): Promise<ApiResult<T>> {
  return client.json<T>(path, init);
}

/** The absolute address of an app path — an image's `uri`, a link to open. */
export function appUrl(path: string): string {
  return raw.url(path);
}

/** The `Cookie` header for an address — for a request the platform makes on its
 *  own (an `<Image>` loading a stored file) that has no jar of ours. */
export function cookieHeaderFor(url: string): string {
  return jar.header(url);
}
