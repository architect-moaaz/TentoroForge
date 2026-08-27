import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useElevation, useRadiusScale } from "../../theme/tokens-context";
import { formatValue } from "../../utils/formatValue";
import type { ALERT_VARIANTS } from "./Alert.schema";

type Variant = (typeof ALERT_VARIANTS)[number];

// Colors read the app's --color-* scale (emitted into every generated app's
// globals.css from its palette) with the old hexes as fallbacks. Hardcoded
// Tailwind-blue callouts were identical in every generated app forever —
// one of the audited "same generator" tells.
const VARIANT_STYLES: Record<Variant, { background: string; color: string; border: string }> = {
  neutral: { background: "var(--color-secondary-100, #f5f5f5)", color: "var(--color-secondary-800, #333)", border: "var(--color-secondary-200, #ddd)" },
  info:    { background: "var(--color-info-100, #eff6ff)", color: "var(--color-info-800, #1e40af)", border: "var(--color-info-200, #bfdbfe)" },
  success: { background: "var(--color-success-100, #f0fdf4)", color: "var(--color-success-800, #166534)", border: "var(--color-success-200, #bbf7d0)" },
  danger:  { background: "var(--color-error-100, #fef2f2)", color: "var(--color-error-800, #991b1b)", border: "var(--color-error-200, #fecaca)" },
  warning: { background: "var(--color-warning-100, #fffbeb)", color: "var(--color-warning-800, #92400e)", border: "var(--color-warning-200, #fde68a)" },
};

// Radius in rem, matching Tailwind equivalents (sharp≈sm, soft≈md, round≈lg)
const RADIUS_REM: Record<"sharp" | "soft" | "round", string> = {
  sharp: "0.125rem",
  soft:  "0.375rem",
  round: "0.5rem",
};

type Props = {
  message: string;
  variant?: Variant;
  title?: string;
  style?: StyleSlotT;
};

export function Alert({ message, variant = "neutral", title, style }: Props) {
  const styles = VARIANT_STYLES[variant];
  const radiusScale = useRadiusScale();
  const elevation = useElevation();

  // Build border + shadow treatment from elevation token.
  // Today's Alert uses border-only (no shadow), which maps to "layered" default.
  // flat → no border, no shadow; bordered → border only; layered → border only (today's default); floating → border + shadow-lg
  const showBorder = elevation !== "flat";
  const boxShadow =
    elevation === "floating"
      ? "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1)"
      : undefined;

  return (
    <div
      role="alert"
      data-alert=""
      data-variant={variant}
      style={{
        backgroundColor: styles.background,
        color: styles.color,
        border: showBorder ? `1px solid ${styles.border}` : undefined,
        borderRadius: RADIUS_REM[radiusScale],
        boxShadow,
        padding: "0.75rem 1rem",
        ...resolveStyle(style),
      }}
      {...useMotion(style?.motion)}
    >
      {title && (
        <div style={{ fontWeight: 600, marginBottom: "0.25rem" }}>
          {formatValue(title as unknown)}
        </div>
      )}
      <div>{formatValue(message as unknown)}</div>
    </div>
  );
}
