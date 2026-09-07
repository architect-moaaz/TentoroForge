import type { ReactNode, CSSProperties } from "react";
import { resolveStyle } from "../../runtime/tokens";
import { applyStyleSlot } from "../../runtime/style-slot";

/**
 * Container — centers its content with a responsive max-width and
 * breakpoint-scaled horizontal padding, so pages keep margins on phones
 * (where edge-to-edge content looks cramped) but expand to the configured
 * width on larger screens.
 *
 * It is ALSO a flex box. The registry has always advertised
 * direction / gap / padding / align / justify / wrap alongside maxWidth
 * (packages/registry/src/starter.ts containerEntry), and until this change
 * this file read `maxWidth` and nothing else: probe_props_5 in
 * docs/editor-audit/panels.md set all six and the rendered element was still
 * `class="mx-auto w-full px-4 sm:px-6 lg:px-8 max-w-screen-sm"` — six live
 * select/toggle controls that moved nothing on the canvas. Container is the
 * node the user builds every page inside, so that was the single largest
 * write-with-no-reader in the editor.
 *
 * The class mapping is deliberately the SAME table Stack.tsx uses (identical
 * prop names in the panel must mean identical results), including the
 * `flex-col md:flex-row` treatment of `direction: "horizontal"` — a horizontal
 * container that did not stack on a phone would overflow the viewport, and
 * making Container the one layout node that behaves differently from Stack
 * would be its own trap.
 */
const MAXW: Record<string, string> = {
  sm:  "max-w-screen-sm",
  md:  "max-w-screen-md",
  lg:  "max-w-screen-lg",
  xl:  "max-w-screen-xl",
  "2xl": "max-w-screen-2xl",
  full: "",
};

const ALIGN_CLASS: Record<string, string> = {
  start:   "items-start",
  center:  "items-center",
  end:     "items-end",
  stretch: "items-stretch",
};

// `evenly` is in the registry's justify options for Container (it is not for
// Stack/Row) — leaving it out here would reproduce the same dead-control bug
// one option deeper.
const JUSTIFY_CLASS: Record<string, string> = {
  start:   "justify-start",
  center:  "justify-center",
  end:     "justify-end",
  between: "justify-between",
  around:  "justify-around",
  evenly:  "justify-evenly",
};

// Same table as Stack.tsx / Grid.tsx: a real Tailwind utility, never an inline
// `gap: var(--token-…)`. The synthesised variables for `tokens.spacing.N` are
// not defined anywhere, so the inline form silently collapsed to 0.
const GAP_CLASS: Record<string, string> = {
  none: "gap-0",
  xs: "gap-1", sm: "gap-2", md: "gap-4", lg: "gap-6", xl: "gap-8", "2xl": "gap-10",
  "tokens.spacing.1": "gap-1",
  "tokens.spacing.2": "gap-2",
  "tokens.spacing.3": "gap-3",
  "tokens.spacing.4": "gap-4",
  "tokens.spacing.5": "gap-5",
  "tokens.spacing.6": "gap-6",
  "tokens.spacing.8": "gap-8",
  "tokens.spacing.10": "gap-10",
  "tokens.spacing.12": "gap-12",
  "tokens.spacing.semantic.input": "gap-3",
  "tokens.spacing.semantic.element": "gap-4",
  "tokens.spacing.semantic.card": "gap-5",
  "tokens.spacing.semantic.section": "gap-8",
  "tokens.spacing.semantic.page": "gap-8",
};

const PADDING_CLASS: Record<string, string> = {
  none: "p-0",
  xs: "p-1", sm: "p-2", md: "p-4", lg: "p-6", xl: "p-8", "2xl": "p-10",
  "tokens.spacing.1": "p-1",
  "tokens.spacing.2": "p-2",
  "tokens.spacing.3": "p-3",
  "tokens.spacing.4": "p-4",
  "tokens.spacing.6": "p-6",
  "tokens.spacing.8": "p-8",
};

// The six flex props are all optional. When NONE of them is present the node
// is a legacy Container (every schema written before the props were wired up,
// including the pages already on disk) and it must keep rendering as the plain
// centred block it always was — turning those into flex boxes with a default
// gap would silently re-space every existing page.
const FLEX_PROPS = ["direction", "gap", "align", "justify", "wrap"] as const;

export function Container({ node, children }: { node: any; children: ReactNode[] }) {
  const p = node.props ?? {};
  const slotProps = applyStyleSlot(node.style);
  const maxKey = p.maxWidth ?? "lg";
  const maxClass = MAXW[maxKey] ?? "max-w-screen-lg";
  // MCP pipeline emits per-node className + style derived from Figma Dev Mode output.
  // When the caller supplies a className, treat the node as a styled passthrough
  // box: emit ONLY that className. The responsive page-container defaults
  // (mx-auto, max-w-screen-lg, breakpoint padding, w-full) would otherwise
  // force width:100% and collide with caller sizing like size-[56px].
  const callerClass = typeof p.className === "string" ? p.className : "";
  const callerStyle = p.style && typeof p.style === "object" ? p.style as CSSProperties : {};

  const wantsFlex = FLEX_PROPS.some((k) => p[k] !== undefined);
  // `padding` replaces the responsive page gutter rather than stacking on top
  // of it: `p-4` and `px-4` have equal specificity, so emitting both leaves the
  // horizontal padding decided by Tailwind's output order instead of by the
  // user. An explicit choice wins; absent the prop the gutter stays.
  const paddingKey = typeof p.padding === "string" ? p.padding : undefined;
  const paddingClass = paddingKey !== undefined
    ? (PADDING_CLASS[paddingKey] ?? "p-4")
    : "px-4 sm:px-6 lg:px-8";

  const layoutClass = [
    "mx-auto w-full",
    paddingClass,
    maxClass,
    ...(wantsFlex
      ? [
          "flex",
          p.direction === "horizontal" ? "flex-col md:flex-row" : "flex-col",
          GAP_CLASS[p.gap as string] ?? (p.gap === undefined ? "" : "gap-4"),
          ALIGN_CLASS[p.align as string] ?? (p.align === undefined ? "" : "items-stretch"),
          JUSTIFY_CLASS[p.justify as string] ?? (p.justify === undefined ? "" : "justify-start"),
          p.wrap ? "flex-wrap" : "",
        ]
      : []),
  ].filter(Boolean).join(" ");

  const className = callerClass ? callerClass : layoutClass;
  // Same shellRole hook as Stack — LLM-generated shells often use Container
  // (not Stack) for the sidebar wrapper, so both need to forward the marker.
  const shellRole = p.shellRole;
  const shellRoleAttr = (shellRole === "sidebar") ? "" : undefined;
  const backdropAttr = (shellRole === "backdrop") ? "" : undefined;
  return (
    <div
      data-node-id={node.id}
      className={className}
      style={{
        ...resolveStyle(node.style),
        ...slotProps.style,
        ...callerStyle,
      }}
      data-motion={slotProps["data-motion"]}
      data-shell-sidebar={shellRoleAttr}
      data-sidebar-backdrop={backdropAttr}
    >
      {children}
    </div>
  );
}
