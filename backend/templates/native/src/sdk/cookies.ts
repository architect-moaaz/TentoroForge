// The app SDK (native) — the cookie jar.
//
// THE APP'S SESSION IS A COOKIE (next-auth's), the same one a browser holds.
// A phone's HTTP stack keeps cookies for us on most platforms — but "most" is
// the problem: a cookie the platform drops (an Android build with the jar
// turned off, a simulator that resets it, a `Secure` cookie on a dev server
// over http) looks exactly like being signed out, and the only sign is a 401
// on the next call. So the SDK also keeps its own copy: it reads `Set-Cookie`
// off every response, remembers what it was told, and sends it back as a
// `Cookie` header. When the jar holds cookies, the platform's jar is told to
// stay out of it (`credentials: "omit"`, see http.ts), so there is only ever
// ONE copy and it cannot go stale in two places.
//
// PURE — no react-native import — so parsing, merging and expiry run under
// plain node in the template's tests. Persistence is the caller's: `toJSON` /
// `CookieJar.fromJSON`, written to secure storage by api.ts.

export interface StoredCookie {
  name: string;
  value: string;
  /** Where it applies; "/" when the server said nothing. */
  path: string;
  /** Sent only over https (a `Secure` cookie, as the browser does). */
  secure: boolean;
  /** Epoch milliseconds, or null for a session cookie. */
  expires: number | null;
}

/** The cookie a signed-out visitor is given on the first thing they do: what a
 *  cart they filled before signing in is theirs by. Sign-out keeps it. */
export const GUEST_COOKIE = "forge-guest";

/** One response header can carry several cookies, joined by commas — and a
 *  cookie's own `Expires=Wed, 21 Oct …` has a comma too. Split only on a comma
 *  that starts a NEW `name=value`. */
export function splitSetCookie(header: string | null | undefined): string[] {
  if (!header) return [];
  return header.split(/,(?=\s*[^;,=\s]+=)/).map((s) => s.trim()).filter(Boolean);
}

/** One `Set-Cookie` line as a stored cookie, or null when it is not a cookie.
 *  `Max-Age` wins over `Expires`, as it does in a browser; either one in the
 *  past makes the cookie a deletion. */
export function parseSetCookie(line: string, now: number = Date.now()): StoredCookie | null {
  const parts = line.split(";").map((p) => p.trim());
  const first = parts.shift() ?? "";
  const eq = first.indexOf("=");
  if (eq <= 0) return null;
  const cookie: StoredCookie = {
    name: first.slice(0, eq).trim(), value: first.slice(eq + 1).trim(),
    path: "/", secure: false, expires: null,
  };
  let maxAge: number | null = null;
  for (const attr of parts) {
    const i = attr.indexOf("=");
    const key = (i < 0 ? attr : attr.slice(0, i)).trim().toLowerCase();
    const val = i < 0 ? "" : attr.slice(i + 1).trim();
    if (key === "path" && val.startsWith("/")) cookie.path = val;
    else if (key === "secure") cookie.secure = true;
    else if (key === "max-age") { const n = Number(val); if (Number.isFinite(n)) maxAge = n; }
    else if (key === "expires") { const t = Date.parse(val); if (Number.isFinite(t)) cookie.expires = t; }
  }
  if (maxAge !== null) cookie.expires = now + maxAge * 1000;
  return cookie;
}

/** Does a cookie scoped to `cookiePath` apply to a request for `requestPath`? */
function pathMatches(cookiePath: string, requestPath: string): boolean {
  if (cookiePath === "/" || requestPath === cookiePath) return true;
  return requestPath.startsWith(cookiePath.endsWith("/") ? cookiePath : `${cookiePath}/`);
}

export class CookieJar {
  private cookies = new Map<string, StoredCookie>();
  private now: () => number;

  constructor(initial: StoredCookie[] = [], now: () => number = Date.now) {
    this.now = now;
    for (const c of initial) this.cookies.set(this.key(c), c);
    this.sweep();
  }

  private key(c: { name: string; path: string }): string { return `${c.name}|${c.path}`; }

  /** Drop what has expired. */
  private sweep(): void {
    const t = this.now();
    for (const [k, c] of this.cookies) if (c.expires !== null && c.expires <= t) this.cookies.delete(k);
  }

