import { tokenToCssVar } from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

/**
 * `thickness` is declared in the registry with a live select (thin/medium/thick)
 * and was never read — the line was always 1px whatever the user chose. Mapped
 * to concrete strokes here rather than to a spacing token, because a divider's
 * stroke is a hairline measure and `spacing.px` is the only token near that
 * scale; medium/thick have no token equivalent to borrow.
 */
const THICKNESS: Record<string, string> = {
  thin: "1px",
  medium: "2px",
  thick: "4px",
};

type Props = {
  orientation?: "horizontal" | "vertical";
  thickness?: "thin" | "medium" | "thick";
  style?: StyleSlotT;
};

export function Divider({ orientation = "horizontal", thickness = "thin", style }: Props) {
  const isVertical = orientation === "vertical";
  const stroke = THICKNESS[thickness] ?? THICKNESS.thin;
  return (
    <hr
      role="separator"
      aria-orientation={orientation}
      style={{
        border: "none",
        backgroundColor: `var(${tokenToCssVar("neutral.200")})`,
        width: isVertical ? stroke : "100%",
        height: isVertical ? "100%" : stroke,
        display: "block",
        margin: isVertical ? `0 var(${tokenToCssVar("spacing.2")})` : `var(${tokenToCssVar("spacing.2")}) 0`,
        ...resolveStyle(style),
      }}
      {...useMotion(style?.motion)}
    />
  );
}
