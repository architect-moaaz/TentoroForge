/**
 * Subscriptions: the application's plans, who holds one, and whether they may
 * use what a plan opens.
 *
 * THE GATEWAY IS THE TRUTH; THE ROW FOLLOWS IT. Every change — the payer
 * coming back, a signed event, a renewal that should have happened — is read
 * from the gateway and written over the row, never applied as a delta. So an
 * event that arrives twice, late or out of order changes nothing it should not.
 *
 * ACCESS: a subscription that is active or trialing; past due within a grace
 * period (a card renewal in India waits on its e-mandate for up to a day and
 * a half); cancelled at the period's end until that end. When the period has
 * passed with nothing heard, the gateway is asked once before access is
 * refused — a lost webhook never locks a paying subscriber out.
 */
import crypto from "node:crypto";
import { sql } from "drizzle-orm";
import { db } from "@/db";
import { PAYMENTS } from "@/lib/payments-config";
import { ADAPTERS, gatewayFor, gateways, secretsFor } from "./index";
import { currencyFor } from "./routing";
import { toMinor } from "./units";
import { GatewayError } from "./http";
import type { Normalized, PlanSpec, Secrets, SubSnapshot, SubscriptionStatus } from "./types";

/** Days a lapsed renewal keeps access while the gateway retries. */
export const GRACE_DAYS = 3;
/** How long the signed access token the middleware reads stays good. */
export const ACCESS_TTL_S = 6 * 3600;

export interface Plan {
  id: string; name: string; description?: string; interval: "day" | "week" | "month" | "year"; intervalCount: number;
  prices: Record<string, number>; trialDays: number; features: string[]; highlighted?: boolean;
}

export interface SubRow {
  id: string; user_id: string; plan_id: string; provider: string; provider_ref: string | null; status: SubscriptionStatus;
  currency: string; amount_minor: number; interval: string; current_period_end: string | Date | null; cancel_at_period_end: boolean;
  customer_ref: string | null; checked_at: string | Date | null; metadata: Record<string, unknown>; created_at?: string | Date;
}

function _rows(res: unknown): any[] {
  return Array.isArray(res) ? res : ((res as { rows?: any[] })?.rows ?? []);
}

export function plans(): Plan[] {
  return ((PAYMENTS?.plans ?? []) as Plan[]).filter((p) => p && p.id && Object.keys(p.prices ?? {}).length);
}

export function subscriptionsOffered(): boolean {
  return Boolean(PAYMENTS?.needed) && (PAYMENTS?.models ?? []).includes("subscription") && plans().length > 0;
}

/** Must a person hold an active subscription to use the application? */
export function accessRequired(): boolean {
  return subscriptionsOffered() && PAYMENTS?.access === "app";
}

/** The currencies a plan list is priced in, the one this payer sees first, and every plan's price in it. */
export function priceList(country?: string | null): { currencies: string[]; currency: string } {
  const currencies = Array.from(new Set(plans().flatMap((p) => Object.keys(p.prices).map((c) => c.toUpperCase()))));
  const appCurrency = String(PAYMENTS?.currency ?? currencies[0] ?? "USD").toUpperCase();
  return { currencies, currency: currencyFor(currencies, appCurrency, country) };
}

/** The gateway's view of one plan at one price — the key changes when the price does. */
export function specFor(plan: Plan, currency: string): PlanSpec {
  const c = currency.toUpperCase();
  const amount = Number(plan.prices[c]);
  const amountMinor = toMinor(amount, c);
  const app = String(process.env.FORGE_APP_ID ?? "app").toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 12) || "app";
  return { key: `forge-${app}-${plan.id}-${plan.interval}${plan.intervalCount}-${c}-${amountMinor}-t${plan.trialDays ?? 0}`.slice(0, 200),
    planId: plan.id, name: plan.name, description: plan.description ?? "", interval: plan.interval, intervalCount: plan.intervalCount || 1,
    amountMinor, currency: c, trialDays: Number(plan.trialDays ?? 0) };
}

/** Which account a gateway's keys belong to, without the secret: a plan made at one
 *  account (or in test mode) is not a plan at another (or live). */
function accountOf(secrets: Secrets | null): string {
  return crypto.createHash("sha256").update(secrets?.keyId || secrets?.secret || "").digest("hex").slice(0, 12);
}

