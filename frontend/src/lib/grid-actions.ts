import type { EditorAction } from "@forge/patches";
import {
  GRID_CELL_TYPE,
  gridColumns,
  gridRows,
  planGridCells,
  type CellNode,
} from "./grid-cells";

/**
 * Translating a rows/columns edit on a <Grid> into editor actions.
 *
 * Why this is a BATCH and not a prop write followed by some inserts: the store
 * pushes one history entry per dispatch, so three separate dispatches would
 * take three Ctrl+Z presses to undo, and the two intermediate states are both
 * invalid (a grid claiming 3 rows while holding 4 cells). dispatchBatch applies
 * the whole list and records a single reversible entry.
 */

/** Every node id anywhere in the artifacts — children AND slots, all pages. */
export function collectAllNodeIds(artifacts: any): Set<string> {
  const ids = new Set<string>();
  for (const page of Object.values(artifacts?.pageSchemas ?? {})) {
    const stack: any[] = [(page as any).root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      if (n.id) ids.add(n.id);
      if (Array.isArray(n.children)) stack.push(...n.children);
      if (n.slots) {
        for (const arr of Object.values(n.slots) as any[]) {
          if (Array.isArray(arr)) stack.push(...arr);
        }
      }
    }
  }
  return ids;
}

/**
 * A cell factory that cannot collide. An id clash makes validateForCommit's
 * uniqueness check fail, and the store REJECTS the whole commit on a failed
 * validation — so a single duplicated cell id would make the row count silently
 * refuse to change with no error anywhere.
 */
export function makeCellFactory(taken: Set<string>) {
  let n = 0;
  return (children: CellNode[] = []): CellNode => {
    let id = "";
    do {
      id = `gridcell-${Math.random().toString(36).slice(2, 8)}${n ? `-${n}` : ""}`;
      n++;
    } while (taken.has(id));
    taken.add(id);
    return { id, type: GRID_CELL_TYPE, props: {}, children };
  };
}

/**
 * The actions for setting `propName` (`rows` or `columns`) to `value` on a Grid.
 *
 * Returns null when this is not a fixed-grid edit at all — a non-Grid node, a
 * different prop, a non-numeric value, or a row count of 0 (auto mode, the
 * legacy behaviour every pre-existing Grid keeps). In that case the caller does
 * its normal single updateProp and nothing about cells happens.
 */
export function gridStructureActions(
  pageId: string,
  node: CellNode,
  propName: string,
  value: unknown,
  artifacts: any,
): EditorAction[] | null {
  if (node?.type !== "Grid") return null;
  if (propName !== "rows" && propName !== "columns") return null;
  if (typeof value !== "number" || !Number.isFinite(value)) return null;

  const nextProps = { ...(node.props ?? {}), [propName]: value };
  const probe: CellNode = { id: node.id, type: "Grid", props: nextProps };
  const rows = gridRows(probe);
  const columns = gridColumns(probe);
  if (rows <= 0) return null;

  const makeCell = makeCellFactory(collectAllNodeIds(artifacts));
  const ops = planGridCells(node.children ?? [], rows, columns, makeCell);
  if (!ops.length) return null;

  const actions: EditorAction[] = [
    { type: "updateProp", pageId, nodeId: node.id, propName, value },
  ];
  for (const op of ops) {
    if (op.kind === "remove") {
      actions.push({ type: "removeNode", pageId, nodeId: op.nodeId });
    } else {
      actions.push({
        type: "insertNode",
        pageId,
        parentId: node.id,
        index: op.index,
        node: op.node as any,
      });
    }
  }
  return actions;
}
