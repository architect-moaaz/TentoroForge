/**
 * PayPal, through its REST API with plain `fetch` (OAuth client credentials,
 * sandbox or live by `PAYPAL_ENV`). The payer approves on PayPal's own page;
 * the money moves when the application CAPTURES the order on their return
 * (`confirm`) — a capture PayPal declines still answers 201, so the capture's
 * own status is read, never assumed. Subscriptions are a PayPal product and
 * plan, made once per price, and a subscription the payer approves.
 *
 * A webhook is believed only once PayPal itself says so: its
 * `verify-webhook-signature` API, given the transmission headers, the app's
 * webhook id (`PAYPAL_WEBHOOK_ID`) and the event exactly as it arrived.
 */
import { apiBase, basic, call as http } from "./http";
import { toMajor, toMinor } from "./units";
import type { Normalized, NormalizedEvent, PaymentAdapter, PaymentStatus, PlanSpec, Secrets, SubSnapshot, SubscriptionStatus } from "./types";

/** Currencies PayPal takes only as whole numbers (HUF and TWD have decimals elsewhere, not at PayPal). */
const WHOLE_AT_PAYPAL = new Set(["HUF", "JPY", "TWD"]);
const tokens = new Map<string, { token: string; until: number }>();

function base(secrets: Secrets): string {
  return apiBase("paypal", secrets.env);
}

/** The app's minor units as PayPal's decimal string: "12.50", "1200". */
export function money(amountMinor: number, currency: string): string {
  const c = currency.toUpperCase();
  const major = toMajor(amountMinor, c);
  return WHOLE_AT_PAYPAL.has(c) ? String(Math.round(major)) : major.toFixed(2);
}

/** PayPal's decimal string back to the app's minor units. */
export function minorOf(value: string | number, currency: string): number {
  return toMinor(Number(value), currency);
}

async function token(secrets: Secrets): Promise<string> {
  const key = `${base(secrets)}|${secrets.keyId}`;
  const held = tokens.get(key);
  if (held && held.until > Date.now() + 60_000) return held.token;
  const res = await http("PayPal", `${base(secrets)}/v1/oauth2/token`, {
    method: "POST", form: "grant_type=client_credentials",
    headers: { Authorization: basic(String(secrets.keyId ?? ""), secrets.secret) },
  });
  const t = String(res.access_token ?? "");
  tokens.set(key, { token: t, until: Date.now() + Number(res.expires_in ?? 300) * 1000 });
  return t;
}

async function call(method: "GET" | "POST", path: string, secrets: Secrets, json?: unknown, requestId?: string): Promise<any> {
  return http("PayPal", `${base(secrets)}${path}`, {
    method, headers: { Authorization: `Bearer ${await token(secrets)}`, ...(requestId ? { "PayPal-Request-Id": requestId } : {}),
      Prefer: "return=representation" },
    ...(json !== undefined ? { json } : {}),
  });
}

function link(obj: any, ...rels: string[]): string {
  for (const rel of rels) {
    const l = (obj?.links ?? []).find((x: any) => x?.rel === rel);
    if (l?.href) return String(l.href);
  }
  return "";
}

function orderStatus(order: any): { status: PaymentStatus; capture?: any } {
  const capture = order?.purchase_units?.[0]?.payments?.captures?.[0];
  const st = String(capture?.status ?? order?.status ?? "");
  if (st === "COMPLETED") return { status: "succeeded", capture };
  if (st === "DECLINED" || st === "FAILED") return { status: "failed", capture };
  if (st === "REFUNDED") return { status: "refunded", capture };
  if (st === "PARTIALLY_REFUNDED") return { status: "partially_refunded", capture };
  if (st === "VOIDED") return { status: "cancelled", capture };
  return { status: "pending", capture };
}

const UNIT: Record<string, string> = { day: "DAY", week: "WEEK", month: "MONTH", year: "YEAR" };

function subStatus(s: string): SubscriptionStatus {
  if (s === "ACTIVE") return "active";
  if (s === "SUSPENDED") return "past_due";
  if (s === "CANCELLED") return "cancelled";
  if (s === "EXPIRED") return "expired";
  return "incomplete";                 // APPROVAL_PENDING, APPROVED (not yet active)
}