  /** Take in what a response said: each `Set-Cookie` line, or the one joined
   *  header. Returns whether the jar changed — the caller persists then. */
  absorb(lines: string | string[] | null | undefined): boolean {
    const all = Array.isArray(lines) ? lines.flatMap(splitSetCookie) : splitSetCookie(lines);
    let changed = false;
    for (const line of all) {
      const c = parseSetCookie(line, this.now());
      if (!c) continue;
      const k = this.key(c);
      if (c.expires !== null && c.expires <= this.now()) {
        changed = this.cookies.delete(k) || changed;
      } else {
        const before = this.cookies.get(k);
        if (!before || before.value !== c.value || before.expires !== c.expires) changed = true;
        this.cookies.set(k, c);
      }
    }
    return changed;
  }

  /** The `Cookie` header for a request to `url`; "" when none apply. A `Secure`
   *  cookie is sent only over https. */
  header(url: string): string {
    this.sweep();
    const m = url.match(/^(https?):\/\/[^/?#]+([^?#]*)/i);
    if (!m) return "";
    const https = m[1].toLowerCase() === "https";
    const path = m[2] || "/";
    return [...this.cookies.values()]
      .filter((c) => (https || !c.secure) && pathMatches(c.path, path))
      .sort((a, b) => b.path.length - a.path.length)
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
  }

  get(name: string): string | null {
    this.sweep();
    for (const c of this.cookies.values()) if (c.name === name) return c.value;
    return null;
  }

  get size(): number { this.sweep(); return this.cookies.size; }

  /** Forget everything, or everything but the named cookies (sign-out keeps
   *  the guest token: it is the visitor's, not the account's). */
  clear(keep: string[] = []): void {
    for (const [k, c] of this.cookies) if (!keep.includes(c.name)) this.cookies.delete(k);
  }

  toJSON(): string {
    this.sweep();
    return JSON.stringify([...this.cookies.values()]);
  }

  /** Take in the text `toJSON()` wrote (what was saved on the last run); text
   *  that is not that is ignored. Cookies already held win over saved ones, so
   *  a sign-in that finished while the saved jar was still being read is kept. */
  load(text: string | null | undefined): void {
    try {
      const raw = JSON.parse(text ?? "[]") as unknown;
      if (!Array.isArray(raw)) return;
      for (const c of raw as Partial<StoredCookie>[]) {
        if (!c || typeof c.name !== "string" || typeof c.value !== "string") continue;
        const cookie: StoredCookie = {
          name: c.name, value: c.value, path: typeof c.path === "string" ? c.path : "/",
          secure: Boolean(c.secure), expires: typeof c.expires === "number" ? c.expires : null,
        };
        if (!this.cookies.has(this.key(cookie))) this.cookies.set(this.key(cookie), cookie);
      }
      this.sweep();
    } catch {
      /* unreadable: start empty */
    }
  }
}

// ---------------------------------------------------------------------------
// Chunked storage. A session token that carries the person's profile can be a
// few kilobytes, and secure storage is sized for small secrets. The jar's text
// is cut into pieces under one key each and joined on the way back.
// ---------------------------------------------------------------------------

export interface KeyValue {
  get(key: string): Promise<string | null>;
  set(key: string, value: string): Promise<void>;
  remove(key: string): Promise<void>;
}

export interface ChunkedStore {
  read(): Promise<string | null>;
  write(text: string): Promise<void>;
  remove(): Promise<void>;
}

export function chunkedStore(kv: KeyValue, name: string, size = 1800): ChunkedStore {
  const countKey = `${name}.n`;
  const partKey = (i: number) => `${name}.${i}`;
  const count = async (): Promise<number> => {
    const n = Number(await kv.get(countKey));
    return Number.isInteger(n) && n > 0 ? n : 0;
  };
  return {
    async read() {
      const n = await count();
      if (!n) return null;
      let out = "";
      for (let i = 0; i < n; i++) {
        const part = await kv.get(partKey(i));
        if (part === null) return null; // a torn write reads as nothing, not as half a jar
        out += part;
      }
      return out;
    },
    async write(text) {
      const before = await count();
      const parts: string[] = [];
      for (let i = 0; i < text.length; i += size) parts.push(text.slice(i, i + size));
      // Parts first, the count last: a write that dies half way keeps the old count.
      for (let i = 0; i < parts.length; i++) await kv.set(partKey(i), parts[i]);
      await kv.set(countKey, String(parts.length));
      for (let i = parts.length; i < before; i++) await kv.remove(partKey(i));
    },
    async remove() {
      const n = await count();
      await kv.remove(countKey);
      for (let i = 0; i < n; i++) await kv.remove(partKey(i));
    },
  };
}
