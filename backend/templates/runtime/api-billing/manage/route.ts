/**
 * POST /api/billing/manage — the gateway's own page where the subscriber
 * changes their card, when the gateway has one (Stripe); otherwise null and
 * the app's billing page is where it is managed. Forge runtime.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";
import { basePath, fromThisApp, originOf, person } from "../_session";

export const runtime = "nodejs";

export async function POST(req: Request) {
  if (!fromThisApp(req)) return NextResponse.json({ error: "This can only be done from the app's own billing page." }, { status: 403 });
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
    // A gateway that did not answer is not a gateway with no page for this.
    return NextResponse.json({ url: null, error: "The payment settings page could not be opened just now. Please try again in a moment." }, { status: 502 });
  }
}
