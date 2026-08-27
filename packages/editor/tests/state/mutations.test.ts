import { describe, it, expect } from "vitest";
import { produce } from "immer";
import { dispatchApply, invert, buildInsertNode, buildRemoveNode, buildSetProp } from "../../src/state/mutations";

const page = (): any => ({
  schemaVersion: "1", id: "p", route: "/",
  root: { id: "r", type: "Stack", children: [
    { id: "a", type: "Text", props: { content: "A" } },
  ]},
});

describe("dispatchApply", () => {
  it("applies insert-node", () => {
    const m = { kind: "insert-node" as const, parentId: "r", index: 1, node: { id: "b", type: "Text", props: { content: "B" } } };
    const next = produce(page(), (d: any) => { dispatchApply(d, m); });
    expect(next.root.children.map((n: any) => n.id)).toEqual(["a", "b"]);
  });

  it("applies set-prop", () => {
    const m = { kind: "set-prop" as const, id: "a", key: "content", value: "X", prevValue: "A" };
    const next = produce(page(), (d: any) => { dispatchApply(d, m); });
    expect(next.root.children[0].props.content).toBe("X");
  });
});

describe("invert", () => {
  it("invert(insert-node) is remove-node", () => {
    const m = { kind: "insert-node" as const, parentId: "r", index: 1, node: { id: "b", type: "Text" } };
    const inv = invert(m);
    expect(inv.kind).toBe("remove-node");
  });

  it("apply → invert → apply restores original state", () => {
    const m = { kind: "set-prop" as const, id: "a", key: "content", value: "X", prevValue: "A" };
    const after = produce(page(), (d: any) => { dispatchApply(d, m); });
    const inv = invert(m);
    const restored = produce(after, (d: any) => { dispatchApply(d, inv); });
    expect(restored).toEqual(page());
  });
});

describe("builders", () => {
  it("buildSetProp captures prevValue from current schema", () => {
    const m = buildSetProp("a", "content", "X", page());
    expect(m).toMatchObject({ kind: "set-prop", id: "a", key: "content", value: "X", prevValue: "A" });
  });

  it("buildRemoveNode captures full snapshot", () => {
    const m = buildRemoveNode("a", page());
    expect(m.kind).toBe("remove-node");
    expect(m.removed.parentId).toBe("r");
    expect(m.removed.index).toBe(0);
    expect(m.removed.node.id).toBe("a");
  });
});
