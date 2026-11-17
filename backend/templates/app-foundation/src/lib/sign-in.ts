/**
 * How people sign in — read from the projected policy (`sign-in-policy.ts`),
 * applied by `auth.ts`, the magic-link route and the sign-in form.
 *
 * NAMES, NEVER VALUES. An identity provider is reached with the values the
 * environment holds under the names the Blueprint declared; this module reads
 * them by name and hands them to next-auth, and no value is ever written to a
 * projected file. A provider whose names are unset is DECLARED but not
 * CONNECTED: the form says so rather than offering a button that fails.
 */
import { createHash, randomBytes } from "node:crypto";
import { SIGN_IN, type SsoEntry } from "@/lib/sign-in-policy";
import * as accountModule from "@/lib/account";
import { sessionCookiePrefix } from "@/lib/session-cookie";

export type { SsoEntry };

/** Issuers the provider itself fixes, so an owner sets only the client.
 *  Microsoft's is the one for every organisation and personal accounts alike
 *  ("Continue with Microsoft"); one tenant's own issuer, set by name, wins. */
const FIXED_ISSUER: Record<string, string> = {
  google: "https://accounts.google.com",
  entra: "https://login.microsoftonline.com/common/v2.0",
};

/** The claim a provider carries a person's groups in, when the policy does not say. */
const GROUP_CLAIM: Record<string, string> = { entra: "groups", okta: "groups", google: "hd", oidc: "groups", saml: "groups" };

export function policy() {
  return SIGN_IN;
}

export function ssoEntries(): SsoEntry[] {
  return SIGN_IN.sso ?? [];
}

export function entryOf(id: string): SsoEntry | null {
  return ssoEntries().find((e) => e.id === id) ?? null;
}

/** The issuer's address for an entry: the environment's, else the provider's own. */
export function issuerOf(e: SsoEntry, env: NodeJS.ProcessEnv = process.env): string {
  return String(env[e.issuerKey] ?? "").trim().replace(/\/+$/, "") || FIXED_ISSUER[e.provider] || "";
}

/** Connected: everything next-auth needs to reach the provider is set. */
export function connected(e: SsoEntry, env: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(issuerOf(e, env) && String(env[e.clientIdKey] ?? "").trim());
}

/** Where the provider sends the person back: next-auth's callback for this entry. */
export function callbackPath(id: string): string {
  return `/api/auth/callback/${id}`;
}

/** The address may sign in through this entry: no `domains` admits every one. */
export function domainAllowed(email: string, e: SsoEntry): boolean {
  const domain = String(email ?? "").toLowerCase().split("@")[1] ?? "";
  if (!e.domains?.length) return true;
  return e.domains.some((d) => domain === String(d).toLowerCase().replace(/^@/, ""));
}

/** The role the provider's claims name: a group in `roleFrom.map` (any
 *  case), else the entry's default, else null (the application decides). */
export function roleFromClaims(claims: Record<string, unknown> | null | undefined, e: SsoEntry): string | null {
  const from = e.roleFrom;
  if (!from) return null;
  const claim = from.claim || GROUP_CLAIM[e.provider] || "groups";
  const raw = (claims ?? {})[claim];
  const values = (Array.isArray(raw) ? raw : raw == null ? [] : [raw]).map((v) => String(v).toLowerCase());
  const map = Object.entries(from.map ?? {});
  for (const v of values) {
    const hit = map.find(([group]) => group.toLowerCase() === v);
    if (hit) return hit[1];
  }
  return from.default ?? null;
}

/** A magic link lives this long. */
export const MAGIC_TTL_MS = 15 * 60_000;

/** The stored form of a magic-link token: only this reaches the database. */
export function digest(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}

/** A fresh token and its digest. The token goes in the link; the digest in the row. */
export function magicToken(): { token: string; hash: string } {
  const token = randomBytes(32).toString("base64url");
  return { token, hash: digest(token) };
}

/** What the sign-in form shows: each method, and for each provider whether
 *  it is connected here (so a declared-but-unset provider is said, not offered). */
export function methods(env: NodeJS.ProcessEnv = process.env) {
  return {
    password: SIGN_IN.password !== false,
    magicLink: SIGN_IN.magicLink === true,
    // `signUp`: a new person may make their account through it (it provisions
    // just in time); an invite-only provider signs in only the people it knows.
    sso: ssoEntries().map((e) => ({ id: e.id, name: e.name, kind: e.kind, connected: connected(e, env), signUp: e.provisioning === "just_in_time" })),
  };
}

/** The cookie a new person's choice rides in while they are at the provider. */
export function signupIntentCookie(): string {
  return `${sessionCookiePrefix()}.signup-as`;
}

/** The roles signup lets a person give themselves (`security.signupRoles`, else the one signup role). */
export function signupRoles(): string[] {
  const m = accountModule as unknown as { SIGNUP_ROLES?: string[]; SIGNUP_ROLE?: string | null };
  const out = [...(m.SIGNUP_ROLES ?? [])];
  if (m.SIGNUP_ROLE && !out.includes(m.SIGNUP_ROLE)) out.push(m.SIGNUP_ROLE);
  return out;
}

/** The role asked for, when signup offers it; null otherwise. */
export function offeredSignupRole(asked: unknown): string | null {
  const v = typeof asked === "string" ? asked.trim() : "";
  return v && signupRoles().includes(v) ? v : null;
}

/** What a cookie written by POST /api/auth/methods carried, checked again. */
export function readSignupIntent(raw: string | undefined | null): { as: string | null; account: Record<string, unknown> } {
  if (!raw) return { as: null, account: {} };
  try {
    const parsed = JSON.parse(Buffer.from(raw, "base64url").toString("utf8")) as { as?: unknown; account?: unknown };
    const account = parsed.account && typeof parsed.account === "object" && !Array.isArray(parsed.account) ? (parsed.account as Record<string, unknown>) : {};
    return { as: offeredSignupRole(parsed.as), account };
  } catch {
    return { as: null, account: {} };
  }
}
