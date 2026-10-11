/**
 * How an outside system signs what it sends — per provider.
 *
 * An integration whose `inbound.verify` is `provider` is checked by the
 * provider's own scheme, registered here by its adapter (a payment
 * provider's signed header, a chat platform's token). Empty until an
 * adapter lands: a provider with no verifier is refused at the route, never
 * believed.
 */
export interface Verified {
  ok: boolean;
  /** The delivery's own id when the provider sends one, for dedupe. */
  eventId?: string;
  /** The event's name in the provider's vocabulary. */
  type?: string;
  reason?: string;
}

export type Verifier = (raw: string, headers: Headers, secret: string) => Verified;

export const PROVIDER_VERIFIERS: Record<string, Verifier> = {};

/** A payment provider's signed call is verified AND settled by its adapter
 *  (`payments/index.ts`): the ledger moves and the normalised event goes on
 *  the bus. The webhook route hands these providers over whole. */
export const PAYMENT_PROVIDERS = new Set(["stripe"]);
