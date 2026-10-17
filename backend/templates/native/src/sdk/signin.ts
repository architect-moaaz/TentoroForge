// The app SDK (native) — the session protocol, without React.
//
// THE APP SIGNS PEOPLE IN WITH next-auth, AND NATIVE USES ITS COOKIE FLOW —
// the same calls a browser makes, no token route:
//
//   GET  /api/auth/csrf                       -> { csrfToken }   (and the csrf cookie)
//   POST /api/auth/callback/credentials       -> sets the session cookie
//        application/x-www-form-urlencoded: csrfToken, email, password, json=true
//   GET  /api/auth/session                    -> { user: {...} } or {} when signed out
//
// The callback's own answer is not trusted as "signed in": with `json=true` a
// wrong password is a 200 whose `url` carries `error=`, and a right one is a
// 200 too. The session read at the end is what says who is signed in.
//
// Password sign-in only. SSO and magic links need a browser redirect and the
// app can switch password sign-in off (`/api/auth/methods`); the login screen
// says so instead of showing a form that cannot work.
//
// An organisation (tenancy on): the session has `activeOrgId`, and until it is
// set writes are refused. `GET /api/org` lists the organisations the person may
// act in, `POST /api/org { orgId }` chooses, and the session token is then
// refreshed (`POST /api/auth/session`, what next-auth's `update()` does) so the
// role and every scoped list follow.
//
// PURE — no react-native import; every function takes the client.

import type { Client } from "./http";
import { GUEST_COOKIE } from "./cookies";

/** The signed-in person, as `/api/auth/session` carries them. Every scalar
 *  column of the user's row rides along (an app's own profile fields). */
export interface SessionUser {
  id: string;
  name: string | null;
  email: string | null;
  role: string | null;
  accountType?: string | null;
  /** Set when the app has several organisations and one is chosen. */
  activeOrgId?: string | null;
  orgRole?: string | null;
  [column: string]: unknown;
}

export interface SignInMethods {
  password: boolean;
  magicLink: boolean;
  sso: { id: string; name: string; kind: "oidc" | "saml"; connected: boolean }[];
}

export interface Organisation {
  orgId: string;
  orgName?: string | null;
  role?: string | null;
}

export interface OrganisationList {
  organisations: Organisation[];
  activeOrgId: string | null;
  platform: boolean;
}

export type SignInOutcome =
  | { ok: true; user: SessionUser }
  | { ok: false; reason: "wrong" | "unavailable" | "network" | "unconfirmed"; message: string };

const WRONG = "That email and password do not match an account.";

function asUser(body: unknown): SessionUser | null {
  const u = (body as { user?: unknown } | null)?.user;
  if (!u || typeof u !== "object") return null;
  const row = u as Record<string, unknown>;
  if (row.id === undefined || row.id === null) return null;
  const s = (v: unknown) => (v === undefined || v === null ? null : String(v));
  return { ...row, id: String(row.id), name: s(row.name), email: s(row.email), role: s(row.role) };
}

/** Who is signed in, or null. A network failure is "unknown", not "signed out":
 *  it throws, so a screen offline on launch keeps the person it remembers. */
export async function fetchSession(client: Client): Promise<SessionUser | null> {
  const res = await client.json("/api/auth/session");
  if (res.networkError) throw new Error(res.networkError);
  return res.ok ? asUser(res.body) : null;
}

const DEFAULT_METHODS: SignInMethods = { password: true, magicLink: false, sso: [] };

/** How this app lets people in. An older app without the route answers 404:
 *  every app has had a password form, so that is what is assumed. */
export async function fetchMethods(client: Client): Promise<SignInMethods> {
  const res = await client.json<Partial<SignInMethods>>("/api/auth/methods");
  if (res.networkError) throw new Error(res.networkError);
  if (!res.ok || !res.body || typeof res.body !== "object") return DEFAULT_METHODS;
  return { ...DEFAULT_METHODS, ...res.body, sso: Array.isArray(res.body.sso) ? res.body.sso : [] };
}

async function csrfToken(client: Client): Promise<string | null> {
  const res = await client.json<{ csrfToken?: string }>("/api/auth/csrf");
  if (res.networkError) throw new Error(res.networkError);
  return res.ok && typeof res.body?.csrfToken === "string" && res.body.csrfToken ? res.body.csrfToken : null;
}

/** The whole sign-in. Never throws: every way it can end is an outcome. */
export async function signInWithPassword(client: Client, email: string, password: string): Promise<SignInOutcome> {
  try {
    const token = await csrfToken(client);
    if (!token) return { ok: false, reason: "unavailable", message: "The app did not give a sign-in token. Try again in a moment." };
    const res = await client.json<{ url?: string }>("/api/auth/callback/credentials", {
      form: { csrfToken: token, email, password, json: "true" },
    });
    if (res.networkError) return { ok: false, reason: "network", message: res.networkError };
    // next-auth answers a failed credential with a url that carries the error.
    const url = typeof res.body?.url === "string" ? res.body.url : "";
    if (/[?&]error=/.test(url)) {
      return /error=CredentialsSignin/.test(url)
        ? { ok: false, reason: "wrong", message: WRONG }
        : { ok: false, reason: "unavailable", message: "Password sign-in is not available for this app." };
    }
    // The session is the proof.
    const user = await fetchSession(client);
    if (!user) {
      return res.status === 401 || res.status === 403
        ? { ok: false, reason: "wrong", message: WRONG }
        : { ok: false, reason: "unconfirmed", message: "Signed in, but the app did not keep the session. Try again." };
    }
    return { ok: true, user };
  } catch (err) {
    return { ok: false, reason: "network", message: err instanceof Error ? err.message : String(err) };
  }
}

/** Sign out: ask the server to end the session (best effort — a phone that is
 *  offline still signs out locally), then forget our cookies but the guest token. */
export async function signOutRequest(client: Client): Promise<void> {
  try {
    const token = await csrfToken(client);
    if (token) await client.json("/api/auth/signout", { form: { csrfToken: token, json: "true" } });
  } catch {
    /* offline: the local sign-out below is what counts */
  }
  client.jar.clear([GUEST_COOKIE]);
}

/** The organisations the person may act in. `{ organisations: [] }` when the
 *  app has one organisation (tenancy off). */
export async function fetchOrganisations(client: Client): Promise<OrganisationList> {
  const res = await client.json<Partial<OrganisationList>>("/api/org");
  if (res.networkError) throw new Error(res.networkError);
  const b = res.ok && res.body ? res.body : {};
  return {
    organisations: Array.isArray(b.organisations) ? b.organisations : [],
    activeOrgId: typeof b.activeOrgId === "string" ? b.activeOrgId : null,
    platform: b.platform === true,
  };
}

/** Choose the organisation to act in, then have the session read it. The
 *  session token is a cookie fixed at sign-in: `POST /api/auth/session` is
 *  next-auth's `update()`, and its answer sets the refreshed cookie. */
export async function switchOrganisation(client: Client, orgId: string): Promise<{ ok: true; user: SessionUser | null } | { ok: false; message: string }> {
  const res = await client.json<{ error?: unknown }>("/api/org", { body: { orgId } });
  if (res.networkError) return { ok: false, message: res.networkError };
  if (!res.ok) {
    const e = res.body?.error;
    return { ok: false, message: typeof e === "string" && e ? e : "That organisation could not be chosen." };
  }
  const token = await csrfToken(client).catch(() => null);
  if (token) await client.json("/api/auth/session", { body: { csrfToken: token, data: {} } });
  return { ok: true, user: await fetchSession(client).catch(() => null) };
}
