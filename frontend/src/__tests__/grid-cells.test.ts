import { describe, it, expect } from "vitest";
import {
  GRID_CELL_TYPE,
  cellAddress,
  cellIndex,
  firstEmptyCellIndex,
  gridCells,
  gridColumns,
  gridRows,
  isEmptyCell,
  isFixedGrid,
  planGridCells,
  type CellNode,
} from "@/lib/grid-cells";
import { cellGuideBoxes } from "@/components/canvas/grid-guides";

let n = 0;
const makeCell = (children: CellNode[] = []): CellNode => ({
  id: `c${++n}`,
  type: GRID_CELL_TYPE,
  props: {},
  children,
});
const filled = (id: string): CellNode => ({
  id,
  type: GRID_CELL_TYPE,
  props: {},
  children: [{ id: `${id}-kid`, type: "Text" }],
});
const grid = (rows: number, columns: number, children: CellNode[] = []): CellNode => ({
  id: "g1",
  type: "Grid",
  props: { rows, columns },
  children,
});

// =============================================================================
describe("fixed-grid detection", () => {
  it("treats a Grid without a rows prop as legacy auto-flow, not 0x0", () => {
    const legacy: CellNode = { id: "g", type: "Grid", props: { columns: 3 }, children: [] };
    expect(gridRows(legacy)).toBe(0);
    expect(isFixedGrid(legacy)).toBe(false);
    expect(gridCells(legacy)).toBeNull();
  });

  it("rows: 0 is explicitly auto — the registry default, so legacy grids stay legacy", () => {
    expect(isFixedGrid(grid(0, 3))).toBe(false);
  });

  it("clamps to the 12 tracks Tailwind's grid-cols-N and Grid.tsx stop at", () => {
    expect(gridColumns({ id: "g", type: "Grid", props: { columns: 99 } })).toBe(12);
    expect(gridRows({ id: "g", type: "Grid", props: { rows: 99 } })).toBe(12);
    expect(gridColumns({ id: "g", type: "Grid", props: { columns: 0 } })).toBe(1);
  });

  it("only counts direct GridCell children, so hand-edited grids do not lie", () => {
    const g = grid(1, 2, [makeCell(), { id: "x", type: "Card" } as CellNode]);
    expect(gridCells(g)!.map((c) => c.type)).toEqual([GRID_CELL_TYPE]);
  });

  it("is not fooled by a non-Grid node that happens to carry rows", () => {
    expect(isFixedGrid({ id: "s", type: "Stack", props: { rows: 3 } })).toBe(false);
  });
});

// =============================================================================
describe("cell addressing is row-major", () => {
  it("maps index to (row, col) and back for a 3-column grid", () => {
    expect(cellAddress(0, 3)).toEqual({ row: 0, col: 0 });
    expect(cellAddress(2, 3)).toEqual({ row: 0, col: 2 });
    expect(cellAddress(3, 3)).toEqual({ row: 1, col: 0 });
    expect(cellAddress(7, 3)).toEqual({ row: 2, col: 1 });
    for (let i = 0; i < 12; i++) {
      const { row, col } = cellAddress(i, 3);
      expect(cellIndex(row, col, 3)).toBe(i);
    }
  });
});

// =============================================================================
describe("auto-fill target selection", () => {
  it("picks the first empty cell in row-major order, not the last", () => {
    const cells = [filled("a"), makeCell(), filled("c"), makeCell()];
    expect(firstEmptyCellIndex(cells)).toBe(1);
  });

  it("returns -1 for a full grid — a full grid does NOT grow a row", () => {
    expect(firstEmptyCellIndex([filled("a"), filled("b")])).toBe(-1);
  });

  it("a cell with any child at all counts as occupied", () => {
    expect(isEmptyCell(makeCell())).toBe(true);
    expect(isEmptyCell(filled("a"))).toBe(false);
  });
});

// =============================================================================
describe("planGridCells — growing", () => {
  it("appends empty cells and touches nothing that already exists", () => {
    const existing = [filled("a"), filled("b")];
    const ops = planGridCells(existing, 2, 2, makeCell);
    expect(ops.every((o) => o.kind === "insert")).toBe(true);
    expect(ops.map((o) => (o.kind === "insert" ? o.index : -1))).toEqual([2, 3]);
    // Existing cells keep their ids — selection and undo entries survive.
    expect(ops.some((o) => o.kind === "remove")).toBe(false);
  });

  it("is a no-op when the count already matches", () => {
    expect(planGridCells([makeCell(), makeCell()], 1, 2, makeCell)).toEqual([]);
  });

  it("does nothing at all in auto mode (rows 0), so legacy grids are untouched", () => {
    const loose = [{ id: "k1", type: "Card" } as CellNode];
    expect(planGridCells(loose, 0, 3, makeCell)).toEqual([]);
  });
});

