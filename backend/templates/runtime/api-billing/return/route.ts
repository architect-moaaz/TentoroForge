/**
 * GET /api/billing/return?subscription=<id> — where a gateway sends a new
 * subscriber back. The subscription is read from the gateway (never taken
 * from the address), written down, and the person sent to their billing page
 * — with the access the middleware reads when it is now theirs. Forge runtime.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";
import { accessCookie, basePath, originOf, person } from "../_session";

export const runtime = "nodejs";

export async function GET(req: Request) {
  await initializeRuntime();
  const url = new URL(req.url);
  const to = (q: string) => `${originOf(req)}${basePath()}/billing${q}`;
  const who = await person();
  if (!who) return NextResponse.redirect(`${originOf(req)}${basePath()}/login`, 303);
  const id = String(url.searchParams.get("subscription") ?? "");
  const billing = await import("@/lib/payments/billing");
  try {
    const params = Object.fromEntries(url.searchParams.entries());
    const row = await billing.confirmReturn(id, who.id, params);
    if (!row) return NextResponse.redirect(to("?problem=unknown"), 303);
    const ok = billing.grants(row);
    const res = NextResponse.redirect(to(ok ? "?welcome=1" : "?pending=1"), 303);
    accessCookie(res, billing.accessToken(who.id, row));
    return res;
  } catch (err) {
    console.error("[billing] return failed:", err);
    return NextResponse.redirect(to("?problem=check"), 303);
  }
}
