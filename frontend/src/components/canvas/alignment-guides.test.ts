import { describe, it, expect } from "vitest";
import {
  computeAlignmentGuides,
  pickSnap,
  snapSizeDelta,
  SNAP_TOLERANCE_CANVAS_PX,
  type AlignmentGuide,
  type GuideRect,
} from "./alignment-guides";

const rect = (left: number, top: number, width: number, height: number): GuideRect => ({
  left,
  top,
  width,
  height,
});

/** Parent is 400x400 at the origin, so its centres are x=200 / y=200. */
const PARENT = rect(0, 0, 400, 400);

const kinds = (gs: AlignmentGuide[]) =>
  gs.map((g) => `${g.axis}:${g.source}:${g.movingEdge}@${Math.round(g.position)}`).sort();

describe("computeAlignmentGuides — parent centres", () => {
  it("fires the vertical centre guide when the moving box is horizontally centred", () => {
    // 100 wide at x=150 → centre 200 === parent centre.
    const gs = computeAlignmentGuides({
      moving: rect(150, 10, 100, 40),
      parent: PARENT,
      siblings: [],
      tolerance: 4,
    });
    expect(kinds(gs)).toEqual(["v:parent:centerX@200"]);
    expect(gs[0].delta).toBe(0);
  });

  it("fires within tolerance and reports the delta needed to align exactly", () => {
    // centre 197 → 3px short of the parent centre, inside a 4px tolerance.
    const gs = computeAlignmentGuides({
      moving: rect(147, 10, 100, 40),
      parent: PARENT,
      siblings: [],
      tolerance: 4,
    });
    expect(kinds(gs)).toEqual(["v:parent:centerX@200"]);
    expect(gs[0].delta).toBe(3);
  });

  it("does not fire outside tolerance", () => {
    // centre 195 → 5px off, outside a 4px tolerance.
    const gs = computeAlignmentGuides({
      moving: rect(145, 10, 100, 40),
      parent: PARENT,
      siblings: [],
      tolerance: 4,
    });
    expect(gs).toEqual([]);
  });

  it("fires both centre axes when the box is dead centre", () => {
    const gs = computeAlignmentGuides({
      moving: rect(150, 180, 100, 40),
      parent: PARENT,
      siblings: [],
      tolerance: 4,
    });
    expect(kinds(gs)).toEqual(["h:parent:centerY@200", "v:parent:centerX@200"]);
  });

  it("draws the parent-centre guide across the whole parent, not just the node", () => {
    const gs = computeAlignmentGuides({
      moving: rect(150, 10, 100, 40),
      parent: PARENT,
      siblings: [],
      tolerance: 4,
    });
    expect(gs[0].start).toBe(0);
    expect(gs[0].end).toBe(400);
  });

  it("emits nothing when there is no parent and no sibling", () => {
    expect(
      computeAlignmentGuides({ moving: rect(0, 0, 10, 10), parent: null, siblings: [], tolerance: 4 }),
    ).toEqual([]);
  });
});

describe("computeAlignmentGuides — sibling edges and centres", () => {
  it("fires a left-edge guide when two left edges are flush", () => {
    const gs = computeAlignmentGuides({
      moving: rect(50, 200, 80, 30),
      parent: null,
      siblings: [{ id: "sib", rect: rect(50, 20, 120, 30) }],
      tolerance: 4,
    });
    expect(kinds(gs)).toContain("v:sibling:left@50");
    expect(gs.find((g) => g.movingEdge === "left")!.siblingId).toBe("sib");
  });

  it("fires a right-edge guide, and reports the delta as the growth required", () => {
    // moving right edge = 128; sibling right edge = 130 → 2px inside tolerance.
    const gs = computeAlignmentGuides({
      moving: rect(50, 200, 78, 30),
      parent: null,
      siblings: [{ id: "sib", rect: rect(50, 20, 80, 30) }],
      tolerance: 4,
    });
    const right = gs.find((g) => g.movingEdge === "right")!;
    expect(right.position).toBe(130);
    expect(right.delta).toBe(2);
  });

  it("matches a moving LEFT edge against a sibling RIGHT edge (flush abutment)", () => {
    // moving left = 130, sibling right = 130.
    const gs = computeAlignmentGuides({
      moving: rect(130, 200, 40, 30),
      parent: null,
      siblings: [{ id: "sib", rect: rect(50, 20, 80, 30) }],
      tolerance: 4,
    });
    expect(kinds(gs)).toContain("v:sibling:left@130");
  });

  it("fires horizontal top/bottom/centre guides for a side-by-side sibling", () => {
    // Identical vertical geometry → top, centreY and bottom all coincide.
    const gs = computeAlignmentGuides({
      moving: rect(200, 20, 40, 60),
      parent: null,
      siblings: [{ id: "sib", rect: rect(0, 20, 40, 60) }],
      tolerance: 4,
    });
    expect(kinds(gs)).toEqual([
      "h:sibling:bottom@80",
      "h:sibling:centerY@50",
      "h:sibling:top@20",
    ]);
  });

  it("spans a sibling guide across the union of the two boxes only", () => {
    const gs = computeAlignmentGuides({
      moving: rect(50, 200, 80, 30),
      parent: PARENT,
      siblings: [{ id: "sib", rect: rect(50, 20, 120, 30) }],
      tolerance: 4,
    });
    const left = gs.find((g) => g.movingEdge === "left" && g.source === "sibling")!;
    expect(left.start).toBe(20);   // sibling top
    expect(left.end).toBe(230);    // moving bottom
  });

  it("merges the same line contributed by several siblings into one span", () => {
    const gs = computeAlignmentGuides({
      moving: rect(50, 300, 80, 30),
      parent: null,
      siblings: [
        { id: "a", rect: rect(50, 0, 80, 20) },
        { id: "b", rect: rect(50, 100, 80, 20) },
        { id: "c", rect: rect(50, 200, 80, 20) },
      ],
      tolerance: 4,
    });
    const lefts = gs.filter((g) => g.movingEdge === "left");
    expect(lefts).toHaveLength(1);
    expect(lefts[0].start).toBe(0);
    expect(lefts[0].end).toBe(330);
  });

  it("ignores siblings that are nowhere near any axis", () => {
    const gs = computeAlignmentGuides({
      moving: rect(0, 0, 10, 10),
      parent: null,
      siblings: [{ id: "far", rect: rect(900, 900, 10, 10) }],
      tolerance: 4,
    });
    expect(gs).toEqual([]);
  });

  it("keeps distinct moving edges that land on the same coordinate", () => {
    // A sibling whose left edge (100) matches the moving box's centreX, and
    // whose centreX (140) matches nothing — plus a second sibling at 100
    // matching the moving box's LEFT edge would be the same line, different
    // delta. Both must survive as separate snap candidates.
    const gs = computeAlignmentGuides({
      moving: rect(100, 0, 0, 10), // zero-width: left === centerX === right === 100
      parent: null,
      siblings: [{ id: "s", rect: rect(100, 40, 80, 10) }],
      tolerance: 4,
    });
    const edges = gs.map((g) => g.movingEdge).sort();
    expect(edges).toEqual(["centerX", "left", "right"]);
  });
});