// =============================================================================
describe("planGridCells — shrinking never deletes content", () => {
  it("removes trailing empty cells", () => {
    const cells = [filled("a"), filled("b"), makeCell(), makeCell()];
    const ops = planGridCells(cells, 1, 2, makeCell);
    expect(ops).toHaveLength(2);
    expect(ops.every((o) => o.kind === "remove")).toBe(true);
  });

  it("stops at the first cell with content, leaving the grid bigger than asked", () => {
    const cells = [filled("a"), filled("b"), filled("c"), makeCell()];
    const ops = planGridCells(cells, 1, 2, makeCell);
    // Only the trailing EMPTY one goes; "c" survives even though 1x2 = 2.
    expect(ops).toEqual([{ kind: "remove", nodeId: cells[3].id }]);
  });

  it("removes nothing when the very next cell up is occupied", () => {
    const cells = [filled("a"), filled("b"), filled("c")];
    expect(planGridCells(cells, 1, 2, makeCell)).toEqual([]);
  });
});

// =============================================================================
describe("planGridCells — converting a legacy grid", () => {
  it("wraps each loose child in its own cell and pads to rows x columns", () => {
    const loose: CellNode[] = [
      { id: "k1", type: "Card" },
      { id: "k2", type: "Text" },
    ];
    const ops = planGridCells(loose, 2, 2, makeCell);
    const removes = ops.filter((o) => o.kind === "remove");
    const inserts = ops.filter((o) => o.kind === "insert") as Extract<
      (typeof ops)[number],
      { kind: "insert" }
    >[];

    // Both loose children are reparented, not recreated.
    expect(removes.map((o) => (o.kind === "remove" ? o.nodeId : ""))).toEqual(["k1", "k2"]);
    expect(inserts).toHaveLength(4);
    expect(inserts.map((o) => o.index)).toEqual([0, 1, 2, 3]);
    expect(inserts.every((o) => o.node.type === GRID_CELL_TYPE)).toBe(true);
    // The original nodes survive verbatim inside the first two cells.
    expect(inserts[0].node.children).toEqual([loose[0]]);
    expect(inserts[1].node.children).toEqual([loose[1]]);
    expect(inserts[2].node.children).toEqual([]);
    expect(inserts[3].node.children).toEqual([]);
  });

  it("keeps overflow children rather than dropping them on the floor", () => {
    const loose: CellNode[] = [
      { id: "k1", type: "Card" },
      { id: "k2", type: "Card" },
      { id: "k3", type: "Card" },
    ];
    const inserts = planGridCells(loose, 1, 2, makeCell).filter((o) => o.kind === "insert");
    // Asked for 2 cells, but k3 has content — 3 cells is the honest answer.
    expect(inserts).toHaveLength(3);
  });

  it("handles a half-converted grid (some cells, some loose children)", () => {
    const mixed: CellNode[] = [filled("a"), { id: "k1", type: "Text" }];
    const inserts = planGridCells(mixed, 1, 2, makeCell).filter(
      (o) => o.kind === "insert",
    ) as Extract<ReturnType<typeof planGridCells>[number], { kind: "insert" }>[];
    expect(inserts).toHaveLength(2);
    // The already-good cell is carried across unchanged (same id).
    expect(inserts[0].node.id).toBe("a");
    expect(inserts[1].node.children).toEqual([mixed[1]]);
  });
});

// =============================================================================
describe("guide geometry", () => {
  it("straddles the hairline across the cell boundary", () => {
    const [b] = cellGuideBoxes([{ left: 100, top: 50, width: 200, height: 80 }], 2);
    expect(b).toMatchObject({ left: 99.5, top: 49.5, width: 201, height: 81 });
  });

  it("labels each box with its row-major address", () => {
    const r = { left: 0, top: 0, width: 10, height: 10 };
    const boxes = cellGuideBoxes([r, r, r, r, r, r], 3);
    expect(boxes.map((b) => `${b.row},${b.col}`)).toEqual([
      "0,0", "0,1", "0,2", "1,0", "1,1", "1,2",
    ]);
  });

  it("drops unlaid-out cells so no stray marker lands at the viewport origin", () => {
    const boxes = cellGuideBoxes(
      [
        { left: 0, top: 0, width: 0, height: 0 },
        { left: 10, top: 10, width: 5, height: 0 },
        { left: 20, top: 20, width: 5, height: 5 },
      ],
      3,
    );
    expect(boxes).toHaveLength(1);
    expect(boxes[0].left).toBe(19.5);
  });

  it("carries no zoom factor — screen rects in, screen boxes out", () => {
    // The canvas frame is CSS-transformed, so a 50%-zoomed cell already arrives
    // measured at half size. Rescaling here would double every offset.
    const zoomed = { left: 200, top: 100, width: 100, height: 40 };
    const [b] = cellGuideBoxes([zoomed], 1);
    expect(b.left).toBe(199.5);
    expect(b.width).toBe(101);
  });
});
