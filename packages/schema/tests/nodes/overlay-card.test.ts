import { describe, it, expect } from "vitest";
import { OverlayCardNode } from "../../src/nodes/foundation";

describe("OverlayCardNode", () => {
  it("parses minimal OverlayCard", () => {
    const r = OverlayCardNode.safeParse({
      id: "card-1",
      type: "OverlayCard",
      props: {},
    });
    expect(r.success).toBe(true);
  });

  it("anchor defaults to bottom-right", () => {
    const r = OverlayCardNode.parse({
      id: "card-1",
      type: "OverlayCard",
      props: {},
    });
    expect(r.props.anchor).toBe("bottom-right");
  });

  it("rejects invalid anchor", () => {
    const r = OverlayCardNode.safeParse({
      id: "card-1",
      type: "OverlayCard",
      props: { anchor: "diagonal" },
    });
    expect(r.success).toBe(false);
  });

  it("accepts all four corner anchors + center", () => {
    for (const a of [
      "top-left",
      "top-right",
      "bottom-left",
      "bottom-right",
      "center",
    ]) {
      const r = OverlayCardNode.safeParse({
        id: "x",
        type: "OverlayCard",
        props: { anchor: a },
      });
      expect(r.success, `anchor=${a} should parse`).toBe(true);
    }
  });

  it("elevation defaults to lg", () => {
    const r = OverlayCardNode.parse({
      id: "x",
      type: "OverlayCard",
      props: {},
    });
    expect(r.props.elevation).toBe("lg");
  });

  it("rejects invalid elevation", () => {
    const r = OverlayCardNode.safeParse({
      id: "x",
      type: "OverlayCard",
      props: { elevation: "none" },
    });
    expect(r.success).toBe(false);
  });

  it("offset defaults to -3rem", () => {
    const r = OverlayCardNode.parse({
      id: "x",
      type: "OverlayCard",
      props: {},
    });
    expect(r.props.offset).toBe("-3rem");
  });

  it("rejects unknown props (strict mode)", () => {
    const r = OverlayCardNode.safeParse({
      id: "x",
      type: "OverlayCard",
      props: { whoops: true },
    });
    expect(r.success).toBe(false);
  });
});
