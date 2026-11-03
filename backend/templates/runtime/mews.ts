/**
 * Mews properties: the hotels this application reaches, and the one place a
 * property's token is opened.
 *
 * Mews issues ONE client token per integration (the organisation's, under
 * Settings → Integrations → Mews, as MEWS_CLIENT_TOKEN) and ONE access token
 * per hotel. An application that serves many hotels keeps them here, in
 * `forge_mews_properties`, where its administrator adds, changes and removes
 * them while the application runs — no redeploy, no environment edit. A
 * property's token is sealed on write and read back only as its mask; it is
 * opened inside `credentialsFor`, for the call being signed, and nowhere
 * else. A property without a token of its own is reached with the
 * organisation's portfolio token (MEWS_ACCESS_TOKEN) and its enterprise id.
 *
 * Server-only. Forge runtime — do not remove.
 */
import { sql } from "drizzle-orm";
import { db } from "@/db";
// Read as a namespace: an application built before `DECLARED` existed has a
// connected.ts without it, and reads as declaring nothing.
import * as connected from "@/lib/integrations/connected";
import { decryptSensitive, encryptSensitive, looksMasked, mask } from "./sensitive-crypto";

export type Environment = "demo" | "production";

/** A property as anyone may read it: the token is only ever its mask. */
export interface MewsProperty {
  id: string;
  name: string;
  enterpriseId: string | null;
  environment: Environment;
  tokenMask: string | null;
  hasToken: boolean;
  enterpriseName: string | null;
  checkedAt: string | null;
  checkOk: boolean | null;
  checkMessage: string | null;
  createdAt: string | null;
  updatedAt: string | null;
}

/** What a Mews call is signed with. Never returned to a page or a step. */
export interface MewsCredentials {
  clientToken: string;
  accessToken: string;
  client: string;
  enterpriseId: string | null;
  host: string;
  property: { id: string; name: string } | null;
}

/** A property the administrator wants, or a change to one. */
export interface PropertyInput {
  name?: unknown;
  enterpriseId?: unknown;
  environment?: unknown;
  /** A new token; null removes it; absent, empty of meaning or a mask keeps it. */
  accessToken?: unknown;
}

export class MewsError extends Error {
  status: number;
  constructor(message: string, status = 400) {
    super(message);
    this.status = status;
  }
}

const HOSTS: Record<Environment, string> = { demo: "https://api.mews-demo.com", production: "https://api.mews.com" };
const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const DEFAULT_CLIENT = "Tentoro Forge 1.0.0";

/** Whether this application declares a Mews integration at all. */
export function mewsOn(): boolean {
  const declared = ((connected as any).DECLARED ?? {}) as Record<string, { provider?: string }>;
  return Object.values(declared).some((s) => String(s?.provider || "").toLowerCase() === "mews");
}

export function hostFor(environment: unknown): string {
  return HOSTS[environment === "production" ? "production" : "demo"];
}

function _rows(res: unknown): any[] {
  return Array.isArray(res) ? res : ((res as { rows?: any[] })?.rows ?? []);
}

let _ensured: Promise<void> | null = null;
/**
 * The table, made where the schema push has not (an application built before
 * properties existed, refreshed by Smith). The schema file declares it too, so
 * the next push keeps it.
 */
export function ensure(): Promise<void> {
  if (!_ensured) {
    _ensured = db.execute(sql`
      CREATE TABLE IF NOT EXISTS forge_mews_properties (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        name text NOT NULL,
        enterprise_id text,
        environment text NOT NULL DEFAULT 'demo',
        access_token_encrypted text,
        access_token_mask text,
        enterprise_name text,
        checked_at timestamp,
        check_ok boolean,
        check_message text,
        created_by text,
        created_at timestamp NOT NULL DEFAULT now(),
        updated_at timestamp NOT NULL DEFAULT now()
      )`).then(() => undefined).catch((err) => { _ensured = null; throw err; });
  }
  return _ensured;
}

function _public(r: any): MewsProperty {
  const iso = (v: unknown) => (v ? new Date(v as string).toISOString() : null);
  return {
    id: String(r.id),
    name: String(r.name),
    enterpriseId: r.enterprise_id ?? null,
    environment: r.environment === "production" ? "production" : "demo",
    tokenMask: r.access_token_mask ?? null,
    hasToken: Boolean(r.has_token),
    enterpriseName: r.enterprise_name ?? null,
    checkedAt: iso(r.checked_at),
    checkOk: r.check_ok ?? null,
    checkMessage: r.check_message ?? null,
    createdAt: iso(r.created_at),
    updatedAt: iso(r.updated_at),
  };
}

// The encrypted column is never selected for reading: only `has_token`.
const PUBLIC_COLUMNS = sql`id, name, enterprise_id, environment, access_token_mask,
  (access_token_encrypted IS NOT NULL) AS has_token, enterprise_name, checked_at, check_ok,
  check_message, created_at, updated_at`;

export async function listProperties(): Promise<MewsProperty[]> {
  await ensure();
  return _rows(await db.execute(sql`SELECT ${PUBLIC_COLUMNS} FROM forge_mews_properties ORDER BY lower(name)`)).map(_public);
}

export async function getProperty(id: string): Promise<MewsProperty | null> {
  if (!GUID.test(id)) return null;
  await ensure();
  const row = _rows(await db.execute(sql`SELECT ${PUBLIC_COLUMNS} FROM forge_mews_properties WHERE id = ${id}::uuid`))[0];
  return row ? _public(row) : null;
}

