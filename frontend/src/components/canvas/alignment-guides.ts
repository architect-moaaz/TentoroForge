/**
 * Pure geometry behind the Canva/Figma-style smart alignment guides.
 *
 * Deliberately free of React and of the DOM: every input is a plain rect, so
 * "which guides fire for this configuration" is unit-testable without a canvas,
 * a layout engine or a synthetic pointer. SelectionOverlay does the measuring
 * and the drawing; this module only decides.
 *
 * COORDINATE SPACE: everything here is SCREEN px — exactly what
 * getBoundingClientRect() returns, which is what CanvasFrame's
 * `transform: scale(zoom)` has already been applied to, and what the overlay's
 * position:fixed divs consume. There is no second coordinate convention in this
 * file. The one thing the caller must convert is the tolerance, which is
 * authored in canvas px — see SNAP_TOLERANCE_CANVAS_PX.
 */

/** Minimal rect shape. DOMRect satisfies it, so callers can pass one directly. */
export interface GuideRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** "v" = a vertical line (constant x); "h" = a horizontal line (constant y). */
export type GuideAxis = "v" | "h";

/** Which feature of the MOVING rect the guide is about. */
export type MovingEdge = "left" | "centerX" | "right" | "top" | "centerY" | "bottom";

export interface AlignmentGuide {
  axis: GuideAxis;
  /** Screen coord of the line: x when axis === "v", y when axis === "h". */
  position: number;
  /** Extent of the drawn line along the OTHER axis (screen coords). */
  start: number;
  end: number;
  movingEdge: MovingEdge;
  /** "parent" = centred within the parent; "sibling" = flush with a sibling. */
  source: "parent" | "sibling";
  /**
   * Signed screen px the moving rect's `movingEdge` must travel to sit exactly
   * on the line. Snapping consumes this; pure display ignores it.
   */
  delta: number;
  /** Which sibling produced the guide. Absent for parent-centre guides. */
  siblingId?: string;
}

/**
 * How close (in UNSCALED canvas px) an edge must come before its guide appears.
 *
 * 4px matches the Figma/Canva figure. Authoring it in canvas px rather than
 * screen px is the load-bearing part: the editor has a zoom control and is
 * routinely driven at 50%, where a screen-px tolerance would silently become
 * 8 canvas px of slop — wide enough that two visibly-unaligned edges would both
 * claim to be flush, which is the exact opposite of what a guide is for.
 * Callers multiply by the live zoom to get a screen-px tolerance.
 */
export const SNAP_TOLERANCE_CANVAS_PX = 4;

function xFeatures(r: GuideRect): Array<{ edge: MovingEdge; at: number }> {
  return [
    { edge: "left", at: r.left },
    { edge: "centerX", at: r.left + r.width / 2 },
    { edge: "right", at: r.left + r.width },
  ];
}

function yFeatures(r: GuideRect): Array<{ edge: MovingEdge; at: number }> {
  return [
    { edge: "top", at: r.top },
    { edge: "centerY", at: r.top + r.height / 2 },
    { edge: "bottom", at: r.top + r.height },
  ];
}

/**
 * Guides a resize can actually satisfy.
 *
 * The canvas lays nodes out in normal flow and the resize handles only write
 * width/height — the left/top edges are pinned by the flow, so a "your left
 * edge lines up with theirs" guide is information, never something the drag can
 * move the node onto. Snapping is therefore restricted to the edges that a size
 * change genuinely relocates.
 */
export const RESIZABLE_EDGES: readonly MovingEdge[] = ["centerX", "right", "centerY", "bottom"];

/**
 * Which alignment guides fire for a node at `moving`, given its parent box and
 * its siblings' boxes.
 *
 * Emits:
 *  - the parent's horizontal and vertical centre axes (the "this is centred"
 *    feedback), drawn across the parent's full extent;
 *  - every sibling left/centre/right and top/centre/bottom coincidence, drawn
 *    only across the union of the two boxes involved so the line reads as
 *    "these two things", not "the whole page".
 *
 * Results are deduped on (axis, movingEdge, rounded position) with their spans
 * unioned, so ten siblings sharing a left edge produce one long line rather
 * than ten stacked 1px divs. Deliberately NOT deduped across differing
 * movingEdge values even at the same coordinate: those carry different `delta`s
 * and collapsing them would throw away a legitimate snap candidate, while the
 * visual cost is two identical overlapping hairlines.
 */
