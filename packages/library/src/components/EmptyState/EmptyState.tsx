import { tokenToCssVar } from "@tentoroforge/renderer";
import type { StyleSlotT } from "@tentoroforge/schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useElevation, useRadiusScale } from "../../theme/tokens-context";

type Action = {
  label: string;
  workflow?: string;
  navigate?: string;
};

type Props = {
  message: string;
  icon?: string;
  action?: Action;
  style?: StyleSlotT;
};

// Radius in rem to match Tailwind equivalents
const RADIUS_REM: Record<"sharp" | "soft" | "round", string> = {
  sharp: "0.125rem",
  soft:  "0.375rem",
  round: "0.5rem",
};

export function EmptyState({ message, icon, action, style }: Props) {
  const radiusScale = useRadiusScale();
  const elevation = useElevation();

  // Today's EmptyState has no border/shadow (flat appearance).
  // "layered" is the default token value; to preserve today's appearance it maps to no chrome.
  // flat → no border, no shadow; bordered → border only; layered → no extra chrome (today's default); floating → border + shadow
  const showBorder = elevation === "bordered" || elevation === "floating";
  const boxShadow =
    elevation === "floating"
      ? "0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1)"
      : undefined;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: `var(${tokenToCssVar("spacing.3")})`,
        padding: `var(${tokenToCssVar("spacing.8")})`,
        color: `var(${tokenToCssVar("neutral.500")})`,
        borderRadius: RADIUS_REM[radiusScale],
        border: showBorder ? "1px solid var(--border, #e5e7eb)" : undefined,
        boxShadow,
        ...resolveStyle(style),
      }}
      {...useMotion(style?.motion)}
    >
      {icon && (
        <span
          aria-hidden="true"
          style={{ fontSize: `var(${tokenToCssVar("typography.3xl")})` }}
        >
          {icon}
        </span>
      )}
      <p
        style={{
          fontSize: `var(${tokenToCssVar("typography.base")})`,
          margin: 0,
        }}
      >
        {message}
      </p>
      {action && (
        // An anchor when it navigates, a dispatch target when it does not:
        // a link the keyboard cannot reach is not a link.
        action.navigate ? (
          <a
            href={action.navigate}
            style={{
              color: `var(${tokenToCssVar("primary.500")})`,
              fontSize: `var(${tokenToCssVar("typography.sm")})`,
            }}
          >
            {action.label}
          </a>
        ) : (
          <span
            data-workflow={action.workflow}
            style={{
              color: `var(${tokenToCssVar("primary.500")})`,
              fontSize: `var(${tokenToCssVar("typography.sm")})`,
              cursor: "pointer",
            }}
          >
            {action.label}
          </span>
        )
      )}
    </div>
  );
}
