"use client";
import * as React from "react";
import { useEditorStore } from "@/lib/editor-store";
import { cellGuideBoxes, type GuideBox, type RectLike } from "./grid-guides";

/**
 * GridGuides — the thin lines that make a fixed R x C <Grid> visible on the
 * canvas.
 *
 * These are an EDITOR AFFORDANCE and nothing else. They are drawn here, over
 * the canvas, and never by <GridCell> itself, because the user's second
 * decision was explicit: no visible cell borders in the generated application.
 * A cell that painted its own hairline would ship one. Rendering them in an
 * overlay makes that structurally impossible rather than merely intended — this
 * file is not part of any package the scaffold builds.
 *
 * Same overlay convention as AlignmentGuides / DropIndicator: position:fixed
 * boxes fed straight from getBoundingClientRect(), pointer-events-none so they
 * can never swallow the drop they exist to guide. Neutral slate rather than the
 * blue of SelectionOverlay, the green of the drop indicator or the fuchsia of
 * the alignment guides — a guide that is on screen the whole time has to recede
 * behind all three of those, and a shared colour would read as one of them.
 */
export function GridGuides({
  canvasRef,
}: {
  canvasRef: React.RefObject<HTMLElement | null>;
}) {
  const [boxes, setBoxes] = React.useState<GuideBox[]>([]);
  // Any dispatch replaces the artifacts object, so this is the cheap "the tree
  // changed shape" signal — a new row, a deleted cell, a different column count.
  const artifacts = useEditorStore((s) => s.artifacts);

  React.useEffect(() => {
    const host = canvasRef.current;
    if (!host) {
      setBoxes([]);
      return;
    }

    const measure = () => {
      const next: GuideBox[] = [];
      // `[data-grid-rows]` is emitted by Grid.tsx only when the user has chosen
      // a fixed row count, so legacy auto-flow grids draw nothing and keep
      // looking exactly as they do today.
      host.querySelectorAll<HTMLElement>("[data-grid-rows]").forEach((grid) => {
        const cells = Array.from(
          grid.querySelectorAll<HTMLElement>(":scope > [data-grid-cell]"),
        );
        if (!cells.length) return;
        const cols = Number(grid.getAttribute("data-grid-columns")) || 1;
        const rects: RectLike[] = cells.map((c) => c.getBoundingClientRect());
        const gridId = grid.getAttribute("data-node-id") ?? "grid";
        for (const b of cellGuideBoxes(rects, cols)) {
          next.push({ ...b, key: `${gridId}:${b.key}` });
        }
      });
      setBoxes(next);
    };

    // Coalesce every trigger to one measure per frame. Scroll fires far faster
    // than the compositor paints and each raw event costs a forced layout per
    // cell — the same reason SelectionOverlay batches its own re-measure.
    let frame = 0;
    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        measure();
      });
    };
    measure();

    const ro = new ResizeObserver(schedule);
    // Observing the canvas root rather than each grid catches the cases that
    // move a grid without resizing it — a sibling growing above it, a zoom
    // step, a device-frame switch.
    ro.observe(host);
    host.querySelectorAll<HTMLElement>("[data-grid-rows]").forEach((g) => ro.observe(g));

    window.addEventListener("scroll", schedule, true);
    window.addEventListener("resize", schedule);
    return () => {
      if (frame) cancelAnimationFrame(frame);
      ro.disconnect();
      window.removeEventListener("scroll", schedule, true);
      window.removeEventListener("resize", schedule);
    };
  }, [canvasRef, artifacts]);

  if (!boxes.length) return null;
  return (
    <>
      {boxes.map((b) => (
        <div
          key={b.key}
          className="pointer-events-none fixed z-30 rounded-[2px]"
          style={{
            left: b.left,
            top: b.top,
            width: b.width,
            height: b.height,
            // Written inline rather than as Tailwind classes so the exact
            // hairline is not at the mercy of the utility layer's border-colour
            // reset (`* { @apply border-border }` in globals.css @layer base).
            border: "1px dashed rgba(100, 116, 139, 0.45)",
          }}
          data-tentoro-grid-guide={`${b.row},${b.col}`}
        />
      ))}
    </>
  );
}
