"use client";
import type { AlignmentGuide } from "./alignment-guides";

/**
 * Draws the smart alignment guides for an in-flight resize.
 *
 * Same overlay convention as ReorderIndicator / DropIndicator: position:fixed
 * divs fed straight from getBoundingClientRect()-space numbers, pointer-events
 * none so they can never swallow the drag that is producing them. Fuchsia
 * rather than the blue of SelectionOverlay or the green of the drop/reorder
 * indicators, because a guide can be on screen at the same time as both of
 * those and a shared colour would read as one continuous thing.
 *
 * Purely presentational and fully controlled — it holds no state of its own, so
 * a guide cannot outlive the drag that produced it. The one and only way a
 * guide is on screen is that SelectionOverlay is currently passing it.
 */
export function AlignmentGuides({ guides }: { guides: AlignmentGuide[] }) {
  if (!guides.length) return null;
  return (
    <>
      {guides.map((g) => {
        const length = Math.max(1, g.end - g.start);
        // -0.5 centres the hairline on the true coordinate instead of drawing it
        // one pixel to the right/below, which is what makes "flush" look flush.
        return (
          <div
            key={`${g.axis}|${g.movingEdge}|${Math.round(g.position)}`}
            className="pointer-events-none fixed z-50 bg-fuchsia-500"
            style={
              g.axis === "v"
                ? { left: g.position - 0.5, top: g.start, width: 1, height: length }
                : { left: g.start, top: g.position - 0.5, width: length, height: 1 }
            }
            data-tentoro-alignment-guide={`${g.axis}:${g.source}:${g.movingEdge}`}
          />
        );
      })}
    </>
  );
}
