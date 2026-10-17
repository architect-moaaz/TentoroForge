// The app SDK (native) — reading data. One hook per read of the web SDK's
// server half (`list`, `record`, `recordsById`, `count`, `total`, `series`,
// `query`, `runWidget`, `similar`, `near`, `myAccount`), same options, same
// row types — answered by the app's own `/api/read/<op>` as the signed-in person,
// so ownership and tenancy scope a native read exactly as they scope the web's.
//
//   const { data, loading, error, refetch } = useList("Order", { where: { status: "open" }, sort: "placedAt", order: "desc" });
//
// EVERY HOOK RETURNS `{ data, loading, refreshing, error, notFound, refetch }`:
//   data        null until the first answer; then the answer, kept while a newer
//               one loads (a list does not blink to a spinner when it refreshes);
//   loading     true only before the FIRST answer — show <Loading />;
//   refreshing  true while a later read is in flight — a pull-to-refresh spinner;
//   error       a sentence, or null. A failed refresh keeps `data` and sets it;
//   notFound    the app answered 404 (a record that is gone, or not yours).
//
// THEY LOOK AGAIN BY THEMSELVES when a workflow finishes (`useWorkflow`
// signals it, the way the web SDK dispatches `forge:workflow-done`) and on each
// tick of `useLive`. They do not loop: an options object written inline is a new
// object on every render, so the hooks key on its CONTENT (`stableKey`).
//
// Pass `null`/`undefined` for an input that is not known yet (`useRecord("Order",
// params.id)` before the route has it) and nothing is read.

import * as React from "react";
import { AppState } from "react-native";
import { useFocusEffect } from "expo-router";
import { client } from "./api";
import { refreshReads } from "./events";
import { stableKey } from "./keys";
import {
  read, requests, ReadError,
  type CountWhere, type Entities, type EntityName, type ListOptions, type Me, type NearOptions, type NumericField,
  type QueryOptions, type QueryRow, type SeriesOptions, type SeriesPoint, type Similar, type SimilarOptions, type WidgetData, type WidgetOptions,
} from "./reads";
import type { WidgetRef } from "./widgets";
import type { GeoPoint } from "./geo";

export interface ReadState<T> {
  data: T | null;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  notFound: boolean;
  refetch: () => Promise<void>;
}

function messageOf(err: unknown): { message: string; status: number } {
  if (err instanceof ReadError) return { message: err.message, status: err.status };
  return { message: err instanceof Error ? err.message : String(err), status: 0 };
}

interface Cell<T> { data: T | null; loading: boolean; refreshing: boolean; error: string | null; notFound: boolean }

/** The one read. `body === null` reads nothing. `keepPrevious` keeps the last
 *  answer on screen while a CHANGED request loads (a search box) instead of
 *  going back to "loading". */
function useRead<R, T>(op: string, body: unknown | null, pick: (r: R) => T, keepPrevious = false): ReadState<T> {
  const key = body === null ? null : `${op}:${stableKey(body)}`;
  const bodyRef = React.useRef(body);
  bodyRef.current = body;
  const pickRef = React.useRef(pick);
  pickRef.current = pick;
  const [cell, setCell] = React.useState<Cell<T>>({ data: null, loading: key !== null, refreshing: false, error: null, notFound: false });
  const seq = React.useRef(0);

  const load = React.useCallback(async (again: boolean) => {
    if (key === null) return;
    const mine = ++seq.current;
    setCell((c) => ({ ...c, loading: c.data === null, refreshing: again && c.data !== null }));
    try {
      const data = pickRef.current(await read<R>(client, op, bodyRef.current));
      if (mine === seq.current) setCell({ data, loading: false, refreshing: false, error: null, notFound: false });
    } catch (err) {
      const { message, status } = messageOf(err);
      if (mine === seq.current) setCell((c) => ({ ...c, loading: false, refreshing: false, error: message, notFound: status === 404 }));
    }
  }, [key, op]);

  // A new request: a new answer. (An older one still in flight is dropped by `seq`.)
  React.useEffect(() => {
    if (key === null) { seq.current++; setCell({ data: null, loading: false, refreshing: false, error: null, notFound: false }); return; }
    setCell((c) => ({ data: keepPrevious ? c.data : null, loading: true, refreshing: false, error: null, notFound: false }));
    void load(false);
    return () => { seq.current++; };
  }, [key, load, keepPrevious]);

  React.useEffect(() => refreshReads.subscribe(() => { void load(true); }), [load]);

  const refetch = React.useCallback(() => load(true), [load]);
  return { ...cell, refetch };
}

