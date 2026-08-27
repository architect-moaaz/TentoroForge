import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SidebarPropsType } from "./Sidebar.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity } from "../../theme/tokens-context";

/**
 * Pinned-narrow + flex-main shell. Children must be exactly 2: [sidebar, main].
 * On mobile the sidebar stacks above the main pane; at md+ it pins to the
 * left at the configured `width` (px / rem / %) with main filling the rest.
 *
 * The sidebar width is configurable per project so we keep it as an inline
 * media-query rule scoped to the rendered instance — Tailwind's `md:w-[60]`
 * arbitrary-value classes work but only when the literal string appears in
 * source code that the JIT scanner sees. A schema's runtime-supplied width
 * doesn't satisfy that, hence the inline approach.
 *
 * Wave 2: density token drives the gap values inside the <style> block.
 * comfortable = 1.5rem (mobile) / 2rem (desktop) matches today's defaults exactly.
 */

// Wave 2: density-aware gap sizes (mobile / desktop).
// comfortable = today's hardcoded 1.5rem / 2rem.
const DENSITY_GAP: Record<"compact" | "comfortable" | "spacious", [string, string]> = {
  compact:     ["0.75rem", "1rem"],
  comfortable: ["1.5rem",  "2rem"],
  spacious:    ["2rem",    "3rem"],
};

export interface SidebarProps extends SidebarPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function Sidebar({ width, style, children }: SidebarProps) {
  const density = useDensity();
  const id = React.useId().replace(/:/g, "-");
  const [gapMobile, gapDesktop] = DENSITY_GAP[density];
  return (
    <>
      <style>{`
        [data-sidebar-id="${id}"] {
          display: grid;
          grid-template-columns: 1fr;
          gap: ${gapMobile};
        }
        [data-sidebar-id="${id}"] > [data-sidebar-pane] {
          width: 100%;
        }
        @media (min-width: 768px) {
          [data-sidebar-id="${id}"] {
            grid-template-columns: ${width} 1fr;
            gap: ${gapDesktop};
          }
        }
      `}</style>
      <div
        data-sidebar-id={id}
        style={resolveStyle(style)}
        {...useMotion(style?.motion)}
      >
        {React.Children.map(children, (child, i) => (
          <div data-sidebar-pane={i === 0 ? "aside" : "main"}>{child}</div>
        ))}
      </div>
    </>
  );
}
