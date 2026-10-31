/**
 * Who a signed-out visitor is, for the assistant's usage limits. Forge runtime — do not remove.
 *
 * A public assistant answers people who have no account, on the app owner's model key, so a visitor has to be counted
 * like anyone else. Two things identify one, and both are used (limits.ts counts each):
 *
 *   - the guest cookie, `forge-guest`: the same one the app's workflows and data engine already give a signed-out
 *     visitor (a random id, httpOnly, sameSite lax). Minted here on the first message if the visitor has none. A
 *     visitor can throw it away, which is why it is not the only key,
 *   - the address the request came from, which they cannot throw away.
 *
 * THE ADDRESS IS READ FROM THE PROXY IN FRONT OF THE APP, NEVER TRUSTED FROM THE CLIENT. A client can send any
 * `X-Forwarded-For` it likes, and a proxy adds the address it saw to the END of that list, so the first entries
 * are the client's to forge. The entry the app's own proxy added is the last one (`FORGE_PROXY_HOPS` says how many
 * proxies the app has in a row; 1 when unset). With no such header there is no address key, only the cookie: an
 * app that is not behind a proxy cannot tell visitors apart by address, and guessing would limit every visitor
 * as one.
 */

export const GUEST_COOKIE = "forge-guest";
const GUEST_ID = /(?:^|;\s*)forge-guest=([0-9a-f-]{36})(?:;|$)/;
const ADDRESS = /^[0-9a-f:.]{2,45}$/;

/** What identifies a visitor to the limits. */
export interface VisitorId {
  guest?: string | null;
  ip?: string | null;
}

/** The guest id in a `Cookie` header, or null. */
export function guestFromCookie(cookie: string | null | undefined): string | null {
  return GUEST_ID.exec(cookie ?? "")?.[1] ?? null;
}

type HeaderSource = { get(name: string): string | null };

/** The address the app's own proxy saw, or null when there is no proxy header to read it from. */
export function clientIp(headers: HeaderSource, env: Record<string, string | undefined> = process.env): string | null {
  const hops = Math.max(1, Math.floor(Number(env.FORGE_PROXY_HOPS)) || 1);
  const chain = (headers.get("x-forwarded-for") ?? "").split(",").map((s) => s.trim()).filter(Boolean);
  const seen = chain.length ? chain[Math.max(0, chain.length - hops)] : (headers.get("x-real-ip") ?? "").trim();
  const ip = seen.toLowerCase();
  return ADDRESS.test(ip) ? ip : null;
}

/** The keys a visitor's usage is counted under: one per thing that identifies them. Empty when nothing does. */
export function visitorKeys(v: VisitorId): string[] {
  const keys: string[] = [];
  if (v.guest) keys.push(`guest:${v.guest}`);
  if (v.ip) keys.push(`ip:${v.ip}`);
  return keys;
}

export interface Visitor extends VisitorId {
  guest: string;
  /** A `Set-Cookie` header value when the visitor had no guest cookie and was just given one; otherwise null. */
  setCookie: string | null;
}

/** The visitor behind a request: their guest id (made now if they have none) and the address their request came from. */
export function visitorOf(req: Request, env: Record<string, string | undefined> = process.env): Visitor {
  const had = guestFromCookie(req.headers.get("cookie"));
  const guest = had ?? globalThis.crypto.randomUUID();
  const secure = new URL(req.url).protocol === "https:" || req.headers.get("x-forwarded-proto") === "https" || Boolean(env.VERCEL);
  return {
    guest,
    ip: clientIp(req.headers, env),
    // The same attributes the app's other guest cookie carries (90 days).
    setCookie: had ? null : `${GUEST_COOKIE}=${guest}; Path=/; Max-Age=${60 * 60 * 24 * 90}; HttpOnly; SameSite=Lax${secure ? "; Secure" : ""}`,
  };
}
