import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SidebarPropsType } from "./Sidebar.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity } from "../../theme/tokens-context";

/**
 * Pinned-narrow + flex-main shell. Children are [sidebar, main]: children[0]
 * is the aside, everything after it is the main pane. At and above the
 * configured `breakpoint` the aside pins to the left at `width` with main
 * filling the rest; below it the two stack.
 *
 * The sidebar width is configurable per project so we keep it as an inline
 * media-query rule scoped to the rendered instance — Tailwind's `md:w-[60]`
 * arbitrary-value classes work but only when the literal string appears in
 * source code that the JIT scanner sees. A schema's runtime-supplied width
 * doesn't satisfy that, hence the inline approach.
 *
 * TWO CHANGES FROM THE AUDIT (docs/editor-audit/containment.md):
 *
 * 1. `breakpoint`. The stacking point used to be a hard-coded 768px with no
 *    prop, so a two-column layout the user arranged in the editor became a
 *    vertical stack on every phone and tablet and there was nothing they could
 *    do about it — Split exposed the same choice, Sidebar did not. `none`
 *    keeps the two columns at every width, which is the honest option for a
 *    layout that is meaningless stacked.
 *
 * 2. The 2-pane contract is now enforced HERE, not only in the editor.
 *    `slots.maxChildren: 2` is an editor rule; a JSON edit, an LLM patch or a
 *    projection could write three children and this component mapped each one
 *    into its own `[data-sidebar-pane]`, labelling children 2 AND 3 "main" and
 *    dropping the third into an implicit extra grid row — a 3-pane
 *    "two-pane" layout. Extra children now join the main pane, which is where
 *    their author meant them to be.
 */

// Wave 2: density-aware gap sizes (mobile / desktop).
// comfortable = today's hardcoded 1.5rem / 2rem.
const DENSITY_GAP: Record<"compact" | "comfortable" | "spacious", [string, string]> = {
  compact:     ["0.75rem", "1rem"],
  comfortable: ["1.5rem",  "2rem"],
  spacious:    ["2rem",    "3rem"],
};

// Same table as Split.tsx so the two containers agree on what "md" means.
const BP_MIN_PX: Record<"sm" | "md" | "lg", number> = { sm: 640, md: 768, lg: 1024 };

export interface SidebarProps extends SidebarPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function Sidebar({ width, breakpoint, style, children }: SidebarProps) {
  const density = useDensity();
  const id = React.useId().replace(/:/g, "-");
  const [gapMobile, gapDesktop] = DENSITY_GAP[density];
  const bp = breakpoint ?? "md";
  const kids = React.Children.toArray(children);
  const aside = kids[0] ?? null;
  const main = kids.slice(1);
  // `none` means "never stack": emit the two-column rule unconditionally so
  // there is no viewport at which the arrangement changes.
  // `${width} 1fr` GIVES THE ASIDE ITS FULL WIDTH EVEN WHEN THERE IS NO ROOM.
  // The media query below only knows the VIEWPORT, not the width of whatever
  // this Sidebar was dropped into. Dropped in a ~294px grid cell on a desktop
  // viewport it computed `239.993px 22.0114px` — a 22-pixel content pane, which
  // renders as a solid block with the main area invisible.
  // `min(width, 40%)` keeps the authored width whenever it fits (a 240px rail in
  // a 1150px page is still exactly 240px) and lets it shrink proportionally when
  // it does not, so the content pane can never be squeezed below 60%.
  const twoCol = `grid-template-columns: min(${width}, 40%) minmax(0, 1fr); gap: ${gapDesktop};`;
  return (
    <>
      <style>{`
        [data-sidebar-id="${id}"] {
          display: grid;
          ${bp === "none" ? twoCol : `grid-template-columns: 1fr; gap: ${gapMobile};`}
        }
        [data-sidebar-id="${id}"] > [data-sidebar-pane] {
          width: 100%;
          min-width: 0;
        }
        ${bp === "none" ? "" : `
        @media (min-width: ${BP_MIN_PX[bp as "sm" | "md" | "lg"] ?? 768}px) {
          [data-sidebar-id="${id}"] { ${twoCol} }
        }`}
      `}</style>
      <div
        data-sidebar-id={id}
        data-sidebar-breakpoint={bp}
        style={resolveStyle(style)}
        {...useMotion(style?.motion)}
      >
        <div data-sidebar-pane="aside">{aside}</div>
        <div data-sidebar-pane="main">{main}</div>
      </div>
    </>
  );
}
