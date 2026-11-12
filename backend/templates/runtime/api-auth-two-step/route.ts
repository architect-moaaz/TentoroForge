/**
 * Two-step sign-in, turned on or off by the signed-in person themselves.
 *
 * GET  /api/auth/two-step                 — { on, email }
 * POST /api/auth/two-step { on }          — mail a code to the person's own
 *                                           address (`sentTo`; `wait` when one
 *                                           went out under thirty seconds ago)
 * PUT  /api/auth/two-step { code, on, remember? }
 *                                         — the code checked, then two-step set
 *                                           to `on`; `remember` trusts this
 *                                           browser for thirty days
 *
 * Either way needs the code: turning it on proves the address can receive
 * one, turning it off is not something a borrowed session may do quietly.
 * The code is the guard's (`lib/sign-in-guard.ts`): a keyed digest, ten
 * minutes, five tries. Once on, `auth.ts` asks for a code after every
 * password on a browser not trusted.
 *
 * Forge runtime — do not remove.
 */
import { eq } from "drizzle-orm";
import { db } from "@/db";
import { users } from "@/db/schema/user";
import { auth } from "@/auth";
import * as guard from "@/lib/sign-in-guard";

export const runtime = "nodejs";

const said = (status: number, code: string, message: string) => Response.json({ error: { code, message } }, { status });

async function me(): Promise<guard.Person | null> {
  const session = await auth();
  const id = (session?.user as { id?: string } | undefined)?.id;
  return id ? guard.readPerson(String(id)) : null;
}

export async function GET(): Promise<Response> {
  const person = await me();
  if (!person) return said(401, "UNAUTHORIZED", "Sign in to see this.");
  return Response.json({ on: person.twoStep === true, email: person.email });
}

export async function POST(): Promise<Response> {
  const person = await me();
  if (!person) return said(401, "UNAUTHORIZED", "Sign in to get a code.");
  const sent = await guard.sendCode(person, "two_step");
  if (sent.wait) return said(429, "TOO_SOON", `A code was just sent. You can ask for another in ${sent.wait} seconds.`);
  return Response.json({ ok: true, sentTo: sent.sentTo, ...(sent.notice ? { notice: sent.notice } : {}) });
}

export async function PUT(request: Request): Promise<Response> {
  const person = await me();
  if (!person) return said(401, "UNAUTHORIZED", "Sign in to change two-step sign-in.");
  let body: { code?: unknown; on?: unknown; remember?: unknown } = {};
  try { body = (await request.json()) ?? {}; } catch { /* no body */ }
  if (typeof body.on !== "boolean") return said(400, "VALIDATION_ERROR", "Say whether two-step sign-in is to be on or off.");
  const check = await guard.checkCode(person, "two_step", body.code);
  if (!check.ok) {
    const status = check.code === "MALFORMED" ? 400 : check.code === "EXPIRED" ? 410 : check.code === "TOO_MANY" ? 429 : 400;
    return said(status, check.code === "MALFORMED" ? "VALIDATION_ERROR" : check.code, guard.codeProblem(check));
  }
  await db.update(users).set({ twoStep: body.on } as any).where(eq(users.id, person.id));
  if (body.on && body.remember === true) await guard.trustThisBrowser(person);
  return Response.json({ ok: true, on: body.on });
}
