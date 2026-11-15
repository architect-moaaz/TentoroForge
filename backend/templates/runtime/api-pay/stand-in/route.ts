/**
 * POST /api/pay/stand-in — the stand-in's outcome: "paid" or "failed" for a
 * ledger row the stand-in took, or for a stand-in subscription. Settles the
 * ledger (or the subscription) and puts the same events on the bus a
 * gateway's signed call would, then sends the person to the success or
 * cancel page. Only a stand-in row can be settled here; a real gateway's row
 * is the gateway's to settle. Forge runtime — do not remove.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";

export const runtime = "nodejs";

export async function POST(req: Request): Promise<Response> {
  await initializeRuntime();
  // NOTHING IS SETTLED HERE IN THE LIVE APP: the stand-in's "Paid" charges
  // nobody, and a real gateway settles its own payments.
  const { liveSide } = await import("@/lib/payments");
  if (liveSide()) return NextResponse.json({ error: "Payments are not switched on in this app yet, so nothing was charged." }, { status: 403 });
  const form = await req.formData().catch(() => null);
  const body: any = form ? Object.fromEntries(form.entries()) : await req.json().catch(() => ({}));
  const outcome = String(body?.outcome ?? "paid");
  const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
  if (body?.subscription) {
    const { auth } = await import("@/auth");
    const session = await auth();
    const uid = String((session?.user as any)?.id ?? "");
    if (!uid) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
    const billing = await import("@/lib/payments/billing");
    const row = await billing.standInSettle(String(body.subscription), uid, outcome === "paid" ? "paid" : "failed");
    if (!row) return NextResponse.json({ error: "no such stand-in subscription" }, { status: 404 });
    const to = `${base}/billing?${billing.grants(row) ? "welcome" : "cancelled"}=1`;
    const res = form ? NextResponse.redirect(new URL(to, req.url), 303) : NextResponse.json({ ok: true, status: row.status, redirect: to });
    const token = billing.accessToken(uid, row);
    if (token) res.cookies.set({ name: "forge_access", value: token.value, httpOnly: true, sameSite: "lax",
      secure: process.env.NODE_ENV === "production", path: base || "/", maxAge: token.maxAge });
    return res;
  }
  const session = String(body?.session ?? body?.sessionId ?? "");
  const pay = await import("@/lib/payments");
  const row = session ? await pay.ledgerGet(session.replace(/^standin_/, "")) : null;
  if (!row) return NextResponse.json({ error: "no such stand-in payment" }, { status: 404 });
  if (row.provider !== "stand_in") return NextResponse.json({ error: "a real gateway settles its own payments" }, { status: 409 });
  const slug = pay.gateways()[0]?.integration ?? "payments";
  await pay.settle(slug, { type: outcome === "paid" ? "payment.succeeded" : "payment.failed", providerRef: String(row.provider_ref ?? session),
    paymentId: row.id, amountMinor: Number(row.amount_minor), currency: row.currency, metadata: {} });
  const to = outcome === "paid" ? row.success_url : row.cancel_url;
  if (form && to) return NextResponse.redirect(to, 303);
  return NextResponse.json({ ok: true, status: outcome === "paid" ? "succeeded" : "failed", redirect: to });
}
