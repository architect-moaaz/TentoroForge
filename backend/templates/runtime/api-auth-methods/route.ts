/**
 * GET /api/auth/methods — how a person may sign in here: password, a magic
 * link, and each identity provider with whether it is CONNECTED in this
 * environment (its names set). The form offers what is connected and says
 * what is declared but not; nothing here is a secret, only names and booleans.
 *
 * POST /api/auth/methods {as, account} — A NEW PERSON GOING OUT TO A PROVIDER
 * TO SIGN UP: the role they chose on the form ("I am joining as…") and the
 * account fields it starts them with, kept in a short-lived cookie of this
 * app's own so the provider's return makes the account the form would have.
 * Without it a recruiter who signed up with Google came back a candidate
 * (DITANS, 2026-11-16). Only a role signup offers is kept; the cookie is read
 * once, on that person's first arrival, and only when no login exists yet.
 *
 * Forge runtime — do not remove.
 */
import { cookies } from "next/headers";
import { methods, signupIntentCookie, offeredSignupRole } from "@/lib/sign-in";
import { isSecure } from "@/lib/session-cookie";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<Response> {
  return Response.json(methods());
}

export async function POST(request: Request): Promise<Response> {
  let body: Record<string, unknown> = {};
  try { body = (await request.json()) as Record<string, unknown>; } catch { body = {}; }
  const as = offeredSignupRole(body.as);
  if (body.as != null && body.as !== "" && !as) {
    return Response.json({ error: { code: "VALIDATION_ERROR", message: "That kind of account cannot be made here." } }, { status: 400 });
  }
  const account = body.account && typeof body.account === "object" && !Array.isArray(body.account) ? body.account : {};
  const value = Buffer.from(JSON.stringify({ as, account }), "utf8").toString("base64url");
  if (value.length > 3000) {
    return Response.json({ error: { code: "VALIDATION_ERROR", message: "Too much to carry through the sign-in." } }, { status: 400 });
  }
  const jar = await cookies();
  jar.set(signupIntentCookie(), value, { httpOnly: true, sameSite: "lax", secure: isSecure(), path: "/", maxAge: 900 });
  return Response.json({ ok: true });
}
