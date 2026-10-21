import type { NextAuthOptions } from "next-auth";
import type { Provider } from "next-auth/providers/index";
import { getServerSession } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import BoxyHQSAMLProvider from "next-auth/providers/boxyhq-saml";
import bcrypt from "bcryptjs";
import { sessionCookies } from "@/lib/session-cookie";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { eq } from "drizzle-orm";
import { connected, digest, domainAllowed, issuerOf, roleFromClaims, ssoEntries, policy as signInPolicy, type SsoEntry } from "@/lib/sign-in";

/** Every scalar column of a users row except the credential and what the
 *  session already names — the profile the session carries so a workspace
 *  scope can read its actor column and a page can bind `{{user.<column>}}`. */
function profileOf(row: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(row)) {
    if (["password", "passwordHash", "id", "email", "name", "role", "accountType"].includes(k)) continue;
    if (v === null || ["string", "number", "boolean"].includes(typeof v)) out[k] = v;
    // A LIST OF IDS rides along too — the properties a person is assigned to
    // are an `actorColumn` of their own; left behind, a person of several
    // properties reached none (pah7lhfz, 2026-10-21).
    else if (Array.isArray(v) && v.length <= 200 && v.every((x) => ["string", "number"].includes(typeof x))) out[k] = v;
  }
  return out;
}

/** A sign-in, or a failed one, on the trail when the level is `regulated`. */
async function _signIn(user: any, email: string, ok: boolean, via = "sign-in"): Promise<void> {
  try {
    const audit = await import("@/lib/audit");
    if (!audit.regulated()) return;
    await audit.recordAudit(db, { action: ok ? "login" : "login_failed", entity: "users",
      entityId: user?.id != null ? String(user.id) : null, after: { email },
      actor: user?.id ? { id: String(user.id), role: String(user.role ?? user.accountType ?? ""), kind: "user" } : { kind: "system" },
      via });
  } catch (err) {
    console.warn("[audit] a sign-in could not be recorded:", err);
  }
}

/**
 * THE ROW, MINUS THE CREDENTIAL — what every way in puts in the session.
 * Every scalar column of the users row rides along: an ownership rule's
 * `actorColumn` (homePropertyId, organisationId) is read off it by the data
 * engine, and a page binds `{{user.<column>}}`. Only the password hash stays
 * behind. An explicit role wins; otherwise the account type chosen at signup
 * stands in. IN AN APPLICATION OF SEVERAL ORGANISATIONS the role is the
 * membership's in the organisation the person acts in; a platform role is
 * held everywhere (`resolve` is the plain role elsewhere).
 */
async function sessionUserOf(user: Record<string, any>): Promise<Record<string, any>> {
  const profile = profileOf(user);
  const stored = user.role || user.accountType || "user";
  const tenancy = await import("@/lib/tenancy");
  const inOrg = await tenancy.resolve({ id: String(user.id), role: stored, activeOrgId: user.activeOrgId ?? null });
  return {
    ...profile,
    id: user.id,
    email: user.email,
    name: user.name || `${user.firstName || ""} ${user.lastName || ""}`.trim(),
    role: inOrg.role || stored,
    accountType: user.accountType || null,
    activeOrgId: inOrg.activeOrgId,
    orgRole: inOrg.orgRole,
  };
}

async function userByEmail(email: string): Promise<Record<string, any> | null> {
  const [row] = await db.select().from(users).where(eq(users.email, email)).limit(1);
  return (row as any) ?? null;
}

/** Email and password: the credential checked against the stored hash. */
const passwordProvider = CredentialsProvider({
  id: "credentials",
  name: "credentials",
  credentials: {
    email: { label: "Email", type: "email" },
    password: { label: "Password", type: "password" },
  },
  async authorize(credentials) {
    if (!credentials?.email || !credentials?.password) return null;
    try {
      const user = await userByEmail(String(credentials.email));
      if (!user) { await _signIn(null, String(credentials.email), false); return null; }
      // Only check isActive if the field exists (not all schemas have it)
      if ("isActive" in user && !user.isActive) { await _signIn(user, String(credentials.email), false); return null; }
      const valid = await bcrypt.compare(credentials.password, user.password);
      if (!valid) { await _signIn(user, String(credentials.email), false); return null; }
      await _signIn(user, String(credentials.email), true);
      return (await sessionUserOf(user)) as any;
    } catch (error) {
      console.error("Auth error:", error);
      return null;
    }
  },
});

