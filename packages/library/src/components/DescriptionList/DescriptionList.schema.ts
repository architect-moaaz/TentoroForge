import { z } from "zod";
// Accept both the canonical {term, description} shape AND the more common
// {label, value} shape LLM-authored schemas tend to emit. The component
// normalizes to term/description at render time.
const Pair = z.union([
  z.object({ term: z.string(), description: z.string() }).passthrough(),
  z.object({ label: z.string(), value: z.union([z.string(), z.number(), z.null()]).optional() }).passthrough(),
]);
export const DescriptionListProps = z.object({
  items:       z.array(Pair).default([]),
  // Alternative to `items`: bind an object (e.g. a jsonb column) and render
  // one row per key/value via `itemMode: "entries"`. Lets a detail page bind
  // an extracted-fields blob directly without a Python-side rekey pass.
  dataSource:  z.union([z.record(z.unknown()), z.array(z.unknown())]).optional(),
  itemMode:    z.enum(["entries", "items"]).optional(),
  emptyText:   z.string().optional(),
  orientation: z.enum(["vertical", "horizontal"]).optional(),
  // Skeleton contract — set true while the data fetch is pending so the
  // list renders matching-dimension placeholder rows and doesn't reflow
  // when data lands. Root-cause fix for CLS class (B-021.5).
  isLoading:   z.boolean().optional(),
  skeletonRows: z.number().optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type DescriptionListPropsType = z.infer<typeof DescriptionListProps>;
