/**
 * The stand-in: what takes a payment before a gateway's key is set (a
 * preview, the test version without test keys). The person is sent to the
 * application's own `/pay/stand-in` page, which shows the amount — or the
 * plan — and offers "Paid" and "Failed"; its route puts the same events on
 * the bus a gateway's signed call would. Honest in the same way as an email
 * with no service connected: the run says it stood in, and nobody is charged.
 */
import type { PaymentAdapter } from "./types";

const base = () => (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");

export const standInAdapter: PaymentAdapter = {
  provider: "stand_in",
  keys: { secret: "", webhookSecret: "" },
  async createCheckout(input, _secrets, origin) {
    const sessionId = `standin_${input.paymentId}`;
    return { url: `${origin}${base()}/pay/stand-in?session=${encodeURIComponent(sessionId)}`, sessionId, providerRef: sessionId };
  },
  async refund() {
    return { refundId: `standin_refund_${Date.now()}`, status: "succeeded" };
  },
  async retrieve() {
    return { status: "pending", amountMinor: 0, currency: "" };
  },
  verifyWebhook() {
    return { ok: false, reason: "the stand-in signs nothing; its page speaks to the bus directly" };
  },
  normalizeEvent() {
    return null;
  },
  subscriptions: {
    async ensurePlan(spec) {
      return `standin_plan_${spec.key}`;
    },
    async start(input, _secrets, origin) {
      return { url: `${origin}${base()}/pay/stand-in?subscription=${encodeURIComponent(input.subscriptionId)}`,
               providerRef: `standin_sub_${input.subscriptionId}` };
    },
    // The stand-in holds nothing of its own: the app's row is the whole truth.
    async retrieve(providerRef) {
      return { status: "incomplete", currentPeriodEnd: null, cancelAtPeriodEnd: false, providerRef };
    },
    async cancel(providerRef, atPeriodEnd) {
      return { status: atPeriodEnd ? "active" : "cancelled", currentPeriodEnd: null, cancelAtPeriodEnd: atPeriodEnd, providerRef };
    },
  },
};
