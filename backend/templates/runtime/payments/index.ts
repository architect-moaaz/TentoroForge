/**
 * Payments: the registry of gateways, which one a payer is sent to, the
 * ledger, and the one path an outcome takes into the application.
 *
 * Which gateways an application uses is the Blueprint's (`payments.gateways`,
 * projected into `@/lib/payments-config`); an application made before that
 * reads its one `serves: "take_payment"` integration (`connected.ts`). A
 * gateway whose keys are not in this environment is replaced by the stand-in,
 * which says so — a preview, or the test version without test keys.
 *
 * A PAYMENT MOVES ONE WAY. pending → succeeded / failed / cancelled; a failed
 * or cancelled attempt may still succeed (the payer tried again on the same
 * order); succeeded → refunded. Each move is one conditional update, so a
 * signed event and the payer's return arriving together settle it once, and
 * only the move that happened is told to the application's processes.
 */
import { sql } from "drizzle-orm";
import { db } from "@/db";
import { connectedService } from "@/lib/integrations/connected";
import { getSecret } from "@/lib/integrations/resolver";
import { PAYMENTS } from "@/lib/payments-config";
import { stripeAdapter } from "./stripe";
import { razorpayAdapter } from "./razorpay";
import { paypalAdapter } from "./paypal";
import { standInAdapter } from "./stand-in";
import { routeFor, type GatewayRef } from "./routing";
import { toMajor, toMinor } from "./units";
import type { Normalized, NormalizedEvent, PaymentAdapter, PaymentStatus, Secrets } from "./types";

export const ADAPTERS: Record<string, PaymentAdapter> = {
  stripe: stripeAdapter, razorpay: razorpayAdapter, paypal: paypalAdapter, stand_in: standInAdapter,
};

export { toMajor, toMinor } from "./units";

export async function currencyOf(): Promise<string> {
  if (PAYMENTS?.currency) return String(PAYMENTS.currency).toUpperCase();
  try {
    const mod: any = await import("@/lib/money");
    return String(mod?.CURRENCY || "USD").toUpperCase();
  } catch {
    return "USD";
  }
}

