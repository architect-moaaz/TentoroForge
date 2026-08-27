import { describe, it, expect } from "vitest";
import { starterRegistry } from "../src/starter";
import { registryDigest } from "../src/digest";

describe("starterRegistry", () => {
  it("contains the core 12 components", () => {
    for (const name of ["Container", "Grid", "Card", "Divider", "Spacer",
                        "Input", "Textarea", "Select", "Checkbox", "Button",
                        "Heading", "NavLink"]) {
      expect(starterRegistry[name], `${name} missing from starter`).toBeDefined();
    }
  });

  it("every prop has a control + group", () => {
    for (const [cName, entry] of Object.entries(starterRegistry)) {
      for (const [pName, p] of Object.entries(entry.props)) {
        expect(p.control, `${cName}.${pName} missing control`).toBeDefined();
        expect(p.group, `${cName}.${pName} missing group`).toBeDefined();
      }
    }
  });

  it("every component has a category and slot rule", () => {
    for (const [cName, entry] of Object.entries(starterRegistry)) {
      expect(entry.category, `${cName} missing category`).toBeDefined();
      expect(entry.slots, `${cName} missing slots`).toBeDefined();
      expect(["leaf", "single", "list"]).toContain(entry.slots.type);
    }
  });

  it("Button exposes its editable props", () => {
    // Spec §13.2 listed only the original five; the editable surface has since
    // grown (opensDialog, clearsFilters). Assert the CURRENT set so the test
    // fails loudly on accidental drift rather than freezing a stale list.
    const b = starterRegistry.Button;
    expect(b.slots.type).toBe("leaf");
    expect(Object.keys(b.props).sort()).toEqual(
      ["clearsFilters", "disabled", "label", "onClick", "opensDialog", "size", "variant"]
    );
    // Reset-all-filters must stay a user-toggleable behaviour in the editor.
    expect(b.props.clearsFilters.control).toBe("toggle");
  });

  it("contains the extended set of frequently-used components", () => {
    for (const name of ["Hero", "Card", "MetricTile", "Avatar", "Stack", "Row"]) {
      expect(starterRegistry[name], `${name} missing from starter`).toBeDefined();
    }
  });

  it("Hero has content + style + behavior props", () => {
    const groups = new Set(Object.values(starterRegistry.Hero.props).map(p => p.group));
    expect(groups.has("content")).toBe(true);
    expect(groups.has("style")).toBe(true);
    expect(groups.has("behavior")).toBe(true);
  });

  it("Avatar includes photoUrl", () => {
    expect(starterRegistry.Avatar.props.photoUrl).toBeDefined();
  });

  it("MetricTile importance is a select with three options", () => {
    const p = starterRegistry.MetricTile.props.importance;
    expect(p.control).toBe("select");
    expect(p.options).toEqual(expect.arrayContaining(["primary", "secondary", "tertiary"]));
  });

  it("contains the extended set of input + display + layout components", () => {
    for (const name of ["Section", "Table", "Tabs", "TabPanel", "Badge", "Breadcrumb",
                        "Alert", "EmptyState", "Form", "IconButton"]) {
      expect(starterRegistry[name], `${name} missing`).toBeDefined();
    }
  });

  it("Tabs only accepts TabPanel children", () => {
    const s = starterRegistry.Tabs.slots;
    expect(s.type).toBe("list");
    if (s.type === "list") {
      expect(s.accepts).toEqual(["TabPanel"]);
    }
  });

  it("Form accepts standard form children", () => {
    const s = starterRegistry.Form.slots;
    expect(s.type).toBe("list");
    if (s.type === "list") {
      expect(s.accepts).toEqual(expect.arrayContaining(["Input", "Button"]));
    }
  });

  it("contains B1 layout extension", () => {
    for (const name of ["Sidebar", "Cluster", "Split", "AppShell", "InspectorPanel", "TabPanelWithDeepLink"]) {
      expect(starterRegistry[name], `${name} missing`).toBeDefined();
    }
  });

  it("contains B2 data components", () => {
    for (const name of ["Chart", "Sparkline", "DataGrid", "Timeline", "TableSortable"]) {
      expect(starterRegistry[name], `${name} missing`).toBeDefined();
    }
  });

  it("contains B3 enterprise batch 2", () => {
    for (const name of ["ApprovalStepper", "PersonCard", "FilterBar", "CommandPalette", "ActivityFeed"]) {
      expect(starterRegistry[name], `${name} missing`).toBeDefined();
    }
  });

  it("contains B4 enterprise batch 3 + misc", () => {
    for (const name of ["EmptyStateRich", "DateRangePicker", "MultiSelect", "FeatureCard", "Skeleton", "LoadingState", "KeyValueList"]) {
      expect(starterRegistry[name], `${name} missing`).toBeDefined();
    }
  });

  it("contains B5 input + motion", () => {
    for (const name of ["Link", "DatePicker", "FadeIn", "Stagger"]) {
      expect(starterRegistry[name], `${name} missing`).toBeDefined();
    }
  });

  it("Cluster + Split have list slots", () => {
    expect(starterRegistry.Cluster.slots.type).toBe("list");
    expect(starterRegistry.Split.slots.type).toBe("list");
  });

  it("Chart accepts data array (actionPicker control)", () => {
    const props = starterRegistry.Chart.props;
    const hasAction = Object.values(props).some(p => p.control === "actionPicker");
    expect(hasAction).toBe(true);
  });
});

describe("registryDigest", () => {
  it("returns a non-empty string", () => {
    const d = registryDigest(starterRegistry);
    expect(d.length).toBeGreaterThan(100);
  });

  it("includes component names + slot indicators", () => {
    const d = registryDigest(starterRegistry);
    expect(d).toContain("Button (leaf)");
    expect(d).toMatch(/Container \[.+children\]/);
  });

  it("includes enum prop options", () => {
    const d = registryDigest(starterRegistry);
    expect(d).toMatch(/variant:primary\|secondary\|ghost/);
  });
});