async function planRef(provider: string, spec: PlanSpec, secrets: Secrets | null, again = false): Promise<string> {
  const key = `${provider}:${accountOf(secrets)}:${spec.key}`;
  if (again) await db.execute(sql`DELETE FROM forge_plan_refs WHERE key = ${key}`);
  const found = again ? null : _rows(await db.execute(sql`SELECT ref FROM forge_plan_refs WHERE key = ${key} LIMIT 1`))[0];
  if (found?.ref) return String(found.ref);
  const adapter = ADAPTERS[provider];
  const keys = provider === "stand_in" ? { secret: "" } : secrets;
  if (!adapter?.subscriptions || !keys) throw new Error(`${provider} cannot hold a subscription here`);
  const ref = await adapter.subscriptions.ensurePlan(spec, keys);
  await db.execute(sql`INSERT INTO forge_plan_refs (key, provider, ref) VALUES (${key}, ${provider}, ${ref}) ON CONFLICT (key) DO NOTHING`);
  // Two first subscribers at once: both may have made one; the first kept is used.
  const kept = _rows(await db.execute(sql`SELECT ref FROM forge_plan_refs WHERE key = ${key} LIMIT 1`))[0];
  return String(kept?.ref ?? ref);
}

/** The gateway no longer knows the plan it was given (archived at Stripe, deactivated at PayPal, an id from before the keys changed). */
export function missingPlan(err: unknown): boolean {
  if (!(err instanceof GatewayError) || ![400, 404, 422].includes(err.status)) return false;
  const said = `${err.message} ${JSON.stringify(err.body ?? {})}`;
  return /no such price|price specified is inactive|"param":"line_items\[0\]\[price\]"/i.test(said)
    || (/plan/i.test(said) && /does not exist|not found|inactive|INVALID_RESOURCE_ID|RESOURCE_NOT_FOUND/i.test(said));
}

/** The gateway does not know the subscription it was asked about (an id from before the keys changed to another account). */
export function missingSubscription(err: unknown): boolean {
  if (!(err instanceof GatewayError) || ![400, 404].includes(err.status)) return false;
  const said = `${err.message} ${JSON.stringify(err.body ?? {})}`;
  return /no such subscription|the id provided does not exist|INVALID_RESOURCE_ID|RESOURCE_NOT_FOUND/i.test(said);
}

export async function rowFor(id: string): Promise<SubRow | null> {
  if (!id) return null;
  const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
  const res = isUuid
    ? await db.execute(sql`SELECT * FROM forge_subscriptions WHERE id = ${id}::uuid OR provider_ref = ${id} LIMIT 1`)
    : await db.execute(sql`SELECT * FROM forge_subscriptions WHERE provider_ref = ${id} LIMIT 1`);
  return (_rows(res)[0] as SubRow) ?? null;
}

/** The person's subscription that matters: the newest that is not abandoned. */
export async function current(userId: string): Promise<SubRow | null> {
  const res = await db.execute(sql`
    SELECT * FROM forge_subscriptions WHERE user_id = ${userId} AND status <> 'incomplete'
    ORDER BY (status IN ('active', 'trialing', 'past_due')) DESC, updated_at DESC LIMIT 1`);
  return (_rows(res)[0] as SubRow) ?? null;
}

function endOf(row: SubRow): number {
  return row.current_period_end ? new Date(row.current_period_end as any).getTime() : 0;
}

/** May this row use what a plan opens, now? */
export function grants(row: SubRow | null, now = Date.now()): boolean {
  if (!row) return false;
  const end = endOf(row);
  if (row.status === "active" || row.status === "trialing") return !end || now < end + GRACE_DAYS * 86_400_000;
  if (row.status === "past_due") return Boolean(end) && now < end + GRACE_DAYS * 86_400_000;
  if (row.status === "cancelled" && row.cancel_at_period_end) return Boolean(end) && now < end;
  return false;
}

