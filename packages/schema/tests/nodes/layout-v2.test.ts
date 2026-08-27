import { describe, it, expect } from "vitest";
import { SplitNode, SidebarNode, ClusterNode, TabsNode, AccordionNode }
  from "../../src/nodes/layout-v2";

describe("SplitNode", () => {
  it("requires exactly 2 children", () => {
    expect(() => SplitNode.parse({ id: "s", type: "Split",
      props: { ratio: "1:1" }, children: [] })).toThrow();
    const r = SplitNode.parse({
      id: "s", type: "Split",
      props: { ratio: "2:1", breakpoint: "md" },
      children: [{ id: "a", type: "Box" }, { id: "b", type: "Box" }],
    });
    expect(r.props.ratio).toBe("2:1");
  });
});

describe("SidebarNode", () => {
  it("requires exactly 2 children", () => {
    expect(() => SidebarNode.parse({ id: "s", type: "Sidebar",
      props: { width: "240px" }, children: [{ id: "a", type: "Box" }] })).toThrow();
  });
});

describe("ClusterNode", () => {
  it("accepts children array", () => {
    const r = ClusterNode.parse({
      id: "c", type: "Cluster",
      props: { gap: "tokens.spacing.4", justify: "start", align: "center" },
      children: [],
    });
    expect(r.props.justify).toBe("start");
  });

  // Codifies the v4 spike CSS fix as schema props — the renderer switches
  // Cluster's underlying display from flex+flex-wrap+justify-between
  // (content-sized children) to CSS grid with N equal-width columns when
  // equalCols is true, so KPI tile rows render visually even.
  it("accepts equalCols for equal-width tiles", () => {
    const r = ClusterNode.safeParse({
      id: "c", type: "Cluster",
      props: { equalCols: true },
      children: [],
    });
    expect(r.success).toBe(true);
    if (r.success) expect(r.data.props.equalCols).toBe(true);
  });

  it("accepts equalRows alongside equalCols", () => {
    const r = ClusterNode.safeParse({
      id: "c", type: "Cluster",
      props: { equalCols: true, equalRows: true },
      children: [],
    });
    expect(r.success).toBe(true);
  });

  it("rejects non-boolean equalCols (strict mode)", () => {
    const r = ClusterNode.safeParse({
      id: "c", type: "Cluster",
      props: { equalCols: "always" },
      children: [],
    });
    expect(r.success).toBe(false);
  });
});

describe("TabsNode", () => {
  it("children length must match tabs[] length", () => {
    expect(() => TabsNode.parse({
      id: "t", type: "Tabs",
      props: { tabs: [{ id: "a", label: "A" }, { id: "b", label: "B" }], value: "a" },
      children: [{ id: "p1", type: "Box" }],
    })).toThrow();

    const r = TabsNode.parse({
      id: "t", type: "Tabs",
      props: { tabs: [{ id: "a", label: "A" }], value: "a" },
      children: [{ id: "p1", type: "Box" }],
    });
    expect(r.props.tabs.length).toBe(1);
  });
});

describe("AccordionNode", () => {
  it("accepts mode + defaultOpen list", () => {
    const r = AccordionNode.parse({
      id: "a", type: "Accordion",
      props: { mode: "single", defaultOpen: ["p1"] },
      children: [{ id: "p1", type: "AccordionPanel",
                   props: { label: "First", value: "p1" }, children: [] }],
    });
    expect(r.props.mode).toBe("single");
  });
});

describe("layout-v2 strict mode", () => {
  it("SplitNode rejects unknown props", () => {
    expect(() => SplitNode.parse({
      id: "s", type: "Split",
      props: { ratio: "1:1", whoops: "extra" },
      children: [{ id: "a", type: "Box" }, { id: "b", type: "Box" }],
    })).toThrow();
  });

  it("ClusterNode rejects empty id", () => {
    expect(() => ClusterNode.parse({
      id: "", type: "Cluster",
      props: { justify: "start", align: "center" },
      children: [],
    })).toThrow();
  });

  it("TabsNode rejects empty tab id/label", () => {
    expect(() => TabsNode.parse({
      id: "t", type: "Tabs",
      props: { tabs: [{ id: "", label: "A" }], value: "a" },
      children: [{ id: "p1", type: "Box" }],
    })).toThrow();
  });

  it("SidebarNode accepts valid widths and rejects invalid ones", () => {
    const valid = SidebarNode.parse({
      id: "s", type: "Sidebar",
      props: { width: "240px" },
      children: [{ id: "a", type: "Box" }, { id: "b", type: "Box" }],
    });
    expect(valid.props.width).toBe("240px");

    expect(SidebarNode.parse({
      id: "s", type: "Sidebar",
      props: { width: "15rem" },
      children: [{ id: "a", type: "Box" }, { id: "b", type: "Box" }],
    }).props.width).toBe("15rem");

    // Reject viewport units, "auto", and bare numbers
    expect(() => SidebarNode.parse({
      id: "s", type: "Sidebar",
      props: { width: "100vh" },
      children: [{ id: "a", type: "Box" }, { id: "b", type: "Box" }],
    })).toThrow();
    expect(() => SidebarNode.parse({
      id: "s", type: "Sidebar",
      props: { width: "auto" },
      children: [{ id: "a", type: "Box" }, { id: "b", type: "Box" }],
    })).toThrow();
  });

  it("ClusterNode rejects invalid justify/align values", () => {
    expect(() => ClusterNode.parse({
      id: "c", type: "Cluster",
      props: { justify: "middle", align: "center" }, // "middle" not in enum
      children: [],
    })).toThrow();
    expect(() => ClusterNode.parse({
      id: "c", type: "Cluster",
      props: { justify: "start", align: "flex-start" }, // "flex-start" not in enum
      children: [],
    })).toThrow();
  });

  it("AccordionNode rejects unknown props (strict mode)", () => {
    expect(() => AccordionNode.parse({
      id: "a", type: "Accordion",
      props: { mode: "single", whoops: 1 },
      children: [],
    })).toThrow();
  });

  it("AccordionPanel rejects empty label", () => {
    expect(() => AccordionNode.parse({
      id: "a", type: "Accordion",
      props: { mode: "single" },
      children: [{ id: "p1", type: "AccordionPanel",
                   props: { label: "", value: "p1" },
                   children: [] }],
    })).toThrow();
  });
});