export function computeAlignmentGuides(input: {
  moving: GuideRect;
  parent: GuideRect | null;
  siblings: Array<{ id: string; rect: GuideRect }>;
  /** Screen px. Convert from SNAP_TOLERANCE_CANVAS_PX by multiplying by zoom. */
  tolerance: number;
}): AlignmentGuide[] {
  const { moving, parent, siblings, tolerance } = input;
  if (!(tolerance >= 0)) return [];

  const out = new Map<string, AlignmentGuide>();

  const add = (g: AlignmentGuide) => {
    const key = `${g.axis}|${g.movingEdge}|${Math.round(g.position)}`;
    const existing = out.get(key);
    if (!existing) {
      out.set(key, g);
      return;
    }
    // Same line, another reference box: stretch it to cover both. Parent-sourced
    // guides are inserted first and keep their identity on collision — a
    // centred-in-parent readout outranks an incidental sibling coincidence.
    existing.start = Math.min(existing.start, g.start);
    existing.end = Math.max(existing.end, g.end);
  };

  const mx = xFeatures(moving);
  const my = yFeatures(moving);
  const mTop = moving.top;
  const mBottom = moving.top + moving.height;
  const mLeft = moving.left;
  const mRight = moving.left + moving.width;

  // --- parent centres -------------------------------------------------------
  if (parent) {
    const pcx = parent.left + parent.width / 2;
    const pcy = parent.top + parent.height / 2;
    const mcx = moving.left + moving.width / 2;
    const mcy = moving.top + moving.height / 2;
    if (Math.abs(pcx - mcx) <= tolerance) {
      add({
        axis: "v",
        position: pcx,
        start: Math.min(parent.top, mTop),
        end: Math.max(parent.top + parent.height, mBottom),
        movingEdge: "centerX",
        source: "parent",
        delta: pcx - mcx,
      });
    }
    if (Math.abs(pcy - mcy) <= tolerance) {
      add({
        axis: "h",
        position: pcy,
        start: Math.min(parent.left, mLeft),
        end: Math.max(parent.left + parent.width, mRight),
        movingEdge: "centerY",
        source: "parent",
        delta: pcy - mcy,
      });
    }
  }

  // --- sibling edges + centres ---------------------------------------------
  for (const sib of siblings) {
    const s = sib.rect;
    const sTop = s.top;
    const sBottom = s.top + s.height;
    const sLeft = s.left;
    const sRight = s.left + s.width;

    for (const m of mx) {
      for (const o of xFeatures(s)) {
        if (Math.abs(o.at - m.at) > tolerance) continue;
        add({
          axis: "v",
          position: o.at,
          start: Math.min(mTop, sTop),
          end: Math.max(mBottom, sBottom),
          movingEdge: m.edge,
          source: "sibling",
          delta: o.at - m.at,
          siblingId: sib.id,
        });
      }
    }
    for (const m of my) {
      for (const o of yFeatures(s)) {
        if (Math.abs(o.at - m.at) > tolerance) continue;
        add({
          axis: "h",
          position: o.at,
          start: Math.min(mLeft, sLeft),
          end: Math.max(mRight, sRight),
          movingEdge: m.edge,
          source: "sibling",
          delta: o.at - m.at,
          siblingId: sib.id,
        });
      }
    }
  }

  // Stable order so snapshots/tests don't depend on Map insertion order.
  return [...out.values()].sort(
    (a, b) =>
      a.axis.localeCompare(b.axis) ||
      a.position - b.position ||
      a.movingEdge.localeCompare(b.movingEdge),
  );
}

/**
 * The guide a resize should snap to on one axis, or null.
 *
 * Picks the nearest satisfiable guide (see RESIZABLE_EDGES), preferring a
 * parent-centre guide over a sibling one when both are equally close — landing
 * dead-centre in the container is the stronger intent.
 */
export function pickSnap(
  guides: AlignmentGuide[],
  axis: GuideAxis,
): AlignmentGuide | null {
  let best: AlignmentGuide | null = null;
  for (const g of guides) {
    if (g.axis !== axis) continue;
    if (!RESIZABLE_EDGES.includes(g.movingEdge)) continue;
    if (!best) {
      best = g;
      continue;
    }
    const d = Math.abs(g.delta);
    const bd = Math.abs(best.delta);
    if (d < bd || (d === bd && g.source === "parent" && best.source !== "parent")) {
      best = g;
    }
  }
  return best;
}

/**
 * Screen-px growth of the moving rect's width/height needed to honour `guide`.
 *
 * A resize pins the left/top edge (normal flow) and moves the far edge, so:
 *  - a right/bottom guide is satisfied by moving that edge exactly `delta`;
 *  - a centre guide is satisfied by moving the far edge `2 * delta`, because a
 *    box pinned on one side only shifts its centre by half of what it grows.
 * Any other edge is unreachable by a resize and yields 0.
 */
export function snapSizeDelta(guide: AlignmentGuide): number {
  switch (guide.movingEdge) {
    case "right":
    case "bottom":
      return guide.delta;
    case "centerX":
    case "centerY":
      return guide.delta * 2;
    default:
      return 0;
  }
}
