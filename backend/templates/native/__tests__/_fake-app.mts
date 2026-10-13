/**
 * A stand-in for the generated app's HTTP surface, as a `fetch` — what the
 * native SDK talks to — just faithful enough to the real routes that the SDK's
 * protocol code is exercised end to end without a device or a server: next-auth's
 * csrf / credentials callback / session cookie flow, /api/org, the 401 JSON the
 * middleware gives an unauthenticated /api call, the workflow route's reply
 * shapes (refused, failed, guest cookie) and /api/read/*.
 */

export interface Seen { method: string; path: string; cookie: string; credentials: string | undefined; body: string }

export function fakeApp(opts: { password?: boolean; orgs?: { orgId: string; orgName: string }[]; dropCookies?: boolean } = {}) {
  const seen: Seen[] = [];
  let session: { activeOrgId: string | null } | null = null;
  const orgs = opts.orgs ?? [];
  const json = (body: unknown, status = 200, cookies: string[] = []) => {
    const h = new Headers({ "content-type": "application/json" });
    if (!opts.dropCookies) for (const c of cookies) h.append("set-cookie", c);
    return new Response(JSON.stringify(body), { status, headers: h });
  };
  const hasSession = (cookie: string) => /(^|; )forge-test\.session-token=ok/.test(cookie);
  const sessionCookie = () => "forge-test.session-token=ok; Path=/; HttpOnly; SameSite=Lax; Expires=Wed, 21 Oct 2099 07:28:00 GMT";

  const fetchLike = async (url: string, init: RequestInit = {}): Promise<Response> => {
    const u = new URL(url);
    const headers = new Headers(init.headers);
    const cookie = headers.get("cookie") ?? "";
    const body = typeof init.body === "string" ? init.body : "";
    const method = (init.method ?? "GET").toUpperCase();
    seen.push({ method, path: u.pathname, cookie, credentials: init.credentials, body });
    const p = u.pathname;

    if (p === "/api/auth/csrf") return json({ csrfToken: "tok123" }, 200, ["forge-test.csrf-token=tok123; Path=/; HttpOnly; SameSite=Lax"]);
    if (p === "/api/auth/methods") return json({ password: opts.password !== false, magicLink: false, sso: [] });
    if (p === "/api/auth/callback/credentials") {
      const f = new URLSearchParams(body);
      if (f.get("csrfToken") !== "tok123") return json({ url: "/login?error=MissingCSRF" });
      if (f.get("email") === "ada@x.io" && f.get("password") === "pw") {
        session = { activeOrgId: null };
        return json({ url: "/" }, 200, [sessionCookie()]);
      }
      return json({ url: "/login?error=CredentialsSignin" });
    }
    if (p === "/api/auth/session" && method === "GET") {
      if (!hasSession(cookie) || !session) return json({});
      return json({ user: { id: "u1", name: "Ada", email: "ada@x.io", role: "Admin", activeOrgId: session.activeOrgId, orgRole: null }, expires: "2099" });
    }
    if (p === "/api/auth/session" && method === "POST") {
      // next-auth's update(): the token is re-read, the cookie re-issued.
      return json({}, 200, [sessionCookie()]);
    }
    if (p === "/api/auth/signout") {
      session = null;
      return json({ url: "/" }, 200, ["forge-test.session-token=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT"]);
    }
    if (p === "/api/org") {
      if (!hasSession(cookie) || !session) return json({ error: "Sign in first." }, 401);
      if (method === "GET") return json({ organisations: orgs.map((o) => ({ ...o, role: "Member" })), activeOrgId: session.activeOrgId, platform: false });
      const want = JSON.parse(body || "{}").orgId;
      if (!orgs.some((o) => o.orgId === want)) return json({ error: "You do not belong to that organisation." }, 403);
      session.activeOrgId = want;
      return json({ ok: true, activeOrgId: want });
    }
    if (p.startsWith("/api/read/")) {
      if (!hasSession(cookie)) return json({ error: { code: "UNAUTHORIZED", message: "Not authenticated" } }, 401);
      if (p.endsWith("/list")) return json({ rows: [{ id: "o1" }], total: 1, page: 1, limit: 50 });
      if (p.endsWith("/record")) return json({ error: { code: "NOT_FOUND", message: "Not found." } }, 404);
      return json({ value: 3 });
    }
    const wf = /^\/api\/workflows\/([^/]+)\/execute$/.exec(p);
    if (wf) {
      const id = decodeURIComponent(wf[1]);
      // The route mints a guest token on the first thing a signed-out visitor does.
      const guest = hasSession(cookie) || /forge-guest=/.test(cookie) ? [] : ["forge-guest=11111111-2222-3333-4444-555555555555; Path=/; HttpOnly; Max-Age=7776000"];
      if (id === "WF-OK") return json({ status: "completed", id: "r1", records: { n1: "r1" }, reply: { total: 5 } }, 200, guest);
      if (id === "WF-REDIRECT") return json({ status: "completed", redirect: "https://pay.example/checkout" }, 200, guest);
      if (id === "WF-REFUSE") return json({ status: "failed", refused: true, error: "A refund over 500 needs a manager." }, 422, guest);
      if (id === "WF-BOOM") return json({ error: { code: "INTERNAL", message: "The step failed." } }, 500, guest);
      if (id === "WF-NOERR") return new Response("<html>bad gateway</html>", { status: 502 });
      if (id === "WF-FAILED200") return json({ status: "failed" }, 200, guest);
      return json({ error: "Unknown workflow" }, 404);
    }
    return json({ error: "no such route" }, 404);
  };

  return { fetch: fetchLike, seen };
}

/** A fetch that cannot reach anything. */
export const offline = async (): Promise<Response> => { throw new TypeError("Network request failed"); };
