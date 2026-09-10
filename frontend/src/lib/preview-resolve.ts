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
  fn?: string;
  field?: string;
  /** Arithmetic over row fields ("quantity * price") when no single field holds
   *  the value. Emitted by the generator's metric-dialect normaliser. */
  expr?: string;
  /** The page composer's own dialect: "sum(quantity * price)", "count(id)".
   *  The generator normalises this away, but a project generated before that
   *  fix still carries it on disk and the editor still has to render it. */
  expression?: string;
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

/**
 * SHARED WITH THE SCAFFOLD — do not re-implement here.
 *
 * These helpers used to be private copies in this file. The scaffold's own
 * resolver (`apps/render-scaffold/src/lib/resolvePreviewSync.ts`) had no
 * equivalent at all: it looked up a pre-computed `<entity>Stats` blob instead
 * of computing anything, so the SAME page whose KPI tiles showed numbers on
 * this canvas rendered three blank tiles in the shipped preview. Two surfaces,
 * two answers to "what is an aggregate metric?".
 *
 * `packages/engine/src/data/aggregate.ts` is now the single implementation and
 * both import it, so they cannot drift again.
 *
 * Delegating also fixes a latent bug here: the local `matchesFilter` did strict
 * equality only, so a comparator filter like `{ quantity: { lt: 5 } }` — which
 * the generated schemas do emit — matched nothing and a "low stock" metric
 * counted 0 rows on this canvas.
 */
import {
  rowsFor,
  matchesFilter,
  aggValue,          // still used directly by resolveSeries below
  computeAggregate as resolveAggregateShared,
} from "@tentoroforge/engine";

const resolveAggregate = (s: PreviewDataSource, pd: PreviewData): Record<string, number> =>
  resolveAggregateShared(s as never, pd);

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
