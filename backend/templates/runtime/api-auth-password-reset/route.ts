/**
 * Forgot password: a six-digit code by email, then the code and a new password.
 *
 * POST /api/auth/password-reset { email }                  — mail a code
 * PUT  /api/auth/password-reset { email, code, password }  — set the password
 *
 * THE SAME ANSWER WHETHER OR NOT THE ADDRESS HAS AN ACCOUNT: the POST always
 * says a code is on its way to the address typed, and every failed PUT says
 * the code is not right or has expired — so neither tells a stranger who
 * has an account here. Whether the mail actually left is written to the
 * server's log, not the answer.
 *
 * The code is the guard's (`lib/sign-in-guard.ts`): a keyed digest, ten
 * minutes, five tries, a new one at most every thirty seconds. A password set
 * this way lifts a sign-in pause, proves the address, and signs the account
 * out everywhere — every session and every trusted browser.
 *
 * Forge runtime — do not remove.
 */
import bcrypt from "bcryptjs";
import { eq, sql } from "drizzle-orm";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { policy } from "@/lib/sign-in";
import * as guard from "@/lib/sign-in-guard";

export const runtime = "nodejs";

const MIN_LENGTH = 6;
const said = (status: number, code: string, message: string) => Response.json({ error: { code, message } }, { status });
const NOT_RIGHT = "That code is not right or has expired. Ask for a new one if it keeps failing.";

async function personByEmail(email: string): Promise<guard.Person | null> {
  // Any case: an address is one address however it was typed at sign-up.
  const [row] = await db.select().from(users).where(sql`lower(${users.email}) = ${email}`).limit(1);
  return (row as guard.Person | undefined) ?? null;
}

async function bodyOf(request: Request): Promise<Record<string, unknown>> {
  try { return ((await request.json()) ?? {}) as Record<string, unknown>; } catch { return {}; }
}

export async function POST(request: Request): Promise<Response> {
  if (policy().password === false) return said(404, "NOT_OFFERED", "This application does not sign people in with a password.");
  const email = String((await bodyOf(request)).email ?? "").trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return said(400, "VALIDATION_ERROR", "Give the email address you sign in with.");
  try {
    const person = await personByEmail(email);
    if (person && !("isActive" in person && person.isActive === false)) {
      const sent = await guard.sendCode(person, "reset");
      if (sent.notice) console.warn(`[auth] a password reset code was not emailed: ${sent.notice}`);
    }
  } catch (err) {
    console.error("[auth] password reset:", err);
  }
  return Response.json({ ok: true, sentTo: email, expiresInMinutes: guard.CODE_TTL_MS / 60_000, resendAfterSeconds: guard.RESEND_MS / 1000 });
}

export async function PUT(request: Request): Promise<Response> {
  if (policy().password === false) return said(404, "NOT_OFFERED", "This application does not sign people in with a password.");
  const body = await bodyOf(request);
  const email = String(body.email ?? "").trim().toLowerCase();
  const password = String(body.password ?? "");
  const code = String(body.code ?? "").replace(/\D/g, "");
  if (code.length !== 6) return said(400, "VALIDATION_ERROR", "Enter the 6-digit code from the email.");
  if (password.length < MIN_LENGTH) return said(400, "VALIDATION_ERROR", `Choose a password of at least ${MIN_LENGTH} characters.`);
  const person = email ? await personByEmail(email) : null;
  if (!person || ("isActive" in person && person.isActive === false)) return said(400, "WRONG_CODE", NOT_RIGHT);
  const check = await guard.checkCode(person, "reset", code);
  if (!check.ok) return said(400, "WRONG_CODE", NOT_RIGHT);
  await db.update(users).set(guard.afterReset(person, await bcrypt.hash(password, 12)) as any).where(eq(users.id, person.id));
  return Response.json({ ok: true, email: person.email });
}