function snapshot(sub: any): SubSnapshot {
  const next = sub?.billing_info?.next_billing_time ?? null;
  return { status: subStatus(String(sub?.status ?? "")), currentPeriodEnd: next ? new Date(String(next)).toISOString() : null,
    cancelAtPeriodEnd: false, providerRef: String(sub?.id ?? ""), customerRef: sub?.subscriber?.payer_id ? String(sub.subscriber.payer_id) : undefined };
}

export const paypalAdapter: PaymentAdapter = {
  provider: "paypal",
  keys: { secret: "PAYPAL_CLIENT_SECRET", webhookSecret: "PAYPAL_WEBHOOK_ID", keyId: "PAYPAL_CLIENT_ID", env: "PAYPAL_ENV" },

  async createCheckout(input, secrets) {
    const items = input.lineItems?.length ? input.lineItems : null;
    const order = await call("POST", "/v2/checkout/orders", secrets, {
      intent: "CAPTURE",
      purchase_units: [{
        reference_id: input.paymentId.slice(0, 256), custom_id: input.paymentId.slice(0, 127),
        description: (input.description || "Payment").slice(0, 127),
        amount: { currency_code: input.currency.toUpperCase(), value: money(input.amountMinor, input.currency),
          ...(items ? { breakdown: { item_total: { currency_code: input.currency.toUpperCase(), value: money(input.amountMinor, input.currency) } } } : {}) },
        ...(items ? { items: items.map((li) => ({ name: li.name.slice(0, 127), quantity: String(li.quantity),
          unit_amount: { currency_code: input.currency.toUpperCase(), value: money(li.amountMinor, input.currency) } })) } : {}),
      }],
      payment_source: { paypal: { experience_context: { return_url: input.successUrl, cancel_url: input.cancelUrl,
        user_action: "PAY_NOW", shipping_preference: "NO_SHIPPING" } } },
    }, `order-${input.paymentId}`);
    const url = link(order, "payer-action", "approve");
    if (!url) throw new Error("PayPal gave no page to send the payer to");
    return { url, sessionId: String(order.id), providerRef: String(order.id) };
  },

  async confirm(row, _params, secrets) {
    const id = String(row.providerRef ?? "");
    let order: any;
    try {
      order = await call("POST", `/v2/checkout/orders/${encodeURIComponent(id)}/capture`, secrets, {}, `capture-${row.id}`);
    } catch (err: any) {
      const issue = String(err?.body?.details?.[0]?.issue ?? "");
      // Captured already (a second return, the webhook first) or not approved yet: the order says which.
      if (err?.status === 422 && (issue === "ORDER_ALREADY_CAPTURED" || issue === "ORDER_NOT_APPROVED")) {
        order = await call("GET", `/v2/checkout/orders/${encodeURIComponent(id)}`, secrets);
      } else {
        throw err;
      }
    }
    const { status, capture } = orderStatus(order);
    const amount = capture?.amount ?? order?.purchase_units?.[0]?.amount ?? {};
    const currency = String(amount.currency_code ?? row.currency).toUpperCase();
    return { status, providerRef: id, amountMinor: amount.value != null ? minorOf(amount.value, currency) : undefined, currency,
      metadata: (capture?.id ? { providerPayment: String(capture.id) } : {}) as Record<string, string> };
  },

  async refund(input, secrets) {
    let captureId = String((input.metadata as any)?.providerPayment ?? "");
    let currency = String(input.currency ?? "").toUpperCase();
    if (!captureId) {
      const order = await call("GET", `/v2/checkout/orders/${encodeURIComponent(input.providerRef)}`, secrets);
      const capture = order?.purchase_units?.[0]?.payments?.captures?.[0];
      captureId = String(capture?.id ?? "");
      currency ||= String(capture?.amount?.currency_code ?? "");
    }
    if (!captureId) throw new Error("the order has no capture to refund");
    if (input.amountMinor && !currency) {
      const capture = await call("GET", `/v2/payments/captures/${encodeURIComponent(captureId)}`, secrets);
      currency = String(capture?.amount?.currency_code ?? "");
    }
    // A PART IS NEVER SENT AS THE WHOLE: PayPal refunds everything when no
    // amount is given, so a partial refund with no currency is refused.
    if (input.amountMinor && !currency) throw new Error("the currency of the capture is unknown; nothing was refunded");
    const body = input.amountMinor ? { amount: { value: money(input.amountMinor, currency), currency_code: currency } } : {};
    const refund = await call("POST", `/v2/payments/captures/${encodeURIComponent(captureId)}/refund`, secrets, body, `refund-${captureId}-${input.amountMinor ?? "all"}`);
    const st = String(refund.status);
    return { refundId: String(refund.id), status: st === "COMPLETED" ? "succeeded" : st === "CANCELLED" || st === "FAILED" ? "failed" : "pending" };
  },

  async retrieve(providerRef, secrets) {
    const order = await call("GET", `/v2/checkout/orders/${encodeURIComponent(providerRef)}`, secrets);
    const amount = order?.purchase_units?.[0]?.amount ?? {};
    const currency = String(amount.currency_code ?? "").toUpperCase();
    return { status: orderStatus(order).status, amountMinor: amount.value != null ? minorOf(amount.value, currency) : 0, currency };
  },

  async verifyWebhook(rawBody, headers, webhookId, secrets) {
    if (!secrets) return { ok: false, reason: "PayPal's webhooks are checked with PayPal; no keys to ask with" };
    const need = ["paypal-auth-algo", "paypal-cert-url", "paypal-transmission-id", "paypal-transmission-sig", "paypal-transmission-time"];
    if (need.some((h) => !headers.get(h))) return { ok: false, reason: "no signature" };
    const certUrl = String(headers.get("paypal-cert-url"));
    try {
      if (!/\.paypal\.com$/.test(new URL(certUrl).hostname) && !process.env.FORGE_PAY_EMULATOR) return { ok: false, reason: "the certificate is not PayPal's" };
    } catch {
      return { ok: false, reason: "the certificate address is not an address" };
    }
    // THE EVENT EXACTLY AS IT ARRIVED: spliced in as text, never parsed and
    // written again (a re-serialised body does not verify).
    const body = `{"auth_algo":${JSON.stringify(headers.get("paypal-auth-algo"))},"cert_url":${JSON.stringify(certUrl)},`
      + `"transmission_id":${JSON.stringify(headers.get("paypal-transmission-id"))},"transmission_sig":${JSON.stringify(headers.get("paypal-transmission-sig"))},`
      + `"transmission_time":${JSON.stringify(headers.get("paypal-transmission-time"))},"webhook_id":${JSON.stringify(webhookId)},"webhook_event":${rawBody}}`;
    const res = await fetch(`${base(secrets)}/v1/notifications/verify-webhook-signature`, {
      method: "POST", body, headers: { Authorization: `Bearer ${await token(secrets)}`, "Content-Type": "application/json" },
    });
    const out: any = await res.json().catch(() => ({}));
    if (!res.ok || String(out?.verification_status) !== "SUCCESS") return { ok: false, reason: "PayPal did not confirm the signature" };
    let eventId: string | undefined;
    try { eventId = String(JSON.parse(rawBody)?.id ?? "") || undefined; } catch { /* no id */ }
    return { ok: true, eventId };
  },

  normalizeEvent(raw): Normalized | null {
    const ev = raw as any;
    const type = String(ev?.event_type ?? "");
    const r = ev?.resource ?? {};
    if (type.startsWith("BILLING.SUBSCRIPTION.")) {
      return { type: "subscription.updated" as NormalizedEvent, providerRef: String(r.id ?? ""),
        subscriptionId: r.custom_id ? String(r.custom_id) : undefined, metadata: {} };
    }
    if (type === "PAYMENT.SALE.COMPLETED" || type === "PAYMENT.SALE.DENIED") {
      if (!r.billing_agreement_id) return null;         // a renewal of a subscription
      return { type: "subscription.updated" as NormalizedEvent, providerRef: String(r.billing_agreement_id), metadata: {} };
    }
    const order = String(r?.supplementary_data?.related_ids?.order_id ?? "");
    const custom = r.custom_id ? String(r.custom_id) : undefined;
    if (type === "PAYMENT.CAPTURE.COMPLETED") {
      if (!order) return null;
      return { type: "payment.succeeded" as NormalizedEvent, providerRef: order, paymentId: custom,
        amountMinor: r.amount?.value != null ? minorOf(r.amount.value, String(r.amount.currency_code ?? "")) : undefined,
        currency: String(r.amount?.currency_code ?? "").toUpperCase(), metadata: { providerPayment: String(r.id ?? "") } };
    }
    if (type === "PAYMENT.CAPTURE.DENIED" || type === "PAYMENT.CAPTURE.DECLINED") {
      if (!order) return null;
      return { type: "payment.failed" as NormalizedEvent, providerRef: order, paymentId: custom, metadata: {} };
    }
    if (type === "PAYMENT.CAPTURE.REFUNDED") {
      return { type: "refund.succeeded" as NormalizedEvent, providerRef: order || String(r.id ?? ""), paymentId: custom,
        amountMinor: r.amount?.value != null ? minorOf(r.amount.value, String(r.amount.currency_code ?? "")) : undefined,
        currency: String(r.amount?.currency_code ?? "").toUpperCase(), metadata: {} };
    }
    return null;
  },

  subscriptions: {
    async ensurePlan(spec: PlanSpec, secrets: Secrets) {
      const product = await call("POST", "/v1/catalogs/products", secrets,
        { name: spec.name.slice(0, 127), type: "SERVICE", description: (spec.description || spec.name).slice(0, 256) }, `product-${spec.key}`);
      const cycles: any[] = [];
      if (spec.trialDays > 0) {
        cycles.push({ tenure_type: "TRIAL", sequence: 1, total_cycles: 1,
          frequency: { interval_unit: "DAY", interval_count: spec.trialDays },
          pricing_scheme: { fixed_price: { value: "0", currency_code: spec.currency.toUpperCase() } } });
      }
      cycles.push({ tenure_type: "REGULAR", sequence: cycles.length + 1, total_cycles: 0,
        frequency: { interval_unit: UNIT[spec.interval], interval_count: spec.intervalCount },
        pricing_scheme: { fixed_price: { value: money(spec.amountMinor, spec.currency), currency_code: spec.currency.toUpperCase() } } });
      const plan = await call("POST", "/v1/billing/plans", secrets, {
        product_id: String(product.id), name: spec.name.slice(0, 127), status: "ACTIVE", billing_cycles: cycles,
        payment_preferences: { auto_bill_outstanding: true, payment_failure_threshold: 2 },
      }, `plan-${spec.key}`);
      return String(plan.id);
    },
    async start(input, secrets) {
      const sub = await call("POST", "/v1/billing/subscriptions", secrets, {
        plan_id: input.planRef, custom_id: input.subscriptionId.slice(0, 127),
        ...(input.customerEmail ? { subscriber: { email_address: input.customerEmail } } : {}),
        application_context: { return_url: input.successUrl, cancel_url: input.cancelUrl, user_action: "SUBSCRIBE_NOW",
          shipping_preference: "NO_SHIPPING" },
      }, `sub-${input.subscriptionId}`);
      const url = link(sub, "approve", "payer-action");
      if (!url) throw new Error("PayPal gave no page to approve the subscription on");
      return { url, providerRef: String(sub.id) };
    },
    async retrieve(providerRef, secrets) {
      return snapshot(await call("GET", `/v1/billing/subscriptions/${encodeURIComponent(providerRef)}`, secrets));
    },
    async cancel(providerRef, atPeriodEnd, secrets) {
      // PayPal stops future charges at once; what was paid for runs to its end
      // (the app keeps access until then — its own `cancel_at_period_end`).
      await call("POST", `/v1/billing/subscriptions/${encodeURIComponent(providerRef)}/cancel`, secrets,
        { reason: "Cancelled by the subscriber" }, `cancel-${providerRef}`);
      const snap = snapshot(await call("GET", `/v1/billing/subscriptions/${encodeURIComponent(providerRef)}`, secrets));
      return { ...snap, cancelAtPeriodEnd: atPeriodEnd };
    },
  },
};