function _text(v: unknown): string | null {
  if (v === undefined || v === null) return null;
  const s = String(v).trim();
  return s ? s : null;
}

function _environment(v: unknown, fallback: Environment): Environment {
  if (v === undefined || v === null || v === "") return fallback;
  if (v === "demo" || v === "production") return v;
  throw new MewsError('The environment is "demo" or "production".');
}

function _enterpriseId(v: unknown): string | null {
  const s = _text(v);
  if (s && !GUID.test(s)) throw new MewsError("The enterprise id is the property's Mews id, e.g. 851df8c8-90f2-4c4a-8e01-a4fc46b25178.");
  return s ? s.toLowerCase() : null;
}

/** A token to seal, null to remove it, undefined to keep what is there. */
function _token(v: unknown): string | null | undefined {
  if (v === undefined) return undefined;
  if (v === null) return null;
  const s = String(v).trim();
  if (!s || looksMasked(s)) return undefined;
  return s;
}

async function _nameTaken(name: string, except: string | null): Promise<boolean> {
  const rows = _rows(await db.execute(sql`
    SELECT 1 FROM forge_mews_properties
    WHERE lower(name) = lower(${name}) AND (${except}::uuid IS NULL OR id <> ${except}::uuid) LIMIT 1`));
  return rows.length > 0;
}

async function _enterpriseTaken(enterpriseId: string, except: string | null): Promise<boolean> {
  const rows = _rows(await db.execute(sql`
    SELECT 1 FROM forge_mews_properties
    WHERE enterprise_id = ${enterpriseId} AND (${except}::uuid IS NULL OR id <> ${except}::uuid) LIMIT 1`));
  return rows.length > 0;
}

function _reachable(hasToken: boolean, enterpriseId: string | null): void {
  // Without a token of its own a property is reached with the portfolio
  // token, which needs the enterprise id to say which hotel.
  if (!hasToken && !enterpriseId) {
    throw new MewsError("Give the property its access token, or its enterprise id to reach it with the organisation's portfolio token.");
  }
}

/** A token sealed with the app's key — or a refusal the administrator can read. */
async function _seal(token: string): Promise<string> {
  try {
    return await encryptSensitive(token);
  } catch {
    throw new MewsError("This application has no encryption key yet (SENSITIVE_ENCRYPTION_KEY), so a token cannot be "
      + "stored safely. Ask Forge to bring the application up to date, then add the token again.", 503);
  }
}

export async function addProperty(input: PropertyInput, actorId: string | null): Promise<MewsProperty> {
  await ensure();
  const name = _text(input.name);
  if (!name) throw new MewsError("A property needs a name.");
  const enterpriseId = _enterpriseId(input.enterpriseId);
  const environment = _environment(input.environment, "demo");
  const token = _token(input.accessToken) ?? null;
  _reachable(Boolean(token), enterpriseId);
  if (await _nameTaken(name, null)) throw new MewsError(`There is already a property called "${name}".`, 409);
  if (enterpriseId && await _enterpriseTaken(enterpriseId, null)) {
    throw new MewsError("That enterprise id already belongs to another property.", 409);
  }
  const sealed = token ? await _seal(token) : null;
  const masked = token ? mask(token, "last4") : null;
  const row = _rows(await db.execute(sql`
    INSERT INTO forge_mews_properties (name, enterprise_id, environment, access_token_encrypted, access_token_mask, created_by)
    VALUES (${name}, ${enterpriseId}, ${environment}, ${sealed}, ${masked}, ${actorId})
    RETURNING ${PUBLIC_COLUMNS}`))[0];
  return _public(row);
}

export async function updateProperty(id: string, input: PropertyInput): Promise<MewsProperty> {
  const current = await getProperty(id);
  if (!current) throw new MewsError("No such property.", 404);
  const name = input.name === undefined ? current.name : _text(input.name);
  if (!name) throw new MewsError("A property needs a name.");
  const enterpriseId = input.enterpriseId === undefined ? current.enterpriseId : _enterpriseId(input.enterpriseId);
  const environment = _environment(input.environment, current.environment);
  const token = _token(input.accessToken);
  const hasToken = token === undefined ? current.hasToken : token !== null;
  _reachable(hasToken, enterpriseId);
  if (name.toLowerCase() !== current.name.toLowerCase() && await _nameTaken(name, id)) {
    throw new MewsError(`There is already a property called "${name}".`, 409);
  }
  if (enterpriseId && enterpriseId !== current.enterpriseId && await _enterpriseTaken(enterpriseId, id)) {
    throw new MewsError("That enterprise id already belongs to another property.", 409);
  }
  // A change of host or hotel makes the last check say nothing about now.
  const recheck = environment !== current.environment || enterpriseId !== current.enterpriseId || token !== undefined;
  const tokenSql = token === undefined
    ? sql`access_token_encrypted = access_token_encrypted, access_token_mask = access_token_mask`
    : token === null
      ? sql`access_token_encrypted = NULL, access_token_mask = NULL`
      : sql`access_token_encrypted = ${await _seal(token)}, access_token_mask = ${mask(token, "last4")}`;
  const checkSql = recheck ? sql`, check_ok = NULL, checked_at = NULL, check_message = NULL, enterprise_name = NULL` : sql``;
  const row = _rows(await db.execute(sql`
    UPDATE forge_mews_properties
    SET name = ${name}, enterprise_id = ${enterpriseId}, environment = ${environment}, ${tokenSql}${checkSql}, updated_at = now()
    WHERE id = ${id}::uuid
    RETURNING ${PUBLIC_COLUMNS}`))[0];
  return _public(row);
}

