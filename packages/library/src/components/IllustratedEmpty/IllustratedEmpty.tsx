import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import { useMotion } from "../../style/useMotion";
import { resolveStyle } from "../../style/resolveStyle";

/**
 * IllustratedEmpty — Spec C Slice 9 branded empty-state.
 *
 * The illustration is a simple geometric SVG (circle + accent shape)
 * that adopts brand colors via CSS variables. Ten `kind` presets each
 * pick a different silhouette so the same domain doesn't stamp the
 * same illustration on every empty state.
 *
 * Pure infrastructure — no image assets, no external fonts.
 */
type Action = { label: string; workflow?: string; navigate?: string };
type Props = {
  kind?: "list" | "search" | "filtered" | "first-use" | "no-data"
       | "success" | "error" | "coming-soon" | "no-access" | "offline";
  title: string;
  message?: string;
  action?: Action;
  style?: StyleSlotT;
};

// Small SVG glyph per kind — kept intentionally minimal + geometric so
// they adopt tokens uniformly and never look "stock".
function Glyph({ kind }: { kind: NonNullable<Props["kind"]> }) {
  const stroke = "var(--primary, hsl(210 60% 45%))";
  const fill = "var(--accent, hsl(30 80% 55%))";
  const muted = "var(--muted-foreground, hsl(0 0% 60%))";
  const c: React.SVGProps<SVGSVGElement> = {
    width: 96, height: 96, viewBox: "0 0 96 96",
    fill: "none", stroke, strokeWidth: 2, strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const, "aria-hidden": true,
  };
  switch (kind) {
    case "search":
      return (<svg {...c}><circle cx="40" cy="40" r="24" /><line x1="60" y1="60" x2="80" y2="80" /><circle cx="70" cy="70" r="4" fill={fill} stroke="none" /></svg>);
    case "filtered":
      return (<svg {...c}><path d="M16 20 L80 20 L56 48 L56 76 L40 68 L40 48 Z" /><circle cx="48" cy="30" r="4" fill={fill} stroke="none" /></svg>);
    case "first-use":
      return (<svg {...c}><circle cx="48" cy="48" r="30" /><path d="M32 48 L48 32 L64 48" /><line x1="48" y1="32" x2="48" y2="66" /></svg>);
    case "no-data":
      return (<svg {...c}><rect x="16" y="20" width="64" height="56" rx="4" /><line x1="16" y1="36" x2="80" y2="36" /><line x1="32" y1="48" x2="64" y2="48" stroke={muted} /><line x1="32" y1="58" x2="56" y2="58" stroke={muted} /><line x1="32" y1="68" x2="60" y2="68" stroke={muted} /></svg>);
    case "success":
      return (<svg {...c}><circle cx="48" cy="48" r="32" /><path d="M32 48 L44 60 L64 36" stroke={fill} strokeWidth={3} /></svg>);
    case "error":
      return (<svg {...c}><circle cx="48" cy="48" r="32" /><line x1="34" y1="34" x2="62" y2="62" stroke={fill} strokeWidth={3} /><line x1="62" y1="34" x2="34" y2="62" stroke={fill} strokeWidth={3} /></svg>);
    case "coming-soon":
      return (<svg {...c}><circle cx="48" cy="48" r="32" /><line x1="48" y1="30" x2="48" y2="48" /><line x1="48" y1="48" x2="62" y2="56" /></svg>);
    case "no-access":
      return (<svg {...c}><rect x="24" y="42" width="48" height="34" rx="4" /><path d="M32 42 V32 a16 16 0 0 1 32 0 V42" /><circle cx="48" cy="58" r="4" fill={fill} stroke="none" /></svg>);
    case "offline":
      return (<svg {...c}><path d="M16 40 Q48 20 80 40" stroke={muted} /><path d="M28 52 Q48 40 68 52" /><path d="M40 64 Q48 58 56 64" strokeWidth={3} stroke={fill} /><circle cx="48" cy="76" r="3" fill={fill} stroke="none" /><line x1="16" y1="16" x2="80" y2="80" stroke={fill} strokeWidth={2} /></svg>);
    case "list":
    default:
      return (<svg {...c}><rect x="16" y="24" width="64" height="8" rx="2" /><rect x="16" y="40" width="48" height="8" rx="2" stroke={muted} /><rect x="16" y="56" width="56" height="8" rx="2" stroke={muted} /><circle cx="76" cy="60" r="6" fill={fill} stroke="none" /></svg>);
  }
}

export function IllustratedEmpty({
  kind = "list", title, message, action, style,
}: Props): React.ReactElement {
  const motion = useMotion(style?.motion);
  const styleProps = resolveStyle(style);
  return (
    <div
      data-forge-illustrated-empty={kind}
      {...motion}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 16,
        padding: 32,
        textAlign: "center",
        color: "var(--foreground, hsl(0 0% 15%))",
        ...styleProps,
      }}
    >
      <Glyph kind={kind} />
      <div style={{ fontWeight: 600, fontSize: "1rem" }}>{title}</div>
      {message ? (
        <div style={{ color: "var(--muted-foreground, hsl(0 0% 45%))", fontSize: "0.875rem", maxWidth: 360 }}>
          {message}
        </div>
      ) : null}
      {action ? (
        // An anchor when it navigates, a button when it dispatches: the
        // element has to match what activating it does.
        React.createElement(
          action.navigate ? "a" : "button",
          {
            ...(action.navigate
              ? { href: action.navigate }
              : { type: "button", "data-forge-workflow": action.workflow }),
            style: {
            marginTop: 8,
            padding: "8px 16px",
            borderRadius: "var(--radius-md, 0.375rem)",
            background: "var(--primary, hsl(210 60% 45%))",
            color: "var(--primary-foreground, white)",
            border: "none",
            cursor: "pointer",
            fontSize: "0.875rem",
              display: "inline-block",
              textDecoration: "none",
            },
          },
          action.label,
        )
      ) : null}
    </div>
  );
}