async function write(row: SubRow, snap: SubSnapshot, endsNow = false): Promise<SubRow> {
  // Asked to end at the period's end, it keeps saying so until the gateway
  // says it ended, or it is ended now.
  const cancelAtEnd = !endsNow && (snap.cancelAtPeriodEnd || (Boolean(row.cancel_at_period_end) && snap.status !== "expired"));
  const res = await db.execute(sql`
    UPDATE forge_subscriptions SET status = ${snap.status},
      -- A KNOWN END IS NOT ERASED BY AN UNKNOWN ONE. PayPal reports no next
      -- billing time once a subscription is cancelled; written over, the
      -- period the person paid for would close the moment the webhook landed.
      current_period_end = COALESCE(${snap.currentPeriodEnd}::timestamptz, current_period_end),
      cancel_at_period_end = ${cancelAtEnd}, provider_ref = COALESCE(${snap.providerRef || null}, provider_ref),
      customer_ref = COALESCE(${snap.customerRef ?? null}, customer_ref), checked_at = NOW(), updated_at = NOW()
    WHERE id = ${row.id}::uuid RETURNING *`);
  return (_rows(res)[0] as SubRow) ?? row;
}

/** Read the subscription from its gateway and write the row to match. */
export async function refresh(row: SubRow): Promise<SubRow> {
  if (row.provider === "stand_in" || !row.provider_ref) return row;
  const adapter = ADAPTERS[row.provider];
  const secrets = await secretsFor(row.provider);
  if (!adapter?.subscriptions || !secrets) return row;
  const snap = await adapter.subscriptions.retrieve(String(row.provider_ref), secrets);
  return write(row, snap);
}

/** Does this person hold access now? Asks the gateway once when the paid period has run out unheard. */
export async function hasAccess(userId: string): Promise<{ ok: boolean; row: SubRow | null }> {
  let row = await current(userId);
  if (!row) return { ok: false, row: null };
  const end = endOf(row);
  const stale = !row.checked_at || Date.now() - new Date(row.checked_at as any).getTime() > 3_600_000;
  // Asked at most once an hour, and only when the row alone would say no, the
  // period has run out, or it has no end yet (a Razorpay subscription waiting
  // on its first charge: unasked, it would open the app for good).
  if (stale && (!grants(row) || !end || Date.now() > end)) {
    try { row = await refresh(row); } catch (err) { console.error("[billing] could not ask the gateway:", err); }
  }
  return { ok: grants(row), row };
}

export interface StartResult { url: string; subscriptionId: string; provider: string; standIn: boolean; notice?: string }

/** Begin a subscription to `planId` for this person: the gateway for their currency, the plan made there once, a row, and where they go to authorise it. */
export async function subscribe(input: { user: { id: string; email?: string | null; name?: string | null }; planId: string;
  currency?: string; country?: string | null; origin: string }): Promise<StartResult> {
  const plan = plans().find((p) => p.id === input.planId);
  if (!plan) throw new Error(`there is no plan "${input.planId}"`);
  const have = await current(input.user.id);
  // Held, or ending but still held: taken again, it would be charged now for
  // a period already paid for. After it ends it can be taken again.
  if (have && grants(have) && have.plan_id === plan.id) {
    throw new Error(have.cancel_at_period_end || have.status === "cancelled"
      ? "you already hold this plan until its period ends; choose it again after that"
      : "you already hold this plan");
  }
  const { currency: suggested } = priceList(input.country);
  const currency = String(input.currency || suggested).toUpperCase();
  if (!(currency in plan.prices)) throw new Error(`${plan.name} has no price in ${currency}`);
  const chosen = await gatewayFor({ currency, country: input.country });
  const adapter = chosen.adapter;
  if (!adapter.subscriptions) throw new Error(`${adapter.provider} cannot take a subscription`);
  const spec = specFor(plan, currency);
  let ref = await planRef(adapter.provider, spec, chosen.secrets);
  const inserted = _rows(await db.execute(sql`
    INSERT INTO forge_subscriptions (user_id, plan_id, provider, status, currency, amount_minor, interval, metadata)
    VALUES (${input.user.id}, ${plan.id}, ${adapter.provider}, 'incomplete', ${currency}, ${spec.amountMinor}, ${plan.interval},
            ${JSON.stringify({ gateway: chosen.gateway?.id ?? null, planKey: spec.key })}::jsonb)
    RETURNING id`))[0];
  const subscriptionId = String(inserted.id);
  const origin = input.origin.replace(/\/$/, "");
  const base = (process.env.NEXT_PUBLIC_BASE_PATH ?? "").replace(/\/$/, "");
  const start = () => adapter.subscriptions!.start({
    subscriptionId, planRef: ref, plan: spec, customerEmail: input.user.email ?? undefined, customerName: input.user.name ?? undefined,
    successUrl: `${origin}${base}/api/billing/return?subscription=${subscriptionId}`,
    cancelUrl: `${origin}${base}/billing?cancelled=1`,
    metadata: { userId: input.user.id, planId: plan.id },
  }, chosen.secrets, origin);
  let started;
  try {
    started = await start();
  } catch (err) {
    if (!missingPlan(err)) throw err;
    // A PLAN THE GATEWAY NO LONGER KNOWS is made again, once — not refused to
    // every subscriber from now on.
    console.warn("[billing] the gateway no longer knows plan", ref, "— making it again");
    ref = await planRef(adapter.provider, spec, chosen.secrets, true);
    started = await start();
  }
  await db.execute(sql`UPDATE forge_subscriptions SET provider_ref = ${started.providerRef}, updated_at = NOW() WHERE id = ${subscriptionId}::uuid`);
  return { url: started.url, subscriptionId, provider: adapter.provider, standIn: !chosen.live, ...(chosen.notice ? { notice: chosen.notice } : {}) };
}

