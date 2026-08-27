import * as React from "react";
import type { StyleSlotT } from "@tentoroforge/schema";
import type { SplitPropsType } from "./Split.schema";
import { resolveStyle } from "../../style/resolveStyle";
import { useMotion } from "../../style/useMotion";
import { useDensity } from "../../theme/tokens-context";

/**
 * Two-column responsive split. On mobile the panes stack vertically; at the
 * configured breakpoint (default md) they split horizontally with the
 * requested ratio. Children must be exactly 2 (schema-enforced).
 *
 * Tailwind doesn't have a built-in arbitrary `grid-cols-[1fr_2fr]` at
 * breakpoints with a generated stylesheet (the JIT scans for literal class
 * names), so we use inline grid-template-columns at the responsive
 * breakpoint via inline style + a media query. Falls back to a plain
 * 2-column equal split if the ratio is unknown.
 *
 * Wave 2: density token drives the default gap when no explicit gap is needed.
 * comfortable = gap-6 matches today's hardcoded default.
 */
const TEMPLATE: Record<string, string> = {
  "1:1": "1fr 1fr",
  "1:2": "1fr 2fr",
  "2:1": "2fr 1fr",
  "1:3": "1fr 3fr",
  "3:1": "3fr 1fr",
};

const BP_MIN_PX: Record<"sm" | "md" | "lg", number> = { sm: 640, md: 768, lg: 1024 };

// Wave 2: density-aware gap. comfortable = gap-6 = today's hardcoded default.
const DENSITY_GAP: Record<"compact" | "comfortable" | "spacious", string> = {
  compact:     "gap-2",
  comfortable: "gap-6",
  spacious:    "gap-8",
};

export interface SplitProps extends SplitPropsType {
  style?: StyleSlotT;
  children?: React.ReactNode;
}

export function Split({ ratio, breakpoint, style, children }: SplitProps) {
  const density = useDensity();
  const bp = (breakpoint ?? "md") as "sm" | "md" | "lg";
  const template = TEMPLATE[ratio] ?? "1fr 1fr";
  // Stable id so the inline @media rule is scoped to this instance.
  const id = React.useId().replace(/:/g, "-");
  const gapClass = DENSITY_GAP[density];
  return (
    <>
      <style>{`
        /* min-width:0 on the grid AND its children — otherwise a wide child
           (a filename H1, a PDF preview, a Card with an object embed) blows
           past its track and forces the whole page horizontal. This is the
           classic CSS-grid overflow trap; the min-width:auto default lets
           children establish an intrinsic minimum equal to their content. */
        [data-split-id="${id}"] { grid-template-columns: 1fr; min-width: 0; }
        [data-split-id="${id}"] > * { min-width: 0; }
        @media (min-width: ${BP_MIN_PX[bp]}px) {
          [data-split-id="${id}"] { grid-template-columns: ${template}; }
        }
      `}</style>
      <div
        data-split-id={id}
        data-split-ratio={ratio}
        data-split-breakpoint={bp}
        className={`grid ${gapClass} w-full`}
        style={resolveStyle(style)}
        {...useMotion(style?.motion)}
      >
        {children}
      </div>
    </>
  );
}
