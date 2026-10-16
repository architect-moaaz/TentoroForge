// The app SDK (native) — what a screen reads, over HTTP, without React.
//
// The web's pages read through `@/sdk/server` in `load.ts`. A phone has no
// `load` and cannot import a server, so each of those reads is one POST to the
// app's own `/api/read/<op>` (the route says: each op IS one function of the
// server SDK, called as the signed-in person). The option and result types
// here are the server SDK's, field for field — `list("Order", { where, sort })`
// means the same on both — so the compiler checks a native screen's reads
// against the same schema the web's are checked against.
//
// Reads only. A change is a workflow (`useWorkflow`).
//
// PURE — no react-native import; only type imports of the generated modules.

import type { Client } from "./http";
import type { Entities, EntityName, NumericField } from "./schema";
import type { WidgetRef } from "./widgets";
import type { SessionUser } from "./signin";
import { humanError } from "./run";

export type { Entities, EntityName, NumericField };

/** Equality filters on an entity's own fields. */
export type Where<E extends EntityName> = Partial<{
  [K in keyof Entities[E]]: string | number | boolean;
}>;

type Scalar = string | number | boolean;

/** A foreign key's filter by the record it points at: `{ in: "Ingredient",
 *  where: { kind: "harmful" } }`. */
export type Related = { [T in EntityName]: { in: T; where: Where<T> } }[EntityName];

/** A count's filter: equality on the entity's own columns — or, on a foreign
 *  key, `Related`. Counts and totals only. */
export type CountWhere<E extends EntityName> = Partial<{
  [K in keyof Entities[E]]: Scalar | Related;
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

export interface SimilarOptions {
  /** A stored image's id (an `image` field's value, or what `uploadFile` returned). */
  image?: string;
  /** Words describing what to find. */
  text?: string;
  /** The embedding field to rank by; the entity's first when omitted. */
  field?: string;
  /** At most this many, closest first (default 12, at most 100). */
  limit?: number;
}

export interface Similar<T> {
  /** Closest first. `similarity` is 0-100 and only means something relative to
   *  the other rows. */
  rows: Array<T & { similarity: number }>;
  /** Why there are no rows when it is not "nothing is alike"; null otherwise. */
  error: string | null;
}

/** One row of a query: each dimension's value under its field name, each
 *  measure under its key, and — for a dimension that points at another
 *  record — its name under `<field>Label`. */
export type QueryRow = Record<string, string | number | boolean | null>;

export type Measure<E extends EntityName> =
  | { fn: "count" }
  | { fn: "count_distinct"; field: keyof Entities[E] & string }
  | { fn: "sum" | "avg"; field: NumericField<E> }
  | { fn: "min" | "max"; field: keyof Entities[E] & string };

export type Dimension<E extends EntityName> =
  | (keyof Entities[E] & string)
  | { field: keyof Entities[E] & string; bucket?: "day" | "week" | "month" | "quarter" | "year" }
  | { field: keyof Entities[E] & string; ranges: readonly { label?: string; from?: number; to?: number }[] };

/** A date window, half-open: `from` inclusive, `to` exclusive. ISO strings. */
export interface DateRange { from?: string; to?: string }

export interface SeriesOptions<E extends EntityName> {
  groupBy: keyof Entities[E] & string;
  /** Groups a date field by day, week or month. */
  bucket?: "day" | "week" | "month";
  /** Counts by default; `fn` + `field` aggregate a number. */
  fn?: "count" | "sum" | "avg" | "min" | "max";
  field?: NumericField<E>;
}

/** TypeScript's own `NoInfer` arrived in 5.4; Expo SDK 51 pins 5.3. The sort
 *  names a measure key, and must not narrow the keys `measures` declares. */
type NoInfer<T> = [T][T extends unknown ? 0 : never];

export interface QueryOptions<E extends EntityName, M extends string> {
  measures: Record<M, Measure<E>>;
  /** At most two: the axis, then the split. None for a single number. */
  dimensions?: Dimension<E>[];
  /** Equality filters; an array means "any of". */
  where?: Partial<{ [K in keyof Entities[E]]: string | number | boolean | (string | number)[] }>;
  range?: DateRange;
  timeField?: keyof Entities[E] & string;
  sort?: { by: NoInfer<M> | (keyof Entities[E] & string); order?: "asc" | "desc" };
  /** Top-N (at most 1000). */
  limit?: number;
}

/** What a widget's read returns: its rows, and — for a single number — that
 *  number; over a date range, the period before it and the change. */
export interface WidgetData {
  rows: QueryRow[];
  value: number | null;
  previous?: number | null;
  delta?: number | null;
}

export interface WidgetOptions {
  range?: DateRange;
  where?: Record<string, string | number | boolean | (string | number)[]>;
}

export interface NearOptions<E extends EntityName> {
  where?: Where<E>;
  radiusKm?: number;
  limit?: number;
  scan?: number;
}

export interface Me {
  user: SessionUser | null;
  /** The person's own record in the app's account entity; null when it has none. */
  account: Record<string, unknown> | null;
}

/** A read the app answered with an error. `status` 401 also signs the app out
 *  (the client says so); a screen shows `message`. */
export class ReadError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ReadError";
    this.status = status;
  }
}

/** POST /api/read/<op>; `GET` for `me`. Resolves the op's answer, rejects with a `ReadError`. */
export async function read<T>(client: Client, op: string, body?: unknown): Promise<T> {
  const res = op === "me"
    ? await client.json<T>("/api/read/me")
    : await client.json<T>(`/api/read/${encodeURIComponent(op)}`, { body: body ?? {} });
  if (res.networkError) throw new ReadError(res.networkError, 0);
  if (!res.ok || res.body === null) {
    const reply = res.body && typeof res.body === "object" ? (res.body as Record<string, unknown>) : {};
    throw new ReadError(humanError(reply, res.status), res.status);
  }
  return res.body;
}

/** The request body of each read, in one place — the hooks (data.ts) and any
 *  plain caller build it the same way. */
export const requests = {
  list: <E extends EntityName>(entity: E, o: ListOptions<E> = {}) => ({ entity, ...o }),
  record: <E extends EntityName>(entity: E, id: string) => ({ entity, id }),
  records: <E extends EntityName>(entity: E, ids: readonly string[]) => ({ entity, ids }),
  count: <E extends EntityName>(entity: E, where?: CountWhere<E>) => ({ entity, where }),
  total: <E extends EntityName>(entity: E, fn: "sum" | "avg" | "min" | "max", field: NumericField<E>, where?: CountWhere<E>) =>
    ({ entity, fn, field, where }),
  series: <E extends EntityName>(entity: E, o: SeriesOptions<E>) => ({ entity, ...o }),
  query: <E extends EntityName, M extends string>(entity: E, o: QueryOptions<E, M>) => ({ entity, ...o }),
  widget: (widget: WidgetRef, o: WidgetOptions = {}) => ({ id: widget.id, ...o }),
  similar: <E extends EntityName>(entity: E, o: SimilarOptions) => ({ entity, ...o }),
  near: <E extends EntityName>(entity: E, field: keyof Entities[E] & string, from: { lat: number; lng: number } | null, o: NearOptions<E> = {}) =>
    ({ entity, field, from, ...o }),
};
