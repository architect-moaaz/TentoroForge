/**
 * GET /api/billing/status — the signed-in person's plan, where it stands and
 * whether it opens the app; refreshes the access the middleware reads.
 * Forge runtime.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";
import { countryOf } from "@/lib/payments/routing";
import { accessCookie, person } from "../_session";

export const runtime = "nodejs";

// ISO, whatever the driver handed back: Postgres's own text form
// ("2026-12-03 12:53:58+00") is read by Chrome and refused by Safari.
const iso = (v: unknown) => (v ? new Date(v as string).toISOString() : null);

export async function GET(req: Request) {
  await initializeRuntime();
  const who = await person();
  if (!who) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  const billing = await import("@/lib/payments/billing");
  const { ok, row } = await billing.hasAccess(who.id);
  const res = NextResponse.json({
    access: ok, required: billing.accessRequired(), plans: billing.subscriptionsOffered() ? billing.plans() : [], ...billing.priceList(countryOf(req.headers)),
    subscription: row ? { id: row.id, plan: row.plan_id, status: row.status, provider: row.provider, currency: row.currency,
      amountMinor: row.amount_minor, interval: row.interval, currentPeriodEnd: iso(row.current_period_end),
      cancelAtPeriodEnd: row.cancel_at_period_end } : null,
  });
  accessCookie(res, billing.accessToken(who.id, row));
  return res;
}
