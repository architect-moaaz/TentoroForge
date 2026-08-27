/**
 * Editor-preview data resolver.
 *
 * The editor canvas Engine renders binding expressions against `previewData`, but
 * it can't hit the DB. The /api/_debug/preview-data endpoint hands us fixture ROWS
 * keyed by ENTITY name (Vehicle | vehicles | Dispatch | …), while page bindings
 * reference DATA SOURCE names — {{dashboardStats.activeDispatches}} (aggregate),
 * {{dispatchByWeek}} (series), {{dispatches}} (list). Without a bridge, aggregate
 * and series sources never resolve, so KPI tiles show raw {{…}} and charts render
 * empty in the editor.
 *
 * This resolves each page dataSource over the entity fixtures into a value keyed by
 * the SOURCE name, mirroring the generated app's server-side resolvers
 * (resolveAggregate / resolveSeries / list) closely enough for a live preview.
 *
 * Pure + defensive: unknown ops pass through as lists, missing entities → [] / {},
 * per-source try/catch so one bad source never blanks the canvas. Never throws.
 */

export type PreviewData = Record<string, unknown>;

interface Metric {
  fn: string;
  field?: string;
  entity?: string;
  filter?: Record<string, unknown>;
}

export interface PreviewDataSource {
  name: string;
  entity?: string;
  op?: string;
  metrics?: Record<string, Metric>;
  groupBy?: string;
  bucket?: "day" | "week" | "month";
  agg?: { fn: string; field?: string };
  sort?: "label" | "value";
  filter?: Record<string, unknown>;
  limit?: number;
}

const norm = (s: string) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");

/** Find an entity's fixture rows in previewData across the many key aliases the
 *  fixture endpoint emits (Vehicle | vehicle | vehicles | …). */
function rowsFor(entity: string | undefined, pd: PreviewData): any[] {
  if (!entity) return [];
  if (Array.isArray(pd[entity])) return pd[entity] as any[];
  const want = norm(entity);
  for (const [k, v] of Object.entries(pd)) {
    if (!Array.isArray(v)) continue;
    const nk = norm(k);
    if (nk === want || nk === want + "s" || nk + "s" === want) return v as any[];
  }
  return [];
}

function matchesFilter(row: any, filter?: Record<string, unknown>): boolean {
  if (!filter) return true;
  return Object.entries(filter).every(([k, v]) => row?.[k] === v);
}

const toNum = (v: unknown): number => {
  const n = Number(v);
  return isNaN(n) ? 0 : n;
};

function aggValue(rows: any[], fn: string, field?: string): number {
  if (fn === "count" || !field) return rows.length;
  const nums = rows.map((r) => toNum(r?.[field]));
  if (!nums.length) return 0;
  switch (fn) {
    case "sum": return nums.reduce((a, b) => a + b, 0);
    case "avg": return Math.round((nums.reduce((a, b) => a + b, 0) / nums.length) * 100) / 100;
    case "min": return Math.min(...nums);
    case "max": return Math.max(...nums);
    default: return rows.length;
  }
}

function resolveAggregate(s: PreviewDataSource, pd: PreviewData): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [key, m] of Object.entries(s.metrics || {})) {
    const rows = rowsFor(m.entity || s.entity, pd).filter((r) => matchesFilter(r, m.filter));
    out[key] = aggValue(rows, m.fn, m.field);
  }
  return out;
}

/** Truncate a date to a bucket start; returns the display label + a numeric sort key. */
function bucketLabel(raw: unknown, bucket: string): { label: string; key: number } {
  const d = new Date(raw as any);
  if (isNaN(d.getTime())) return { label: String(raw ?? "—"), key: 0 };
  const dd = new Date(d);
  dd.setHours(0, 0, 0, 0);
  if (bucket === "month") {
    dd.setDate(1);
    return { label: dd.toLocaleDateString("en-US", { month: "short", year: "numeric" }), key: dd.getTime() };
  }
  if (bucket === "week") {
    dd.setDate(dd.getDate() - dd.getDay()); // back to Sunday
  }
  return { label: dd.toLocaleDateString("en-US", { month: "short", day: "numeric" }), key: dd.getTime() };
}

function resolveSeries(s: PreviewDataSource, pd: PreviewData): Array<{ label: string; value: number }> {
  if (!s.groupBy) return [];
  const rows = rowsFor(s.entity, pd).filter((r) => matchesFilter(r, s.filter));
  const fn = s.agg?.fn || "count";
  const field = s.agg?.field;
  const groups = new Map<string, { key: number; rows: any[] }>();
  for (const r of rows) {
    const raw = r?.[s.groupBy];
    const { label, key } = s.bucket ? bucketLabel(raw, s.bucket) : { label: String(raw ?? "—"), key: 0 };
    if (!groups.has(label)) groups.set(label, { key, rows: [] });
    groups.get(label)!.rows.push(r);
  }
  let out = Array.from(groups.entries()).map(([label, g]) => ({
    label, value: aggValue(g.rows, fn, field), _key: g.key,
  }));
  if (s.sort === "value") out.sort((a, b) => b.value - a.value);
  else if (s.bucket) out.sort((a, b) => a._key - b._key);
  else out.sort((a, b) => a.label.localeCompare(b.label));
  const trimmed = s.limit && s.limit > 0 ? out.slice(0, s.limit) : out;
  return trimmed.map(({ label, value }) => ({ label, value }));
}

/**
 * Resolve every page dataSource over the entity fixtures, returning previewData
 * enriched with one key per SOURCE name (alongside the original entity keys).
 */
export function resolvePreviewSources(
  dataSources: PreviewDataSource[] | undefined,
  previewData: PreviewData | null | undefined,
): PreviewData {
  const pd: PreviewData = previewData && typeof previewData === "object" ? previewData : {};
  if (!Array.isArray(dataSources) || dataSources.length === 0) return pd;
  const out: PreviewData = { ...pd };
  for (const s of dataSources) {
    if (!s || !s.name) continue;
    try {
      const op = s.op;
      if (op === "aggregate" || op === "stats") {
        out[s.name] = resolveAggregate(s, pd);
      } else if (op === "series") {
        out[s.name] = resolveSeries(s, pd);
      } else if (op === "get" || op === "detail" || op === "find" || op === "one") {
        out[s.name] = rowsFor(s.entity, pd)[0] ?? null;
      } else {
        let rows = rowsFor(s.entity, pd).filter((r) => matchesFilter(r, s.filter));
        if (s.limit && s.limit > 0) rows = rows.slice(0, s.limit);
        out[s.name] = rows;
      }
    } catch {
      // leave this source unresolved — the Engine shows empty, never crashes
    }
  }
  return out;
}