describe("pickSnap", () => {
  const guides: AlignmentGuide[] = [
    { axis: "v", position: 100, start: 0, end: 10, movingEdge: "left", source: "sibling", delta: 1 },
    { axis: "v", position: 300, start: 0, end: 10, movingEdge: "right", source: "sibling", delta: 3 },
    { axis: "h", position: 200, start: 0, end: 10, movingEdge: "bottom", source: "sibling", delta: -2 },
  ];

  it("never snaps to a left/top edge — a resize cannot move it in normal flow", () => {
    const g = pickSnap(guides, "v");
    expect(g?.movingEdge).toBe("right");
  });

  it("picks the nearest candidate on the requested axis", () => {
    const g = pickSnap(guides, "h");
    expect(g?.movingEdge).toBe("bottom");
    expect(g?.delta).toBe(-2);
  });

  it("prefers the parent centre when two candidates are equally close", () => {
    const tie: AlignmentGuide[] = [
      { axis: "v", position: 100, start: 0, end: 10, movingEdge: "right", source: "sibling", delta: 2 },
      { axis: "v", position: 104, start: 0, end: 10, movingEdge: "centerX", source: "parent", delta: 2 },
    ];
    expect(pickSnap(tie, "v")?.source).toBe("parent");
  });

  it("returns null when nothing on that axis is snappable", () => {
    expect(
      pickSnap(
        [{ axis: "v", position: 1, start: 0, end: 1, movingEdge: "left", source: "sibling", delta: 0 }],
        "v",
      ),
    ).toBeNull();
    expect(pickSnap(guides, "h")).not.toBeNull();
  });
});

describe("snapSizeDelta", () => {
  const g = (movingEdge: AlignmentGuide["movingEdge"], delta: number): AlignmentGuide => ({
    axis: movingEdge === "left" || movingEdge === "centerX" || movingEdge === "right" ? "v" : "h",
    position: 0,
    start: 0,
    end: 0,
    movingEdge,
    source: "sibling",
    delta,
  });

  it("moves a far edge by exactly the delta", () => {
    expect(snapSizeDelta(g("right", 3))).toBe(3);
    expect(snapSizeDelta(g("bottom", -2))).toBe(-2);
  });

  it("moves a centre by growing twice the delta, since the near edge is pinned", () => {
    expect(snapSizeDelta(g("centerX", 3))).toBe(6);
    expect(snapSizeDelta(g("centerY", -1.5))).toBe(-3);
  });

  it("is a no-op for edges a resize cannot relocate", () => {
    expect(snapSizeDelta(g("left", 3))).toBe(0);
    expect(snapSizeDelta(g("top", 3))).toBe(0);
  });
});

describe("tolerance is expressed in canvas px", () => {
  it("scales with zoom so 50% zoom keeps the same canvas-px slop", () => {
    // At 50% zoom, 4 canvas px is 2 screen px. A box 3 SCREEN px from the parent
    // centre is 6 CANVAS px away and must NOT claim to be centred.
    const tolerance50 = SNAP_TOLERANCE_CANVAS_PX * 0.5;
    expect(
      computeAlignmentGuides({
        moving: rect(147, 10, 100, 40), // centre 197, 3 screen px off
        parent: PARENT,
        siblings: [],
        tolerance: tolerance50,
      }),
    ).toEqual([]);
    // The same 3px gap at 100% zoom is only 3 canvas px and does fire.
    expect(
      computeAlignmentGuides({
        moving: rect(147, 10, 100, 40),
        parent: PARENT,
        siblings: [],
        tolerance: SNAP_TOLERANCE_CANVAS_PX * 1,
      }),
    ).toHaveLength(1);
  });

  it("guards against a nonsense tolerance rather than firing everything", () => {
    expect(
      computeAlignmentGuides({
        moving: rect(0, 0, 10, 10),
        parent: PARENT,
        siblings: [],
        tolerance: Number.NaN,
      }),
    ).toEqual([]);
  });
});
