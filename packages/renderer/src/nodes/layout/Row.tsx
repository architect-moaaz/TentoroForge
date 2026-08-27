import type { ReactNode } from "react";
import { resolveStyle, tokenToCssVar } from "../../runtime/tokens";
import { applyStyleSlot, dataAttrProps } from "../../runtime/style-slot";

/**
 * Row — horizontal flex container. Wraps by default so children flow onto
 * additional rows on narrow viewports rather than overflowing horizontally.
 * Use `wrap: false` if a single-line group is required.
 */
const ALIGN_CLASS: Record<string, string> = {
  start:   "items-start",
  center:  "items-center",
  end:     "items-end",
  stretch: "items-stretch",
};
const JUSTIFY_CLASS: Record<string, string> = {
  start:   "justify-start",
  center:  "justify-center",
  end:     "justify-end",
  between: "justify-between",
  around:  "justify-around",
};

// See Stack.tsx for full rationale — schemas commonly emit
// `gap: "tokens.spacing.4"` which never resolved as a real CSS var, leaving
// rows visually un-gapped. Map to a Tailwind utility instead.
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
};
function _gapClass(gap: unknown): string {
  if (typeof gap !== "string" || !gap) return "gap-3";  // Rows tend to be tighter than Stacks
  return GAP_CLASS[gap] ?? "gap-3";
}

export function Row({ node, children }: { node: any; children: ReactNode[] }) {
  const p = node.props ?? {};
  const slotProps = applyStyleSlot(node.style);
  // MCP pipeline emits per-node className + style derived from Figma Dev Mode output.
  const callerClassRaw = typeof p.className === "string" ? p.className : "";
  const callerStyle = p.style && typeof p.style === "object" ? p.style as React.CSSProperties : {};

  // Detect whether the caller's className already supplies the alignment /
  // justification / gap utility. If so, drop our default for that axis —
  // Tailwind's compiled CSS orders utilities alphabetically so a base
  // `justify-start` would otherwise beat a caller's `justify-between` regardless
  // of class-string order. Same logic for `items-*` and `gap-*`.
  const hasItems   = /\bitems-(start|center|end|stretch|baseline)\b/.test(callerClassRaw);
  const hasJustify = /\bjustify-(start|center|end|between|around|evenly)\b/.test(callerClassRaw);
  const hasGap     = /\bgap-/.test(callerClassRaw);

  // Full-height rows (page shells, sidebar columns) need their children
  // to stretch so a 247px sidebar and a flex-1 main both fill the viewport.
  // `items-center` (our previous default) vertically centred them, leaving
  // a visible gap above + below the content equal to the height delta.
  // When the row carries an h-screen / h-full / min-h-screen utility,
  // default to items-stretch instead.
  const hasFullHeight = /\b(?:h-screen|h-full|min-h-screen|min-h-full)\b/.test(callerClassRaw);
  const defaultAlign = hasFullHeight ? "stretch" : "center";

  const className = [
    "flex flex-row",
    hasGap   ? "" : _gapClass(p.gap),
    p.wrap === false ? "" : "flex-wrap",
    hasItems ? "" : (ALIGN_CLASS[p.align ?? defaultAlign] ?? `items-${defaultAlign}`),
    hasJustify ? "" : (JUSTIFY_CLASS[p.justify ?? "start"] ?? "justify-start"),
    callerClassRaw,
  ].filter(Boolean).join(" ");
  const style: React.CSSProperties = {
    ...resolveStyle(node.style),
    ...slotProps.style,
    ...callerStyle,
  };
  return (
    <div data-node-id={node.id} className={className} style={style} data-motion={slotProps["data-motion"]} {...dataAttrProps(p)}>
      {children}
    </div>
  );
}