/** The gateways this application chose; for an app made before the choice, its one declared integration. */
export function gateways(): GatewayRef[] {
  const chosen = (PAYMENTS?.gateways ?? []) as GatewayRef[];
  if (chosen.length) return chosen;
  const declared = connectedService("take_payment");
  if (!declared || !ADAPTERS[declared.provider]) return [];
  const slug = String(declared.name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return [{ id: declared.provider, provider: declared.provider, label: declared.name, coverage: "both", currencies: [], integration: slug }];
}

/** The keys of one gateway in this environment, by name. Never logged. */
export async function secretsFor(provider: string): Promise<Secrets | null> {
  const adapter = ADAPTERS[provider];
  if (!adapter || provider === "stand_in") return null;
  const secret = (await getSecret(provider, adapter.keys.secret)) ?? "";
  const keyId = adapter.keys.keyId ? ((await getSecret(provider, adapter.keys.keyId)) ?? "") : "";
  if (!secret || (adapter.keys.keyId && !keyId)) return null;
  return {
    secret, keyId: keyId || undefined,
    webhookSecret: (await getSecret(provider, adapter.keys.webhookSecret)) ?? undefined,
    publishable: adapter.keys.publishable ? ((await getSecret(provider, adapter.keys.publishable)) ?? undefined) : undefined,
    env: adapter.keys.env ? ((await getSecret(provider, adapter.keys.env)) ?? "sandbox") : undefined,
  };
}

export interface Chosen { adapter: PaymentAdapter; secrets: Secrets; live: boolean; declared: string | null; gateway: GatewayRef | null; notice?: string }

/** The gateway for a payer paying in `currency` (from `country`, when known), its keys, and whether it is live. */
export async function gatewayFor(opts: { currency?: string; country?: string | null; provider?: string } = {}): Promise<Chosen> {
  const list = gateways();
  const currency = String(opts.currency || (await currencyOf())).toUpperCase();
  if (!list.length) {
    return { adapter: standInAdapter, secrets: { secret: "" }, live: false, declared: null, gateway: null,
      notice: "No payment gateway is connected; a stand-in took the payment and nobody was charged. Choose one under Payments." };
  }
  const gw = (opts.provider ? list.find((g) => g.provider === opts.provider) : null)
    ?? (list.length === 1 || !list.some((g) => g.currencies.length) ? list[0] : routeFor(list, currency, opts.country))
    ?? list.find((g) => g.isDefault) ?? list[0];
  const adapter = ADAPTERS[gw.provider];
  if (!adapter) {
    return { adapter: standInAdapter, secrets: { secret: "" }, live: false, declared: gw.provider, gateway: gw,
      notice: `${gw.label} has no payment adapter; a stand-in took the payment.` };
  }
  const secrets = await secretsFor(gw.provider);
  if (!secrets) {
    return { adapter: standInAdapter, secrets: { secret: "" }, live: false, declared: gw.provider, gateway: gw,
      notice: `Payments go through ${gw.label}, but its keys are not set where this copy runs — a stand-in took the payment and nobody was charged.` };
  }
  return { adapter, secrets, live: true, declared: gw.provider, gateway: gw };
}

/** Kept for the steps written before gateways were chosen per payer. */
export async function adapterFor(): Promise<Chosen> {
  return gatewayFor({});
}

function _rows(res: unknown): any[] {
  return Array.isArray(res) ? res : ((res as { rows?: any[] })?.rows ?? []);
}

export interface LedgerRow {
  id: string; provider: string; provider_ref: string | null; status: PaymentStatus; amount_minor: number; currency: string;
  entity: string | null; entity_id: string | null; actor_id: string | null; description: string | null;
  success_url: string | null; cancel_url: string | null; metadata: Record<string, unknown>;
}

export async function ledgerInsert(row: Omit<LedgerRow, "id" | "status"> & { id?: string }): Promise<string> {
  const res = await db.execute(sql`
    INSERT INTO forge_payments (id, provider, provider_ref, status, amount_minor, currency, entity, entity_id, actor_id, description,
                                success_url, cancel_url, metadata)
    VALUES (${row.id ?? sql`gen_random_uuid()`}, ${row.provider}, ${row.provider_ref}, 'pending', ${row.amount_minor}, ${row.currency},
            ${row.entity}, ${row.entity_id}, ${row.actor_id}, ${row.description}, ${row.success_url}, ${row.cancel_url},
            ${JSON.stringify(row.metadata ?? {})}::jsonb)
    RETURNING id
  `);
  return String(_rows(res)[0]?.id);
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A ledger row by its own id, the gateway's reference, or the gateway's id for the money (a refund names that). */
export async function ledgerGet(id: string): Promise<LedgerRow | null> {
  if (!id) return null;
  const res = UUID.test(id)
    ? await db.execute(sql`SELECT * FROM forge_payments WHERE id = ${id}::uuid OR provider_ref = ${id} LIMIT 1`)
    : await db.execute(sql`SELECT * FROM forge_payments WHERE provider_ref = ${id} OR metadata->>'providerPayment' = ${id} LIMIT 1`);
  return (_rows(res)[0] as LedgerRow) ?? null;
}

export async function ledgerSet(id: string, patch: { status?: PaymentStatus; provider_ref?: string; metadata?: Record<string, unknown> }): Promise<void> {
  if (patch.status) await db.execute(sql`UPDATE forge_payments SET status = ${patch.status}, updated_at = NOW() WHERE id = ${id}::uuid`);
  if (patch.provider_ref) await db.execute(sql`UPDATE forge_payments SET provider_ref = ${patch.provider_ref}, updated_at = NOW() WHERE id = ${id}::uuid`);
  if (patch.metadata) await db.execute(sql`UPDATE forge_payments SET metadata = metadata || ${JSON.stringify(patch.metadata)}::jsonb, updated_at = NOW() WHERE id = ${id}::uuid`);
}

/** Where a payment may move from, to each status. */
export const MOVES: Record<string, PaymentStatus[]> = {
  succeeded: ["pending", "failed", "cancelled"],
  failed: ["pending"],
  cancelled: ["pending"],
  refunded: ["succeeded", "partially_refunded"],
  partially_refunded: ["succeeded", "partially_refunded"],
};

/** Move a payment, only from where it may move: true when THIS call moved it. */
export async function ledgerMove(id: string, to: PaymentStatus, providerRef?: string): Promise<boolean> {
  const from = MOVES[to] ?? [];
  if (!from.length) return false;
  const list = sql.join(from.map((s) => sql`${s}`), sql`, `);
  const res = await db.execute(sql`
    UPDATE forge_payments SET status = ${to}, provider_ref = COALESCE(${providerRef ?? null}, provider_ref), updated_at = NOW()
    WHERE id = ${id}::uuid AND status IN (${list}) RETURNING id
  `);
  return _rows(res).length > 0;
}

/** The integration slugs a payment outcome is told under: every payment gateway's, so a process listening on any of them hears it. */
function slugsFor(integrationSlug: string): string[] {
  return Array.from(new Set([integrationSlug, ...gateways().map((g) => g.integration)].filter(Boolean)));
}

/**
 * An outcome, from a gateway (its signed event, or a read when the payer
 * came back) or the stand-in's page, into the ledger and — when it moved the
 * payment — onto the bus as `<integration>.<event>`, where the processes whose
 * webhook trigger names it start.
 */
export async function settle(integrationSlug: string, ev: { type: NormalizedEvent; providerRef: string; paymentId?: string;
  amountMinor?: number; currency?: string; metadata: Record<string, string> }): Promise<{ paymentId: string | null; event: string; moved: boolean }> {
  const row = (ev.paymentId ? await ledgerGet(ev.paymentId) : null) ?? await ledgerGet(ev.providerRef)
    ?? (ev.metadata?.providerPayment ? await ledgerGet(ev.metadata.providerPayment) : null);
  const event = `${integrationSlug}.${ev.type}`;
  if (!row) return { paymentId: null, event, moved: false };
  let status: PaymentStatus | null = ev.type === "payment.succeeded" ? "succeeded" : ev.type === "payment.failed" ? "failed"
    : ev.type === "refund.succeeded" ? (ev.amountMinor && ev.amountMinor < Number(row.amount_minor) ? "partially_refunded" : "refunded") : null;
  if (!status) return { paymentId: row.id, event, moved: false };
  // PAID IS PAID ONLY AT THE PRICE: a gateway's word for a different amount or
  // currency than the ledger's is not this payment succeeding.
  if (status === "succeeded" && ev.amountMinor != null && ev.currency
      && (Number(ev.amountMinor) !== Number(row.amount_minor) || ev.currency.toUpperCase() !== String(row.currency).toUpperCase())) {
    console.error(`[payments] ${row.id}: the gateway reported ${ev.amountMinor} ${ev.currency}, the ledger holds ${row.amount_minor} ${row.currency} — not settled as paid`);
    await ledgerSet(row.id, { metadata: { mismatch: `${ev.amountMinor} ${ev.currency}` } });
    status = "failed";
  }
  if (ev.metadata && Object.keys(ev.metadata).length) {
    const keep = Object.fromEntries(Object.entries(ev.metadata).filter(([k]) => k === "providerPayment" || k === "paymentIntent"));
    if (Object.keys(keep).length) await ledgerSet(row.id, { metadata: keep });
  }
  const moved = await ledgerMove(row.id, status, ev.type === "refund.succeeded" ? undefined : ev.providerRef);
  if (!moved) return { paymentId: row.id, event, moved: false };
  const { emitEventAndProcess } = await import("@/lib/events/bus");
  const payload = { paymentId: row.id, entity: row.entity ?? null, entityId: row.entity_id ?? null,
    amount: toMajor(Number(row.amount_minor), row.currency), currency: row.currency, status, providerRef: ev.providerRef,
    provider: row.provider, event: ev.type, ...(row.actor_id ? { user: { id: row.actor_id } } : {}) };
  for (const slug of slugsFor(integrationSlug)) {
    await emitEventAndProcess(`${slug}.${ev.type}`, {
      entity: row.entity ?? slug, entityId: row.entity_id ?? null, payload: { ...payload, integration: slug },
      dedupeKey: `${slug}:${ev.type}:${row.id}`,
    });
  }
  return { paymentId: row.id, event, moved: true };
}

/**
 * The payer came back from the gateway: ask the gateway what became of the
 * payment (Stripe's session, Razorpay's signed payment, PayPal's capture) and
 * settle it. Works with no webhook at all — a preview on a laptop, or before
 * the owner pasted Razorpay's webhook in.
 */
export async function confirmPayment(paymentId: string, params: Record<string, string>): Promise<{ row: LedgerRow | null; status: PaymentStatus | "unknown"; error?: string }> {
  const row = await ledgerGet(paymentId);
  if (!row) return { row: null, status: "unknown", error: "no such payment" };
  if (row.status !== "pending" && row.status !== "failed" && row.status !== "cancelled") return { row, status: row.status };
  const adapter = ADAPTERS[row.provider];
  if (!adapter || row.provider === "stand_in" || !adapter.confirm) return { row, status: row.status };
  const secrets = await secretsFor(row.provider);
  if (!secrets) return { row, status: row.status, error: "the gateway's keys are not set here" };
  try {
    const found = await adapter.confirm({ id: row.id, providerRef: row.provider_ref, amountMinor: Number(row.amount_minor),
      currency: row.currency, metadata: row.metadata ?? {} }, params, secrets);
    if (found.status === "succeeded" || found.status === "failed") {
      const slug = gateways().find((g) => g.provider === row.provider)?.integration ?? row.provider;
      await settle(slug, { type: found.status === "succeeded" ? "payment.succeeded" : "payment.failed", providerRef: found.providerRef ?? String(row.provider_ref),
        paymentId: row.id, amountMinor: found.amountMinor, currency: found.currency, metadata: (found.metadata ?? {}) as Record<string, string> });
    }
    const after = await ledgerGet(row.id);
    return { row: after, status: after?.status ?? found.status };
  } catch (err) {
    console.error(`[payments] confirming ${row.id} with ${row.provider} failed:`, err);
    return { row, status: row.status, error: String((err as Error)?.message ?? err) };
  }
}

/** The gateway's signed call, verified and settled; for the webhook route. */
export async function onProviderCall(provider: string, integrationSlug: string, raw: string, headers: Headers, secret: string):
  Promise<{ ok: boolean; status: number; body: Record<string, unknown> }> {
  const adapter = ADAPTERS[provider];
  if (!adapter) return { ok: false, status: 501, body: { error: `no payment adapter for ${provider}` } };
  const v = await adapter.verifyWebhook(raw, headers, secret, (await secretsFor(provider)) ?? undefined);
  if (!v.ok) return { ok: false, status: 401, body: { error: v.reason ?? "bad signature" } };
  let parsed: unknown = {};
  try { parsed = JSON.parse(raw); } catch { /* not JSON */ }
  const ev: Normalized | null = adapter.normalizeEvent(parsed);
  if (!ev) return { ok: true, status: 200, body: { ignored: true, eventId: v.eventId ?? null } };
  try {
    if (ev.type === "subscription.updated") {
      const { onSubscriptionEvent } = await import("./billing");
      const out = await onSubscriptionEvent(provider, ev);
      return { ok: true, status: 200, body: { accepted: true, ...out, eventId: v.eventId ?? null } };
    }
    const out = await settle(integrationSlug, ev);
    return { ok: true, status: out.moved ? 202 : 200, body: { accepted: true, ...out, eventId: v.eventId ?? null } };
  } catch (err) {
    // 500 so the gateway tries again: nothing was settled.
    console.error(`[payments] ${provider} event could not be settled:`, err);
    return { ok: false, status: 500, body: { error: "the event could not be settled; the gateway will send it again" } };
  }
}

export type { NormalizedEvent, PaymentAdapter, PaymentStatus, Secrets } from "./types";