/**
 * A MAGIC LINK: the token from the link, used once, within its quarter hour.
 * The row it opens was written by `/api/auth/magic` with only the token's
 * digest (`forge_invites`, purpose `magic_link`), so a leaked database hands
 * nobody a way in and a used or expired link opens nothing.
 */
const magicProvider = CredentialsProvider({
  id: "magic",
  name: "magic link",
  credentials: { token: { label: "Token", type: "text" } },
  async authorize(credentials) {
    const token = String(credentials?.token ?? "");
    if (!token) return null;
    try {
      const { forgeInvites } = await import("@/db/schema/_forge_invites");
      const [row] = await db.select().from(forgeInvites).where(eq(forgeInvites.tokenHash, digest(token))).limit(1);
      if (!row || String(row.purpose) !== "magic_link" || row.usedAt) return null;
      if (new Date(row.expiresAt as unknown as string).getTime() < Date.now()) return null;
      const user = await userByEmail(String(row.email));
      if (!user) { await _signIn(null, String(row.email), false, "magic-link"); return null; }
      if ("isActive" in user && !user.isActive) { await _signIn(user, String(row.email), false, "magic-link"); return null; }
      // ONE-TIME: spent the moment it signs someone in.
      await db.update(forgeInvites).set({ usedAt: new Date() }).where(eq(forgeInvites.id, row.id));
      await _signIn(user, String(row.email), true, "magic-link");
      return (await sessionUserOf(user)) as any;
    } catch (error) {
      console.error("Magic link error:", error);
      return null;
    }
  },
});

/**
 * AN IDENTITY PROVIDER, by the names the Blueprint declared. OpenID Connect
 * to the provider itself — Entra, Google, Okta or any issuer with discovery
 * — or, for SAML, OpenID Connect to the platform's SAML bridge (BoxyHQ
 * Jackson), which speaks SAML to the enterprise; the application only ever
 * speaks OIDC, so one path proves both. An entry whose names are unset is
 * not offered: the form says it is not connected here.
 */
function ssoProvider(e: SsoEntry): Provider | null {
  if (!connected(e)) return null;
  const issuer = issuerOf(e);
  const clientId = String(process.env[e.clientIdKey] ?? "").trim();
  const clientSecret = String(process.env[e.clientSecretKey] ?? "").trim() || "none";
  if (e.kind === "saml") {
    return BoxyHQSAMLProvider({ id: e.id, name: e.name, issuer, clientId, clientSecret });
  }
  return {
    id: e.id,
    name: e.name,
    type: "oauth",
    wellKnown: `${issuer}/.well-known/openid-configuration`,
    issuer,
    clientId,
    clientSecret,
    authorization: { params: { scope: "openid email profile" } },
    idToken: true,
    checks: ["pkce", "state"],
    profile(p: Record<string, any>) {
      return { id: String(p.sub), email: p.email ?? p.preferred_username ?? p.upn ?? null, name: p.name ?? null, claims: p } as any;
    },
  };
}

function providers(): Provider[] {
  const out: Provider[] = [];
  if (signInPolicy().password !== false) out.push(passwordProvider);
  if (signInPolicy().magicLink) out.push(magicProvider);
  for (const e of ssoEntries()) {
    const p = ssoProvider(e);
    if (p) out.push(p);
  }
  return out;
}

/**
 * A PERSON ARRIVING FROM A PROVIDER: admitted when their address's domain is
 * one the entry allows and the application knows them — or, when the entry
 * provisions just in time, made now with the role the claims name. Refused
 * in words otherwise (`/login?error=…`), never silently.
 */
