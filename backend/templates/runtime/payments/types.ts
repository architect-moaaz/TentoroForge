/**
 * What a payment gateway does for the application — the one interface each
 * gateway is written to (Stripe, Razorpay, PayPal, and the stand-in). The
 * runtime holds no card data: a payer pays on the gateway's own page or
 * window, and a payment is believed only from the gateway — its signed
 * event, or a server-side read of the payment (`confirm`) — never from the
 * browser.
 */
export type PaymentStatus = "pending" | "succeeded" | "failed" | "refunded" | "partially_refunded" | "cancelled";

export type NormalizedEvent =
  | "payment.succeeded" | "payment.failed" | "refund.succeeded" | "account.updated" | "subscription.updated";

export interface Secrets {
  /** The secret the gateway's API is called with (Stripe secret key, Razorpay key secret, PayPal client secret). */
  secret: string;
  webhookSecret?: string;
  publishable?: string;
  /** Razorpay's key id; PayPal's client id. */
  keyId?: string;
  /** PayPal: "sandbox" or "live". */
  env?: string;
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

/** What the gateway says a payment is, after the payer came back. */
export interface Confirmed {
  status: PaymentStatus;
  providerRef?: string;
  amountMinor?: number;
  currency?: string;
  /** Ids the gateway gave the money once it moved (a refund needs them). */
  metadata?: Record<string, string>;
}

/** A plan as the gateway needs it: one price, one currency, one interval. */
export interface PlanSpec {
  /** Stable across deploys and unique per price: `<plan>-<interval>-<currency>-<amount>`. */
  key: string;
  planId: string;
  name: string;
  description?: string;
  interval: "day" | "week" | "month" | "year";
  intervalCount: number;
  amountMinor: number;
  currency: string;
  trialDays: number;
}

export type SubscriptionStatus = "incomplete" | "trialing" | "active" | "past_due" | "paused" | "cancelled" | "expired";

/** A subscription as the gateway holds it — the truth the app's own row follows. */
export interface SubSnapshot {
  status: SubscriptionStatus;
  /** ISO time the paid period ends (the next charge), or null when unknown. */
  currentPeriodEnd: string | null;
  cancelAtPeriodEnd: boolean;
  /** The gateway's id for the subscription itself, once it exists. */
  providerRef?: string;
  customerRef?: string;
}

export interface SubscriptionStart {
  /** The app's own id for the subscription row. */
  subscriptionId: string;
  planRef: string;
  plan: PlanSpec;
  customerEmail?: string;
  customerName?: string;
  successUrl: string;
  cancelUrl: string;
  metadata: Record<string, string>;
}

export interface Subscriptions {
  /** Create the plan/price at the gateway; returns its id there. Idempotent per `spec.key` where the gateway allows. */
  ensurePlan(spec: PlanSpec, secrets: Secrets): Promise<string>;
  /** Where the payer goes to authorise it, and the gateway's reference so far. */
  start(input: SubscriptionStart, secrets: Secrets, origin: string): Promise<{ url: string; providerRef: string }>;
  retrieve(providerRef: string, secrets: Secrets): Promise<SubSnapshot>;
  cancel(providerRef: string, atPeriodEnd: boolean, secrets: Secrets): Promise<SubSnapshot>;
  /** The gateway's own page where the payer manages the subscription, when it has one. */
  manageUrl?(snapshot: { providerRef: string; customerRef?: string | null }, returnUrl: string, secrets: Secrets): Promise<string | null>;
}

export interface Verified { ok: boolean; eventId?: string; timestamp?: number; reason?: string }

export interface Normalized {
  type: NormalizedEvent;
  providerRef: string;
  paymentId?: string;
  /** The app's own subscription id, when the gateway carried it back. */
  subscriptionId?: string;
  amountMinor?: number;
  currency?: string;
  metadata: Record<string, string>;
}

export interface PaymentAdapter {
  provider: string;
  /** Environment variable NAMES. */
  keys: { secret: string; webhookSecret: string; publishable?: string; keyId?: string; env?: string };
  createCheckout(input: CheckoutInput, secrets: Secrets, origin: string): Promise<{ url: string; sessionId: string; providerRef: string }>;
  /** Ask the gateway what became of a payment the payer came back from (`params`: what the return carried). */
  confirm?(row: { id: string; providerRef: string | null; amountMinor: number; currency: string; metadata: Record<string, unknown> },
           params: Record<string, string>, secrets: Secrets): Promise<Confirmed>;
  /** `amountMinor` absent refunds it all; present, that much, in the payment's `currency`. */
  refund(input: { providerRef: string; amountMinor?: number; currency?: string; metadata?: Record<string, unknown> }, secrets: Secrets): Promise<{ refundId: string; status: "pending" | "succeeded" | "failed" }>;
  retrieve(providerRef: string, secrets: Secrets): Promise<{ status: PaymentStatus; amountMinor: number; currency: string }>;
  verifyWebhook(rawBody: string, headers: Headers, webhookSecret: string, secrets?: Secrets): Verified | Promise<Verified>;
  normalizeEvent(raw: unknown): Normalized | null;
  subscriptions?: Subscriptions;
  connect?: {
    createAccount(input: { reference: string; email?: string }, secrets: Secrets): Promise<{ accountRef: string }>;
    onboardingLink(input: { accountRef: string; returnUrl: string; refreshUrl: string }, secrets: Secrets): Promise<{ url: string }>;
  };
}
