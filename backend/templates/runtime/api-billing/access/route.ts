/**
 * GET /api/billing/access?next=/path — the middleware sends a signed-in person
 * here when their access token is missing or ran out. Their subscription is
 * checked (and the gateway asked when its period ran out unheard); with
 * access they go on to `next`, without it to the plans. Forge runtime.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";
import { accessCookie, basePath, originOf, person, safeNext } from "../_session";

export const runtime = "nodejs";

export async function GET(req: Request) {
  await initializeRuntime();
  const url = new URL(req.url);
  const next = safeNext(url.searchParams.get("next"));
  // A CALL FROM THE APP'S OWN PAGES (`api=1`): answered as an API is, and
  // sent back to what it asked for — a paying subscriber's open dashboard
  // was told "Choose a plan" by every call once their access token ran out.
  const api = url.searchParams.get("api") === "1";
  const home = `${originOf(req)}${basePath()}`;
  const who = await person();
  if (!who) return api ? NextResponse.json({ error: { code: "UNAUTHORIZED", message: "Sign in to use this." } }, { status: 401 })
    : NextResponse.redirect(`${home}/login`, 303);
  const billing = await import("@/lib/payments/billing");
  const { ok, row } = await billing.hasAccess(who.id);
  if (!ok) return api ? NextResponse.json({ error: { code: "SUBSCRIPTION_REQUIRED", message: "Choose a plan to use this." } }, { status: 402 })
    : NextResponse.redirect(`${home}/billing?required=1&next=${encodeURIComponent(next)}`, 303);
  const token = billing.accessToken(who.id, row);
  // No token can be signed (the app's secret is not set): sent back, it would
  // come here again for ever.
  if (!token) return NextResponse.json({ error: "Access could not be confirmed: the app's sign-in secret is not set." }, { status: 503 });
  const res = NextResponse.redirect(`${home}${next}`, api ? 307 : 303);
  accessCookie(res, token);
  return res;
}
