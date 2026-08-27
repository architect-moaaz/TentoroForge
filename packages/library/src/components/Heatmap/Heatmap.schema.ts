import { z } from "zod";

export const HeatmapProps = z.object({
  // Flat cells: [{ x, y, value }] — field names configurable via xKey/yKey/valueKey.
  // Accepts a Mustache binding string too (resolved to an array at runtime).
  data: z.preprocess(
    (v) => (v == null ? [] : v),
    z.union([z.array(z.record(z.unknown())), z.string().min(1)]),
  ),
  xKey:     z.string().optional(),   // default "x" (column)
  yKey:     z.string().optional(),   // default "y" (row)
  valueKey: z.string().optional(),   // default "value"
  rows:     z.array(z.string()).optional(),    // explicit row order (else inferred)
  columns:  z.array(z.string()).optional(),    // explicit column order (else inferred)
  color:    z.string().optional(),   // base cell color; intensity via opacity
  min:      z.number().optional(),   // value → 0 intensity (else data min)
  max:      z.number().optional(),   // value → full intensity (else data max)
  showValues: z.boolean().optional(),
  cellSize: z.number().optional(),   // px, default 34
  bind:      z.string().optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type HeatmapPropsType = z.infer<typeof HeatmapProps>;
