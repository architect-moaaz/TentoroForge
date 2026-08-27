import { describe, it, expect } from "vitest";
import { produce } from "immer";
import { insertNode, removeNode, moveNode, setNodeField } from "../../src/state/apply";

const fixture = () => ({
  schemaVersion: "1" as const,
  id: "p",
  route: "/",
  root: {
    id: "r",
    type: "Stack",
    children: [
      { id: "a", type: "Text", props: { content: "A" } },
      { id: "b", type: "Text", props: { content: "B" } },
    ],
  },
});

describe("insertNode", () => {
  it("inserts a node at the specified index", () => {
    const out = produce(fixture(), (draft) => {
      insertNode(draft, "r", 1, { id: "c", type: "Text", props: { content: "C" } });
    });
    expect(out.root.children!.map((n: any) => n.id)).toEqual(["a", "c", "b"]);
  });
});

describe("removeNode", () => {
  it("removes by id and returns snapshot", () => {
    let snap;
    const out = produce(fixture(), (draft) => {
      snap = removeNode(draft, "a");
    });
    expect(out.root.children!.map((n: any) => n.id)).toEqual(["b"]);
    expect(snap).toEqual({ node: expect.objectContaining({ id: "a" }), parentId: "r", index: 0 });
  });
});

describe("moveNode", () => {
  it("relocates a node to a new parent + index", () => {
    const out = produce(fixture(), (draft) => {
      moveNode(draft, "a", "r", 1);
    });
    expect(out.root.children!.map((n: any) => n.id)).toEqual(["b", "a"]);
  });
});

describe("setNodeField", () => {
  it("sets a nested field by path", () => {
    const out = produce(fixture(), (draft) => {
      setNodeField(draft, "a", ["props", "content"], "X");
    });
    expect((out.root.children![0] as any).props.content).toBe("X");
  });
});
