import { describe, it, expect } from "vitest";
import { applyAction, validateForCommit } from "@forge/patches";
import { starterRegistry } from "@forge/registry";
import { gridStructureActions, collectAllNodeIds, makeCellFactory } from "@/lib/grid-actions";
import { gridCells } from "@/lib/grid-cells";

const cell = (id: string, children: any[] = []) => ({
  id,
  type: "GridCell",
  props: {},
  children,
});

function page(gridChildren: any[], props: Record<string, unknown>) {
  return {
    pageSchemas: {
      p1: {
        schemaVersion: "2" as const,
        id: "p1",
        route: "/",
        root: {
          id: "root",
          type: "Stack",
          children: [{ id: "g1", type: "Grid", props, children: gridChildren }],
        },
      },
    },
    navFlow: { pages: [{ id: "p1", route: "/", title: "P" }], transitions: [], initialPage: "p1" },
    tokens: {},
  } as any;
}

function run(artifacts: any, actions: any[]) {
  let cur = artifacts;
  for (const a of actions) cur = applyAction(cur, a).next;
  return cur;
}

const gridOf = (a: any) => a.pageSchemas.p1.root.children[0];

// =============================================================================
describe("gridStructureActions — when it declines to act", () => {
  const a = page([cell("c1"), cell("c2")], { rows: 1, columns: 2 });
  const grid = gridOf(a);

  it("ignores non-Grid nodes", () => {
    expect(gridStructureActions("p1", { id: "s", type: "Stack" }, "rows", 3, a)).toBeNull();
  });
  it("ignores props that are not rows/columns", () => {
    expect(gridStructureActions("p1", grid, "gap", 3, a)).toBeNull();
  });
  it("ignores a non-numeric value (a bound {{expr}} string)", () => {
    expect(gridStructureActions("p1", grid, "rows", "{{x}}", a)).toBeNull();
  });
  it("ignores rows: 0 — that is auto mode, where cells must not exist", () => {
    expect(gridStructureActions("p1", grid, "rows", 0, a)).toBeNull();
  });
  it("returns null when the cell count already matches, so the caller does a plain updateProp", () => {
    expect(gridStructureActions("p1", grid, "columns", 2, a)).toBeNull();
  });
});

// =============================================================================
describe("gridStructureActions — applied end to end through @forge/patches", () => {
  it("growing 1x2 -> 2x2 writes the prop and lands exactly 4 cells", () => {
    const a = page([cell("c1"), cell("c2")], { rows: 1, columns: 2 });
    const actions = gridStructureActions("p1", gridOf(a), "rows", 2, a)!;
    expect(actions[0]).toMatchObject({ type: "updateProp", propName: "rows", value: 2 });

    const next = run(a, actions);
    const g = gridOf(next);
    expect(g.props.rows).toBe(2);
    expect(gridCells(g)).toHaveLength(4);
    // The two originals kept their ids and their positions.
    expect(g.children.slice(0, 2).map((c: any) => c.id)).toEqual(["c1", "c2"]);
  });

  it("widening 2x2 -> 2x3 appends to the end, so existing content stays put", () => {
    const a = page(
      [cell("c1", [{ id: "t1", type: "Text" }]), cell("c2"), cell("c3"), cell("c4")],
      { rows: 2, columns: 2 },
    );
    const next = run(a, gridStructureActions("p1", gridOf(a), "columns", 3, a)!);
    const g = gridOf(next);
    expect(gridCells(g)).toHaveLength(6);
    expect(g.children[0].children[0].id).toBe("t1");
  });

  it("shrinking never removes a cell that has content", () => {
    const a = page(
      [cell("c1"), cell("c2"), cell("c3", [{ id: "keep", type: "Card" }]), cell("c4")],
      { rows: 2, columns: 2 },
    );
    const next = run(a, gridStructureActions("p1", gridOf(a), "rows", 1, a)!);
    const g = gridOf(next);
    // c4 was empty and went; c3 holds the user's Card and stayed, so the grid is
    // 3 cells rather than the 2 that were asked for.
    expect(g.children.map((c: any) => c.id)).toEqual(["c1", "c2", "c3"]);
    expect(g.props.rows).toBe(1);
  });

  it("converting a legacy free-flow Grid reparents its children into cells", () => {
    const a = page(
      [
        { id: "k1", type: "Card", children: [{ id: "deep", type: "Text" }] },
        { id: "k2", type: "Heading", props: { text: "hi" } },
      ],
      { columns: 2 }, // no `rows` at all — the legacy shape
    );
    const next = run(a, gridStructureActions("p1", gridOf(a), "rows", 2, a)!);
    const g = gridOf(next);
    expect(gridCells(g)).toHaveLength(4);
    expect(g.children[0].children[0].id).toBe("k1");
    // The whole subtree came across, not just the top node.
    expect(g.children[0].children[0].children[0].id).toBe("deep");
    expect(g.children[1].children[0].id).toBe("k2");
    expect(g.children[2].children).toEqual([]);
  });

  it("the resulting page passes validateForCommit — unique ids, types in the registry", () => {
    // A failing page is SILENTLY rejected by the store, so an id collision or an
    // unregistered cell type would make the row count refuse to change with no
    // error anywhere. This is the assertion that catches that.
    const a = page([{ id: "k1", type: "Card" }], { columns: 3 });
    const next = run(a, gridStructureActions("p1", gridOf(a), "rows", 3, a)!);
    expect(gridCells(gridOf(next))).toHaveLength(9);
    expect(validateForCommit(next, starterRegistry as any)).toEqual([]);
  });
});

// =============================================================================
describe("cell id generation", () => {
  it("never reuses an id that is already somewhere in the tree", () => {
    const a = page([cell("c1")], { rows: 1, columns: 1 });
    const taken = collectAllNodeIds(a);
    expect(taken.has("c1")).toBe(true);
    expect(taken.has("root")).toBe(true);
    expect(taken.has("g1")).toBe(true);

    const make = makeCellFactory(taken);
    const ids = new Set(Array.from({ length: 50 }, () => make().id));
    expect(ids.size).toBe(50);
    for (const id of ids) expect(taken.has(id)).toBe(true);
  });
});
