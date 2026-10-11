/**
 * Stripe, through its REST API with plain `fetch` — no SDK in every app.
 * Checkout Sessions take the payment on Stripe's page; a signed event
 * (`Stripe-Signature: t=<unix>,v1=<hmac>` over `<t>.<body>`) says what
 * happened; Connect Express accounts receive split payouts.
 */
import crypto from "node:crypto";
import type { CheckoutInput, NormalizedEvent, PaymentAdapter, PaymentStatus, Secrets } from "./types";

const API = "https://api.stripe.com/v1";
const TOLERANCE_S = 300;

function form(obj: Record<string, unknown>, prefix = ""): string[] {
  const out: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === null) continue;
    const key = prefix ? `${prefix}[${k}]` : k;
    if (Array.isArray(v)) v.forEach((item, i) => out.push(...(typeof item === "object" ? form(item as any, `${key}[${i}]`) : [`${encodeURIComponent(`${key}[${i}]`)}=${encodeURIComponent(String(item))}`])));
    else if (typeof v === "object") out.push(...form(v as any, key));
    else out.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(v))}`);
  }
  return out;
}

async function call(method: "GET" | "POST", path: string, secret: string, body?: Record<string, unknown>): Promise<any> {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${secret}`, "Content-Type": "application/x-www-form-urlencoded" },
    body: body ? form(body).join("&") : undefined,
  });
  const json: any = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`Stripe ${method} ${path} answered ${res.status}: ${json?.error?.message ?? "no message"}`);
  return json;
}

function statusOf(session: any): PaymentStatus {
  const ps = String(session?.payment_status ?? "");
  if (ps === "paid") return "succeeded";
  if (String(session?.status) === "expired") return "cancelled";
  return "pending";
}

export const stripeAdapter: PaymentAdapter = {
  provider: "stripe",
  keys: { secret: "STRIPE_SECRET_KEY", webhookSecret: "STRIPE_WEBHOOK_SECRET", publishable: "STRIPE_PUBLISHABLE_KEY" },

  async createCheckout(input: CheckoutInput, secrets: Secrets) {
    const items = input.lineItems?.length
      ? input.lineItems.map((li) => ({ quantity: li.quantity, price_data: { currency: input.currency.toLowerCase(),
          unit_amount: li.amountMinor, product_data: { name: li.name } } }))
      : [{ quantity: 1, price_data: { currency: input.currency.toLowerCase(), unit_amount: input.amountMinor,
          product_data: { name: input.description || "Payment" } } }];
    const body: Record<string, unknown> = {
      mode: "payment",
      line_items: items,
      success_url: input.successUrl,
      cancel_url: input.cancelUrl,
      metadata: { ...input.metadata, paymentId: input.paymentId },
      ...(input.customerEmail ? { customer_email: input.customerEmail } : {}),
    };
    if (input.transfer?.destinationAccountRef) {
      body.payment_intent_data = {
        transfer_data: { destination: input.transfer.destinationAccountRef },
        ...(input.transfer.applicationFeePercent
          ? { application_fee_amount: Math.round(input.amountMinor * (input.transfer.applicationFeePercent / 100)) } : {}),
      };
    }
    const session = await call("POST", "/checkout/sessions", secrets.secret, body);
    return { url: String(session.url), sessionId: String(session.id), providerRef: String(session.id) };
  },

  async refund(input, secrets) {
    const session = await call("GET", `/checkout/sessions/${encodeURIComponent(input.providerRef)}`, secrets.secret);
    const intent = String(session?.payment_intent ?? "");
    if (!intent) throw new Error("the payment has no intent to refund (not paid?)");
    const refund = await call("POST", "/refunds", secrets.secret, { payment_intent: intent,
      ...(input.amountMinor ? { amount: input.amountMinor } : {}) });
    const st = String(refund.status);
    return { refundId: String(refund.id), status: st === "succeeded" ? "succeeded" : st === "failed" ? "failed" : "pending" };
  },

  async retrieve(providerRef, secrets) {
    const session = await call("GET", `/checkout/sessions/${encodeURIComponent(providerRef)}`, secrets.secret);
    return { status: statusOf(session), amountMinor: Number(session.amount_total ?? 0), currency: String(session.currency ?? "").toUpperCase() };
  },

  verifyWebhook(rawBody, headers, webhookSecret) {
    const header = headers.get("stripe-signature") ?? "";
    const parts: Record<string, string[]> = {};
    for (const p of header.split(",")) {
      const [k, ...v] = p.trim().split("=");
      (parts[k] ??= []).push(v.join("="));
    }
    const t = Number(parts.t?.[0]);
    const sigs = parts.v1 ?? [];
    if (!Number.isFinite(t) || !sigs.length) return { ok: false, reason: "no signature" };
    if (Math.abs(Math.floor(Date.now() / 1000) - t) > TOLERANCE_S) return { ok: false, reason: "stale signature" };
    const expected = crypto.createHmac("sha256", webhookSecret).update(`${t}.${rawBody}`).digest("hex");
    const ok = sigs.some((s) => s.length === expected.length && crypto.timingSafeEqual(Buffer.from(s), Buffer.from(expected)));
    if (!ok) return { ok: false, reason: "bad signature" };
    let eventId: string | undefined;
    try { eventId = String(JSON.parse(rawBody)?.id ?? "") || undefined; } catch { /* no id */ }
    return { ok: true, eventId, timestamp: t };
  },

  normalizeEvent(raw) {
    const ev = raw as any;
    const type = String(ev?.type ?? "");
    const obj = ev?.data?.object ?? {};
    const meta: Record<string, string> = Object.fromEntries(Object.entries(obj?.metadata ?? {}).map(([k, v]) => [k, String(v)]));
    const common = { paymentId: meta.paymentId, metadata: meta };
    if (type === "checkout.session.completed" || type === "checkout.session.async_payment_succeeded") {
      if (String(obj.payment_status) !== "paid") return null;
      return { type: "payment.succeeded" as NormalizedEvent, providerRef: String(obj.id), amountMinor: Number(obj.amount_total ?? 0),
        currency: String(obj.currency ?? "").toUpperCase(), ...common };
    }
    if (type === "checkout.session.async_payment_failed" || type === "checkout.session.expired") {
      return { type: "payment.failed" as NormalizedEvent, providerRef: String(obj.id), ...common };
    }
    if (type === "charge.refunded") {
      return { type: "refund.succeeded" as NormalizedEvent, providerRef: String(obj.payment_intent ?? obj.id),
        amountMinor: Number(obj.amount_refunded ?? 0), currency: String(obj.currency ?? "").toUpperCase(), ...common };
    }
    if (type === "account.updated") {
      return { type: "account.updated" as NormalizedEvent, providerRef: String(obj.id), ...common };
    }
    return null;
  },

  connect: {
    async createAccount(input, secrets) {
      const acct = await call("POST", "/accounts", secrets.secret, { type: "express", metadata: { reference: input.reference },
        ...(input.email ? { email: input.email } : {}) });
      return { accountRef: String(acct.id) };
    },
    async onboardingLink(input, secrets) {
      const link = await call("POST", "/account_links", secrets.secret, { account: input.accountRef, type: "account_onboarding",
        return_url: input.returnUrl, refresh_url: input.refreshUrl });
      return { url: String(link.url) };
    },
  },
};
