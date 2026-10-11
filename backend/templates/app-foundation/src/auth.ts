import type { NextAuthOptions } from "next-auth";
import { getServerSession } from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";
import bcrypt from "bcryptjs";
import { sessionCookies } from "@/lib/session-cookie";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { eq } from "drizzle-orm";

/** Every scalar column of a users row except the credential and what the
 *  session already names — the profile the session carries so a workspace
 *  scope can read its actor column and a page can bind `{{user.<column>}}`. */
function profileOf(row: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(row)) {
    if (["password", "passwordHash", "id", "email", "name", "role", "accountType"].includes(k)) continue;
    if (v === null || ["string", "number", "boolean"].includes(typeof v)) out[k] = v;
  }
  return out;
}

/** A sign-in, or a failed one, on the trail when the level is `regulated`. */
async function _signIn(user: any, email: string, ok: boolean): Promise<void> {
  try {
    const audit = await import("@/lib/audit");
    if (!audit.regulated()) return;
    await audit.recordAudit(db, { action: ok ? "login" : "login_failed", entity: "users",
      entityId: user?.id != null ? String(user.id) : null, after: { email },
      actor: user?.id ? { id: String(user.id), role: String(user.role ?? user.accountType ?? ""), kind: "user" } : { kind: "system" },
      via: "sign-in" });
  } catch (err) {
    console.warn("[audit] a sign-in could not be recorded:", err);
  }
}

export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      name: "credentials",
      credentials: {
        email: { label: "Email", type: "email" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null;

        try {
          const [user] = await db
            .select()
            .from(users)
            .where(eq(users.email, credentials.email))
            .limit(1);

          if (!user) { await _signIn(null, String(credentials.email), false); return null; }
          // Only check isActive if the field exists (not all schemas have it)
          if ("isActive" in user && !(user as any).isActive) { await _signIn(user, String(credentials.email), false); return null; }

          const valid = await bcrypt.compare(
            credentials.password,
            (user as any).password
          );
          if (!valid) { await _signIn(user, String(credentials.email), false); return null; }
          await _signIn(user, String(credentials.email), true);

          // THE ROW, MINUS THE CREDENTIAL. Every scalar column of the users
          // row rides in the session: an ownership rule's `actorColumn`
          // (homePropertyId, organisationId) is read off it by the data
          // engine, and a page binds `{{user.<column>}}`. Only the password
          // hash stays behind.
          const profile = profileOf(user as Record<string, unknown>);
          // An explicit role wins; otherwise the account type chosen at
          // signup stands in, so an app whose only role signal is the
          // signup choice still drives menu visibility off it.
          const stored = (user as any).role || (user as any).accountType || "user";
          // IN AN APPLICATION OF SEVERAL ORGANISATIONS the role is the
          // membership's in the organisation the person acts in; a platform
          // role is held everywhere. `resolve` is the plain role elsewhere.
          const tenancy = await import("@/lib/tenancy");
          const inOrg = await tenancy.resolve({ id: String(user.id), role: stored, activeOrgId: (user as any).activeOrgId ?? null });
          return {
            ...profile,
            id: user.id,
            email: user.email,
            name: (user as any).name || `${(user as any).firstName || ""} ${(user as any).lastName || ""}`.trim(),
            role: inOrg.role || stored,
            accountType: (user as any).accountType || null,
            activeOrgId: inOrg.activeOrgId,
            orgRole: inOrg.orgRole,
          };
        } catch (error) {
          console.error("Auth error:", error);
          return null;
        }
      },
    }),
  ],
  session: { strategy: "jwt" },
  pages: { signIn: "/login", error: "/login" },
  callbacks: {
    async jwt({ token, user, trigger }) {
      if (user) {
        token.id = user.id;
        token.role = (user as any).role;
        token.accountType = (user as any).accountType ?? null;
        (token as any).profile = profileOf(user as Record<string, unknown>);
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
          const tenancy = await import("@/lib/tenancy");
          await tenancy.policy();
          if (tenancy.tenancyOn()) {
            const [row] = await db.select().from(users).where(eq(users.id, String(token.id))).limit(1);
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
  // name — `withAuth` asks for next-auth's default unless it is told.
  cookies: sessionCookies(),
};

/** The signed-in person, on the server. Every page and route reads through
 *  this — `getServerSession` with this app's own options. */
export async function auth() {
  return getServerSession(authOptions);
}

declare module "next-auth" {
  interface User { id: string; role?: string; accountType?: string | null; activeOrgId?: string | null; orgRole?: string | null; }
  interface Session { user: { id: string; role?: string; accountType?: string | null; activeOrgId?: string | null; orgRole?: string | null; name?: string | null; email?: string | null; image?: string | null; }; }
}
declare module "next-auth/jwt" {
  interface JWT { id: string; role?: string; accountType?: string | null; activeOrgId?: string | null; orgRole?: string | null; }
}
