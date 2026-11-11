/**
 * The code a new account proves its address with (`signIn.verifyEmail`).
 *
 * POST /api/auth/email-code            — send a fresh six-digit code to the
 *                                        signed-in person's own address
 * PUT  /api/auth/email-code { code }   — check it; "verified" on a match
 *
 * Only the code's digest is stored on the person's row, with a ten-minute
 * expiry and five attempts; a new code may be asked for every thirty seconds.
 * The code goes out through the application's connected email service by the
 * same step a process sends with — on the test version too, because it goes
 * to the address the person just signed up with. When no service is
 * connected the answer says so in `notice` rather than pretending it was sent.
 *
 * Forge runtime — do not remove.
 */
import { createHash, randomInt } from "node:crypto";
import { eq } from "drizzle-orm";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { auth } from "@/auth";

export const runtime = "nodejs";

const TTL_MS = 10 * 60_000;
const RESEND_MS = 30_000;
const ATTEMPTS = 5;
const digest = (code: string) => createHash("sha256").update(code).digest("hex");
const said = (status: number, code: string, message: string) => Response.json({ error: { code, message } }, { status });

async function me() {
  const session = await auth();
  const id = (session?.user as { id?: string } | undefined)?.id;
  if (!id) return null;
  const [row] = await db.select().from(users).where(eq(users.id, String(id))).limit(1);
  return row ?? null;
}

export async function POST(): Promise<Response> {
  const person = await me();
  if (!person) return said(401, "UNAUTHORIZED", "Sign in to get a code.");
  const row = person as any;
  if (row.emailVerification !== "pending") return Response.json({ ok: true, verified: true });
  const last = row.emailCodeSentAt ? new Date(row.emailCodeSentAt).getTime() : 0;
  if (Date.now() - last < RESEND_MS) {
    return said(429, "TOO_SOON", `A code was just sent. You can ask for another in ${Math.ceil((RESEND_MS - (Date.now() - last)) / 1000)} seconds.`);
  }
  const code = String(randomInt(0, 1_000_000)).padStart(6, "0");
  await db.update(users).set({
    emailCodeHash: digest(code), emailCodeExpiresAt: new Date(Date.now() + TTL_MS),
    emailCodeSentAt: new Date(), emailCodeAttempts: 0,
  } as any).where(eq(users.id, row.id));
  const wf = await import("@/lib/workflows");
  wf.registerDefaultActions();
  const send = wf.getActionHandler("send_email");
  let notice: string | undefined;
  if (send) {
    const out: any = await send({
      to: row.email, toTheirOwnAddress: true, subject: `${code} is your verification code`,
      body: `Your verification code is ${code}. It expires in 10 minutes. If you did not create an account, ignore this email.`,
    }, { input: {}, variables: {}, log: [] } as any);
    if (!out?.sent) notice = String(out?.notice ?? out?.reason ?? "the code could not be sent: no email service is connected");
  } else {
    notice = "the code could not be sent: no email service is connected";
  }
  return Response.json({ ok: true, sentTo: row.email, ...(notice ? { notice } : {}) });
}

export async function PUT(request: Request): Promise<Response> {
  const person = await me();
  if (!person) return said(401, "UNAUTHORIZED", "Sign in to verify your email.");
  const row = person as any;
  if (row.emailVerification !== "pending") return Response.json({ ok: true, verified: true });
  let code = "";
  try { code = String((await request.json())?.code ?? "").replace(/\D/g, ""); } catch { /* no body */ }
  if (code.length !== 6) return said(400, "VALIDATION_ERROR", "Enter the 6-digit code from the email.");
  if (!row.emailCodeHash || !row.emailCodeExpiresAt || new Date(row.emailCodeExpiresAt).getTime() < Date.now()) {
    return said(410, "EXPIRED", "That code has expired. Ask for a new one.");
  }
  if (Number(row.emailCodeAttempts ?? 0) >= ATTEMPTS) {
    return said(429, "TOO_MANY", "Too many wrong codes. Ask for a new one.");
  }
  if (digest(code) !== row.emailCodeHash) {
    await db.update(users).set({ emailCodeAttempts: Number(row.emailCodeAttempts ?? 0) + 1 } as any).where(eq(users.id, row.id));
    const left = ATTEMPTS - Number(row.emailCodeAttempts ?? 0) - 1;
    return said(400, "WRONG_CODE", left > 0 ? `That code is not right. ${left} ${left === 1 ? "try" : "tries"} left.` : "Too many wrong codes. Ask for a new one.");
  }
  await db.update(users).set({
    emailVerification: "verified", emailCodeHash: null, emailCodeExpiresAt: null, emailCodeAttempts: 0,
  } as any).where(eq(users.id, row.id));
  return Response.json({ ok: true, verified: true });
}
