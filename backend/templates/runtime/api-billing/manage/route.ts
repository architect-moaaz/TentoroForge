/**
 * POST /api/billing/manage — the gateway's own page where the subscriber
 * changes their card, when the gateway has one (Stripe); otherwise null and
 * the app's billing page is where it is managed. Forge runtime.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";
import { basePath, originOf, person } from "../_session";

export const runtime = "nodejs";

export async function POST(req: Request) {
  await initializeRuntime();
  const who = await person();
  if (!who) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  const billing = await import("@/lib/payments/billing");
  const row = await billing.current(who.id);
  if (!row) return NextResponse.json({ url: null });
  try {
    return NextResponse.json({ url: await billing.manageUrl(row, `${originOf(req)}${basePath()}/billing`) });
  } catch (err) {
    console.error("[billing] manage failed:", err);
    return NextResponse.json({ url: null });
  }
}