export async function removeProperty(id: string): Promise<boolean> {
  if (!GUID.test(id)) return false;
  await ensure();
  return _rows(await db.execute(sql`DELETE FROM forge_mews_properties WHERE id = ${id}::uuid RETURNING id`)).length > 0;
}

function _env(name: string): string {
  return String(process.env[name] ?? "").trim();
}

/** The organisation's settings: the client token, the client name, and a portfolio or single-hotel token. */
function _organisation() {
  return {
    clientToken: _env("MEWS_CLIENT_TOKEN"),
    accessToken: _env("MEWS_ACCESS_TOKEN"),
    client: _env("MEWS_CLIENT") || DEFAULT_CLIENT,
    environment: (_env("MEWS_ENVIRONMENT") === "production" ? "production" : "demo") as Environment,
  };
}

async function _findRow(ref: string): Promise<any | null> {
  await ensure();
  const key = ref.trim();
  if (!key) return null;
  const rows = _rows(await db.execute(sql`
    SELECT id, name, enterprise_id, environment, access_token_encrypted FROM forge_mews_properties
    WHERE (${GUID.test(key)} AND (id::text = lower(${key}) OR enterprise_id = lower(${key})))
       OR lower(name) = lower(${key})
    ORDER BY (id::text = lower(${key})) DESC LIMIT 1`));
  return rows[0] ?? null;
}

/**
 * What a Mews call is signed with.
 *
 * `ref` names a property (its id, Mews enterprise id or name). Without one:
 * the organisation's own access token when it set one (an application with a
 * single hotel), else the only property there is. A named property that is
 * not there, or several with none named, is an error: a call never goes to a
 * hotel nobody chose.
 */
export async function credentialsFor(ref?: unknown): Promise<MewsCredentials> {
  const org = _organisation();
  if (!org.clientToken) throw new MewsError("MEWS_CLIENT_TOKEN is not set in this environment");
  const named = _text(ref);
  let row: any | null = null;
  if (named) {
    row = await _findRow(named);
    if (!row) throw new MewsError(`No Mews property is "${named}"`, 404);
  } else if (org.accessToken) {
    return { clientToken: org.clientToken, accessToken: org.accessToken, client: org.client,
             enterpriseId: null, host: hostFor(org.environment), property: null };
  } else {
    await ensure();
    const rows = _rows(await db.execute(sql`
      SELECT id, name, enterprise_id, environment, access_token_encrypted FROM forge_mews_properties LIMIT 2`));
    if (rows.length === 0) throw new MewsError("No Mews property is set up, and MEWS_ACCESS_TOKEN is not set in this environment");
    if (rows.length > 1) throw new MewsError("There are several Mews properties: the step must say which (auth.property)");
    row = rows[0];
  }
  let accessToken = "";
  if (row.access_token_encrypted) {
    try {
      accessToken = await decryptSensitive(String(row.access_token_encrypted));
    } catch {
      throw new MewsError(`The access token of "${row.name}" could not be opened; enter it again`, 500);
    }
  } else {
    accessToken = org.accessToken;
    if (!accessToken) throw new MewsError(`"${row.name}" has no access token, and MEWS_ACCESS_TOKEN (the portfolio token) is not set`);
  }
  return { clientToken: org.clientToken, accessToken, client: org.client,
           enterpriseId: row.enterprise_id ?? null, host: hostFor(row.environment),
           property: { id: String(row.id), name: String(row.name) } };
}

/** The body Mews reads: the operation's own fields, then the credentials. */
export function signedBody(given: unknown, creds: MewsCredentials): Record<string, unknown> {
  const base = given && typeof given === "object" && !Array.isArray(given) ? (given as Record<string, unknown>) : {};
  return {
    ...base,
    ...(creds.enterpriseId && base.EnterpriseId === undefined ? { EnterpriseId: creds.enterpriseId } : {}),
    ClientToken: creds.clientToken,
    AccessToken: creds.accessToken,
    Client: creds.client,
  };
}

/**
 * Ask Mews who the property is (configuration/get) and keep the answer, so
 * the administrator sees at once whether its token and enterprise id work.
 */
export async function checkProperty(id: string): Promise<MewsProperty> {
  const current = await getProperty(id);
  if (!current) throw new MewsError("No such property.", 404);
  let ok = false;
  let message = "";
  let enterpriseName: string | null = null;
  try {
    const creds = await credentialsFor(id);
    const res = await fetch(`${creds.host}/api/connector/v1/configuration/get`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(signedBody({}, creds)),
      signal: AbortSignal.timeout(20_000),
    });
    const body: any = await res.json().catch(() => null);
    if (res.ok) {
      ok = true;
      enterpriseName = body?.Enterprise?.Name ? String(body.Enterprise.Name) : null;
      message = enterpriseName ? `Connected to ${enterpriseName}.` : "Connected.";
    } else {
      message = `Mews answered ${res.status}: ${String(body?.Message || res.statusText || "no reason given")}`;
    }
  } catch (err) {
    message = err instanceof MewsError ? err.message : `Mews could not be reached: ${String((err as Error)?.message || err)}`;
  }
  const row = _rows(await db.execute(sql`
    UPDATE forge_mews_properties
    SET check_ok = ${ok}, check_message = ${message.slice(0, 500)}, enterprise_name = ${enterpriseName}, checked_at = now()
    WHERE id = ${id}::uuid
    RETURNING ${PUBLIC_COLUMNS}`))[0];
  return _public(row);
}

