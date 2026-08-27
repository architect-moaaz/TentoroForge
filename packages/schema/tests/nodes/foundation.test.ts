import { describe, it, expect } from "vitest";
import { HeroNode, SectionNode, MetricTileNode, FeatureCardNode } from "../../src/nodes/foundation";

describe("HeroNode", () => {
  it("requires headline + layout", () => {
    expect(() => HeroNode.parse({ id: "h", type: "Hero", props: { ctas: [] } })).toThrow();
    const r = HeroNode.parse({
      id: "h", type: "Hero",
      props: { headline: "Hi", layout: "centered", ctas: [] },
    });
    expect(r.props.layout).toBe("centered");
  });

  it("accepts ctas with both navigate and workflow actions", () => {
    const r = HeroNode.parse({
      id: "h", type: "Hero",
      props: {
        headline: "Hi", layout: "centered",
        ctas: [
          { label: "Sign up",   action: { type: "navigate", to: "/signup" } },
          { label: "Subscribe", action: { type: "workflow", name: "subscribeFlow" }, variant: "secondary" },
        ],
      },
    });
    expect(r.props.ctas).toHaveLength(2);
    expect(r.props.ctas[0].variant).toBe("primary"); // default
    expect(r.props.ctas[1].variant).toBe("secondary");
  });

  it("rejects unknown props (strict mode)", () => {
    expect(() => HeroNode.parse({
      id: "h", type: "Hero",
      props: { headline: "x", layout: "centered", whoops: "ignored" },
    })).toThrow();
  });
});

describe("SectionNode", () => {
  it("requires variant + children array", () => {
    const r = SectionNode.parse({
      id: "s", type: "Section",
      props: { variant: "feature" },
      children: [],
    });
    expect(r.props.variant).toBe("feature");
  });
});

describe("SectionNode variant=full-bleed", () => {
  it("accepts full-bleed", () => {
    const r = SectionNode.safeParse({
      id: "s",
      type: "Section",
      props: { variant: "full-bleed" },
    });
    expect(r.success).toBe(true);
  });

  it("rejects unknown variants", () => {
    const r = SectionNode.safeParse({
      id: "s",
      type: "Section",
      props: { variant: "balloon" },
    });
    expect(r.success).toBe(false);
  });

  it("accepts all existing variants still", () => {
    for (const v of ["plain", "feature", "cta", "stats", "split", "full-bleed"] as const) {
      const r = SectionNode.safeParse({
        id: "s", type: "Section",
        props: { variant: v },
      });
      expect(r.success, `variant "${v}" should be valid`).toBe(true);
    }
  });
});

describe("MetricTileNode", () => {
  it("requires label, value, format", () => {
    const r = MetricTileNode.parse({
      id: "m", type: "MetricTile",
      props: { label: "Active users", value: 1234, format: "number",
               delta: { value: 0.12, direction: "up" } },
    });
    expect(r.props.delta?.direction).toBe("up");
  });
});

describe("FeatureCardNode", () => {
  it("requires title + description + layout", () => {
    const r = FeatureCardNode.parse({
      id: "f", type: "FeatureCard",
      props: { title: "Fast", description: "Built for speed", layout: "icon-top" },
    });
    expect(r.props.layout).toBe("icon-top");
  });
});

describe("HeroNode backgroundImage", () => {
  it("accepts url + overlay", () => {
    const r = HeroNode.safeParse({
      id: "h", type: "Hero",
      props: { headline: "Hi", layout: "centered", backgroundImage: { url: "https://x.jpg", overlay: 0.3 } },
    });
    expect(r.success).toBe(true);
  });

  it("overlay defaults to 0.4 when omitted", () => {
    const r = HeroNode.parse({
      id: "h", type: "Hero",
      props: { headline: "Hi", layout: "centered", backgroundImage: { url: "https://x.jpg" } },
    });
    expect(r.props.backgroundImage?.overlay).toBe(0.4);
  });

  it("rejects overlay > 1", () => {
    const r = HeroNode.safeParse({
      id: "h", type: "Hero",
      props: { headline: "Hi", layout: "centered", backgroundImage: { url: "https://x.jpg", overlay: 1.5 } },
    });
    expect(r.success).toBe(false);
  });

  it("backgroundImage is optional", () => {
    const r = HeroNode.safeParse({ id: "h", type: "Hero", props: { headline: "Hi", layout: "centered" } });
    expect(r.success).toBe(true);
  });
});