// ---------------------------------------------------------------------------
// Lists — paged
// ---------------------------------------------------------------------------

export interface ListState<T> extends ReadState<T[]> {
  /** Rows that match, over every page. */
  total: number;
  hasMore: boolean;
  /** The next page, appended. Pass to `ListView`'s `onEndReached`. */
  loadMore: () => Promise<void>;
  loadingMore: boolean;
}

/** `list` — rows of an entity, a page at a time. `data` is every row loaded so
 *  far; `loadMore()` appends the next page. Options are the web's `ListOptions`
 *  (`where`, `search`, `sort`, `order`, `limit` = page size, default 50). */
export function useList<E extends EntityName>(entity: E, options: Omit<ListOptions<E>, "page"> = {}): ListState<Entities[E]> {
  type Row = Entities[E];
  const key = stableKey({ entity, options });
  const optionsRef = React.useRef(options);
  optionsRef.current = options;
  const [cell, setCell] = React.useState<Cell<Row[]> & { total: number; page: number; limit: number; loadingMore: boolean }>(
    { data: null, loading: true, refreshing: false, error: null, notFound: false, total: 0, page: 0, limit: 50, loadingMore: false });
  const seq = React.useRef(0);

  /** Page 1 replaces what is shown; a later page appends (a row seen twice is kept once). */
  const fetchPage = React.useCallback(async (page: number, again: boolean) => {
    const mine = ++seq.current;
    setCell((c) => page === 1
      ? { ...c, loading: c.data === null, refreshing: again && c.data !== null }
      : { ...c, loadingMore: true });
    try {
      const res = await read<{ rows: Row[]; total: number; page: number; limit: number }>(
        client, "list", requests.list(entity, { ...optionsRef.current, page }));
      if (mine !== seq.current) return;
      setCell((c) => {
        let rows = res.rows;
        if (page > 1 && c.data) {
          const seen = new Set(c.data.map((r) => (r as { id?: unknown }).id));
          rows = [...c.data, ...res.rows.filter((r) => !seen.has((r as { id?: unknown }).id))];
        }
        return { data: rows, loading: false, refreshing: false, error: null, notFound: false,
                 total: res.total, page: res.page, limit: res.limit, loadingMore: false };
      });
    } catch (err) {
      if (mine !== seq.current) return;
      const { message, status } = messageOf(err);
      setCell((c) => ({ ...c, loading: false, refreshing: false, loadingMore: false, error: message, notFound: status === 404 }));
    }
  }, [entity]);

  // A new request (another search, another filter) starts from page 1; the rows
  // on screen stay until the first page of the new one arrives.
  React.useEffect(() => {
    void fetchPage(1, false);
    return () => { seq.current++; };
  }, [key, fetchPage]);

  React.useEffect(() => refreshReads.subscribe(() => { void fetchPage(1, true); }), [fetchPage]);

  const hasMore = cell.data !== null && cell.data.length < cell.total && cell.page > 0;
  const stateRef = React.useRef({ hasMore, page: cell.page, busy: cell.loadingMore || cell.loading });
  stateRef.current = { hasMore, page: cell.page, busy: cell.loadingMore || cell.loading };
  const loadMore = React.useCallback(async () => {
    const s = stateRef.current;
    if (!s.hasMore || s.busy) return;
    await fetchPage(s.page + 1, false);
  }, [fetchPage]);
  const refetch = React.useCallback(() => fetchPage(1, true), [fetchPage]);

  return { data: cell.data, loading: cell.loading, refreshing: cell.refreshing, error: cell.error, notFound: cell.notFound,
           refetch, total: cell.total, hasMore, loadMore, loadingMore: cell.loadingMore };
}

// ---------------------------------------------------------------------------
// The rest of the reads
// ---------------------------------------------------------------------------

/** `record` — one row by id; `data` stays null and `notFound` is true when it
 *  does not exist or is not this person's to see. */
export function useRecord<E extends EntityName>(entity: E, id: string | null | undefined): ReadState<Entities[E]> {
  return useRead<{ record: Entities[E] }, Entities[E]>("record", id ? requests.record(entity, id) : null, (r) => r.record);
}

