import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useElevation, useRadiusScale } from "../../theme/tokens-context";
import { formatValue } from "../../utils/formatValue";
import type { ALERT_VARIANTS } from "./Alert.schema";

type Variant = (typeof ALERT_VARIANTS)[number];

// Colors read the ONE token contract's status tints — `<status>-subtle` for
// the callout surface, `<status>-subtle-foreground` for its text — filled from
// the Blueprint's palette by the projector, so a callout wears the design's
// colours and matches the status Badge. (Alert's `danger` maps to the
// contract's `destructive`; `neutral` uses the muted surface.) The hex
// fallbacks stand only when a token is unset. Same status semantics as
// components/Badge/Badge.tsx — the two must not drift.
const VARIANT_STYLES: Record<Variant, { background: string; color: string; border: string }> = {
  neutral: { background: "hsl(var(--muted, 210 40% 96%))",             color: "hsl(var(--foreground, 221 39% 11%))",                   border: "hsl(var(--border, 220 13% 91%))" },
  info:    { background: "hsl(var(--info-subtle, 204 94% 94%))",       color: "hsl(var(--info-subtle-foreground, 201 96% 26%))",       border: "hsl(var(--info-subtle-foreground, 201 96% 26%) / 0.2)" },
  success: { background: "hsl(var(--success-subtle, 141 79% 93%))",    color: "hsl(var(--success-subtle-foreground, 142 71% 22%))",    border: "hsl(var(--success-subtle-foreground, 142 71% 22%) / 0.2)" },
  danger:  { background: "hsl(var(--destructive-subtle, 0 86% 97%))",  color: "hsl(var(--destructive-subtle-foreground, 0 74% 32%))",  border: "hsl(var(--destructive-subtle-foreground, 0 74% 32%) / 0.2)" },
  warning: { background: "hsl(var(--warning-subtle, 48 96% 89%))",     color: "hsl(var(--warning-subtle-foreground, 31 92% 30%))",     border: "hsl(var(--warning-subtle-foreground, 31 92% 30%) / 0.2)" },
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
  ariaLive?: "off" | "polite" | "assertive";
  style?: StyleSlotT;
};

export function Alert({ message, variant = "neutral", title, ariaLive, style }: Props) {
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
      aria-live={ariaLive}
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
