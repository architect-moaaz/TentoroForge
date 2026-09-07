/**
 * Resolve dataSources synchronously against pre-fetched previewData.
 * Extracted from SchemaRendererWrapper so it can be unit-tested without
 * importing React or Next.js "use client" boundaries.
 *
 * Scaffold-specific: /api/_debug/preview-data returns fixture data keyed by
 * entity name. The engine's fetchDataSources loader would fire real /api/
 * requests instead. Both the editor preview and the scaffold want
 * fixture-driven rendering.
 */

import { computeAggregate, type AggregateSource } from "@tentoroforge/engine";

type DataSource = { name: string; entity?: string; table?: string; op?: string;
                    metrics?: Record<string, unknown>; filter?: Record<string, unknown> };

export function resolvePreviewSync(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  page: any,
  previewData: Record<string, unknown> | undefined,
): Record<string, unknown> {
  if (!previewData || Object.keys(previewData).length === 0) return {};

  const sources: Array<DataSource> =
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (page?.dataSources ?? []) as any;
  const resolved: Record<string, unknown> = {};

  for (const s of sources) {
    const entity = (s.entity || s.table || s.name || "") as string;
    const op = (s.op || "list") as string;
    if (op === "stats" || op === "aggregate" || op === "summary" || op === "count") {
      // LLM emits "aggregate" (or "summary"/"count") instead of "stats".
      // Treat all of these as a stats lookup: prefer <entity>Stats key,
      // then fall back to a top-level "stats" key, then the dataSource's
      // own name. When entity is "Unknown" or absent, skip the entityStats
      // lookup and go straight to the top-level fallbacks.
      const entityStats =
        entity && entity !== "Unknown"
          ? previewData[`${entity.toLowerCase()}Stats`]
          : undefined;
      const looked =
        entityStats && typeof entityStats === "object" && !Array.isArray(entityStats)
          ? entityStats
          : (previewData["stats"] ?? previewData[s.name]);
      const blob =
        looked && typeof looked === "object" && !Array.isArray(looked)
          ? (looked as Record<string, unknown>)
          : {};

      // THE SOURCE'S DECLARED `metrics` ARE THE CONTRACT — compute them.
      //
      // This branch used to just look up a pre-computed `<entity>Stats` object
      // and hand it over whole. That LOOKS like it works, and it is why the bug
      // survived: the fixture endpoint does return `itemStats`, so the lookup
      // "succeeded" — with a generic blob (`total`, `count`, `active`,
      // `growthRate`, …) containing NONE of the metric names the page actually
      // declares (`totalValue`, `itemCount`, `lowStockCount`). Every
      // `{{source.metric}}` binding resolved to undefined and all three KPI
      // tiles on /items rendered blank, on a page whose schema was by then
      // completely correct.
      //
      // So: when a source declares metrics, those names win and are calculated
      // from the rows. The looked-up blob stays underneath, so a source that
      // declares no metrics behaves exactly as before and any binding pointing
      // at a generic key still resolves. `computeAggregate` is the engine's
      // shared implementation — the editor canvas computes the same way, and
      // the two surfaces disagreeing is what produced this in the first place.
      const declared = s.metrics && Object.keys(s.metrics).length > 0;
      resolved[s.name] = declared
        ? { ...blob, ...computeAggregate(s as unknown as AggregateSource, previewData) }
        : blob;
      continue;
    }
    // Build candidate keys to look up in previewData. The first match wins.
    // Covers casing variance (PascalCase / camelCase / lowercase / pluralised)
    // plus common LLM-emitted alias entities (e.g. "Employee" → User).
    const PERSON_ALIASES = [
      "Employee", "Author", "Person", "Owner", "Manager",
      "Customer", "Submitter", "Approver", "Assignee",
    ];
    const personFallback = PERSON_ALIASES.includes(entity) ? ["User", "user", "users"] : [];
    const candidates = [
      entity,
      entity.toLowerCase(),
      entity.length > 0 ? entity[0].toLowerCase() + entity.slice(1) : entity,
      entity.length > 0
        ? (entity[0].toLowerCase() + entity.slice(1)).replace(/s?$/, "s")
        : entity,
      ...personFallback,
    ];
    let val: unknown;
    for (const key of candidates) {
      if (previewData[key] !== undefined) {
        val = previewData[key];
        break;
      }
    }
    if (val !== undefined) {
      const arr = Array.isArray(val) ? val : [val];
      resolved[s.name] = op === "get" ? (arr[0] ?? {}) : arr;
    } else {
      resolved[s.name] = op === "get" ? {} : [];
    }
  }

  // Detail pages (op="get") commonly bind nested-entity templates without
  // the parent prefix — `{{employee.name}}` rather than
  // `{{leaveRequest.employee.name}}`. Lift FK-joined sub-objects from any
  // single-record source to the top level so both forms resolve. Only
  // object-shaped values are lifted (not arrays/scalars) — purely additive.
  for (const s of sources) {
    if ((s.op || "list") !== "get") continue;
    const record = resolved[s.name];
    if (!record || typeof record !== "object" || Array.isArray(record)) continue;
    for (const [key, value] of Object.entries(record as Record<string, unknown>)) {
      if (value && typeof value === "object" && !Array.isArray(value)) {
        if (!(key in resolved)) resolved[key] = value;
      }
    }
  }
  return resolved;
}