/** `recordsById` — the rows a set of foreign keys point at, keyed by id: show a
 *  row's related record by name, never by id. */
export function useRecords<E extends EntityName>(entity: E, ids: ReadonlyArray<string | null | undefined>): ReadState<Record<string, Entities[E]>> {
  const unique = [...new Set(ids.filter((i): i is string => typeof i === "string" && i.length > 0))];
  return useRead<{ records: Record<string, Entities[E]> }, Record<string, Entities[E]>>(
    "records", unique.length ? requests.records(entity, unique) : null, (r) => r.records);
}

/** `count` — how many rows match. */
export function useCount<E extends EntityName>(entity: E, where?: CountWhere<E>): ReadState<number> {
  return useRead<{ value: number }, number>("count", requests.count(entity, where), (r) => Number(r.value ?? 0));
}

/** `total` — a sum, average, minimum or maximum of a numeric field. */
export function useTotal<E extends EntityName>(
  entity: E, fn: "sum" | "avg" | "min" | "max", field: NumericField<E>, where?: CountWhere<E>,
): ReadState<number> {
  return useRead<{ value: number }, number>("total", requests.total(entity, fn, field, where), (r) => Number(r.value ?? 0));
}

/** `series` — rows grouped by a field: a chart's data (`{ label, value }[]`). */
export function useSeries<E extends EntityName>(entity: E, options: SeriesOptions<E>): ReadState<SeriesPoint[]> {
  return useRead<{ points: SeriesPoint[] }, SeriesPoint[]>("series", requests.series(entity, options), (r) => r.points);
}

/** `query` — measures by dimensions: the query behind every chart and KPI. */
export function useQuery<E extends EntityName, M extends string>(entity: E, options: QueryOptions<E, M>): ReadState<QueryRow[]> {
  return useRead<{ rows: QueryRow[] }, QueryRow[]>("query", requests.query(entity, options), (r) => r.rows, true);
}

/** `runWidget` — one of the page's widgets (`widgets.x` from "@/sdk"), as the
 *  Blueprint declares it. `range` narrows it to a date window; `where` adds filters. */
export function useWidget(widget: WidgetRef, options: WidgetOptions = {}): ReadState<WidgetData> {
  return useRead<WidgetData, WidgetData>("widget", requests.widget(widget, options), (r) => r, true);
}

/** `similar` — records ranked by how alike they are to an image or a
 *  description. Nothing to compare (no image, no text) reads nothing. */
export function useSimilar<E extends EntityName>(entity: E, options: SimilarOptions): ReadState<Similar<Entities[E]>> {
  const asked = Boolean(options.image) || Boolean(options.text?.trim());
  return useRead<Similar<Entities[E]>, Similar<Entities[E]>>("similar", asked ? requests.similar(entity, options) : null, (r) => r, true);
}

/** `near` — rows of `entity` nearest to `from`, closest first, each with its `distanceKm`. */
export function useNear<E extends EntityName>(
  entity: E, field: keyof Entities[E] & string, from: GeoPoint | null, options: NearOptions<E> = {},
): ReadState<(Entities[E] & { distanceKm: number | null })[]> {
  return useRead<{ rows: (Entities[E] & { distanceKm: number | null })[] }, (Entities[E] & { distanceKm: number | null })[]>(
    "near", requests.near(entity, field, from, options), (r) => r.rows, true);
}

/** `currentUser` + `myAccount` — the signed-in person and their own account record. */
export function useMe(): ReadState<Me> {
  return useRead<Me, Me>("me", {}, (r) => r);
}

/** A SCREEN THAT CHANGES WHILE SOMEONE WATCHES — an orders board, a rider's
 *  live trip: every read on screen looks again each `seconds` while this screen
 *  is the one in front and the app is in the foreground, and at once when the
 *  person comes back to it. The web's `useLive`. */
export function useLive(seconds = 10): void {
  useFocusEffect(React.useCallback(() => {
    const every = Math.max(3, seconds) * 1000;
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => { if (!timer) timer = setInterval(() => refreshReads.emit({}), every); };
    const stop = () => { if (timer) { clearInterval(timer); timer = null; } };
    start();
    const sub = AppState.addEventListener("change", (s) => {
      if (s === "active") { refreshReads.emit({}); start(); } else stop();
    });
    return () => { stop(); sub.remove(); };
  }, [seconds]));
}
