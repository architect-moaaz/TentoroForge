/**
 * The stand-in: what takes a payment before a provider's key is set. The
 * person is sent to the application's own `/pay/stand-in` page, which shows
 * the amount and offers "Paid" and "Failed"; its route puts the same events
 * on the bus a provider's signed call would. Honest in the same way as an
 * email with no service connected: the run says it stood in.
 */
import type { PaymentAdapter } from "./types";

export const standInAdapter: PaymentAdapter = {
  provider: "stand_in",
  keys: { secret: "", webhookSecret: "" },
  async createCheckout(input, _secrets, origin) {
    const sessionId = `standin_${input.paymentId}`;
    return { url: `${origin}/pay/stand-in?session=${encodeURIComponent(sessionId)}`, sessionId, providerRef: sessionId };
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
};
