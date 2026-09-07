/**
 * Geometry for the canvas grid guides. Pure — see grid-guides.test.ts.
 *
 * ZOOM: there is deliberately no scale factor anywhere in here. The canvas
 * frame scales with a CSS transform, so getBoundingClientRect() already returns
 * SCREEN pixels, and the guides are drawn as `position: fixed` boxes in that
 * same screen space — the identical convention AlignmentGuides / DropIndicator /
 * ReorderIndicator use. Anything computed in raw canvas px and then painted
 * fixed would be misplaced by exactly the zoom factor (at the 50% step the user
 * works at, every guide would land at twice its offset from the viewport
 * origin). The one thing that must NOT be scaled is the hairline itself: a 1px
 * fixed border stays 1px at every zoom step, which is what keeps a guide a
 * guide instead of a 0.5px smear or a 2px rule.
 */

/** The subset of DOMRect we use — plain numbers so tests need no DOM. */
export interface RectLike {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface GuideBox {
  key: string;
  left: number;
  top: number;
  width: number;
  height: number;
  /** Row-major address, for the data attribute a human reads in devtools. */
  row: number;
  col: number;
}

/**
 * One hairline box per cell, in screen coordinates.
 *
 * The -0.5 / +1 pair straddles the hairline across the true cell boundary
 * rather than drawing it one pixel inside — the same centring AlignmentGuides
 * does with its `position - 0.5`, and the reason a "flush" guide looks flush.
 *
 * Cells that measure zero in either axis are dropped. That is not a
 * micro-optimisation: an element that has not been laid out yet reports a
 * 0x0 rect at (0,0), and drawing it would park a stray marker in the top-left
 * corner of the viewport, far away from the grid it claims to describe.
 */
export function cellGuideBoxes(
  cellRects: ReadonlyArray<RectLike>,
  columns: number,
): GuideBox[] {
  const cols = Math.max(1, Math.trunc(columns));
  const out: GuideBox[] = [];
  cellRects.forEach((r, i) => {
    if (!(r.width > 0) || !(r.height > 0)) return;
    out.push({
      key: `${i}`,
      left: r.left - 0.5,
      top: r.top - 0.5,
      width: r.width + 1,
      height: r.height + 1,
      row: Math.floor(i / cols),
      col: i % cols,
    });
  });
  return out;
}
