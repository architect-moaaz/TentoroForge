/**
 * The person a token stands for, signed in for one call.
 *
 * A tool runs through the same routes a screen uses — the workflow route
 * with its launch gate, the data route with its access table — and those
 * read the person from this app's session cookie. So the MCP route makes the
 * cookie a sign-in would make, for the token's person, valid for a few
 * minutes, and calls the routes with it. Nothing is trusted that a screen
 * would not be trusted with, and no rule needs a second copy here.
 *
 * `refreshedAt: 0` hands the role to the app's own session callback, which
 * reads it again from the database (and the organisation the person acts in)
 * exactly as it does every quarter hour for a browser.
 *
 * Platform file: every app carries it and the platform replaces it.
 */
import { encode } from "next-auth/jwt";
import { eq } from "drizzle-orm";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { sessionCookieName } from "@/lib/session-cookie";

const MINUTES = 5;

function profileOf(row: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(row)) {
    if (["password", "passwordHash", "id", "email", "name", "role", "accountType"].includes(k)) continue;
    if (v === null || ["string", "number", "boolean"].includes(typeof v)) out[k] = v;
  }
  return out;
}

export type SignedIn = { cookie: string; person: { id: string; role: string; email: string | null; name: string | null } };

export async function signIn(userId: string): Promise<SignedIn | null> {
  const [row] = await db.select().from(users).where(eq((users as any).id, userId)).limit(1);
  const user = row as Record<string, any> | undefined;
  if (!user) return null;
  if ("isActive" in user && !user.isActive) return null;
  const role = String(user.role || user.accountType || "user");
  const name = user.name || `${user.firstName || ""} ${user.lastName || ""}`.trim() || null;
  const token = {
    sub: String(user.id), id: String(user.id), name, email: user.email ?? null, role,
    accountType: user.accountType ?? null, profile: profileOf(user),
    activeOrgId: user.activeOrgId ?? null, orgRole: null, refreshedAt: 0,
  };
  const jwt = await encode({ token: token as any, secret: process.env.NEXTAUTH_SECRET || "dev-secret", maxAge: MINUTES * 60 });
  return { cookie: `${sessionCookieName()}=${jwt}`, person: { id: String(user.id), role, email: user.email ?? null, name } };
}
