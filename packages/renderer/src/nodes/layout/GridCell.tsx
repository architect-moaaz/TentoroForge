import type { ReactNode } from "react";
import * as React from "react";
import { resolveStyle } from "../../runtime/tokens";
import { applyStyleSlot, dataAttrProps } from "../../runtime/style-slot";

/**
 * GridCell — one addressable box of a fixed R×C <Grid>.
 *
 * Why this exists as a REAL node rather than an editor fiction: <Grid> renders
 * `{children}` straight into the CSS grid, so an empty Grid has zero children
 * and therefore zero drop targets — there is nothing on the canvas to drop
 * "into cell 4" of. The alternative (leave the schema cell-less and place
 * children with `grid-column` / `grid-row`) is exactly the inline-style trap
 * Grid.tsx documents: an explicit `grid-column: 3` outlives every media query,
 * so a node pinned to column 3 stays in column 3 at 375px where the grid is
 * one column wide. Real children carry no position at all — they flow, and the
 * responsive ladder keeps deciding how many columns that flow wraps at.
 *
 * The rendered box is deliberately inert: no border, no background, no
 * padding, no radius. The cell boundaries the user designs against are drawn
 * by the EDITOR overlay (frontend/src/components/canvas/GridGuides.tsx) and
 * never ship — a cell that painted its own border would put a visible grid of
 * hairlines in the generated application.
 *
 * The two classes it does carry both earn their place:
 *  - `min-w-0`: a grid item defaults to `min-width: auto`, which is the
 *    intrinsic width of its content. A long unbroken string (a URL, a table)
 *    inside a cell would then force its track wider than 1fr and blow the whole
 *    row past the container. `min-w-0` is the standard fix and is invisible
 *    otherwise.
 *  - `flex flex-col gap-2`: a cell is a container the user drops several things
 *    into ("inside each box I should be able to add anything"). Without a gap
 *    two stacked children touch; gap-2 is the smallest spacing that reads as
 *    deliberate, and it is inert for the one-child case that dominates.
 */
export function GridCell({ node, children }: { node: any; children: ReactNode[] }) {
  const p = node.props ?? {};
  const slotProps = applyStyleSlot(node.style);
  const callerClass = typeof p.className === "string" ? ` ${p.className}` : "";
  const callerStyle = p.style && typeof p.style === "object" ? p.style as React.CSSProperties : {};

  return (
    <div
      data-node-id={node.id}
      // Structural marker, same idea as Sidebar's `data-sidebar-pane`. The
      // editor's canvas stylesheet and the guide overlay both key off it, and
      // it is inert in the generated app (an attribute selector nothing in the
      // shipped CSS matches).
      data-grid-cell=""
      className={`flex flex-col gap-2 min-w-0${callerClass}`}
      style={{
        ...resolveStyle(node.style),
        ...slotProps.style,
        ...callerStyle,
      }}
      data-motion={slotProps["data-motion"]}
      {...dataAttrProps(p)}
    >
      {children}
    </div>
  );
}
