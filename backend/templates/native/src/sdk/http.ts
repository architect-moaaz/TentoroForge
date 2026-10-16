// The app SDK (native) — the one HTTP client, with `fetch` and the cookie jar
// handed in. api.ts builds the real one (react-native's fetch, secure storage);
// the tests build one over a fake server, so the sign-in sequence, the 401
// rule and the cookie handling are exercised without a device.
//
// WHAT EVERY CALL DOES, so no screen has to:
//   - goes to the app's address (base URL + base path),
//   - carries the session: the jar's `Cookie` header, or the platform's own jar
//     when ours is empty (`credentials: "include"`) — never both, so one copy,
//   - reads `Set-Cookie` off the answer into the jar (the session, the CSRF
//     token, the guest token a first workflow run mints),
//   - turns a 401 that is not part of signing in into a `signed-out` signal,
//   - never throws on the network: `json()` says `networkError` instead, so a
//     screen shows a sentence rather than a red box.
//
// PURE — no react-native import.

import { CookieJar } from "./cookies";

export type FetchLike = (url: string, init?: RequestInit) => Promise<Response>;

export interface ClientOptions {
  /** `https://app.example.com` — no trailing slash needed. */
  baseUrl: string;
  /** The app's base path (empty for a published app; a preview serves under one). */
  basePath?: string;
  fetch: FetchLike;
  jar: CookieJar;
  /** The jar changed: persist it. */
  onJarChange?: () => void;
  /** A call outside `/api/auth/` was answered 401. */
  onSignedOut?: () => void;
}

/** What `json()` answers: never a throw. `body` is the parsed JSON (null when
 *  the answer was not JSON), `networkError` a sentence when no answer came. */
export interface ApiResult<T> {
  ok: boolean;
  status: number;
  body: T | null;
  networkError: string | null;
}

export interface JsonInit {
  method?: string;
  /** Sent as JSON. */
  body?: unknown;
  /** Sent as `application/x-www-form-urlencoded` (next-auth's sign-in wants it). */
  form?: Record<string, string>;
  headers?: Record<string, string>;
}

export interface Client {
  readonly jar: CookieJar;
  /** The absolute address of an app path (`/api/read/list`). */
  url(path: string): string;
  /** The raw call — for a body that is not JSON (an upload). */
  request(path: string, init?: RequestInit): Promise<Response>;
  json<T = Record<string, unknown>>(path: string, init?: JsonInit): Promise<ApiResult<T>>;
}

/** `a=1&b=x%20y` — URLSearchParams is not complete on every engine, this is. */
function formEncode(fields: Record<string, string>): string {
  return Object.entries(fields).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
}

/** The cookies a response set, however the engine exposes them: a list where
 *  `getSetCookie` exists, else the one joined header. */
function setCookiesOf(res: Response): string | string[] | null {
  const h = res.headers as Headers & { getSetCookie?: () => string[] };
  const list = typeof h.getSetCookie === "function" ? h.getSetCookie() : [];
  return list.length ? list : h.get("set-cookie");
}

export function createClient(opts: ClientOptions): Client {
  const base = opts.baseUrl.replace(/\/+$/, "") + (opts.basePath ?? "").replace(/\/+$/, "");
  const url = (path: string) => `${base}${path.startsWith("/") ? path : `/${path}`}`;

  async function request(path: string, init: RequestInit = {}): Promise<Response> {
    const target = url(path);
    const headers = new Headers(init.headers);
    if (!headers.has("Accept")) headers.set("Accept", "application/json");
    const cookie = opts.jar.header(target);
    if (cookie) headers.set("Cookie", cookie);
    // One copy of the cookies: ours when we hold any, the platform's when not.
    const res = await opts.fetch(target, { ...init, headers, credentials: opts.jar.size ? "omit" : "include" });
    if (opts.jar.absorb(setCookiesOf(res))) opts.onJarChange?.();
    if (res.status === 401 && !path.startsWith("/api/auth/")) opts.onSignedOut?.();
    return res;
  }

  async function json<T>(path: string, init: JsonInit = {}): Promise<ApiResult<T>> {
    const headers: Record<string, string> = { ...(init.headers ?? {}) };
    let body: string | undefined;
    if (init.form) {
      headers["Content-Type"] = "application/x-www-form-urlencoded";
      body = formEncode(init.form);
    } else if (init.body !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(init.body);
    }
    try {
      const res = await request(path, { method: init.method ?? (body === undefined ? "GET" : "POST"), headers, body });
      const text = await res.text();
      let parsed: unknown = null;
      try { parsed = text ? JSON.parse(text) : null; } catch { parsed = null; }
      return { ok: res.ok, status: res.status, body: parsed as T | null, networkError: null };
    } catch (err) {
      const why = err instanceof Error && err.message ? ` (${err.message})` : "";
      return { ok: false, status: 0, body: null,
               networkError: `The app could not be reached${why}. Check the connection and try again.` };
    }
  }

  return { jar: opts.jar, url, request, json };
}
