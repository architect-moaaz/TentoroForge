import type { ReactNode } from "react";
import * as React from "react";
import { resolveStyle, tokenToCssVar } from "../../runtime/tokens";
import { applyStyleSlot, dataAttrProps } from "../../runtime/style-slot";

/**
 * Grid — N-column responsive grid. The schema's `columns` value is the
 * desktop layout; on smaller viewports the grid steps down through
 * sensible breakpoints so cards don't get squashed:
 *
 *   columns=2 → 1 col phone | 2 cols md+
 *   columns=3 → 1 col phone | 2 cols sm | 3 cols lg+
 *   columns=4 → 1 col phone | 2 cols sm | 4 cols lg+
 *   columns=6 → 2 cols phone | 3 cols sm | 6 cols lg+
 *
 * Token-based gap and slot-style still flow through inline styles.
 */
function gridColsClass(columns: number): string {
  // Tailwind's `grid-cols-N` only goes up to 12 by default. We clamp at 12
  // because no realistic schema asks for more.
  const n = Math.max(1, Math.min(12, Math.trunc(columns)));
  if (n <= 1) return "grid-cols-1";
  if (n === 2) return "grid-cols-1 md:grid-cols-2";
  if (n === 3) return "grid-cols-1 sm:grid-cols-2 lg:grid-cols-3";
  if (n === 4) return "grid-cols-1 sm:grid-cols-2 lg:grid-cols-4";
  if (n === 5) return "grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5";
  if (n <= 6) return "grid-cols-2 sm:grid-cols-3 lg:grid-cols-6";
  // 7+ → split as evenly as we can across breakpoints.
  const md = Math.ceil(n / 2);
  return `grid-cols-2 sm:grid-cols-3 md:grid-cols-${md} lg:grid-cols-${n}`;
}

// Map common gap tokens / shorthand keywords to a real Tailwind `gap-N`
// utility class. This replaces the older inline `style={{ gap: var(--...) }}`
// pattern which silently collapsed to 0 when the synthesised token name
// didn't exist (e.g. `tokens.spacing.4` mapped to a malformed
// `--token-tokens-spacing-4` that no CSS variable defined). With this
// mapping the gap is always a Tailwind utility class — so it appears in
// the compiled CSS and never depends on an undefined runtime variable.
const GAP_CLASS: Record<string, string> = {
  none: "gap-0",
  xs: "gap-1",
  sm: "gap-2",
  md: "gap-4",
  lg: "gap-6",
  xl: "gap-8",
  "2xl": "gap-10",
  // Common LLM-emitted token paths — all map to a sane Tailwind utility.
  "tokens.spacing.1": "gap-1",
  "tokens.spacing.2": "gap-2",
  "tokens.spacing.3": "gap-3",
  "tokens.spacing.4": "gap-4",
  "tokens.spacing.5": "gap-5",
  "tokens.spacing.6": "gap-6",
  "tokens.spacing.8": "gap-8",
  "tokens.spacing.10": "gap-10",
  "tokens.spacing.12": "gap-12",
  // Semantic spacing scale — same mapping as Stack.tsx so grids and stacks agree.
  "tokens.spacing.semantic.input": "gap-3",
  "tokens.spacing.semantic.element": "gap-4",
  "tokens.spacing.semantic.card": "gap-5",
  "tokens.spacing.semantic.section": "gap-8",
  "tokens.spacing.semantic.page": "gap-8",
};

function gapClass(gap: unknown): string {
  if (typeof gap !== "string" || !gap) return "gap-4";  // sensible default
  return GAP_CLASS[gap] ?? "gap-4";
}

export function Grid({ node, children }: { node: any; children: ReactNode[] }) {
  const p = node.props ?? {};
  const slotProps = applyStyleSlot(node.style);
  const columns = typeof p.columns === "number" ? p.columns : 1;

  // equalRows — `grid-auto-rows: 1fr` so mixed-content rows render equal
  // height (fixes the "uneven KPI tiles" look reviewers flagged). A row rule
  // is viewport-independent, so an inline style is safe here.
  //
  // equalCols deliberately emits NOTHING. It used to set an inline
  // `grid-template-columns: repeat(N, minmax(0, 1fr))`, and because an inline
  // style beats every media query, `lg:grid-cols-3` could never apply — a
  // 3-column row stayed 3 columns at 375px, ~100px per column, headings
  // wrapping one letter per line. The whole responsive ladder above was dead.
  //
  // It also bought nothing. Tailwind's `grid-cols-N` is *defined* as
  // `repeat(N, minmax(0, 1fr))` — the exact rule equalCols wanted, already
  // applied at every breakpoint. So the prop's intent (children can't grow
  // their column past its equal share) is satisfied by the classes alone,
  // and it is kept as an accepted no-op so existing schemas stay valid.
  const equalRows = p.equalRows === true;
  const extraStyle: React.CSSProperties = {};
  if (equalRows) extraStyle.gridAutoRows = "1fr";

  // `rows` — the FIXED row count the user picked in the visual editor. A grid
  // with rows > 0 holds exactly rows × columns <GridCell> children, in row-major
  // order; a grid without it (every schema written before this prop existed)
  // keeps the original behaviour where rows are implicit and children just wrap.
  //
  // It deliberately emits NO css here — no `grid-template-rows`, and above all
  // no `grid-template-columns`. That is the same trap equalCols fell into: an
  // inline template beats every media query, so pinning the desktop column count
  // would kill the responsive ladder and put a 3-column row at ~100px per column
  // on a phone. The user's decision is "fixed in the editor, responsive in the
  // app", and the way to honour both is to publish the COUNT as an inert data
  // attribute and let the editor's own stylesheet (frontend/src/app/globals.css,
  // scoped to `[data-canvas-root]`) turn it into a fixed template. Nothing in the
  // shipped CSS matches these selectors, so in the generated application the
  // ladder above remains the only thing that decides the column count.
  const fixedRows =
    typeof p.rows === "number" && p.rows > 0 ? Math.min(12, Math.trunc(p.rows)) : 0;
  const fixedCols = Math.max(1, Math.min(12, Math.trunc(columns)));

  // MCP pipeline emits per-node className + style derived from Figma Dev Mode output.
  const callerClass = typeof p.className === "string" ? ` ${p.className}` : "";
  const callerStyle = p.style && typeof p.style === "object" ? p.style as React.CSSProperties : {};

  return (
    <div
      data-node-id={node.id}
      className={`grid ${gridColsClass(columns)} ${gapClass(p.gap)}${callerClass}`}
      style={{
        ...resolveStyle(node.style),
        ...slotProps.style,
        ...extraStyle,
        ...callerStyle,
      }}
      data-motion={slotProps["data-motion"]}
      data-grid-rows={fixedRows > 0 ? fixedRows : undefined}
      data-grid-columns={fixedRows > 0 ? fixedCols : undefined}
      {...dataAttrProps(p)}
    >
      {children}
    </div>
  );
}
