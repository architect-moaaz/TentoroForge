import { z } from "zod";
import { PageV2, type PageV2T } from "./page";

// Re-uses PageV2's envelope by spreading PageV2.shape, but relaxes `root`
// to z.unknown() so:
//   1) v2 round-trip preserves zod defaults (no injection that would
//      break test 1's toEqual)
//   2) v1 pages with LibraryNode subtypes (e.g. Heading) survive — those
//      aren't in the NodeV2 union by design
const PageV2Loose = z.object({
  ...PageV2.shape,
  root: z.unknown(),
});

/**
 * The migrated-page type is structurally PageV2 except `root` is unknown,
 * because migratePage preserves v1 LibraryNode subtypes that PageV2's strict
 * NodeV2 union doesn't recognize. Callers wanting strict node-union
 * validation should call PageV2.parse(migrated) and handle errors.
 */
export type PageV2Migrated = z.infer<typeof PageV2Loose>;

/**
 * Idempotent v1→v2 migration.
 *
 * Pure additive: stamps schemaVersion: "2" if missing or "1". Does NOT
 * modify the node tree — nodes are preserved as-is so that unknown v1 node
 * types (LibraryNode subtypes) survive migration. Validates only the page
 * envelope, not the node union.
 *
 * Throws if the page envelope itself is structurally incompatible (e.g.
 * missing required id/route/layout). If strict node-union validation is
 * needed, call PageV2.parse() on the result separately.
 */
export function migratePage(raw: unknown): PageV2Migrated {
  const obj = (raw && typeof raw === "object" ? { ...(raw as Record<string, unknown>) } : {});
  if (obj.schemaVersion !== "2") obj.schemaVersion = "2";
  return PageV2Loose.parse(obj);
}
