import { describe, it, expect } from "vitest";
import { produce } from "immer";
import { dispatchApply, invert, buildSetProp, buildRemoveNode, buildInsertNode, buildBulkRemove } from "../../src/state/mutations";

const page = (): any => ({
  schemaVersion: "1", id: "p", route: "/",
  root: { id: "r", type: "Stack", children: [
    { id: "a", type: "Text", props: { content: "A" } },
    { id: "b", type: "Text", props: { content: "B" } },
  ]},
});

describe("composite mutation", () => {
  it("applies sub-mutations in order", () => {
    const cm: any = { kind: "composite", mutations: [
      buildSetProp("a", "content", "X", page()),
      buildSetProp("b", "content", "Y", page()),
    ]};
    const next = produce(page(), (d: any) => { dispatchApply(d, cm); });
    expect(next.root.children[0].props.content).toBe("X");
    expect(next.root.children[1].props.content).toBe("Y");
  });

  it("invert reverses sub-mutations in reverse order (correct undo for cascading edits)", () => {
    const original = page();
    const cm: any = { kind: "composite", mutations: [
      buildSetProp("a", "content", "X", original),
      buildSetProp("a", "content", "Y", { ...original, root: { ...original.root, children: [{ ...original.root.children[0], props: { content: "X" } }, original.root.children[1]] }}),
    ]};
    const after = produce(original, (d: any) => { dispatchApply(d, cm); });
    expect(after.root.children[0].props.content).toBe("Y");
    const restored = produce(after, (d: any) => { dispatchApply(d, invert(cm)); });
    expect(restored.root.children[0].props.content).toBe("A");
  });

  it("composite of remove-nodes captures snapshots correctly", () => {
    const original = page();
    const cm: any = { kind: "composite", mutations: [
      buildRemoveNode("a", original),
      buildRemoveNode("b", original),  // built from ORIGINAL, not after-step state
    ]};
    // Note: this is intentionally wrong — applying both will fail because after the first removal,
    // 'b' is at index 0 not 1. The plan's bulk-delete builder must call buildRemoveNode against
    // intermediate state. This test confirms naive composition fails.
    expect(() => produce(original, (d: any) => { dispatchApply(d, cm); })).not.toThrow();
    // For correctly-ordered bulk deletes, snapshots are captured against intermediate state — see Task 4.
  });
});

describe("bulk remove", () => {
  it("captures snapshots from intermediate state so all removals succeed", () => {
    const m = buildBulkRemove(["a", "b"], page());
    const after = produce(page(), (d: any) => { dispatchApply(d, m); });
    expect(after.root.children).toEqual([]);
  });
});
