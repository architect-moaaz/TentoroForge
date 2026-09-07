/**
 * "Is this colour actually set?" — asked once, here.
 *
 * THE BUG THIS EXISTS FOR
 * -----------------------
 * A dropped Sparkline drew a polyline with correct geometry and **no ink**:
 * `stroke=""`, computed `stroke: none`. SVG treats an invalid paint value as
 * the initial value, so the line was painted in nothing. The component looked
 * fine — `color = "currentColor"` as a parameter default — but a **JS parameter
 * default only fires for `undefined`**, and the value arriving was `""`. Same
 * hole one operator over in the chart family: `s.color ?? DEFAULT_PALETTE[i]`
 * is nullish coalescing, which also passes `""` straight through.
 *
 * Whoever produced the `""` (a registry seed, a Figma import, a user who typed
 * into a colour box and deleted it again) is a separate question and worth
 * fixing separately. But a component that renders NOTHING because a prop is
 * present-and-empty is failing in the worst available way — silently, with no
 * error and no clue — and the defence belongs where the value is consumed, once,
 * rather than as a different ad-hoc guard in each of eight files.
 */

/** The colour to paint with: `value` when it is a non-blank string, else `fallback`. */
export function paintOr(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() !== "" ? value : fallback;
}
