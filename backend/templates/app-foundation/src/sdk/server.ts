// The app SDK — server half. What a page's `load.ts` may read, typed from the
// Living Blueprint (`./schema`, projected). Every read runs as the signed-in
// user, so the ownership rules the Blueprint declares scope it: a list is the
// rows this person may see, a count is their count.
//
// Server-only: imports the database. A `view.tsx` never imports this module;
// it receives what `load` returned as props.

import { auth } from "@/auth";
import * as engine from "@/lib/data-engine";
import { actorCtx, resolveAggregate, resolveQuery, resolveSeries } from "@/lib/data-engine-bridge";
import { ensureDataEngineInitialized } from "@/lib/data-init";
import { NUMERIC_FIELDS, READABLE_FIELDS } from "./schema";
import type { Entities, EntityName, NumericField } from "./schema";
import type { WidgetRef } from "./widgets";

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

/** The page reviewer's empty state: on the reviewer's own server — the one
 *  that builds into `.next-review`, which nothing else does — a request
 *  carrying the `forge-review-empty` cookie reads an application with no rows,
 *  so the reviewer can see every page's empty state without a second database. */
async function reviewingEmpty(): Promise<boolean> {
  if (process.env.NEXT_DIST_DIR !== ".next-review") return false;
  try {
    const { cookies } = await import("next/headers");
    return (await cookies()).get("forge-review-empty")?.value === "1";
  } catch {
    return false;
  }
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
  const limit = Math.min(Math.max(opts.limit ?? 50, 1), 200);
  const page = Math.max(opts.page ?? 1, 1);
  if (await reviewingEmpty()) return { rows: [], total: 0, page, limit };
  await ensureDataEngineInitialized();
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
  if (!id || /[[\]]/.test(id) || (await reviewingEmpty())) return null;
  await ensureDataEngineInitialized();
  try {
    return plain(entity, await engine.findById(entity, id, await actor()));
  } catch {
    return null;
  }
}

/** How many rows match. */
export async function count<E extends EntityName>(entity: E, where?: Where<E>): Promise<number> {
  if (await reviewingEmpty()) return 0;
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
  if (await reviewingEmpty()) return 0;
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
  if (await reviewingEmpty()) return [];
  return resolveSeries({
    name: "series", entity, op: "series",
    groupBy: opts.groupBy, bucket: opts.bucket,
    agg: { fn: opts.fn ?? "count", field: opts.field },
  }, await actor());
}

/** One row of a query: each dimension's value under its field name (a date
 *  bucket as "2026-03", "2026-Q1"…), each measure under its key, and — for a
 *  dimension that points at another record — its name under `<field>Label`. */
export type QueryRow = Record<string, string | number | null>;

export type Measure<E extends EntityName> =
  | { fn: "count" }
  | { fn: "count_distinct"; field: keyof Entities[E] & string }
  | { fn: "sum" | "avg"; field: NumericField<E> }
  | { fn: "min" | "max"; field: keyof Entities[E] & string };

export type Dimension<E extends EntityName> =
  | (keyof Entities[E] & string)
  | { field: keyof Entities[E] & string; bucket?: "day" | "week" | "month" | "quarter" | "year" };

/** A date window, half-open: `from` inclusive, `to` exclusive. ISO strings. */
export interface DateRange { from?: string; to?: string }

export interface QueryOptions<E extends EntityName, M extends string> {
  measures: Record<M, Measure<E>>;
  /** At most two: the axis, then the split. None for a single number. */
  dimensions?: Dimension<E>[];
  /** Equality filters; an array means "any of". */
  where?: Partial<{ [K in keyof Entities[E]]: string | number | boolean | (string | number)[] }>;
  /** Narrows `timeField` (default: the bucketed dimension) to a date window. */
  range?: DateRange;
  timeField?: keyof Entities[E] & string;
  // NoInfer: the measure keys are what `measures` declares; a sort naming
  // one must not narrow them to itself.
  sort?: { by: NoInfer<M> | (keyof Entities[E] & string); order?: "asc" | "desc" };
  /** Top-N (at most 1000). */
  limit?: number;
}

/** Measures by dimensions — the query behind every chart and KPI, run by the
 *  Data Engine as one GROUP BY over the rows this user may read.
 *
 *    query("Order", { measures: { revenue: { fn: "sum", field: "total" } },
 *                     dimensions: [{ field: "placedAt", bucket: "month" }, "region"] })
 *    → [{ placedAt: "2026-01", region: "EU", revenue: 1840 }, …]
 */
export async function query<E extends EntityName, M extends string>(
  entity: E, opts: QueryOptions<E, M>,
): Promise<QueryRow[]> {
  if (await reviewingEmpty()) return [];
  const measures = Object.entries(opts.measures).map(([key, m]) => {
    const spec = m as { fn: string; field?: string };
    return { key, aggregation: spec.fn, field: spec.field };
  });
  const dimensions = (opts.dimensions ?? []).map((d) => (typeof d === "string" ? { field: d } : d));
  return resolveQuery({
    name: "query", entity, op: "query", measures, dimensions,
    filter: opts.where ?? {}, range: opts.range, timeField: opts.timeField,
    sort: opts.sort, limit: opts.limit,
  }, await actor());
}

/** What a widget's read returns: its rows, and — for a single number (a
 *  metric or gauge, a query with no dimension) — that number. */
export interface WidgetData {
  rows: QueryRow[];
  value: number | null;
}

/** Read one of the page's widgets (`widgets` from "@/sdk"), exactly as the
 *  Blueprint declares it. `range` narrows it to a date window (the page's
 *  date filter); `where` adds equality filters (a record page's own id). */
export async function runWidget(
  widget: WidgetRef,
  opts: { range?: DateRange; where?: Record<string, string | number | boolean | (string | number)[]> } = {},
): Promise<WidgetData> {
  const src = widget.source;
  if (await reviewingEmpty()) return { rows: [], value: src.op === "query" && !src.dimensions.length ? 0 : null };
  if (src.op === "list") {
    const rows = await list(src.entity, {
      where: { ...src.filter, ...opts.where } as Where<typeof src.entity>,
      sort: src.sort as never, order: "desc", limit: src.limit,
    });
    return { rows: rows as unknown as QueryRow[], value: null };
  }
  const rows = await resolveQuery({
    name: widget.id, entity: src.entity, op: "query",
    measures: src.measures, dimensions: src.dimensions,
    filter: { ...src.filter, ...opts.where }, timeField: src.timeField,
    range: opts.range, sort: src.sort, limit: src.limit,
  }, await actor());
  const single = src.dimensions.length === 0;
  const first = src.measures[0]?.key;
  const v = single && first ? rows[0]?.[first] : null;
  return { rows, value: single ? Number(v ?? 0) : null };
}
