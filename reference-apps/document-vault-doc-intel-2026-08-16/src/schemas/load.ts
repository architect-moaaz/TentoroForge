import { Page } from "@tentoroforge/schema";
import type { z } from "zod";

// Module-level cache: schema name → validated Page object (per-process in RSC).
const cache = new Map<string, z.infer<typeof Page>>();

/** Validate a raw JSON object against the Page schema and cache the result.
 * Validation is ADVISORY: generated schemas use binding expressions
 * ("{{stats.total}}") in typed fields and may omit fields that are optional at
 * runtime (e.g. layout). The Engine resolves/tolerates these, so a strict-schema
 * miss must NOT 500 the page — warn and render the raw schema as-is. */
export function loadSchema(name: string, raw: unknown): z.infer<typeof Page> {
  const hit = cache.get(name);
  if (hit) return hit;
  const result = Page.safeParse(raw);
  if (result.success) {
    cache.set(name, result.data);
    return result.data;
  }
  const msg = result.error.errors
    .map((e) => `${e.path.join(".") || "<root>"}: ${e.message}`)
    .join("; ");
  console.warn(`[schema] '${name}' did not strictly validate (${msg}); rendering as-is.`);
  const data = raw as z.infer<typeof Page>;
  cache.set(name, data);
  return data;
}
