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
  const sealed = token ? await encryptSensitive(token) : null;
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
      : sql`access_token_encrypted = ${await encryptSensitive(token)}, access_token_mask = ${mask(token, "last4")}`;
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

/** How far back and ahead a room's stays are looked for: Mews caps an interval. */
const ROOM_WINDOW_DAYS = { back: 60, ahead: 30 };

async function _call(creds: MewsCredentials, operation: string, body: Record<string, unknown>): Promise<any> {
  const res = await fetch(`${creds.host}/api/connector/v1/${operation}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(signedBody(body, creds)),
    signal: AbortSignal.timeout(20_000),
  });
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
    StartUtc: _iso(new Date(now - ROOM_WINDOW_DAYS.back * 864e5)),
    EndUtc: _iso(new Date(now + ROOM_WINDOW_DAYS.ahead * 864e5)),
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

  const accountIds = [...new Set(reservations.map((r) => r.AccountId).filter(Boolean))];
  const roomIds = [...new Set(reservations.map((r) => r.AssignedResourceId).filter(Boolean))];
  const [customers, rooms, payments] = await Promise.all([
    accountIds.length ? call("customers/getAll", { CustomerIds: accountIds, Extent: { Customers: true },
                                                   Limitation: { Count: accountIds.length } }) : {},
    roomIds.length ? call("resources/getAll", { ResourceIds: roomIds, Limitation: { Count: roomIds.length } }) : {},
    call("payments/getAll", { ReservationIds: reservations.map((r) => r.Id), Limitation: { Count: 100 } }),
  ]);
  const customer = new Map<string, any>((customers?.Customers ?? []).map((c: any) => [c.Id, c]));
  const room = new Map<string, any>((rooms?.Resources ?? []).map((r: any) => [r.Id, r]));
  const paid = new Map<string, any[]>();
  for (const p of payments?.Payments ?? []) {
    if (!p?.ReservationId) continue;
    paid.set(p.ReservationId, [...(paid.get(p.ReservationId) ?? []), p]);
  }
  return reservations.map((r) => {
    const c = customer.get(r.AccountId);
    const name = c ? [c.FirstName, c.LastName].filter(Boolean).join(" ").trim() : "";
    const payment = _payment(paid.get(r.Id) ?? []);
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
