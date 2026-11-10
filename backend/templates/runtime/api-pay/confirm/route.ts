/**
 * POST /api/pay/confirm — Razorpay's Checkout window answered. Its signature
 * is checked on the server against what the app stored (the order, or the
 * subscription), the payment read from Razorpay, and only then settled.
 *   {payment, razorpay_payment_id, razorpay_order_id, razorpay_signature}
 *   {subscription, razorpay_payment_id, razorpay_subscription_id, razorpay_signature}
 * Forge runtime.
 */
import { NextResponse } from "next/server";
import { initializeRuntime } from "@/lib/runtime-loader";
import { accessCookie, basePath, originOf, person } from "../../billing/_session";

export const runtime = "nodejs";

export async function POST(req: Request) {
  await initializeRuntime();
  const body: any = await req.json().catch(() => ({}));
  const params: Record<string, string> = Object.fromEntries(Object.entries(body ?? {}).map(([k, v]) => [k, String(v ?? "")]));
  if (body?.subscription) {
    const who = await person();
    if (!who) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
    const billing = await import("@/lib/payments/billing");
    try {
      const row = await billing.confirmReturn(String(body.subscription), who.id, params);
      if (!row) return NextResponse.json({ error: "no such subscription" }, { status: 404 });
      const ok = billing.grants(row);
      const res = NextResponse.json({ ok, status: row.status, redirect: `${originOf(req)}${basePath()}/billing?${ok ? "welcome" : "pending"}=1` });
      accessCookie(res, billing.accessToken(who.id, row));
      return res;
    } catch (err) {
      console.error("[pay] subscription confirm failed:", err);
      return NextResponse.json({ error: "The payment could not be confirmed. If money left your account, it will be confirmed shortly." }, { status: 400 });
    }
  }
  const pay = await import("@/lib/payments");
  const out = await pay.confirmPayment(String(body?.payment ?? ""), params);
  if (!out.row) return NextResponse.json({ error: "no such payment" }, { status: 404 });
  const status = out.row.status;
  const target = status === "succeeded" ? out.row.success_url : out.row.cancel_url ?? out.row.success_url;
  let redirect: string | null = null;
  if (status === "pending" && !out.refused && out.row.success_url) {
    // Paid in the window, not yet settled at the gateway: the payer waits, never on the cancel page.
    const wait = new URL(`${basePath()}/pay/confirming`, new URL(out.row.success_url).origin);
    wait.searchParams.set("payment", out.row.id);
    return NextResponse.json({ ok: false, status, redirect: wait.toString() });
  }
  if (target) {
    const dest = new URL(target);
    dest.searchParams.set("payment", out.row.id);
    dest.searchParams.set("status", status);
    redirect = dest.toString();
  }
  return NextResponse.json({ ok: status === "succeeded", status, redirect, ...(out.error ? { error: out.error } : {}) },
    { status: out.error && status !== "succeeded" ? 400 : 200 });
}
