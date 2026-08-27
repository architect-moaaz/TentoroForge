import { describe, it, expect } from "vitest";
import { FadeInNode, StaggerNode } from "../../src/nodes/motion";

describe("FadeInNode", () => {
  it("optional delay/duration, children allowed", () => {
    const r = FadeInNode.parse({
      id: "f", type: "FadeIn",
      props: { delay: 0, duration: 300 },
      children: [],
    });
    expect(r.props.duration).toBe(300);
  });

  it("accepts FadeIn with no props (defaults)", () => {
    const r = FadeInNode.parse({
      id: "f", type: "FadeIn",
      children: [{ id: "c", type: "Box" }],
    });
    expect(r.props).toBeDefined();
    expect(r.children?.length).toBe(1);
  });
});

describe("StaggerNode", () => {
  it("interval positive int", () => {
    expect(() => StaggerNode.parse({ id: "s", type: "Stagger",
      props: { interval: -10 }, children: [] })).toThrow();
  });

  it("interval defaults to 80 when omitted", () => {
    const r = StaggerNode.parse({
      id: "s", type: "Stagger",
      props: {},
      children: [],
    });
    expect(r.props.interval).toBe(80);
  });

  it("accepts Stagger with all props populated", () => {
    const r = StaggerNode.parse({
      id: "s", type: "Stagger",
      props: { delay: 50, interval: 200 },
      children: [],
    });
    expect(r.props.delay).toBe(50);
    expect(r.props.interval).toBe(200);
  });
});

describe("motion strict mode", () => {
  it("FadeInNode rejects unknown props", () => {
    expect(() => FadeInNode.parse({
      id: "f", type: "FadeIn",
      props: { delay: 0, whoops: 1 },
      children: [],
    })).toThrow();
  });

  it("FadeInNode rejects negative delay", () => {
    expect(() => FadeInNode.parse({
      id: "f", type: "FadeIn",
      props: { delay: -100 },
      children: [],
    })).toThrow();
  });

  it("FadeInNode rejects non-positive duration", () => {
    expect(() => FadeInNode.parse({
      id: "f", type: "FadeIn",
      props: { duration: 0 },
      children: [],
    })).toThrow();
  });

  it("StaggerNode rejects unknown props", () => {
    expect(() => StaggerNode.parse({
      id: "s", type: "Stagger",
      props: { interval: 80, whoops: 1 },
      children: [],
    })).toThrow();
  });

  it("StaggerNode rejects empty id", () => {
    expect(() => StaggerNode.parse({
      id: "", type: "Stagger",
      props: { interval: 80 },
      children: [],
    })).toThrow();
  });
});
