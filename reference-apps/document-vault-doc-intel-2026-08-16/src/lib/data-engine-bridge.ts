// Data-engine bridge: adapts the generated app's data-engine.ts (functional
// CRUD API: query/create/update/remove/findById) to the DataEngine interface
// the @tentoroforge SchemaRenderer expects ({ run(source, ctx) → items[] }).
//
// The renderer passes a DataSource describing what to load; we translate it
// into the appropriate query call. Schema "id" lookups go through findById;
// list sources go through query() with optional search/filters.

import type { DataEngine } from "@tentoroforge/renderer";
import * as engine from "./data-engine";
import { resolveAggregate as _resolveAggregate, resolveSeries as _resolveSeries } from "./data-engine";
// SSR data path: the entity registry is otherwise only populated on the first API
// request, so server-side renders saw "Unknown entity". Initialise it here too.
import { ensureDataEngineInitialized } from "./data-init";

type Source = {
  type?: string;
  entity?: string;
  query?: Record<string, unknown>;
  id?: unknown;
};

/** Resolve an op:"aggregate" dataSource to a flat { metricKey: number } object. */
export async function resolveAggregate(source: unknown): Promise<Record<string, number>> {
  try {
    await ensureDataEngineInitialized();
    return await _resolveAggregate(source as any);
  } catch (err) {
    console.warn(`[data-engine-bridge] aggregate run failed:`, err);
    return {};
  }
}

/** Resolve an op:"series" dataSource to an array of { label, value } rows (a
 *  grouped aggregate for charts). Degrades to [] so a chart never blanks. */
export async function resolveSeries(source: unknown): Promise<Array<{ label: string; value: number }>> {
  try {
    await ensureDataEngineInitialized();
    return await _resolveSeries(source as any);
  } catch (err) {
    console.warn(`[data-engine-bridge] series run failed:`, err);
    return [];
  }
}

// Scalar aggregate ops that resolve to a single number via resolveAggregate.
// Written by the planner as `{op: "max", entity, field}` — the ergonomic
// shorthand — but resolveAggregate expects the richer
// `{op: "aggregate", metrics: {key: SimpleMetric}}` shape. We adapt on the
// way in so both shapes work.
const SCALAR_OPS = new Set(["max", "avg", "sum", "count", "min"]);

export const dataEngine: DataEngine = {
  async run(source: unknown, ctx?: { request?: Request; user?: { id?: string; role?: string; email?: string } }) {
    const src = (source ?? {}) as Source & { op?: string; field?: string; metrics?: Record<string, unknown> };
    const entity = src.entity;
    if (!entity) return [];

    const user = ctx?.user;
    const userCtx = user?.id ? { user: { id: String(user.id), role: user.role, email: user.email } } : undefined;

    try {
      await ensureDataEngineInitialized();

      // op:"series" — grouped aggregate → [{label, value}] for charts.
      if (src.op === "series") {
        return await resolveSeries(src);
      }

      // op:"aggregate" — passthrough (planner-authored richer shape).
      if (src.op === "aggregate") {
        return await resolveAggregate(src as unknown as Record<string, unknown>);
      }

      // Scalar aggregate shorthand — {op:"max", field:"mrr"} → wrap into a
      // single-metric aggregate and unwrap the scalar. Binds like
      // `{{KpiSummary_max_0}}` resolve to a number that MetricTile.value
      // can render directly (any other return shape shows as "0").
      if (src.op && SCALAR_OPS.has(src.op)) {
        const field = src.field;
        const wrapped = {
          entity,
          metrics: { value: { fn: src.op, field } as Record<string, unknown> },
        };
        const result = await resolveAggregate(wrapped as unknown as Record<string, unknown>);
        return result?.value ?? 0;
      }

      // Detail load — { type: "detail", entity, id } or { id } in query
      if (src.id !== undefined) {
        const item = await engine.findById(entity, String(src.id), userCtx);
        return item ? [item] : [];
      }
      const q = src.query || {};
      let id = (q as Record<string, unknown>).id;
      // Detail routes pass the row id via the request URL (internal:?id=…), not on
      // the source — read it here so `get`/detail dataSources resolve the single
      // record instead of silently falling through to a full list query.
      // Only fall back to the URL id for sources that expect a single record
      // (op:"get"/"detail"/undefined) — list sources with their own scoping
      // (where/orderBy/query.filters) must NOT be reinterpreted as findById.
      const op = (src as { op?: string }).op;
      const isListOp = op === "list" || (src as { where?: unknown }).where !== undefined || (q as { filters?: unknown }).filters !== undefined;
      if (id === undefined && ctx?.request && !isListOp) {
        try { id = new URL(ctx.request.url).searchParams.get("id") ?? undefined; } catch { /* non-URL request */ }
      }
      if (id !== undefined && typeof id !== "object" && id !== null && id !== "") {
        const item = await engine.findById(entity, String(id), userCtx);
        return item ? [item] : [];
      }
      // Equality filters — accept `filter` on the source itself (schema shape:
      // `{name, entity, op, filter: {status: 'pending'}}`) OR `filters` nested
      // under `query`. Both flow into QueryOptions.filters so Drizzle's `eq`
      // conditions apply on the SQL side. Without this the schema-page
      // renderer would silently drop the constraint, and any stateful page
      // that scopes "the current record" by status (scan flow, task flow,
      // approval flow) shows a stale row forever.
      const rawFilter = (src as { filter?: unknown }).filter ?? (q as { filters?: unknown }).filters;
      const filters: Record<string, string> = {};
      if (rawFilter && typeof rawFilter === "object" && !Array.isArray(rawFilter)) {
        for (const [k, v] of Object.entries(rawFilter as Record<string, unknown>)) {
          if (v !== undefined && v !== null) filters[k] = String(v);
        }
      }
      // Sort — accept either `sort: "field"` (asc default) or
      // `sort: {field, order}` on the source.
      const rawSort = (src as { sort?: unknown }).sort;
      let sort: string | undefined;
      let order: "asc" | "desc" | undefined;
      if (typeof rawSort === "string") sort = rawSort;
      else if (rawSort && typeof rawSort === "object" && !Array.isArray(rawSort)) {
        const s = rawSort as { field?: unknown; order?: unknown };
        if (typeof s.field === "string") sort = s.field;
        if (s.order === "asc" || s.order === "desc") order = s.order;
      }
      const opts: engine.QueryOptions = {
        search: typeof q.search === "string" ? q.search : undefined,
        page: typeof q.page === "number" ? q.page : 1,
        limit: typeof q.limit === "number" ? q.limit : 50,
        ...(Object.keys(filters).length ? { filters } : {}),
        ...(sort ? { sort, ...(order ? { order } : {}) } : {}),
      };
      const result = await engine.query(entity, opts, userCtx);
      return result.data;
    } catch (err) {
      console.warn(`[data-engine-bridge] ${entity} run failed:`, err);
      return [];
    }
  },
};