async function admitSso(e: SsoEntry, user: Record<string, any>, claims: Record<string, unknown>): Promise<string | true> {
  const email = String(user.email ?? "").toLowerCase();
  if (!email) return "/login?error=NoEmail";
  if (!domainAllowed(email, e)) { await _signIn(null, email, false, `sso:${e.id}`); return "/login?error=DomainNotAllowed"; }
  let row = await userByEmail(email);
  const claimed = roleFromClaims(claims, e);
  if (!row) {
    if (e.provisioning !== "just_in_time") { await _signIn(null, email, false, `sso:${e.id}`); return "/login?error=NotInvited"; }
    const { SIGNUP_ROLE } = await import("@/lib/account");
    const role = claimed || SIGNUP_ROLE || undefined;
    const name = String(user.name ?? email.split("@")[0]);
    const [created] = await db.insert(users).values({
      email,
      // A credential nobody holds: this person signs in through the provider.
      password: await bcrypt.hash(`sso:${e.id}:${Date.now()}:${Math.random()}`, 10),
      ...("name" in (users as any) ? { name } : {}),
      ...("firstName" in (users as any) ? { firstName: name.split(" ")[0], lastName: name.split(" ").slice(1).join(" ") || "" } : {}),
      ...("role" in (users as any) && role ? { role } : {}),
      ...("accountType" in (users as any) && role ? { accountType: role } : {}),
      ...("isActive" in (users as any) ? { isActive: true } : {}),
    } as any).returning();
    row = created as any;
  } else if (claimed && "role" in row && row.role !== claimed) {
    // THE PROVIDER'S GROUPS DECIDE THE ROLE on every sign-in: a person moved
    // between groups holds the new role next time, with nobody re-roling them here.
    await db.update(users).set({ role: claimed } as any).where(eq(users.id, row.id));
    row = { ...row, role: claimed };
  }
  if (!row) return "/login?error=AccessDenied";
  if ("isActive" in row && !row.isActive) { await _signIn(row, email, false, `sso:${e.id}`); return "/login?error=AccessDenied"; }
  await _signIn(row, email, true, `sso:${e.id}`);
  // The same object next-auth hands to `jwt`: what the session carries is
  // decided here, for every way in alike.
  Object.assign(user, await sessionUserOf(row));
  return true;
}

