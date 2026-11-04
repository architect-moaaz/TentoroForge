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
  const home = `${originOf(req)}${basePath()}`;
  const who = await person();
  if (!who) return NextResponse.redirect(`${home}/login`, 303);
  const billing = await import("@/lib/payments/billing");
  const { ok, row } = await billing.hasAccess(who.id);
  if (!ok) return NextResponse.redirect(`${home}/billing?required=1&next=${encodeURIComponent(next)}`, 303);
  const res = NextResponse.redirect(`${home}${next}`, 303);
  accessCookie(res, billing.accessToken(who.id, row));
  return res;
}
