/**
 * GET /api/pay/return?payment=<id> — where a gateway sends a payer back after
 * a one-time payment (Stripe's session, PayPal's approval). The payment is
 * confirmed with the gateway — PayPal's is captured here — and the payer is
 * sent on to the page the process named, as the ledger holds it (never an
 * address from the request). Outside the sign-in gate: a guest's checkout
 * returns here too, and nothing here trusts the request. Forge runtime.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";

export const runtime = "nodejs";

export async function GET(req: Request) {
  await initializeRuntime();
  const url = new URL(req.url);
  const id = String(url.searchParams.get("payment") ?? "");
  const cancelled = url.searchParams.get("cancelled") === "1";
  const pay = await import("@/lib/payments");
  const row = id ? await pay.ledgerGet(id) : null;
  if (!row) return NextResponse.json({ error: "no such payment" }, { status: 404 });
  const params = Object.fromEntries(url.searchParams.entries());
  // The gateway is asked either way: a payer who cancelled in one tab may have paid in another.
  const out = await pay.confirmPayment(row.id, params);
  let status = out.row?.status ?? row.status;
  if (cancelled && status === "pending") {
    // BACK WITHOUT PAYING, written down as such; a payment made later still
    // settles it (`MOVES.succeeded` takes a cancelled one).
    if (await pay.ledgerMove(row.id, "cancelled")) status = "cancelled";
  }
  const target = status === "succeeded" ? row.success_url : row.cancel_url ?? row.success_url;
  if (!target) return NextResponse.json({ status });
  const dest = new URL(target);
  dest.searchParams.set("payment", row.id);
  dest.searchParams.set("status", status);
  if (cancelled) dest.searchParams.set("cancelled", "1");
  return NextResponse.redirect(dest.toString(), 303);
}
