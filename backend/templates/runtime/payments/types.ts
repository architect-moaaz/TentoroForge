/**
 * What a payment provider does for the application — the one interface a
 * second provider is written to. The runtime holds no card data: a
 * checkout is a hosted page the person is sent to, and a payment is
 * believed only from the provider's signed event.
 */
export type PaymentStatus = "pending" | "succeeded" | "failed" | "refunded" | "partially_refunded" | "cancelled";

export type NormalizedEvent = "payment.succeeded" | "payment.failed" | "refund.succeeded" | "account.updated";

export interface Secrets {
  secret: string;
  webhookSecret?: string;
  publishable?: string;
}

export interface LineItem {
  name: string;
  /** Major units. */
  amount: number;
  quantity?: number;
}

export interface CheckoutInput {
  /** The ledger's id for this payment, carried to the provider as metadata. */
  paymentId: string;
  /** Minor units, as the provider wants them. */
  amountMinor: number;
  currency: string;
  description?: string;
  lineItems?: Array<{ name: string; amountMinor: number; quantity: number }>;
  customerEmail?: string;
  successUrl: string;
  cancelUrl: string;
  metadata: Record<string, string>;
  transfer?: { destinationAccountRef: string; applicationFeePercent?: number };
}

export interface PaymentAdapter {
  provider: string;
  /** Environment variable NAMES. */
  keys: { secret: string; webhookSecret: string; publishable?: string };
  createCheckout(input: CheckoutInput, secrets: Secrets, origin: string): Promise<{ url: string; sessionId: string; providerRef: string }>;
  refund(input: { providerRef: string; amountMinor?: number }, secrets: Secrets): Promise<{ refundId: string; status: "pending" | "succeeded" | "failed" }>;
  retrieve(providerRef: string, secrets: Secrets): Promise<{ status: PaymentStatus; amountMinor: number; currency: string }>;
  verifyWebhook(rawBody: string, headers: Headers, webhookSecret: string): { ok: boolean; eventId?: string; timestamp?: number; reason?: string };
  normalizeEvent(raw: unknown): { type: NormalizedEvent; providerRef: string; paymentId?: string; amountMinor?: number; currency?: string; metadata: Record<string, string> } | null;
  connect?: {
    createAccount(input: { reference: string; email?: string }, secrets: Secrets): Promise<{ accountRef: string }>;
    onboardingLink(input: { accountRef: string; returnUrl: string; refreshUrl: string }, secrets: Secrets): Promise<{ url: string }>;
  };
}
