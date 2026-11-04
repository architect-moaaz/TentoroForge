/**
 * Razorpay, through its REST API with plain `fetch` (Basic auth, key id and
 * key secret). The payer pays in Razorpay's own Checkout window, opened on the
 * application's `/pay/razorpay` page: UPI, cards, netbanking, wallets — and
 * for a subscription, the e-mandate the RBI requires.
 *
 * A payment is believed only from Razorpay: the Checkout handler's
 * `razorpay_signature` (an HMAC-SHA256 with the key secret over
 * `<our stored order id>|<payment id>`, or `<payment id>|<subscription id>`)
 * checked on the server and followed by a read of the payment itself; or a
 * webhook signed in `X-Razorpay-Signature` (an HMAC-SHA256 of the raw body
 * with the webhook secret the owner set in Razorpay's dashboard).
 */
import crypto from "node:crypto";
import { apiBase, basic, call as http } from "./http";
import type { NormalizedEvent, PaymentAdapter, PaymentStatus, PlanSpec, Secrets, SubSnapshot, SubscriptionStatus } from "./types";

async function call(method: "GET" | "POST", path: string, secrets: Secrets, json?: unknown): Promise<any> {
  return http("Razorpay", `${apiBase("razorpay")}/v1${path}`, {
    method, headers: { Authorization: basic(String(secrets.keyId ?? ""), secrets.secret) },
    ...(json !== undefined ? { json } : {}),
  });
}

export function hmacHex(secret: string, text: string): string {
  return crypto.createHmac("sha256", secret).update(text).digest("hex");
}

export function same(a: string, b: string): boolean {
  const x = Buffer.from(String(a));
  const y = Buffer.from(String(b));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}

const PERIOD: Record<string, string> = { day: "daily", week: "weekly", month: "monthly", year: "yearly" };
/** Billing cycles a subscription is created for; a renewal past them is a new subscription. */
const CYCLES: Record<string, number> = { day: 104, week: 104, month: 60, year: 10 };

function subStatus(s: string): SubscriptionStatus {
  if (s === "active") return "active";
  if (s === "authenticated") return "trialing";
  if (s === "pending") return "past_due";
  if (s === "halted") return "past_due";
  if (s === "paused") return "paused";
  if (s === "cancelled") return "cancelled";
  if (s === "completed" || s === "expired") return "expired";
  return "incomplete";
}

function snapshot(sub: any): SubSnapshot {
  // An ended subscription ran until it ended (`ended_at`), not to the cycle it was billed for.
  const ended = String(sub?.status ?? "") === "cancelled" ? Number(sub?.ended_at ?? 0) : 0;
  const end = ended > 0 ? ended : Number(sub?.current_end ?? sub?.charge_at ?? 0);
  return { status: subStatus(String(sub?.status ?? "")), currentPeriodEnd: end > 0 ? new Date(end * 1000).toISOString() : null,
    // Whether a cancel waits for the cycle's end is the app's own record (it asked); Razorpay reports `cancelled` once it happens.
    cancelAtPeriodEnd: false,
    providerRef: String(sub?.id ?? ""), customerRef: sub?.customer_id ? String(sub.customer_id) : undefined };
}

