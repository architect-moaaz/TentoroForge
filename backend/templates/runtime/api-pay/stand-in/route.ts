/**
 * POST /api/pay/stand-in — the stand-in's outcome: "paid" or "failed" for a
 * ledger row the stand-in took. Settles the ledger and puts the same event
 * on the bus a provider's signed call would, then sends the person to the
 * success or cancel page. Only a stand-in row can be settled here; a real
 * provider's row is the provider's to settle. Forge runtime — do not remove.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";

export const runtime = "nodejs";

export async function POST(req: Request): Promise<Response> {
  await initializeRuntime();
  const form = await req.formData().catch(() => null);
  const body = form ? Object.fromEntries(form.entries()) : await req.json().catch(() => ({}));
  const session = String(body?.session ?? body?.sessionId ?? "");
  const outcome = String(body?.outcome ?? "paid");
  const pay = await import("@/lib/payments");
  const row = session ? await pay.ledgerGet(session.replace(/^standin_/, "")) : null;
  if (!row) return NextResponse.json({ error: "no such stand-in payment" }, { status: 404 });
  if (row.provider !== "stand_in") return NextResponse.json({ error: "a real provider settles its own payments" }, { status: 409 });
  const { connectedService } = await import("@/lib/integrations/connected");
  const declared = connectedService("take_payment");
  const slug = declared ? String(declared.name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") : "payments";
  await pay.settle(slug, { type: outcome === "paid" ? "payment.succeeded" : "payment.failed", providerRef: String(row.provider_ref ?? session),
    paymentId: row.id, amountMinor: Number(row.amount_minor), currency: row.currency, metadata: {} });
  const to = outcome === "paid" ? row.success_url : row.cancel_url;
  if (form && to) return NextResponse.redirect(to, 303);
  return NextResponse.json({ ok: true, status: outcome === "paid" ? "succeeded" : "failed", redirect: to });
}
