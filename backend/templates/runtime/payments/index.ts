/**
 * Payments: the registry of providers, the ledger, and the one path an
 * outcome takes into the application.
 *
 * A second provider is one file beside `stripe.ts` and one line in
 * `ADAPTERS`; which one an application uses is the Blueprint's
 * (`integrations[].serves === "take_payment"`, projected into
 * `connected.ts`). With no live key the stand-in takes over, and says so.
 */
import { sql } from "drizzle-orm";
import { db } from "@/db";
import { connectedService } from "@/lib/integrations/connected";
import { getSecret } from "@/lib/integrations/resolver";
import { stripeAdapter } from "./stripe";
import { standInAdapter } from "./stand-in";
import type { NormalizedEvent, PaymentAdapter, PaymentStatus, Secrets } from "./types";

export const ADAPTERS: Record<string, PaymentAdapter> = { stripe: stripeAdapter, stand_in: standInAdapter };

/** Currencies whose minor unit IS the major unit. */
const ZERO_DECIMAL = new Set(["BIF", "CLP", "DJF", "GNF", "JPY", "KMF", "KRW", "MGA", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"]);

export function toMinor(amount: number, currency: string): number {
  return ZERO_DECIMAL.has(String(currency).toUpperCase()) ? Math.round(amount) : Math.round(amount * 100);
}

export function toMajor(amountMinor: number, currency: string): number {
  return ZERO_DECIMAL.has(String(currency).toUpperCase()) ? amountMinor : amountMinor / 100;
}

export async function currencyOf(): Promise<string> {
  try {
    const mod: any = await import("@/lib/money");
    return String(mod?.CURRENCY || "USD").toUpperCase();
  } catch {
    return "USD";
  }
}

/** The provider the application pays through, its secrets, and whether it is live. */
export async function adapterFor(): Promise<{ adapter: PaymentAdapter; secrets: Secrets; live: boolean; declared: string | null; notice?: string }> {
  const declared = connectedService("take_payment");
  const provider = declared?.provider ?? "";
  const adapter = ADAPTERS[provider];
  if (!adapter) {
    return { adapter: standInAdapter, secrets: { secret: "" }, live: false, declared: null,
      notice: declared ? `${declared.name} has no payment adapter; a stand-in took the payment.`
                       : "No payment service is connected; a stand-in took the payment. Connect one under Settings → Integrations." };
  }
  const secret = (await getSecret(provider, adapter.keys.secret)) ?? "";
  if (!secret) {
    return { adapter: standInAdapter, secrets: { secret: "" }, live: false, declared: provider,
      notice: `Payments go through ${declared?.name ?? provider} but ${adapter.keys.secret} is not set — a stand-in took the payment.` };
  }
  return { adapter, declared: provider, live: true, secrets: { secret,
    webhookSecret: (await getSecret(provider, adapter.keys.webhookSecret)) ?? undefined,
    publishable: adapter.keys.publishable ? ((await getSecret(provider, adapter.keys.publishable)) ?? undefined) : undefined } };
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

export async function ledgerGet(id: string): Promise<LedgerRow | null> {
  const res = await db.execute(sql`SELECT * FROM forge_payments WHERE id = ${id}::uuid OR provider_ref = ${id} LIMIT 1`);
  return (_rows(res)[0] as LedgerRow) ?? null;
}

export async function ledgerSet(id: string, patch: { status?: PaymentStatus; provider_ref?: string; metadata?: Record<string, unknown> }): Promise<void> {
  if (patch.status) await db.execute(sql`UPDATE forge_payments SET status = ${patch.status}, updated_at = NOW() WHERE id = ${id}::uuid`);
  if (patch.provider_ref) await db.execute(sql`UPDATE forge_payments SET provider_ref = ${patch.provider_ref}, updated_at = NOW() WHERE id = ${id}::uuid`);
  if (patch.metadata) await db.execute(sql`UPDATE forge_payments SET metadata = metadata || ${JSON.stringify(patch.metadata)}::jsonb, updated_at = NOW() WHERE id = ${id}::uuid`);
}

/**
 * An outcome, from a provider's signed event or the stand-in's page, into
 * the ledger and onto the bus as `<integration>.<event>` — where the
 * processes whose webhook trigger names it start.
 */
export async function settle(integrationSlug: string, ev: { type: NormalizedEvent; providerRef: string; paymentId?: string;
  amountMinor?: number; currency?: string; metadata: Record<string, string> }): Promise<{ paymentId: string | null; event: string }> {
  const row = ev.paymentId ? await ledgerGet(ev.paymentId) : await ledgerGet(ev.providerRef);
  const status: PaymentStatus | null = ev.type === "payment.succeeded" ? "succeeded" : ev.type === "payment.failed" ? "failed"
    : ev.type === "refund.succeeded" ? (row && ev.amountMinor && ev.amountMinor < Number(row.amount_minor) ? "partially_refunded" : "refunded") : null;
  if (row && status) await ledgerSet(row.id, { status, provider_ref: ev.providerRef });
  const event = `${integrationSlug}.${ev.type}`;
  const { emitEventAndProcess } = await import("@/lib/events/bus");
  await emitEventAndProcess(event, {
    entity: row?.entity ?? integrationSlug, entityId: row?.entity_id ?? null,
    payload: { paymentId: row?.id ?? ev.paymentId ?? null, entity: row?.entity ?? null, entityId: row?.entity_id ?? null,
      amount: row ? toMajor(Number(row.amount_minor), row.currency) : (ev.amountMinor != null && ev.currency ? toMajor(ev.amountMinor, ev.currency) : null),
      currency: row?.currency ?? ev.currency ?? null, status, providerRef: ev.providerRef, integration: integrationSlug, event: ev.type,
      ...(row?.actor_id ? { user: { id: row.actor_id } } : {}) },
    dedupeKey: `${integrationSlug}:${ev.type}:${ev.providerRef}`,
  });
  return { paymentId: row?.id ?? null, event };
}

/** The provider's signed call, verified and settled; for the webhook route. */
export async function onProviderCall(provider: string, integrationSlug: string, raw: string, headers: Headers, secret: string):
  Promise<{ ok: boolean; status: number; body: Record<string, unknown> }> {
  const adapter = ADAPTERS[provider];
  if (!adapter) return { ok: false, status: 501, body: { error: `no payment adapter for ${provider}` } };
  const v = adapter.verifyWebhook(raw, headers, secret);
  if (!v.ok) return { ok: false, status: 401, body: { error: v.reason ?? "bad signature" } };
  let parsed: unknown = {};
  try { parsed = JSON.parse(raw); } catch { /* not JSON */ }
  const ev = adapter.normalizeEvent(parsed);
  if (!ev) return { ok: true, status: 200, body: { ignored: true, eventId: v.eventId ?? null } };
  const out = await settle(integrationSlug, ev);
  return { ok: true, status: 202, body: { accepted: true, ...out, eventId: v.eventId ?? null } };
}

export type { NormalizedEvent, PaymentAdapter, PaymentStatus, Secrets } from "./types";
