import { describe, it, expect } from "vitest";
import { syntheticNodeId } from "../src/synthetic-id";

describe("syntheticNodeId", () => {
  it("same node produces same id", () => {
    const n = { type: "Text", props: { content: "hi" } };
    expect(syntheticNodeId(n)).toBe(syntheticNodeId(n));
  });

  it("different types produce different ids", () => {
    expect(syntheticNodeId({ type: "Text" })).not.toBe(
      syntheticNodeId({ type: "Button" })
    );
  });

  it("different prop sets produce different ids", () => {
    expect(
      syntheticNodeId({ type: "Text", props: { content: "a" } })
    ).not.toBe(
      syntheticNodeId({ type: "Text", props: { variant: "x" } })
    );
  });

  it("different prop VALUES produce different ids (full serialisation hash)", () => {
    expect(
      syntheticNodeId({ type: "Text", props: { content: "a" } })
    ).not.toBe(
      syntheticNodeId({ type: "Text", props: { content: "b" } })
    );
  });

  it("missing type defaults to 'unknown'", () => {
    expect(syntheticNodeId({})).toMatch(/^unknown_/);
  });

  it("starts with type name", () => {
    expect(syntheticNodeId({ type: "Hero" })).toMatch(/^Hero_/);
  });

  it("id is stable across calls with identical input", () => {
    const a = syntheticNodeId({
      type: "Hero",
      props: { headline: "x", layout: "centered" },
    });
    const b = syntheticNodeId({
      type: "Hero",
      props: { headline: "x", layout: "centered" },
    });
    expect(a).toBe(b);
  });

  it("matches renderer dispatch.tsx algorithm exactly", () => {
    // Replicate the original djb2 inline to confirm output is identical
    const node = { type: "Stack", props: { gap: "md" } };
    const key = node.type + JSON.stringify(node.props ?? {});
    let h = 0;
    for (let i = 0; i < key.length; i++) {
      h = ((h << 5) - h + key.charCodeAt(i)) | 0;
    }
    const expected = `${node.type}_${(h >>> 0).toString(16)}`;
    expect(syntheticNodeId(node)).toBe(expected);
  });
});