/** The payer came back from the gateway (or its window): read the subscription and write it down. */
export async function confirmReturn(subscriptionId: string, userId: string, params: Record<string, string> = {}): Promise<SubRow | null> {
  let row = await rowFor(subscriptionId);
  if (!row || row.user_id !== userId) return null;
  if (row.provider === "razorpay" && params.razorpay_signature) {
    const { subscriptionSignatureOk } = await import("./razorpay");
    const secrets = await secretsFor("razorpay");
    if (!secrets || !subscriptionSignatureOk(secrets.secret, String(row.provider_ref), String(params.razorpay_payment_id ?? ""), String(params.razorpay_signature))) {
      throw new Error("the subscription's signature did not check out");
    }
  }
  row = await refresh(row);
  // An authorised Razorpay subscription is `authenticated` until its first charge
  // lands (minutes): the signature above already proved the payer authorised it.
  if (row.provider === "razorpay" && params.razorpay_signature && row.status === "incomplete") {
    row = await write(row, { status: "trialing", currentPeriodEnd: null, cancelAtPeriodEnd: false });
  }
  if (grants(row)) await supersede(row);
  return row;
}

/** A new plan taken: the person's other live subscriptions end with their periods (never two charges). */
async function supersede(row: SubRow): Promise<void> {
  const others = _rows(await db.execute(sql`
    SELECT * FROM forge_subscriptions WHERE user_id = ${row.user_id} AND id <> ${row.id}::uuid
      AND status IN ('active', 'trialing', 'past_due') AND cancel_at_period_end = false`)) as SubRow[];
  for (const other of others) {
    try { await cancel(other, true); } catch (err) { console.error("[billing] could not end the earlier subscription:", err); }
  }
}

/** The stand-in's page: "subscribed" makes it active for one period; "failed" leaves it incomplete. */
export async function standInSettle(subscriptionId: string, userId: string, outcome: "paid" | "failed"): Promise<SubRow | null> {
  const row = await rowFor(subscriptionId);
  if (!row || row.user_id !== userId || row.provider !== "stand_in") return null;
  if (outcome !== "paid") return row;
  const days = { day: 1, week: 7, month: 30, year: 365 }[String(row.interval)] ?? 30;
  const written = await write(row, { status: "active", currentPeriodEnd: new Date(Date.now() + days * 86_400_000).toISOString(), cancelAtPeriodEnd: false });
  await supersede(written);
  return written;
}

