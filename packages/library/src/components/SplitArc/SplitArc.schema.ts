import { z } from "zod";

/**
 * One coloured segment of the arc. Value is in the same units as `total` (or
 * un-normalised — the component divides through). `label` renders next to the
 * segment's dot in the legend; `endLabel` (optional) is the number rendered
 * at the segment's terminal end of the arc (e.g. "2.15 kW ↑").
 */
export const SplitArcSegment = z.object({
  value:      z.number(),
  color:      z.string(),                    // CSS colour or design token
  label:      z.string(),                    // legend text
  endLabel:   z.string().optional(),         // arc-endpoint value (e.g. "2.15 kW")
  trend:      z.enum(["up", "down", "flat"]).optional(),
});

/**
 * Half-arc gauge whose sweep is split across ≥2 segments. Unlike `Gauge`
 * (single value, needle, threshold zones) this shows a *ratio* between two or
 * more contributors — the classic "energy balance / expenses vs income /
 * received vs used" shape from consumer-utility dashboards.
 *
 * The arc is a 180° sweep centred at the top; segments start left, run clockwise
 * to the right, in the order given. Each segment gets a proportional slice of
 * the sweep. A small dot-per-segment legend renders below the arc.
 */
export const SplitArcProps = z.object({
  segments:   z.array(SplitArcSegment).min(1),
  /** Optional numerator/denominator normalisation. Defaults to `sum(values)`. */
  total:      z.number().optional(),
  /** Title above the arc — e.g. "Energy Balance Today". */
  title:      z.string().optional(),
  /** Diameter in px. Default 220. Height is ≈ diameter × 0.7 (half-arc). */
  size:       z.number().optional(),
  /** Arc stroke width in px. Default derived from size (~11%). */
  stroke:     z.number().optional(),
  /** Show the legend row (coloured dot + label). Default true. */
  showLegend: z.boolean().optional(),
  /** Show the endpoint labels under the arc (Received / Costs style). Default true. */
  showEndLabels: z.boolean().optional(),
  bind:       z.string().optional(),
  className:  z.string().optional(),
  style:      z.record(z.unknown()).optional(),
});
export type SplitArcSegmentType = z.infer<typeof SplitArcSegment>;
export type SplitArcPropsType   = z.infer<typeof SplitArcProps>;