// --------------------------------------------------------------------------- //
// FINDING A STAY. A desk starts a refund from the stay it is about: a
// confirmation number, a guest's last name or a room. Mews answers each of
// those directly — reservations by `Numbers`, customers by `LastNames` then
// their reservations by `AccountIds`, rooms by `Names` then the stays in them
// by `AssignedResourceIds` — so a search never downloads a hotel's whole
// reservation list to read the match out of it. Each stay comes back with its
// guest, room and charged payment, ready to be kept as records.
// --------------------------------------------------------------------------- //

/** A stay Mews found, in the words a refund case needs. */
export interface MewsStay {
  reservationId: string;
  confirmationNumber: string | null;
  reservationStatus: string | null;
  arrivalDate: string | null;
  departureDate: string | null;
  customerId: string | null;
  accountId: string | null;
  guestName: string | null;
  guestEmail: string | null;
  roomNumber: string | null;
  billId: string | null;
  /** The stay's charged payment (a card one when there is one), or null. */
  payment: { id: string; amount: number | null; currency: string | null; kind: string | null;
             cardLast4: string | null; billId: string | null } | null;
}

/** How far back and ahead stays are looked for and kept: Mews caps an interval at three months. */
const STAY_WINDOW_DAYS = { back: 60, ahead: 30 };

