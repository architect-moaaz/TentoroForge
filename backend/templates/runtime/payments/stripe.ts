/**
 * Stripe, through its REST API with plain `fetch` — no SDK in every app.
 * Checkout Sessions take the payment (or start the subscription) on Stripe's
 * page; a signed event (`Stripe-Signature: t=<unix>,v1=<hmac>` over
 * `<t>.<body>`) or a read of the session when the payer returns says what
 * happened; the Billing Portal is where a subscriber manages their card;
 * Connect Express accounts receive split payouts.
 */
import crypto from "node:crypto";
import { apiBase, call as http, GatewayError } from "./http";
import type { CheckoutInput, NormalizedEvent, PaymentAdapter, PaymentStatus, PlanSpec, Secrets, SubSnapshot, SubscriptionStatus } from "./types";

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

async function call(method: "GET" | "POST" | "DELETE", path: string, secret: string, body?: Record<string, unknown>, idempotencyKey?: string): Promise<any> {
  try {
    return await http("Stripe", `${apiBase("stripe")}/v1${path}`, {
      method,
      headers: { Authorization: `Bearer ${secret}`, ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}) },
      ...(body ? { form: form(body).join("&") } : {}),
    });
  } catch (err: any) {
    // Stripe's own status and body kept: what it refused (an unknown price, a card) is read off them.
    throw new GatewayError(`Stripe ${method} ${path} answered ${err?.status ?? "no answer"}: ${err?.body?.error?.message ?? err?.message ?? "no message"}`,
      Number(err?.status ?? 0), err?.body ?? null);
  }
}

function statusOf(session: any): PaymentStatus {
  const ps = String(session?.payment_status ?? "");
  if (ps === "paid" || ps === "no_payment_required") return "succeeded";
  if (String(session?.status) === "expired") return "cancelled";
  return "pending";
}

function subStatus(s: string): SubscriptionStatus {
  if (s === "active") return "active";
  if (s === "trialing") return "trialing";
  if (s === "past_due" || s === "unpaid") return "past_due";
  if (s === "paused") return "paused";
  if (s === "canceled") return "cancelled";
  if (s === "incomplete_expired") return "expired";
  return "incomplete";
}

function periodEnd(sub: any): string | null {
  // AN ENDED SUBSCRIPTION RAN UNTIL IT ENDED: at once for one cancelled now,
  // at the period's end for one that waited. The period it was billed for
  // would open the app past a "cancel now".
  const ended = Number(sub?.ended_at ?? 0);
  if (String(sub?.status ?? "") === "canceled" && ended > 0) return new Date(ended * 1000).toISOString();
  // Newer API versions keep the period on each item; older ones on the subscription.
  const t = Number(sub?.current_period_end ?? sub?.items?.data?.[0]?.current_period_end ?? 0);
  return t > 0 ? new Date(t * 1000).toISOString() : null;
}

function snapshot(sub: any): SubSnapshot {
  return { status: subStatus(String(sub?.status ?? "")), currentPeriodEnd: periodEnd(sub),
    cancelAtPeriodEnd: Boolean(sub?.cancel_at_period_end) || Boolean(sub?.cancel_at),
    providerRef: String(sub?.id ?? ""), customerRef: sub?.customer ? String(typeof sub.customer === "object" ? sub.customer.id : sub.customer) : undefined };
}

