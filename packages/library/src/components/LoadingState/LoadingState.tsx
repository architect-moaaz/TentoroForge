import { tokenToCssVar } from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useElevation, useRadiusScale } from "../../theme/tokens-context";

type Props = {
  label: string;
  style?: StyleSlotT;
};

// Radius in rem to match Tailwind equivalents
const RADIUS_REM: Record<"sharp" | "soft" | "round", string> = {
  sharp: "0.125rem",
  soft:  "0.375rem",
  round: "0.5rem",
};

export function LoadingState({ label, style }: Props) {
  const radiusScale = useRadiusScale();
  const elevation = useElevation();

  // Today's LoadingState has no border/shadow (flat appearance).
  // "layered" is the default token value; to preserve today's appearance it maps to no chrome.
  // flat → no border, no shadow; bordered → border only; layered → no extra chrome (today's default); floating → border + shadow
  const showBorder = elevation === "bordered" || elevation === "floating";
  const boxShadow =
    elevation === "floating"
      ? "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1)"
      : undefined;

  return (
    <div
      role="status"
      aria-label={label}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: `var(${tokenToCssVar("spacing.3")})`,
        padding: `var(${tokenToCssVar("spacing.8")})`,
        borderRadius: RADIUS_REM[radiusScale],
        border: showBorder ? "1px solid var(--border, #e5e7eb)" : undefined,
        boxShadow,
        ...resolveStyle(style),
      }}
      {...useMotion(style?.motion)}
    >
      <span
        aria-hidden="true"
        style={{
          display: "inline-block",
          width: `var(${tokenToCssVar("spacing.8")})`,
          height: `var(${tokenToCssVar("spacing.8")})`,
          border: `2px solid var(${tokenToCssVar("neutral.200")})`,
          borderTopColor: `var(${tokenToCssVar("primary.500")})`,
          borderRadius: "50%",
        }}
      />
      <p
        style={{
          fontSize: `var(${tokenToCssVar("typography.sm")})`,
          color: `var(${tokenToCssVar("neutral.500")})`,
          margin: 0,
        }}
      >
        {label}
      </p>
    </div>
  );
}
