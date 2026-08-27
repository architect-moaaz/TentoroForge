import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * SearchResults — SEARCH-3 ranked hit list, backed by the shared
 * searchStore that SearchInput writes into. Renders three distinct
 * states — pristine (no query yet), loading skeleton, no-matches — plus
 * the populated list.
 *
 * Row shape (from op:"search" resolver):
 *   {id, entity, snippet: "<b>match</b>...", rank, <primaryField>: string}
 *
 * A row click navigates to `hrefPattern` with `${entity}` / `${id}`
 * substituted — falls back to no-op when unset. The snippet is rendered
 * via dangerouslySetInnerHTML because ts_headline emits <b> markup
 * (Postgres HTML-escapes everything else in the source text).
 */
export const SearchResultsProps = z
  .object({
    /** Route template for a clicked hit. `${entity}` / `${id}` are substituted.
     *  Empty string = rows are non-navigating (results panel only). */
    hrefPattern: z.string().default("/${entity}/${id}"),
    /** Number of skeleton rows shown while a query is loading. */
    skeletonRows: z.number().int().min(1).max(20).default(5),
    /** Copy shown before the user has typed a query. */
    pristineText: z.string().default("Search across your data."),
    /** Copy shown when a query returned no matches. Distinct from pristine so
     *  the caller can suggest widening the search. */
    emptyText: z.string().default("No matches found. Try different keywords or check spelling."),
    style: StyleSlot.optional(),
  })
  .strict();

export type SearchResultsPropsType = z.infer<typeof SearchResultsProps>;
