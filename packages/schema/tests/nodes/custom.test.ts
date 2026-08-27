import { describe, it, expect } from "vitest";
import { CustomNode } from "../../src/nodes/custom";

describe("CustomNode", () => {
  it("requires html string", () => {
    expect(() => CustomNode.parse({ id: "c1", type: "Custom", props: {} })).toThrow();
  });

  it("accepts html + optional tailwind/label + style", () => {
    const r = CustomNode.parse({
      id: "c1",
      type: "Custom",
      props: { html: "<div>hi</div>", tailwind: "p-4 bg-gradient-to-br",
               label: "Hero with parallax" },
      style: { padding: "tokens.spacing.semantic.section" },
    });
    expect(r.props.html).toBe("<div>hi</div>");
    expect(r.style?.padding).toMatch(/^tokens\./);
  });

  it("rejects empty html string", () => {
    expect(() => CustomNode.parse({
      id: "c1", type: "Custom", props: { html: "" },
    })).toThrow();
  });

  it("rejects unknown props (strict mode)", () => {
    expect(() => CustomNode.parse({
      id: "c1", type: "Custom",
      props: { html: "<x/>", whoops: "ignored" },
    })).toThrow();
  });
});