/** End a subscription: at the end of what was paid for (the default) or now. */
export async function cancel(row: SubRow, atPeriodEnd = true): Promise<SubRow> {
  const over = row.status === "cancelled" || row.status === "expired";
  // ASKED ALREADY, OR OVER: nothing is sent again. Every gateway refuses to
  // cancel a cancelled subscription, and a second "at the period's end"
  // changes nothing.
  if (atPeriodEnd && (over || row.cancel_at_period_end)) return row;
  // ENDED NOW, whatever an earlier "at the period's end" said: what the plan
  // opened closes with it.
  const endedNow = (snap?: SubSnapshot) => write(row, { ...(snap ?? { providerRef: "" }), status: "cancelled",
    cancelAtPeriodEnd: false, currentPeriodEnd: new Date().toISOString() }, true);
  if (over) return endedNow();
  if (row.provider === "stand_in") {
    return atPeriodEnd ? write(row, { status: row.status, currentPeriodEnd: null, cancelAtPeriodEnd: true, providerRef: "" }) : endedNow();
  }
  const adapter = ADAPTERS[row.provider];
  const secrets = await secretsFor(row.provider);
  if (!adapter?.subscriptions || !secrets || !row.provider_ref) throw new Error("this subscription cannot be cancelled here");
  let snap: SubSnapshot;
  try {
    snap = await adapter.subscriptions.cancel(String(row.provider_ref), atPeriodEnd, secrets);
  } catch (err) {
    if (!missingSubscription(err)) throw err;
    // A SUBSCRIPTION THE GATEWAY NO LONGER KNOWS can charge no one again: it
    // ends here as asked, not refused at every try. What was paid for stays
    // open until its end.
    console.warn("[billing] the gateway no longer knows subscription", row.provider_ref, "— ending it here");
    return atPeriodEnd && endOf(row) > Date.now()
      ? write(row, { status: "cancelled", currentPeriodEnd: null, cancelAtPeriodEnd: true, providerRef: "" })
      : endedNow();
  }
  return atPeriodEnd ? write(row, { ...snap, cancelAtPeriodEnd: true }) : endedNow(snap);
}

/** Where the subscriber manages their card at the gateway, when it has such a page. */
export async function manageUrl(row: SubRow, returnUrl: string): Promise<string | null> {
  const adapter = ADAPTERS[row.provider];
  const secrets = await secretsFor(row.provider);
  if (!adapter?.subscriptions?.manageUrl || !secrets || !row.provider_ref) return null;
  return adapter.subscriptions.manageUrl({ providerRef: String(row.provider_ref), customerRef: row.customer_ref }, returnUrl, secrets);
}

/** A gateway's signed event about a subscription: find the row and read the subscription again. */
export async function onSubscriptionEvent(provider: string, ev: Normalized): Promise<{ subscriptionId: string | null; status: string | null }> {
  let row = (ev.subscriptionId ? await rowFor(ev.subscriptionId) : null) ?? await rowFor(ev.providerRef);
  if (!row) return { subscriptionId: null, status: null };
  if (row.provider !== provider) return { subscriptionId: row.id, status: row.status };
  // Stripe's checkout session becomes a subscription id: the row learns it.
  if (ev.providerRef && ev.providerRef !== row.provider_ref && !String(ev.providerRef).startsWith("cs_")) {
    await db.execute(sql`UPDATE forge_subscriptions SET provider_ref = ${ev.providerRef} WHERE id = ${row.id}::uuid`);
    row = { ...row, provider_ref: ev.providerRef };
  }
  const before = row.status;
  row = await refresh(row);
  if (grants(row) && before === "incomplete") await supersede(row);
  if (before !== row.status) {
    try {
      const { emitEventAndProcess } = await import("@/lib/events/bus");
      await emitEventAndProcess(`billing.subscription.${row.status}`, {
        entity: "subscription", entityId: row.id,
        payload: { subscriptionId: row.id, planId: row.plan_id, status: row.status, user: { id: row.user_id }, provider },
        dedupeKey: `billing:${row.id}:${row.status}:${row.current_period_end ?? ""}`,
      });
    } catch (err) {
      console.error("[billing] could not tell the app about the subscription:", err);
    }
  }
  return { subscriptionId: row.id, status: row.status };
}

// --------------------------------------------------------------------------
// The access token the middleware reads: who, until when, signed.
// --------------------------------------------------------------------------

function key(): string {
  return String(process.env.NEXTAUTH_SECRET ?? process.env.AUTH_SECRET ?? "");
}

export const ACCESS_COOKIE = "forge_access";

export function signAccess(userId: string, until: number): string {
  const body = `${userId}.${Math.floor(until)}`;
  const sig = crypto.createHmac("sha256", key()).update(body).digest("base64url");
  return `${Buffer.from(body).toString("base64url")}.${sig}`;
}

/** The token for this person, good until the earlier of its TTL and the end of what they hold. */
export function accessToken(userId: string, row: SubRow | null): { value: string; maxAge: number } | null {
  if (!key() || !grants(row)) return null;
  const end = row ? endOf(row) : 0;
  const now = Date.now();
  const until = Math.min(now + ACCESS_TTL_S * 1000, end ? end + GRACE_DAYS * 86_400_000 : now + ACCESS_TTL_S * 1000);
  return { value: signAccess(userId, until / 1000), maxAge: Math.max(60, Math.floor((until - now) / 1000)) };
}

export { gateways };
