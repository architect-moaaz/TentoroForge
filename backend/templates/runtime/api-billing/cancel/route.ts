/**
 * POST /api/billing/cancel {now?} — end the signed-in person's subscription,
 * at the end of what they paid for unless they ask for now. Forge runtime.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";
import { accessCookie, fromThisApp, person } from "../_session";

export const runtime = "nodejs";

// ISO, whatever the driver handed back: Safari refuses Postgres's own text form.
const iso = (v: unknown) => (v ? new Date(v as string).toISOString() : null);

export async function POST(req: Request) {
  if (!fromThisApp(req)) return NextResponse.json({ error: "This can only be done from the app's own billing page." }, { status: 403 });
  await initializeRuntime();
  const who = await person();
  if (!who) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  const body: any = await req.json().catch(() => ({}));
  const billing = await import("@/lib/payments/billing");
  const row = await billing.current(who.id);
  // A plan the gateway still charges can be ended, its grace over or not
  // (a card retried, a plan paused).
  const going = row && (billing.grants(row) || ["active", "trialing", "past_due", "paused"].includes(String(row.status)));
  if (!row || !going) return NextResponse.json({ error: "You have no active subscription." }, { status: 404 });
  try {
    const after = await billing.cancel(row, !body?.now);
    const res = NextResponse.json({ ok: true, status: after.status, cancelAtPeriodEnd: after.cancel_at_period_end, currentPeriodEnd: iso(after.current_period_end) });
    // Ended now: closed now, in this browser too.
    accessCookie(res, billing.accessToken(who.id, after));
    return res;
  } catch (err) {
    console.error("[billing] cancel failed:", err);
    return NextResponse.json({ error: "The subscription could not be cancelled just now. Please try again." }, { status: 502 });
  }
}
