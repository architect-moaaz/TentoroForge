import type { ReactNode } from "react";
import { resolveStyle, tokenToCssVar } from "../../runtime/tokens";
import { applyStyleSlot, dataAttrProps } from "../../runtime/style-slot";

/**
 * Stack — vertical flex container by default. Horizontal mode is responsive:
 * stacks on mobile (< md) and lays out as a row at md+ so schema-driven
 * pages adapt to the viewport instead of overflowing on phones.
 *
 * Token-based gap keeps the design-system spacing scale; align / justify /
 * wrap are mapped to Tailwind utilities so the className-based layout wins
 * over inline styles for breakpoint-conditional behaviour.
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

// Map gap tokens / shorthand keywords to a real Tailwind `gap-N` utility.
// Replaces the older inline `style={{ gap: var(--…) }}` pattern which
// silently collapsed to 0 when the synthesised token variable didn't
// resolve at runtime (e.g. `tokens.spacing.4` → `--token-tokens-spacing-4`,
// which no CSS variable defined). With this mapping the gap is always a
// real Tailwind utility class — it appears in the compiled CSS and never
// depends on an undefined runtime variable. Same logic lives in Grid.tsx.
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
  // Semantic spacing scale (what page agents actually emit). Without these every
  // semantic token fell through to the gap-4 default, so a tight element gap and a
  // large section gap rendered identically. Map them to a real visual hierarchy.
  "tokens.spacing.semantic.input": "gap-3",
  "tokens.spacing.semantic.element": "gap-4",
  "tokens.spacing.semantic.card": "gap-5",
  "tokens.spacing.semantic.section": "gap-8",
  "tokens.spacing.semantic.page": "gap-8",
};
function _gapClass(gap: unknown): string {
  if (typeof gap !== "string" || !gap) return "gap-4";
  return GAP_CLASS[gap] ?? "gap-4";
}

export function Stack({ node, children }: { node: any; children: ReactNode[] }) {
  const p = node.props ?? {};
  const slotProps = applyStyleSlot(node.style);
  const horizontal = p.direction === "horizontal";
  // MCP pipeline emits per-node className + style derived from Figma Dev Mode output.
  const callerClassRaw = typeof p.className === "string" ? p.className : "";
  const callerStyle = p.style && typeof p.style === "object" ? p.style as React.CSSProperties : {};

  // Suppress base defaults when the caller's className already supplies that
  // utility — Tailwind orders compiled CSS alphabetically, so a default
  // `justify-start` beats a caller's `justify-between` regardless of class-
  // string order. Same for `items-*` and `gap-*`.
  const hasItems   = /\bitems-(start|center|end|stretch|baseline)\b/.test(callerClassRaw);
  const hasJustify = /\bjustify-(start|center|end|between|around|evenly)\b/.test(callerClassRaw);
  const hasGap     = /\bgap-/.test(callerClassRaw);
  // A CLASS THAT DECLARES `flex` IS A DRAWN ROW. A page composed from a design
  // frame arrives with the row's own layout — direction, gap or none, and
  // whether it wraps, decided by the transform from what was drawn. The
  // defaults below exist for authored layouts that state nothing; laid on top
  // of a drawn row they put a 12px gap the design never had between a KPI's
  // label and its number, and wrapped the icon beside a title under it.
  const drawn = /\bflex\b/.test(callerClassRaw);

  const className = [
    "flex",
    horizontal ? "flex-col md:flex-row" : "flex-col",
    hasGap || drawn ? "" : _gapClass(p.gap),
    hasItems ? "" : (ALIGN_CLASS[p.align ?? "stretch"] ?? "items-stretch"),
    hasJustify ? "" : (JUSTIFY_CLASS[p.justify ?? "start"] ?? "justify-start"),
    p.wrap ? "flex-wrap" : "",
    callerClassRaw,
  ].filter(Boolean).join(" ");
  const style: React.CSSProperties = {
    ...resolveStyle(node.style),
    ...slotProps.style,
    ...callerStyle,
  };
  // shellRole — page-shell heuristic marks the sidebar / backdrop with this
  // prop. We emit it as a data-attribute so the ShellStateProvider's CSS
  // selectors (`[data-sidebar-open="true"] [data-shell-sidebar]`) and its
  // delegated click handler (`[data-sidebar-backdrop]`) can hook in without
  // every component knowing about the shell state.
  const shellRoleAttr = (p.shellRole === "sidebar") ? "" : undefined;
  const backdropAttr = (p.shellRole === "backdrop") ? "" : undefined;
  return (
    <div
      data-node-id={node.id}
      className={className}
      style={style}
      data-motion={slotProps["data-motion"]}
      data-shell-sidebar={shellRoleAttr}
      data-sidebar-backdrop={backdropAttr}
      {...dataAttrProps(p)}
    >
      {children}
    </div>
  );
}
