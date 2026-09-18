// The app SDK — server half. What a page's `load.ts` may read, typed from the
// Living Blueprint (`./schema`, projected). Every read runs as the signed-in
// user, so the ownership rules the Blueprint declares scope it: a list is the
// rows this person may see, a count is their count.
//
// Server-only: imports the database. A `view.tsx` never imports this module;
// it receives what `load` returned as props.

import { auth } from "@/auth";
import * as engine from "@/lib/data-engine";
import { actorCtx, resolveAggregate, resolveSeries } from "@/lib/data-engine-bridge";
import { ensureDataEngineInitialized } from "@/lib/data-init";
import { NUMERIC_FIELDS, READABLE_FIELDS } from "./schema";
import type { Entities, EntityName, NumericField } from "./schema";

export type { Entities, EntityName } from "./schema";

/** The person the page is rendered for. */
export interface SessionUser {
  id: string;
  name: string | null;
  email: string | null;
  role: string | null;
}

/** What a page's `load` is handed: the route's params (`id` on a `[id]`
 *  route), the query string, and the signed-in user. */
export interface PageContext {
  params: Record<string, string>;
  searchParams: Record<string, string | undefined>;
  user: SessionUser | null;
}

/** Equality filters on an entity's own fields. */
export type Where<E extends EntityName> = Partial<{
  [K in keyof Entities[E]]: string | number | boolean;
}>;

export interface ListOptions<E extends EntityName> {
  where?: Where<E>;
  /** Free-text search over the entity's searchable columns. */
  search?: string;
  sort?: keyof Entities[E] & string;
  order?: "asc" | "desc";
  /** Rows per page (default 50, at most 200). */
  limit?: number;
  page?: number;
}

export interface Page<T> {
  rows: T[];
  total: number;
  page: number;
  limit: number;
}

export interface SeriesPoint {
  label: string;
  value: number;
}

async function actor() {
  try {
    const session = await auth();
    return actorCtx(session?.user as Record<string, unknown> | undefined) ?? {};
  } catch {
    return {};
  }
}

/** A row as its type says: only the typed columns (a credential never
 *  leaves the server, however a view passes rows around), dates as ISO
 *  strings, numeric columns as numbers (the driver returns `numeric` as text). */
function plain<E extends EntityName>(entity: E, row: Record<string, unknown>): Entities[E] {
  const numeric = new Set(NUMERIC_FIELDS[entity] ?? []);
  const out: Record<string, unknown> = {};
  for (const k of READABLE_FIELDS[entity] ?? Object.keys(row)) {
    const v = row[k];
    if (v === undefined) out[k] = null;
    else if (v instanceof Date) out[k] = v.toISOString();
    else if (numeric.has(k) && typeof v === "string" && v !== "" && !Number.isNaN(Number(v))) out[k] = Number(v);
    else out[k] = v;
  }
  return out as Entities[E];
}

function filters(where?: Record<string, unknown>): Record<string, string> | undefined {
  if (!where) return undefined;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(where)) if (v !== undefined && v !== null) out[k] = String(v);
  return Object.keys(out).length ? out : undefined;
}

/** The signed-in user, or null. */
export async function currentUser(): Promise<SessionUser | null> {
  try {
    const u = (await auth())?.user as Record<string, unknown> | undefined;
    if (!u?.id) return null;
    const s = (v: unknown) => (v === undefined || v === null ? null : String(v));
    return { id: String(u.id), name: s(u.name), email: s(u.email), role: s(u.role) };
  } catch {
    return null;
  }
}

/** One page of rows and the total that matches. */
export async function listPage<E extends EntityName>(
  entity: E, opts: ListOptions<E> = {},
): Promise<Page<Entities[E]>> {
  await ensureDataEngineInitialized();
  const limit = Math.min(Math.max(opts.limit ?? 50, 1), 200);
  const page = Math.max(opts.page ?? 1, 1);
  try {
    const res = await engine.query(entity, {
      search: opts.search || undefined,
      filters: filters(opts.where as Record<string, unknown>),
      sort: opts.sort,
      order: opts.order,
      page, limit,
    }, await actor());
    return { rows: res.data.map((r) => plain(entity, r)), total: res.total, page, limit };
  } catch (err) {
    console.warn(`[sdk] list ${entity} failed:`, err);
    return { rows: [], total: 0, page, limit };
  }
}

/** The rows, without the paging envelope. */
export async function list<E extends EntityName>(
  entity: E, opts: ListOptions<E> = {},
): Promise<Entities[E][]> {
  return (await listPage(entity, opts)).rows;
}

/** One record by id, or null when it does not exist or is not this user's to see. */
export async function record<E extends EntityName>(
  entity: E, id: string | undefined,
): Promise<Entities[E] | null> {
  if (!id || /[[\]]/.test(id)) return null;
  await ensureDataEngineInitialized();
  try {
    return plain(entity, await engine.findById(entity, id, await actor()));
  } catch {
    return null;
  }
}

/** How many rows match. */
export async function count<E extends EntityName>(entity: E, where?: Where<E>): Promise<number> {
  const out = await resolveAggregate({
    name: "count", entity, op: "aggregate",
    metrics: { value: { fn: "count", filter: where ?? undefined } },
  }, await actor());
  return Number(out.value ?? 0);
}

/** A sum, average, minimum or maximum of a numeric field. */
export async function total<E extends EntityName>(
  entity: E, fn: "sum" | "avg" | "min" | "max", field: NumericField<E>, where?: Where<E>,
): Promise<number> {
  const out = await resolveAggregate({
    name: "total", entity, op: "aggregate",
    metrics: { value: { fn, field, filter: where ?? undefined } },
  }, await actor());
  return Number(out.value ?? 0);
}

/** Rows grouped by a field — a chart's data. `bucket` groups a date field by
 *  day, week or month. Counts by default; `fn` + `field` aggregate a number. */
export async function series<E extends EntityName>(
  entity: E,
  opts: {
    groupBy: keyof Entities[E] & string;
    bucket?: "day" | "week" | "month";
    fn?: "count" | "sum" | "avg" | "min" | "max";
    field?: NumericField<E>;
  },
): Promise<SeriesPoint[]> {
  return resolveSeries({
    name: "series", entity, op: "series",
    groupBy: opts.groupBy, bucket: opts.bucket,
    agg: { fn: opts.fn ?? "count", field: opts.field },
  }, await actor());
}