export const razorpayAdapter: PaymentAdapter = {
  provider: "razorpay",
  keys: { secret: "RAZORPAY_KEY_SECRET", webhookSecret: "RAZORPAY_WEBHOOK_SECRET", keyId: "RAZORPAY_KEY_ID" },

  async createCheckout(input, secrets, origin) {
    const order = await call("POST", "/orders", secrets, {
      amount: input.amountMinor, currency: input.currency.toUpperCase(),
      // `receipt` is at most 40 characters: the ledger's id (a uuid) fits.
      receipt: input.paymentId.slice(0, 40),
      notes: { ...input.metadata, paymentId: input.paymentId },
    });
    const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
    return { url: `${origin}${base}/pay/razorpay?payment=${encodeURIComponent(input.paymentId)}`, sessionId: String(order.id), providerRef: String(order.id) };
  },

  async confirm(row, params, secrets) {
    const paymentId = String(params.razorpay_payment_id ?? "");
    const signature = String(params.razorpay_signature ?? "");
    const order = String(row.providerRef ?? "");
    if (!paymentId || !signature || !order) return { status: "pending" as PaymentStatus };
    // OUR order id, never the one the browser sent back.
    if (!same(hmacHex(secrets.secret, `${order}|${paymentId}`), signature)) {
      throw new Error("the payment's signature did not check out");
    }
    let payment = await call("GET", `/payments/${encodeURIComponent(paymentId)}`, secrets);
    if (String(payment.order_id ?? "") !== order) throw new Error("the payment belongs to another order");
    if (String(payment.status) === "authorized") {
      payment = await call("POST", `/payments/${encodeURIComponent(paymentId)}/capture`, secrets,
        { amount: Number(payment.amount), currency: String(payment.currency) });
    }
    const st = String(payment.status);
    const status: PaymentStatus = st === "captured" ? "succeeded" : st === "failed" ? "failed" : st === "refunded" ? "refunded" : "pending";
    return { status, providerRef: order, amountMinor: Number(payment.amount ?? 0), currency: String(payment.currency ?? "").toUpperCase(),
      metadata: { providerPayment: paymentId } };
  },

  async refund(input, secrets) {
    let paymentId = String((input.metadata as any)?.providerPayment ?? "");
    if (!paymentId) {
      const paid = await call("GET", `/orders/${encodeURIComponent(input.providerRef)}/payments`, secrets);
      paymentId = String((paid?.items ?? []).find((p: any) => p.status === "captured")?.id ?? "");
    }
    if (!paymentId) throw new Error("the order has no captured payment to refund");
    const refund = await call("POST", `/payments/${encodeURIComponent(paymentId)}/refund`, secrets,
      input.amountMinor ? { amount: input.amountMinor } : {});
    const st = String(refund.status);
    return { refundId: String(refund.id), status: st === "processed" ? "succeeded" : st === "failed" ? "failed" : "pending" };
  },

  async retrieve(providerRef, secrets) {
    const order = await call("GET", `/orders/${encodeURIComponent(providerRef)}`, secrets);
    const st = String(order.status);
    return { status: (st === "paid" ? "succeeded" : "pending") as PaymentStatus, amountMinor: Number(order.amount ?? 0), currency: String(order.currency ?? "").toUpperCase() };
  },

  verifyWebhook(rawBody, headers, webhookSecret) {
    const sig = headers.get("x-razorpay-signature") ?? "";
    if (!sig) return { ok: false, reason: "no signature" };
    if (!same(hmacHex(webhookSecret, rawBody), sig)) return { ok: false, reason: "bad signature" };
    const eventId = headers.get("x-razorpay-event-id") ?? undefined;
    return { ok: true, eventId: eventId || undefined };
  },

  normalizeEvent(raw) {
    const ev = raw as any;
    const type = String(ev?.event ?? "");
    const pay = ev?.payload?.payment?.entity ?? {};
    const notes: Record<string, string> = Object.fromEntries(Object.entries(pay?.notes ?? {}).map(([k, v]) => [k, String(v)]));
    if (type.startsWith("subscription.")) {
      const sub = ev?.payload?.subscription?.entity ?? {};
      const subNotes = sub?.notes ?? {};
      return { type: "subscription.updated" as NormalizedEvent, providerRef: String(sub.id ?? ""),
        subscriptionId: subNotes.subscriptionId ? String(subNotes.subscriptionId) : undefined, metadata: {} };
    }
    if (type === "payment.captured" || type === "order.paid") {
      const order = ev?.payload?.order?.entity ?? {};
      const orderId = String(pay.order_id ?? order.id ?? "");
      if (!orderId) return null;            // a subscription's charge: its own event says it
      return { type: "payment.succeeded" as NormalizedEvent, providerRef: orderId, paymentId: notes.paymentId ?? (order?.notes?.paymentId ? String(order.notes.paymentId) : undefined),
        amountMinor: Number(pay.amount ?? order.amount_paid ?? 0), currency: String(pay.currency ?? order.currency ?? "").toUpperCase(),
        metadata: { ...notes, ...(pay.id ? { providerPayment: String(pay.id) } : {}) } };
    }
    if (type === "payment.failed") {
      if (!pay.order_id) return null;
      return { type: "payment.failed" as NormalizedEvent, providerRef: String(pay.order_id), paymentId: notes.paymentId, metadata: notes };
    }
    if (type === "refund.processed") {
      const refund = ev?.payload?.refund?.entity ?? {};
      return { type: "refund.succeeded" as NormalizedEvent, providerRef: String(pay.order_id ?? refund.payment_id ?? ""), paymentId: notes.paymentId,
        amountMinor: Number(refund.amount ?? 0), currency: String(refund.currency ?? "").toUpperCase(), metadata: { providerPayment: String(refund.payment_id ?? "") } };
    }
    return null;
  },

  subscriptions: {
    async ensurePlan(spec: PlanSpec, secrets: Secrets) {
      // Razorpay has no lookup by key: the billing layer keeps the plan id it
      // made (`forge_plan_refs`) and asks only once.
      const plan = await call("POST", "/plans", secrets, {
        period: PERIOD[spec.interval],
        interval: spec.interval === "day" ? Math.max(7, spec.intervalCount) : spec.intervalCount,
        item: { name: spec.name.slice(0, 100), amount: spec.amountMinor, currency: spec.currency.toUpperCase(), description: spec.description?.slice(0, 200) || spec.name },
        notes: { planId: spec.planId, forgeKey: spec.key },
      });
      return String(plan.id);
    },
    async start(input, secrets, origin) {
      const startAt = input.plan.trialDays > 0 ? Math.floor(Date.now() / 1000) + input.plan.trialDays * 86_400 : undefined;
      const sub = await call("POST", "/subscriptions", secrets, {
        plan_id: input.planRef,
        total_count: CYCLES[input.plan.interval] ?? 60,
        quantity: 1,
        customer_notify: 1,
        ...(startAt ? { start_at: startAt } : {}),
        notes: { ...input.metadata, subscriptionId: input.subscriptionId },
      });
      const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
      return { url: `${origin}${base}/pay/razorpay?subscription=${encodeURIComponent(input.subscriptionId)}`, providerRef: String(sub.id) };
    },
    async retrieve(providerRef, secrets) {
      return snapshot(await call("GET", `/subscriptions/${encodeURIComponent(providerRef)}`, secrets));
    },
    async cancel(providerRef, atPeriodEnd, secrets) {
      const sub = await call("POST", `/subscriptions/${encodeURIComponent(providerRef)}/cancel`, secrets,
        { cancel_at_cycle_end: atPeriodEnd ? 1 : 0 });
      const snap = snapshot(sub);
      return atPeriodEnd ? { ...snap, cancelAtPeriodEnd: true } : snap;
    },
  },
};

/** The Checkout handler's answer for a subscription, checked: `<payment id>|<our stored subscription ref>`. */
export function subscriptionSignatureOk(secret: string, subscriptionRef: string, paymentId: string, signature: string): boolean {
  return Boolean(subscriptionRef && paymentId && signature) && same(hmacHex(secret, `${paymentId}|${subscriptionRef}`), signature);
}