/** A session id or a subscription id, to the subscription. */
async function subscriptionOf(providerRef: string, secret: string): Promise<any | null> {
  if (providerRef.startsWith("cs_")) {
    const session = await call("GET", `/checkout/sessions/${encodeURIComponent(providerRef)}`, secret);
    const sub = session?.subscription;
    if (!sub) return null;
    return typeof sub === "object" ? sub : await call("GET", `/subscriptions/${encodeURIComponent(String(sub))}`, secret);
  }
  return await call("GET", `/subscriptions/${encodeURIComponent(providerRef)}`, secret);
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
      client_reference_id: input.paymentId,
      metadata: { ...input.metadata, paymentId: input.paymentId },
      payment_intent_data: { metadata: { paymentId: input.paymentId } },
      ...(input.customerEmail ? { customer_email: input.customerEmail } : {}),
    };
    if (input.transfer?.destinationAccountRef) {
      body.payment_intent_data = {
        metadata: { paymentId: input.paymentId },
        transfer_data: { destination: input.transfer.destinationAccountRef },
        ...(input.transfer.applicationFeePercent
          ? { application_fee_amount: Math.round(input.amountMinor * (input.transfer.applicationFeePercent / 100)) } : {}),
      };
    }
    const session = await call("POST", "/checkout/sessions", secrets.secret, body, `pay-${input.paymentId}`);
    return { url: String(session.url), sessionId: String(session.id), providerRef: String(session.id) };
  },

  async confirm(row, _params, secrets) {
    const session = await call("GET", `/checkout/sessions/${encodeURIComponent(String(row.providerRef))}`, secrets.secret);
    return { status: statusOf(session), providerRef: String(session.id), amountMinor: Number(session.amount_total ?? 0),
      currency: String(session.currency ?? "").toUpperCase(),
      metadata: (session.payment_intent ? { paymentIntent: String(typeof session.payment_intent === "object" ? session.payment_intent.id : session.payment_intent) } : {}) as Record<string, string> };
  },

  async refund(input, secrets) {
    let intent = String((input.metadata as any)?.paymentIntent ?? "");
    if (!intent) {
      const session = await call("GET", `/checkout/sessions/${encodeURIComponent(input.providerRef)}`, secrets.secret);
      intent = String(session?.payment_intent ?? "");
    }
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
    if (type.startsWith("checkout.session.") && String(obj.mode) === "subscription") {
      if (!obj.subscription) return null;
      return { type: "subscription.updated" as NormalizedEvent, providerRef: String(typeof obj.subscription === "object" ? obj.subscription.id : obj.subscription),
        subscriptionId: obj.client_reference_id ? String(obj.client_reference_id) : meta.subscriptionId, metadata: meta };
    }
    if (type === "checkout.session.completed" || type === "checkout.session.async_payment_succeeded") {
      if (String(obj.payment_status) !== "paid") return null;
      return { type: "payment.succeeded" as NormalizedEvent, providerRef: String(obj.id), amountMinor: Number(obj.amount_total ?? 0),
        currency: String(obj.currency ?? "").toUpperCase(), ...common, paymentId: meta.paymentId ?? (obj.client_reference_id ? String(obj.client_reference_id) : undefined) };
    }
    if (type === "checkout.session.async_payment_failed" || type === "checkout.session.expired") {
      return { type: "payment.failed" as NormalizedEvent, providerRef: String(obj.id), ...common };
    }
    if (type === "charge.refunded") {
      const pid = String(obj.metadata?.paymentId ?? "");
      return { type: "refund.succeeded" as NormalizedEvent, providerRef: String(obj.payment_intent ?? obj.id),
        amountMinor: Number(obj.amount_refunded ?? 0), currency: String(obj.currency ?? "").toUpperCase(), ...common, ...(pid ? { paymentId: pid } : {}) };
    }
    if (type.startsWith("customer.subscription.")) {
      return { type: "subscription.updated" as NormalizedEvent, providerRef: String(obj.id), subscriptionId: meta.subscriptionId, metadata: meta };
    }
    if (type === "invoice.paid" || type === "invoice.payment_failed" || type === "invoice.payment_action_required") {
      const sub = obj.subscription ?? obj.parent?.subscription_details?.subscription;
      if (!sub) return null;
      const subMeta = obj.subscription_details?.metadata ?? obj.parent?.subscription_details?.metadata ?? {};
      return { type: "subscription.updated" as NormalizedEvent, providerRef: String(typeof sub === "object" ? sub.id : sub),
        subscriptionId: subMeta.subscriptionId ? String(subMeta.subscriptionId) : undefined, metadata: meta };
    }
    if (type === "account.updated") {
      return { type: "account.updated" as NormalizedEvent, providerRef: String(obj.id), ...common };
    }
    return null;
  },

  subscriptions: {
    async ensurePlan(spec: PlanSpec, secrets: Secrets) {
      // A price is found again by its lookup key — the same plan at the same
      // price is one price at Stripe however many times the app is deployed.
      const found = await call("GET", `/prices?active=true&limit=1&lookup_keys[0]=${encodeURIComponent(spec.key)}`, secrets.secret);
      const existing = found?.data?.[0];
      if (existing?.id) return String(existing.id);
      const price = await call("POST", "/prices", secrets.secret, {
        // An archived price keeps its lookup key; the new one takes it over.
        currency: spec.currency.toLowerCase(), unit_amount: spec.amountMinor, lookup_key: spec.key, transfer_lookup_key: true,
        recurring: { interval: spec.interval, interval_count: spec.intervalCount },
        product_data: { name: spec.name, metadata: { planId: spec.planId } },
        metadata: { planId: spec.planId },
      }, `price-${spec.key}`);
      return String(price.id);
    },
    async start(input, secrets) {
      const session = await call("POST", "/checkout/sessions", secrets.secret, {
        mode: "subscription",
        line_items: [{ price: input.planRef, quantity: 1 }],
        success_url: input.successUrl,
        cancel_url: input.cancelUrl,
        client_reference_id: input.subscriptionId,
        metadata: { ...input.metadata, subscriptionId: input.subscriptionId },
        subscription_data: { metadata: { ...input.metadata, subscriptionId: input.subscriptionId },
          ...(input.plan.trialDays > 0 ? { trial_period_days: input.plan.trialDays } : {}) },
        ...(input.customerEmail ? { customer_email: input.customerEmail } : {}),
      }, `sub-${input.subscriptionId}`);
      return { url: String(session.url), providerRef: String(session.id) };
    },
    async retrieve(providerRef, secrets) {
      const sub = await subscriptionOf(providerRef, secrets.secret);
      if (!sub) {
        const session = providerRef.startsWith("cs_") ? await call("GET", `/checkout/sessions/${encodeURIComponent(providerRef)}`, secrets.secret) : null;
        return { status: String(session?.status) === "expired" ? "expired" : "incomplete", currentPeriodEnd: null, cancelAtPeriodEnd: false, providerRef };
      }
      return snapshot(sub);
    },
    async cancel(providerRef, atPeriodEnd, secrets) {
      const sub = await subscriptionOf(providerRef, secrets.secret);
      if (!sub) throw new Error("there is no subscription at Stripe to cancel yet");
      const out = atPeriodEnd
        ? await call("POST", `/subscriptions/${encodeURIComponent(String(sub.id))}`, secrets.secret, { cancel_at_period_end: "true" })
        : await call("DELETE", `/subscriptions/${encodeURIComponent(String(sub.id))}`, secrets.secret);
      return snapshot(out);
    },
    async manageUrl(snap, returnUrl, secrets) {
      if (!snap.customerRef) return null;
      try {
        const portal = await call("POST", "/billing_portal/sessions", secrets.secret, { customer: snap.customerRef, return_url: returnUrl });
        return portal?.url ? String(portal.url) : null;
      } catch {
        // No portal configured in this Stripe account's dashboard: the app's own page manages it.
        return null;
      }
    },
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
