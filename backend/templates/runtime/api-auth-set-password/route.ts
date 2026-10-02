/**
 * POST /api/auth/set-password { token, password } — the person invited to the
 * application chooses their own password.
 *
 * THE ONLY WAY AN ACCOUNT GETS A PASSWORD other than sign-up, and it is the
 * same path: this route hashes with the algorithm `auth.ts` verifies, exactly
 * as `/api/auth/signup` does. Nothing upstream — not the Blueprint, not a
 * workflow, not Smith — ever holds the plaintext, which is why `users` keeps
 * an unusable hash until this route runs (see `seedAccounts` in `src/db/seed.ts`).
 *
 * GET /api/auth/set-password?token=… answers whether a token is still good, so
 * the page can say "this link has expired" before asking for a password rather
 * than after.
 *
 * Forge runtime — do not remove.
 */
import { createHash } from "node:crypto";
import bcrypt from "bcryptjs";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { forgeInvites } from "@/db/schema/_forge_invites";
import { eq } from "drizzle-orm";

export const runtime = "nodejs";

/** The stored form of a token. Only this reaches the database. */
function digest(token: string): string {
  return createHash("sha256").update(token, "utf8").digest("hex");
}

/** The invite this token opens, or null when there is none or it has expired. */
async function pending(token: string): Promise<{ email: string; purpose: string } | null> {
  if (!token) return null;
  const [row] = await db
    .select()
    .from(forgeInvites)
    .where(eq(forgeInvites.tokenHash, digest(token)))
    .limit(1);
  if (!row) return null;
  // ALREADY USED. The row is kept rather than deleted so the seed can tell an
  // invite it has applied from a new one; `usedAt` is what makes the link
  // one-time, so it is checked here.
  if (row.usedAt) return null;
  // An expired link is refused, not deleted: the person may have taken a week
  // to open it, and the owner can issue a new one for the same account.
  if (new Date(row.expiresAt as unknown as string).getTime() < Date.now()) return null;
  return { email: String(row.email), purpose: String(row.purpose || "invite") };
}

export async function GET(request: Request): Promise<Response> {
  try {
    const token = new URL(request.url).searchParams.get("token") || "";
    const invite = await pending(token);
    if (!invite) {
      return Response.json(
        { error: { code: "INVALID_TOKEN", message: "This link has expired or has already been used." } },
        { status: 404 },
      );
    }
    // The email is shown so the person can see which account they are setting
    // up. It is not a secret: they were sent the link.
    return Response.json({ email: invite.email, purpose: invite.purpose });
  } catch (err) {
    console.error("[api/auth/set-password] GET", err);
    return Response.json(
      { error: { code: "INTERNAL_ERROR", message: "Could not check that link." } },
      { status: 500 },
    );
  }
}

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.json();
    const token = String(body?.token || "");
    const password = String(body?.password || "");
    // The same minimum the signup route enforces, so the two ways in agree.
    if (password.length < 6) {
      return Response.json(
        { error: { code: "VALIDATION_ERROR", message: "Password must be at least 6 characters" } },
        { status: 400 },
      );
    }
    const invite = await pending(token);
    if (!invite) {
      return Response.json(
        { error: { code: "INVALID_TOKEN", message: "This link has expired or has already been used." } },
        { status: 404 },
      );
    }

    const hashed = await bcrypt.hash(password, 12);
    const set: Record<string, unknown> = { password: hashed };
    // The account was created inactive precisely so an un-set-up invite could
    // not be signed into; setting the password is what activates it.
    if ("isActive" in users) set.isActive = true;
    // `as any` the way the signup route does: the users table's shape is the
    // app's, not the platform's, so the columns are named at runtime.
    await db.update(users).set(set as any).where(eq(users.email, invite.email));

    // ONE-TIME. The link is spent the moment the password lands, so one that
    // reaches the wrong inbox later opens nothing.
    await db
      .update(forgeInvites)
      .set({ usedAt: new Date() })
      .where(eq(forgeInvites.email, invite.email));

    return Response.json({ ok: true, email: invite.email });
  } catch (err) {
    console.error("[api/auth/set-password] POST", err);
    return Response.json(
      { error: { code: "INTERNAL_ERROR", message: "Could not set that password." } },
      { status: 500 },
    );
  }
}
