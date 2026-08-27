import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * SearchInput — SEARCH-3 full-text search bar backed by the shared
 * `searchStore`. Debounces keystrokes, fires the configured endpoint
 * (a data-engine op:"search" URL by convention), and pushes the hits
 * into the store the paired SearchResults reads from.
 *
 * Distinct from GlobalSearch (which dispatches a workflow event) —
 * SearchInput calls a data endpoint directly and manages result state
 * in the store. Use when the results are ranked hits from op:"search";
 * use GlobalSearch when the search triggers navigation or a workflow.
 */
export const SearchInputProps = z
  .object({
    placeholder: z.string().min(1).default("Search…"),
    /** HTTP endpoint that resolves op:"search" and returns SearchHit[].
     *  Convention: /api/search?q=… ; the endpoint is expected to POST or GET
     *  and return a JSON array. */
    endpoint: z.string().min(1),
    debounceMs: z.number().int().min(0).max(2000).default(300),
    /** Minimum query length before firing. Sub-threshold input clears results. */
    minChars: z.number().int().min(0).max(20).default(2),
    style: StyleSlot.optional(),
  })
  .strict();

export type SearchInputPropsType = z.infer<typeof SearchInputProps>;
