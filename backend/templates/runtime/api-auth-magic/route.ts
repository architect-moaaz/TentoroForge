/**
 * POST /api/auth/magic { email } — a one-time sign-in link for the address.
 *
 * THE ANSWER IS THE SAME FOR EVERY ADDRESS ("if that address has an account,
 * a link is on its way"), so the route tells nobody who has one. The row
 * holds only the token's digest (`forge_invites`, purpose `magic_link`,
 * fifteen minutes, one per address — a new link supersedes the old); the link
 * itself goes out through the application's connected email service, by the
 * same step a process sends with. When no service is connected the link is
 * not sent and the answer says so in `notice`, as `send_email` does, rather
 * than reporting a send that did not happen — and the link is NEVER in the
 * answer: that would let anyone sign in as anyone.
 *
 * Forge runtime — do not remove.
 */
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { forgeInvites } from "@/db/schema/_forge_invites";
import { eq } from "drizzle-orm";
import { MAGIC_TTL_MS, magicToken, policy } from "@/lib/sign-in";

export const runtime = "nodejs";

const SAID = "If that address has an account, a sign-in link is on its way.";

export async function POST(request: Request): Promise<Response> {
  if (!policy().magicLink) {
    return Response.json({ error: { code: "NOT_OFFERED", message: "This application does not sign people in by link." } }, { status: 404 });
  }
  let email = "";
  try {
    const body = await request.json();
    email = String(body?.email ?? "").trim().toLowerCase();
  } catch { /* no body */ }
  if (!email || !email.includes("@")) {
    return Response.json({ error: { code: "VALIDATION_ERROR", message: "Give the email address you sign in with." } }, { status: 400 });
  }
  try {
    const [person] = await db.select().from(users).where(eq(users.email, email)).limit(1);
    if (!person || ("isActive" in person && !(person as any).isActive)) {
      return Response.json({ ok: true, message: SAID });
    }
    const { token, hash } = magicToken();
    const expiresAt = new Date(Date.now() + MAGIC_TTL_MS);
    const issue = `magic:${hash.slice(0, 16)}:${Date.now()}`;
    await db
      .insert(forgeInvites)
      .values({ email, tokenHash: hash, issue, purpose: "magic_link", expiresAt, usedAt: null } as any)
      .onConflictDoUpdate({ target: forgeInvites.email, set: { tokenHash: hash, issue, purpose: "magic_link", expiresAt, usedAt: null } as any });
    const origin = new URL(request.url).origin;
    const base = (process.env.NEXTAUTH_URL ?? origin).replace(/\/+$/, "");
    const link = `${base}${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/login?magic=${encodeURIComponent(token)}`;
    // Sent by the same hand a process sends with: the connected service, or
    // an honest "not sent" when there is none.
    const wf = await import("@/lib/workflows");
    wf.registerDefaultActions();
    const send = wf.getActionHandler("send_email");
    let notice: string | undefined;
    if (send) {
      const out: any = await send({ to: email, subject: "Your sign-in link",
        body: `Open this link to sign in. It works once and for the next 15 minutes: ${link}` },
        { input: {}, variables: {}, log: [] });
      if (!out?.sent) notice = String(out?.notice ?? out?.reason ?? "the link could not be sent: no email service is connected");
    } else {
      notice = "the link could not be sent: no email service is connected";
    }
    return Response.json({ ok: true, message: SAID, ...(notice ? { notice } : {}) });
  } catch (err) {
    console.error("[api/auth/magic] POST", err);
    return Response.json({ error: { code: "INTERNAL_ERROR", message: "Could not send a sign-in link." } }, { status: 500 });
  }
}
