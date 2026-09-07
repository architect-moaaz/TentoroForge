/**
 * Fixed R x C grid cells — the pure logic.
 *
 * A "cell" here is a real `GridCell` node in the saved schema, not an editor
 * fiction. The reasons are recorded in packages/renderer/src/nodes/layout/
 * GridCell.tsx (an empty <Grid> renders zero children, so there is nothing to
 * drop into; and positioning children with `grid-column` would pin them past
 * the responsive breakpoints). The consequence for this module is that cell
 * identity is purely POSITIONAL: the direct children of a fixed grid are its
 * cells in row-major order, so cell (r, c) is `children[r * columns + c]`.
 * Nothing needs to be reconstructed at load time, and nothing can drift.
 *
 * Everything here is pure and exported for unit tests (grid-cells.test.ts).
 */

export const GRID_CELL_TYPE = "GridCell";

/** The structural subset of a schema node this module needs. */
export interface CellNode {
  id: string;
  type: string;
  props?: Record<string, unknown>;
  children?: CellNode[];
  slots?: Record<string, CellNode[]>;
}

/** Tailwind's `grid-cols-N` stops at 12, and Grid.tsx clamps there too. */
const MAX_TRACKS = 12;

function clampInt(v: unknown, lo: number, hi: number): number {
  if (typeof v !== "number" || !Number.isFinite(v)) return lo;
  return Math.min(hi, Math.max(lo, Math.trunc(v)));
}

/** Column count of a Grid node, clamped the same way the renderer clamps it. */
export function gridColumns(node: CellNode | null | undefined): number {
  return clampInt(node?.props?.columns, 1, MAX_TRACKS);
}

/**
 * Fixed row count, or 0 when the grid is in the legacy "rows are implicit"
 * mode. 0 is the default for every schema written before the `rows` prop
 * existed, and it is what keeps those grids untouched by everything below.
 */
export function gridRows(node: CellNode | null | undefined): number {
  return clampInt(node?.props?.rows, 0, MAX_TRACKS);
}

/** True for a Grid the user has committed to a fixed R x C shape. */
export function isFixedGrid(node: CellNode | null | undefined): boolean {
  return node?.type === "Grid" && gridRows(node) > 0;
}

/**
 * The cells of a fixed grid, or null when `node` is not one.
 *
 * Only direct `GridCell` children count. A fixed grid whose children have been
 * hand-edited into something else (raw JSON editing, an LLM patch) returns a
 * shorter list rather than lying about the addressing — callers treat a
 * mismatched length as "needs reconciling", never as "cell 5 is over there".
 */
export function gridCells(node: CellNode | null | undefined): CellNode[] | null {
  if (!isFixedGrid(node)) return null;
  return (node!.children ?? []).filter((c) => c?.type === GRID_CELL_TYPE);
}

/** A cell nobody has dropped anything into yet. */
export function isEmptyCell(cell: CellNode | null | undefined): boolean {
  return !!cell && cell.type === GRID_CELL_TYPE && (cell.children?.length ?? 0) === 0;
}

/**
 * The auto-fill target: index of the first empty cell in row-major order, or
 * -1 when the grid is full.
 *
 * "First empty" rather than "append": the whole point of a fixed R x C is that
 * the user chose that shape, so a drop that lands on the grid rather than on a
 * specific cell fills the next hole instead of growing the grid. Deliberately
 * NOT paired with an auto-add-a-row rule — a full grid stays full.
 */
export function firstEmptyCellIndex(cells: readonly CellNode[]): number {
  return cells.findIndex(isEmptyCell);
}

/** Row/column address of a cell index, row-major. */
export function cellAddress(index: number, columns: number): { row: number; col: number } {
  const cols = Math.max(1, Math.trunc(columns));
  return { row: Math.floor(index / cols), col: index % cols };
}

/** Inverse of cellAddress. */
export function cellIndex(row: number, col: number, columns: number): number {
  return row * Math.max(1, Math.trunc(columns)) + col;
}

// ---------------------------------------------------------------------------
// Reconciling cells when the user changes rows / columns
// ---------------------------------------------------------------------------

/** One structural change, translated by the caller into an EditorAction. */
export type CellOp =
  | { kind: "insert"; index: number; node: CellNode }
  | { kind: "remove"; nodeId: string };

/** Builds a fresh cell. The caller supplies id generation so ids stay unique
 *  against the whole page tree, which this module cannot see. */
export type MakeCell = (children: CellNode[]) => CellNode;

/**
 * The ops that turn `children` into exactly `rows * columns` cells.
 *
 * Three rules, each of which exists to avoid destroying work:
 *
 *  1. GROWING appends empty cells at the end. Existing cells keep their ids, so
 *     the current selection and any undo entry that names them survive.
 *  2. SHRINKING removes trailing cells only while they are EMPTY, and stops at
 *     the first one with content. Typing "2" into a rows field must never be a
 *     silent delete of whatever was in row 3; the grid is left larger than
 *     asked for instead, which is visible and recoverable.
 *  3. CONVERTING a legacy grid (children that are not cells) wraps each existing
 *     child in its own cell, in order, then pads. Nothing is dropped — the
 *     free-flowing children become the contents of cells 0..n-1.
 *
 * Returns [] when there is nothing to do, including for rows <= 0 (auto mode),
 * so a legacy grid is never touched until the user asks for a fixed shape.
 */
export function planGridCells(
  children: readonly CellNode[],
  rows: number,
  columns: number,
  makeCell: MakeCell,
): CellOp[] {
  const r = clampInt(rows, 0, MAX_TRACKS);
  const c = clampInt(columns, 1, MAX_TRACKS);
  const target = r * c;
  if (target <= 0) return [];

  const allCells = children.every((ch) => ch?.type === GRID_CELL_TYPE);

  if (allCells) {
    // Fast path — the grid is already made of cells, so only the tail changes.
    if (children.length < target) {
      const ops: CellOp[] = [];
      for (let i = children.length; i < target; i++) {
        ops.push({ kind: "insert", index: i, node: makeCell([]) });
      }
      return ops;
    }
    const ops: CellOp[] = [];
    for (let i = children.length - 1; i >= target; i--) {
      if (!isEmptyCell(children[i])) break; // rule 2 — stop at real content
      ops.push({ kind: "remove", nodeId: children[i].id });
    }
    return ops;
  }

  // Conversion path. Rebuild the child list wholesale: the loose children have
  // to move INSIDE new cells, which is a remove + re-insert however it is
  // expressed. Every original node object is carried across unchanged (same id,
  // same subtree), so this reparents rather than recreates.
  const wrapped: CellNode[] = children.map((ch) =>
    ch?.type === GRID_CELL_TYPE ? ch : makeCell([ch]),
  );
  while (wrapped.length < target) wrapped.push(makeCell([]));
  while (wrapped.length > target && isEmptyCell(wrapped[wrapped.length - 1])) {
    wrapped.pop();
  }

  const ops: CellOp[] = children.map((ch) => ({ kind: "remove", nodeId: ch.id }) as CellOp);
  wrapped.forEach((cell, i) => ops.push({ kind: "insert", index: i, node: cell }));
  return ops;
}
