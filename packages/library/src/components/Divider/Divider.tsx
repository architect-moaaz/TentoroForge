import { tokenToCssVar } from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";

type Props = {
  orientation?: "horizontal" | "vertical";
  style?: StyleSlotT;
};

export function Divider({ orientation = "horizontal", style }: Props) {
  const isVertical = orientation === "vertical";
  return (
    <hr
      role="separator"
      aria-orientation={orientation}
      style={{
        border: "none",
        backgroundColor: `var(${tokenToCssVar("neutral.200")})`,
        width: isVertical ? `var(${tokenToCssVar("spacing.px")})` : "100%",
        height: isVertical ? "100%" : `var(${tokenToCssVar("spacing.px")})`,
        display: "block",
        margin: isVertical ? `0 var(${tokenToCssVar("spacing.2")})` : `var(${tokenToCssVar("spacing.2")}) 0`,
        ...resolveStyle(style),
      }}
      {...useMotion(style?.motion)}
    />
  );
}