async function _call(creds: MewsCredentials, operation: string, body: Record<string, unknown>): Promise<any> {
  let res!: Response;
  // TOO MANY REQUESTS IS WAITED OUT. Mews limits each token; a sync reading a
  // busy hotel met it on the demo and stopped (2026-11-03).
  for (let attempt = 0; attempt < 3; attempt++) {
    res = await fetch(`${creds.host}/api/connector/v1/${operation}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(signedBody(body, creds)),
      signal: AbortSignal.timeout(20_000),
    });
    if (res.status !== 429 || attempt === 2) break;
    const after = Number(res.headers.get("retry-after"));
    await new Promise((r) => setTimeout(r, Number.isFinite(after) && after > 0 ? Math.min(after, 10) * 1000 : 1500 * (attempt + 1)));
  }
  const answer: any = await res.json().catch(() => null);
  if (!res.ok) throw new MewsError(`Mews answered ${res.status} to ${operation}: ${String(answer?.Message || res.statusText || "no reason given")}`, 502);
  return answer ?? {};
}

function _day(utc: unknown): string | null {
  const s = typeof utc === "string" ? utc : "";
  return /^\d{4}-\d{2}-\d{2}/.test(s) ? s.slice(0, 10) : null;
}

function _iso(d: Date): string {
  return d.toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** A charged payment of the stay, a card one first. */
function _payment(payments: any[]): MewsStay["payment"] {
  const charged = payments.filter((p) => String(p?.State || "") === "Charged");
  const card = (p: any) => /card/i.test(String(p?.Type || "")) || /card/i.test(String(p?.Kind || ""))
    || Boolean(p?.Data?.CreditCard);
  const p = charged.find(card) ?? charged[0];
  if (!p) return null;
  const gross = Number(p?.Amount?.GrossValue);
  const masked = String(p?.Data?.CreditCard?.ObfuscatedNumber || p?.Data?.CreditCard?.Number || "");
  return {
    id: String(p.Id),
    amount: Number.isFinite(gross) ? Math.abs(gross) : null,
    currency: p?.Amount?.Currency ? String(p.Amount.Currency) : null,
    kind: card(p) ? "Card" : String(p?.Type || p?.Kind || "") || null,
    cardLast4: /\d{4}$/.test(masked) ? masked.slice(-4) : null,
    billId: p?.BillId ? String(p.BillId) : null,
  };
}

/**
 * The stays matching `term` — a confirmation number, a guest's last name or a
 * room — newest first, at most `limit`. `ref` names the property as
 * `credentialsFor` reads it; without one, the organisation's own connection.
 */
export async function findStays(term: unknown, ref?: unknown, limit = 10): Promise<MewsStay[]> {
  const q = String(term ?? "").trim();
  if (!q) return [];
  const creds = await credentialsFor(ref);
  const call = (op: string, body: Record<string, unknown>) => _call(creds, op, body);
  const now = Date.now();
  const window = {
    StartUtc: _iso(new Date(now - STAY_WINDOW_DAYS.back * 864e5)),
    EndUtc: _iso(new Date(now + STAY_WINDOW_DAYS.ahead * 864e5)),
  };
  const capital = q.charAt(0).toUpperCase() + q.slice(1);
  const byNumber = call("reservations/getAll/2023-06-06", { Numbers: [q], Limitation: { Count: limit } });
  const byName = call("customers/getAll", { LastNames: [...new Set([q, capital])], Extent: { Customers: true },
                                            Limitation: { Count: 25 } })
    .then((a) => {
      const ids = (a?.Customers ?? []).map((c: any) => c?.Id).filter(Boolean);
      return ids.length ? call("reservations/getAll/2023-06-06", { AccountIds: ids, Limitation: { Count: limit } }) : {};
    });
  const byRoom = call("resources/getAll", { Names: [q], Limitation: { Count: 10 } })
    .then((a) => {
      const ids = (a?.Resources ?? []).map((r: any) => r?.Id).filter(Boolean);
      return ids.length ? call("reservations/getAll/2023-06-06", { AssignedResourceIds: ids, CollidingUtc: window,
                                                                    Limitation: { Count: limit } }) : {};
    });
  const settled = await Promise.allSettled([byNumber, byName, byRoom]);
  if (settled.every((s) => s.status === "rejected")) throw (settled[0] as PromiseRejectedResult).reason;
  const seen = new Map<string, any>();
  for (const s of settled) {
    if (s.status !== "fulfilled") continue;
    for (const r of s.value?.Reservations ?? []) if (r?.Id && !seen.has(r.Id)) seen.set(r.Id, r);
  }
  const reservations = [...seen.values()]
    .sort((a, b) => String(b?.ScheduledStartUtc || "").localeCompare(String(a?.ScheduledStartUtc || "")))
    .slice(0, limit);
  if (!reservations.length) return [];

  return _enrich(call, reservations);
}

/** Reservations as stays: each with its guest, room and charged payment, in as
 *  few calls as Mews allows (ids are asked for a thousand at a time). */
async function _enrich(call: (op: string, body: Record<string, unknown>) => Promise<any>,
                       reservations: any[]): Promise<MewsStay[]> {
  const chunks = <T,>(xs: T[], n = 1000): T[][] => {
    const out: T[][] = [];
    for (let i = 0; i < xs.length; i += n) out.push(xs.slice(i, i + n));
    return out;
  };
  const accountIds = [...new Set(reservations.map((r) => r.AccountId).filter(Boolean))] as string[];
  const roomIds = [...new Set(reservations.map((r) => r.AssignedResourceId).filter(Boolean))] as string[];
  const reservationIds = reservations.map((r) => r.Id) as string[];
  const all = async (op: string, key: string, ids: string[], list: string, extra: Record<string, unknown> = {}) => {
    const rows: any[] = [];
    for (const part of chunks(ids)) {
      const a = await call(op, { ...extra, [key]: part, Limitation: { Count: Math.max(part.length, 1) } });
      rows.push(...(a?.[list] ?? []));
    }
    return rows;
  };
  // A PAYMENT TAKEN ON THE GUEST'S BILL is the account's, not the
  // reservation's: Mews returned the card charge a desk processed on the bill
  // (kkb5mzo3, Zedwell demo, 2026-11-03) for the guest's account and not for
  // the reservation, so the stay looked unpaid. The account's payments are
  // asked for too (a hundred accounts a call) and stand in when the
  // reservation has none of its own.
  const accountPayments = async () => {
    const rows: any[] = [];
    for (const part of chunks(accountIds, 100)) {
      const a = await call("payments/getAll", { AccountIds: part, Limitation: { Count: 1000 } });
      rows.push(...(a?.Payments ?? []));
    }
    return rows;
  };
  const [customers, rooms, payments, ofAccounts] = await Promise.all([
    accountIds.length ? all("customers/getAll", "CustomerIds", accountIds, "Customers", { Extent: { Customers: true } }) : [],
    roomIds.length ? all("resources/getAll", "ResourceIds", roomIds, "Resources") : [],
    reservationIds.length ? all("payments/getAll", "ReservationIds", reservationIds, "Payments") : [],
    accountIds.length ? accountPayments() : [],
  ]);
  const customer = new Map<string, any>(customers.map((c: any) => [c.Id, c]));
  const room = new Map<string, any>(rooms.map((r: any) => [r.Id, r]));
  const paid = new Map<string, any[]>();
  const seenPayment = new Set<string>();
  for (const p of payments) {
    if (!p?.ReservationId) continue;
    seenPayment.add(String(p.Id));
    paid.set(p.ReservationId, [...(paid.get(p.ReservationId) ?? []), p]);
  }
  // An account's payment without a reservation goes to that guest's stay
  // whose arrival is nearest the moment it was charged — one stay, never all.
  const unplaced = new Map<string, any[]>();
  const at = (v: unknown) => Date.parse(String(v || "")) || 0;
  for (const p of ofAccounts) {
    if (!p?.AccountId || seenPayment.has(String(p.Id))) continue;
    if (p.ReservationId) {
      if (reservationIds.includes(p.ReservationId)) paid.set(p.ReservationId, [...(paid.get(p.ReservationId) ?? []), p]);
      continue;
    }
    const when = at(p.ChargedUtc) || at(p.CreatedUtc);
    const stay = reservations.filter((r) => r.AccountId === p.AccountId)
      .sort((a, b) => Math.abs(at(a.ScheduledStartUtc) - when) - Math.abs(at(b.ScheduledStartUtc) - when))[0];
    if (stay) unplaced.set(stay.Id, [...(unplaced.get(stay.Id) ?? []), p]);
  }
  return reservations.map((r) => {
    const c = customer.get(r.AccountId);
    const name = c ? [c.FirstName, c.LastName].filter(Boolean).join(" ").trim() : "";
    const payment = _payment(paid.get(r.Id) ?? []) ?? _payment(unplaced.get(r.Id) ?? []);
    return {
      reservationId: String(r.Id),
      confirmationNumber: r.Number ? String(r.Number) : null,
      reservationStatus: r.State ? String(r.State) : null,
      arrivalDate: _day(r.ScheduledStartUtc),
      departureDate: _day(r.ScheduledEndUtc),
      customerId: c?.Id ? String(c.Id) : (r.AccountId ? String(r.AccountId) : null),
      accountId: r.AccountId ? String(r.AccountId) : null,
      guestName: name || null,
      guestEmail: c?.Email ? String(c.Email) : null,
      roomNumber: room.get(r.AssignedResourceId)?.Name ? String(room.get(r.AssignedResourceId).Name) : null,
      billId: payment?.billId ?? null,
      payment,
    };
  });
}

// --------------------------------------------------------------------------- //
// THE STAYS, KEPT. Mews matches a last name only exactly, and its name search
// sees only who is in the hotel now — the guest a refund is about has usually
// left. So the application keeps its own copy of the recent stays
// (`forge_mews_stays`): the window Mews allows, filled once and then kept
// fresh with what changed since (`syncStays`, from the cron tick), and a desk
// typing part of a name is answered from it at once (`suggestStays`).
// --------------------------------------------------------------------------- //

/** A sync stops asking Mews past this, and carries on next time. */
const SYNC_BUDGET_MS = 40_000;

let _staysEnsured: Promise<void> | null = null;
/** The kept stays and how far each connection's sync has got. The schema file
 *  declares both too, so the next push keeps them. */
export function ensureStays(): Promise<void> {
  if (!_staysEnsured) {
    _staysEnsured = (async () => {
      await db.execute(sql`
        CREATE TABLE IF NOT EXISTS forge_mews_stays (
          reservation_id text PRIMARY KEY,
          connection text NOT NULL,
          confirmation_number text,
          state text,
          arrival_date text,
          departure_date text,
          customer_id text,
          account_id text,
          guest_name text,
          guest_email text,
          room_number text,
          bill_id text,
          payment jsonb,
          updated_utc timestamp,
          synced_at timestamp NOT NULL DEFAULT now()
        )`);
      await db.execute(sql`
        CREATE TABLE IF NOT EXISTS forge_mews_sync (
          connection text PRIMARY KEY,
          synced_through timestamp,
          last_run_at timestamp,
          last_error text,
          stays integer NOT NULL DEFAULT 0,
          pending jsonb
        )`);
      await db.execute(sql`ALTER TABLE forge_mews_sync ADD COLUMN IF NOT EXISTS pending jsonb`);
    })().catch((err) => { _staysEnsured = null; throw err; });
  }
  return _staysEnsured;
}

/** Which connection a sync or a suggestion is about: a property's id, else the
 *  organisation's own. */
function _connectionOf(creds: MewsCredentials): string {
  return creds.property?.id ?? "organisation";
}

async function _keep(connection: string, stays: MewsStay[], updated: Map<string, string | null>): Promise<void> {
  for (const s of stays) {
    await db.execute(sql`
      INSERT INTO forge_mews_stays (reservation_id, connection, confirmation_number, state, arrival_date, departure_date,
        customer_id, account_id, guest_name, guest_email, room_number, bill_id, payment, updated_utc, synced_at)
      VALUES (${s.reservationId}, ${connection}, ${s.confirmationNumber}, ${s.reservationStatus}, ${s.arrivalDate},
        ${s.departureDate}, ${s.customerId}, ${s.accountId}, ${s.guestName}, ${s.guestEmail}, ${s.roomNumber},
        ${s.billId}, ${s.payment ? JSON.stringify(s.payment) : null}::jsonb, ${updated.get(s.reservationId) ?? null}, now())
      ON CONFLICT (reservation_id) DO UPDATE SET
        connection = EXCLUDED.connection, confirmation_number = EXCLUDED.confirmation_number,
        state = EXCLUDED.state, arrival_date = EXCLUDED.arrival_date, departure_date = EXCLUDED.departure_date,
        customer_id = EXCLUDED.customer_id, account_id = EXCLUDED.account_id, guest_name = EXCLUDED.guest_name,
        guest_email = EXCLUDED.guest_email, room_number = EXCLUDED.room_number, bill_id = EXCLUDED.bill_id,
        payment = EXCLUDED.payment, updated_utc = EXCLUDED.updated_utc, synced_at = now()`);
  }
}

export interface StaySync { connection: string; stays: number; complete: boolean; error: string | null }

/**
 * Keep the recent stays: the first time, every stay in the window Mews allows
 * (60 days back, 30 ahead); after that, the ones Mews changed since the last
 * sync finished. A sync that runs out of time keeps what it read and carries
 * on from the same point next time. `ref` names a property as
 * `credentialsFor` reads it; without one, the organisation's own connection.
 */
export async function syncStays(ref?: unknown, opts: { now?: Date; budgetMs?: number } = {}): Promise<StaySync> {
  await ensureStays();
  const creds = await credentialsFor(ref);
  const connection = _connectionOf(creds);
  const call = (op: string, body: Record<string, unknown>) => _call(creds, op, body);
  const now = opts.now ?? new Date();
  const deadline = Date.now() + (opts.budgetMs ?? SYNC_BUDGET_MS);
  const state = _rows(await db.execute(sql`
    SELECT synced_through, pending FROM forge_mews_sync WHERE connection = ${connection}`))[0];
  const windowStart = new Date(now.getTime() - STAY_WINDOW_DAYS.back * 864e5);
  // A PASS IS FINISHED WHERE IT STOPPED. A busy hotel has thousands of stays
  // in the window — the demo's had over 9,500 — and a pass that ran out of
  // time began again at page one, so it never finished.
  const pending = typeof state?.pending === "string" ? JSON.parse(state.pending) : state?.pending;
  let filter: Record<string, unknown>;
  let startedAt: string;
  let cursor: string | null = null;
  if (pending?.filter) {
    filter = pending.filter;
    startedAt = String(pending.startedAt);
    cursor = pending.cursor ?? null;
  } else {
    const since = state?.synced_through ? new Date(state.synced_through) : null;
    // Changed since the last finished pass, a few minutes back for clock
    // drift — or, the first time and after a long gap, the whole window.
    filter = since && since > windowStart
      ? { UpdatedUtc: { StartUtc: _iso(new Date(since.getTime() - 5 * 60_000)), EndUtc: _iso(now) } }
      : { CollidingUtc: { StartUtc: _iso(windowStart),
                          EndUtc: _iso(new Date(now.getTime() + STAY_WINDOW_DAYS.ahead * 864e5)) } };
    startedAt = _iso(now);
  }
  const remember = (next: Record<string, unknown> | null) => db.execute(sql`
    INSERT INTO forge_mews_sync (connection, pending, last_run_at) VALUES (${connection}, ${next ? JSON.stringify(next) : null}::jsonb, now())
    ON CONFLICT (connection) DO UPDATE SET pending = EXCLUDED.pending, last_run_at = now()`);
  let kept = 0;
  let complete = false;
  let error: string | null = null;
  try {
    for (;;) {
      const page: any = await call("reservations/getAll/2023-06-06",
        { ...filter, Limitation: { Count: 500, ...(cursor ? { Cursor: cursor } : {}) } });
      const reservations = (page?.Reservations ?? []) as any[];
      if (reservations.length) {
        const updated = new Map<string, string | null>(reservations.map((r) => [String(r.Id), r.UpdatedUtc ?? null]));
        const stays = await _enrich(call, reservations);
        await _keep(connection, stays, updated);
        kept += stays.length;
      }
      cursor = page?.Cursor && reservations.length ? String(page.Cursor) : null;
      if (!cursor) { complete = true; break; }
      await remember({ filter, cursor, startedAt });
      if (Date.now() > deadline) break;
    }
  } catch (err) {
    error = err instanceof MewsError ? err.message : String((err as Error)?.message || err);
  }
  // PAYING A BILL DOES NOT CHANGE THE BOOKING. A pass by what changed reads
  // bookings, so a card taken after the first pass never reached the kept
  // stays, and the Guest field bound Amelia Hart's stay without its £100
  // (kkb5mzo3, 2026-11-03). The payments changed in the same window name the
  // stays to read again.
  if (complete && filter.UpdatedUtc) {
    try {
      const changed: any = await call("payments/getAll", { UpdatedUtc: filter.UpdatedUtc, Limitation: { Count: 1000 } });
      const payments = (changed?.Payments ?? []) as any[];
      const ids = (pick: (p: any) => unknown) => [...new Set(payments.map(pick).filter(Boolean).map(String))];
      const asks: [string, string[]][] = [
        ["ReservationIds", ids((p) => p?.ReservationId)],
        ["AccountIds", ids((p) => (p?.ReservationId ? null : p?.AccountId))],
      ];
      const again = new Map<string, any>();
      for (const [key, all] of asks) {
        for (let i = 0; i < all.length; i += 100) {
          const page: any = await call("reservations/getAll/2023-06-06",
            { [key]: all.slice(i, i + 100), Limitation: { Count: 1000 } });
          for (const r of (page?.Reservations ?? []) as any[]) if (r?.Id) again.set(String(r.Id), r);
        }
      }
      if (again.size) {
        const reservations = [...again.values()];
        const updated = new Map<string, string | null>(reservations.map((r) => [String(r.Id), r.UpdatedUtc ?? null]));
        const stays = await _enrich(call, reservations);
        await _keep(connection, stays, updated);
        kept += stays.length;
      }
    } catch (err) {
      error = err instanceof MewsError ? err.message : String((err as Error)?.message || err);
    }
  }
  if (complete) await remember(null);
  await db.execute(sql`
    INSERT INTO forge_mews_sync (connection, synced_through, last_run_at, last_error, stays)
    VALUES (${connection}, ${complete ? startedAt : null}, now(), ${error}, ${kept})
    ON CONFLICT (connection) DO UPDATE SET
      synced_through = COALESCE(${complete ? startedAt : null}::timestamp, forge_mews_sync.synced_through),
      last_run_at = now(), last_error = EXCLUDED.last_error, stays = EXCLUDED.stays`);
  // Stays that left the window are not kept.
  await db.execute(sql`
    DELETE FROM forge_mews_stays WHERE connection = ${connection} AND departure_date < ${_day(_iso(windowStart))}`);
  return { connection, stays: kept, complete, error };
}

/** Every connection this application keeps stays for: each property set up,
 *  else the organisation's own. What the cron tick refreshes. */
export async function syncAllStays(opts: { now?: Date } = {}): Promise<StaySync[]> {
  if (!mewsOn() || !_organisation().clientToken) return [];
  await ensure();
  const props = _rows(await db.execute(sql`SELECT id FROM forge_mews_properties ORDER BY name`));
  const refs: (string | undefined)[] = props.length ? props.map((p) => String(p.id)) : [undefined];
  const out: StaySync[] = [];
  for (const ref of refs) {
    try {
      out.push(await syncStays(ref, opts));
    } catch (err) {
      out.push({ connection: ref ?? "organisation", stays: 0, complete: false,
                 error: err instanceof MewsError ? err.message : String((err as Error)?.message || err) });
    }
  }
  return out;
}

function _kept(r: any): MewsStay {
  const payment = typeof r.payment === "string" ? JSON.parse(r.payment) : (r.payment ?? null);
  return {
    reservationId: String(r.reservation_id), confirmationNumber: r.confirmation_number ?? null,
    reservationStatus: r.state ?? null, arrivalDate: r.arrival_date ?? null, departureDate: r.departure_date ?? null,
    customerId: r.customer_id ?? null, accountId: r.account_id ?? null, guestName: r.guest_name ?? null,
    guestEmail: r.guest_email ?? null, roomNumber: r.room_number ?? null, billId: r.bill_id ?? null, payment,
  };
}

/** Kept stays older than this are brought up to date before a suggestion. */
const STAYS_STALE_MS = 2 * 60_000;

/** One refresh per connection at a time: a desk typing fires several searches. */
const _syncing = new Map<string, Promise<unknown>>();
function _syncOnce(connection: string, run: () => Promise<unknown>): Promise<unknown> {
  let p = _syncing.get(connection);
  if (!p) {
    p = run().catch(() => null).finally(() => _syncing.delete(connection));
    _syncing.set(connection, p);
  }
  return p;
}

/** What a live name search found, for a few seconds: a desk types, Mews limits. */
const _inHouse = new Map<string, { at: number; stays: MewsStay[] }>();

/**
 * Stays to suggest while a desk types: part of a guest's name or email, the
 * start of a confirmation number, or a room — from the kept stays, newest
 * first. A name search of three letters or more that keeps few is also put to
 * Mews (`customers/search`), which finds who is in the hotel now even if the
 * last sync has not. The kept stays are refreshed first when they are stale.
 */
export async function suggestStays(term: unknown, ref?: unknown, limit = 8):
    Promise<{ stays: MewsStay[]; syncedAt: string | null; refreshed: boolean }> {
  const q = String(term ?? "").trim();
  await ensureStays();
  const creds = await credentialsFor(ref);
  const connection = _connectionOf(creds);
  let state = _rows(await db.execute(sql`
    SELECT synced_through, last_run_at FROM forge_mews_sync WHERE connection = ${connection}`))[0];
  let refreshed = false;
  // NOTHING KEPT YET: read the first pages now, so the first search answers.
  // After that the cron tick keeps them fresh, and a search never waits on it.
  const any = _rows(await db.execute(sql`
    SELECT 1 AS one FROM forge_mews_stays WHERE connection = ${connection} LIMIT 1`)).length > 0;
  const ranAgo = Date.now() - (state?.last_run_at ? new Date(state.last_run_at).getTime() : 0);
  if (!any && ranAgo > 60_000) {
    await _syncOnce(connection, () => syncStays(ref, { budgetMs: 15_000 }));
    refreshed = true;
  } else if (any && ranAgo > STAYS_STALE_MS) {
    // KEPT, BUT NOT LATELY: the cron tick is what keeps them fresh, and a test
    // deployment has none (Vercel runs scheduled jobs on production only) —
    // Criterion's ten new bookings never reached the Guest field (kkb5mzo3,
    // 2026-11-03). What changed since the last pass is a page or two.
    await _syncOnce(connection, () => syncStays(ref, { budgetMs: 5_000 }));
    refreshed = true;
  }
  if (refreshed) {
    state = _rows(await db.execute(sql`
      SELECT synced_through, last_run_at FROM forge_mews_sync WHERE connection = ${connection}`))[0];
  }
  if (!q) return { stays: [], syncedAt: state?.synced_through ? String(state.synced_through) : null, refreshed };
  const like = `%${q.replace(/[\\%_]/g, (c) => "\\" + c)}%`;
  const starts = `${q.replace(/[\\%_]/g, (c) => "\\" + c)}%`;
  const rows = _rows(await db.execute(sql`
    SELECT * FROM forge_mews_stays
    WHERE connection = ${connection}
      AND (guest_name ILIKE ${like} OR guest_email ILIKE ${like}
           OR confirmation_number ILIKE ${starts} OR lower(room_number) = lower(${q}))
    ORDER BY (guest_name ILIKE ${starts}) DESC, arrival_date DESC NULLS LAST
    LIMIT ${limit}`));
  const stays = rows.map(_kept);
  if (q.length >= 3 && stays.length < limit && /[a-z]/i.test(q)) {
    const key = `${connection}|${q.toLowerCase()}`;
    let live = _inHouse.get(key);
    if (!live || Date.now() - live.at > 30_000) {
      live = { at: Date.now(), stays: [] };
      try {
        const call = (op: string, body: Record<string, unknown>) => _call(creds, op, body);
        const found: any = await call("customers/search", { Name: q });
        const ids = [...new Set((found?.Customers ?? []).map((c: any) => c?.Customer?.Id).filter(Boolean))] as string[];
        if (ids.length) {
          const res: any = await call("reservations/getAll/2023-06-06", { AccountIds: ids.slice(0, 50), Limitation: { Count: limit } });
          live.stays = await _enrich(call, res?.Reservations ?? []);
        }
      } catch {
        // The kept stays still answer; a live search is a bonus, not a door.
      }
      _inHouse.set(key, live);
    }
    const seen = new Set(stays.map((s) => s.reservationId));
    for (const s of live.stays) if (!seen.has(s.reservationId) && stays.length < limit) stays.push(s);
  }
  return { stays, syncedAt: state?.synced_through ? String(state.synced_through) : null, refreshed };
}