export const authOptions: NextAuthOptions = {
  providers: providers(),
  session: { strategy: "jwt" },
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    // AN ORGANISATION'S OWN ADDRESS IS THIS APP TOO: after signing in at
    // acme.clinicapp.com the person stays there, not on the main address.
    async redirect({ url, baseUrl }) {
      if (url.startsWith("/")) return `${baseUrl}${url}`;
      try {
        const u = new URL(url);
        if (u.origin === baseUrl) return url;
        const base = String(process.env.FORGE_ORG_DOMAIN || "").toLowerCase().replace(/^\*\./, "");
        if (base && u.protocol === "https:" && (u.hostname === base || u.hostname.endsWith(`.${base}`))) return url;
      } catch { /* not a URL: home */ }
      return baseUrl;
    },
    async signIn({ user, account, profile }) {
      const e = account ? ssoEntries().find((x) => x.id === account.provider) : null;
      if (!e) return true;
      try {
        const claims = { ...((profile as Record<string, unknown>) ?? {}), ...(((user as any).claims as Record<string, unknown>) ?? {}) };
        return await admitSso(e, user as Record<string, any>, claims);
      } catch (error) {
        console.error("SSO sign-in error:", error);
        return "/login?error=AccessDenied";
      }
    },
    async jwt({ token, user, trigger }) {
      if (user) {
        token.id = user.id;
        token.role = (user as any).role;
        token.accountType = (user as any).accountType ?? null;
        (token as any).profile = profileOf(user as unknown as Record<string, unknown>);
        (token as any).activeOrgId = (user as any).activeOrgId ?? null;
        (token as any).orgRole = (user as any).orgRole ?? null;
        (token as any).refreshedAt = Date.now();
      }
      // A CHANGED MEMBERSHIP REACHES THE SESSION: on `update()` (a switch, a
      // re-role) and every fifteen minutes, the organisation and the role
      // are read again. A token used to be frozen at sign-in.
      const stale = Date.now() - Number((token as any).refreshedAt ?? 0) > 15 * 60_000;
      if (token.id && (trigger === "update" || stale)) {
        try {
          const [row] = await db.select().from(users).where(eq(users.id, String(token.id))).limit(1);
          // WHAT THE PERSON'S ROW SAYS NOW — the properties they were given
          // since signing in reach the session too, tenancy or not.
          if (row) (token as any).profile = { ...profileOf(row as Record<string, unknown>), activeOrgId: (token as any).activeOrgId ?? null };
          const tenancy = await import("@/lib/tenancy");
          await tenancy.policy();
          if (tenancy.tenancyOn()) {
            if (row) {
              const stored = (row as any).role || (row as any).accountType || "user";
              const inOrg = await tenancy.resolve({ id: String(row.id), role: stored, activeOrgId: (row as any).activeOrgId ?? null });
              token.role = inOrg.role || stored;
              (token as any).activeOrgId = inOrg.activeOrgId;
              (token as any).orgRole = inOrg.orgRole;
              (token as any).profile = { ...profileOf(row as Record<string, unknown>), activeOrgId: inOrg.activeOrgId };
            }
          }
        } catch (err) {
          console.warn("[auth] the session could not be refreshed:", err);
        }
        (token as any).refreshedAt = Date.now();
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user && token) {
        Object.assign(session.user as any, (token as any).profile ?? {});
        (session.user as any).id = token.id;
        (session.user as any).role = token.role;
        (session.user as any).accountType = (token as any).accountType ?? null;
        (session.user as any).activeOrgId = (token as any).activeOrgId ?? null;
        (session.user as any).orgRole = (token as any).orgRole ?? null;
      }
      return session;
    },
  },
  secret: process.env.NEXTAUTH_SECRET || "dev-secret",
  // THIS APPLICATION'S OWN COOKIE. Every generated app used next-auth's
  // default name, and a browser sends a cookie for the HOST, not the port —
  // so two apps on localhost overwrite each other's session. The second one
  // then reads a token it cannot decrypt and logs
  // "[next-auth][error][JWT_SESSION_ERROR] decryption operation failed" on
  // every request, while the person is quietly signed out.
  //
  // The name is derived from the secret, which is already this app's alone,
  // so nothing new has to be configured or kept in step.
  // NAMED IN ONE PLACE, because `middleware.ts` has to look for the same
  // name — `withAuth` asks for next-auth's default unless it is told. The
  // sign-in's own cookies (state, PKCE verifier, nonce) are named there too:
  // two apps on one host would otherwise finish each other's sign-in.
  cookies: sessionCookies(),
};

/** The signed-in person, on the server. Every page and route reads through
 *  this — `getServerSession` with this app's own options. AT AN
 *  ORGANISATION'S OWN ADDRESS (`<slug>.<FORGE_ORG_DOMAIN>`) the address
 *  decides the organisation the request acts in (`tenancy.atAddress`). */
export async function auth() {
  const session = await getServerSession(authOptions);
  const user = session?.user as Record<string, any> | undefined;
  if (!user?.id || !process.env.FORGE_ORG_DOMAIN) return session;
  try {
    const tenancy = await import("@/lib/tenancy");
    const { headers } = await import("next/headers");
    const h = await headers();
    const at = await tenancy.atAddress(user as any, h.get("x-forwarded-host") || h.get("host"));
    if (at) Object.assign(user, at);
  } catch { /* no request (a job), or no address table yet: the stored organisation */ }
  return session;
}

declare module "next-auth" {
  interface User { id: string; role?: string; accountType?: string | null; activeOrgId?: string | null; orgRole?: string | null; }
  interface Session { user: { id: string; role?: string; accountType?: string | null; activeOrgId?: string | null; orgRole?: string | null; outsideOrg?: string; name?: string | null; email?: string | null; image?: string | null; }; }
}
declare module "next-auth/jwt" {
  interface JWT { id: string; role?: string; accountType?: string | null; activeOrgId?: string | null; orgRole?: string | null; }
}
