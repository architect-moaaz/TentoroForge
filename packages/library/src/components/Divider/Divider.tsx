import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

type Props = {
  orientation?: "horizontal" | "vertical";
  thickness?: "thin" | "medium" | "thick";
  style?: StyleSlotT;
};

/**
 * Divider — a hairline rule.
 *
 * Two defects fixed here, both recorded in docs/editor-audit/containment.md
 * ("Divider — PARTIAL: horizontal hairline survives; vertical is destroyed;
 * thickness is dead"):
 *
 * 1. `thickness` was a live `select` in the properties panel that this file
 *    did not accept, so validateProps dropped it and picking "thick" changed
 *    nothing. It now maps to a real stroke.
 *
 * 2. The style slot was spread AFTER the rule's own dimensions, so the
 *    width the drop handler derives from the drop rectangle (900px on a
 *    full-width canvas) overwrote the 1px width of a VERTICAL divider and
 *    turned the hairline into a full-height grey slab:
 *      <hr aria-orientation="vertical" style="…width:900px;height:100%…">
 *    The stroke dimension is the component's identity, so it is now applied
 *    LAST on the cross axis and the style slot only decides the divider's
 *    LENGTH (height when vertical, width when horizontal) plus everything
 *    that is not a dimension.
 *
 * The stroke is also a literal px rather than `var(--token-spacing-px)`:
 * no token set in this repo defines a `spacing.px` entry, so that variable
 * resolved to nothing and the declaration was dropped — a "1px" horizontal
 * rule measured 1280x0 and was invisible on the canvas.
 */
const STROKE: Record<string, string> = {
  thin: "1px",
  medium: "2px",
  thick: "4px",
};

export function Divider({ orientation = "horizontal", thickness = "thin", style }: Props) {
  const isVertical = orientation === "vertical";
  const stroke = STROKE[thickness] ?? STROKE.thin;
  const resolved = resolveStyle(style);
  // Split the slot: length keys are the author's to set, cross-axis keys are
  // the component's. `resolved` still supplies background, radius, shadow,
  // margins-by-way-of-padding and the motion duration.
  const { width: slotWidth, height: slotHeight, ...restStyle } = resolved;
  return (
    <hr
      role="separator"
      aria-orientation={orientation}
      data-divider-thickness={thickness}
      style={{
        border: "none",
        backgroundColor: `var(--token-color-border-default, var(--token-neutral-200, #e4e4e7))`,
        display: "block",
        margin: isVertical
          ? "0 var(--token-spacing-2, 0.5rem)"
          : "var(--token-spacing-2, 0.5rem) 0",
        // `height: 100%` resolves to 0 inside an auto-height block parent, so a
        // vertical divider dropped into a Stack would be invisible for the same
        // reason the missing spacing.px token made the horizontal one invisible.
        // One line-box is the smallest height that reads as a rule; an explicit
        // slot minHeight below still wins.
        ...(isVertical ? { minHeight: "1em" } : {}),
        ...restStyle,
        // Cross axis last — a drop-derived width must never be able to erase
        // the stroke that makes a divider a divider.
        width: isVertical ? stroke : (slotWidth ?? "100%"),
        height: isVertical ? (slotHeight ?? "100%") : stroke,
        // A vertical rule inside a flex row has no intrinsic height to take
        // 100% of; `align-self: stretch` gives it the row's height. Harmless
        // in every other layout context.
        alignSelf: isVertical ? "stretch" : undefined,
        flexShrink: 0,
      }}
      {...useMotion(style?.motion)}
    />
  );
}
