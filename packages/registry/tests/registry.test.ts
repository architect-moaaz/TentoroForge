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
    // grown. Assert the CURRENT set so the test fails loudly on accidental drift
    // rather than freezing a stale list.
    //
    // The eleven added here are not new features — they are prop surface
    // Button.schema.ts has always had and the panel could not reach, so the
    // component could navigate, dispatch a workflow with arguments, submit a
    // form, show a spinner or carry an icon while the editor could express none
    // of it. `navigate`/`workflow`/`submit` are the three declarative behaviours
    // Button actually implements.
    const b = starterRegistry.Button;
    expect(b.slots.type).toBe("leaf");
    expect(Object.keys(b.props).sort()).toEqual(
      ["args", "aria-label", "clearsFilters", "dataJourney", "disabled", "icon",
       "iconPosition", "iconSrc", "label", "loading", "navigate", "onClick",
       "opensDialog", "size", "submit", "togglesSidebar", "variant", "workflow"]
    );
    // Reset-all-filters must stay a user-toggleable behaviour in the editor.
    expect(b.props.clearsFilters.control).toBe("toggle");
  });

  it("Button.variant offers every variant the component implements", () => {
    // The registry used to offer three of the component's five, which made a red
    // destructive button impossible to author: `danger` and `accent` exist in
    // Button.schema.ts's enum and were simply absent from the select.
    expect(starterRegistry.Button.props.variant.options).toEqual(
      ["primary", "secondary", "accent", "danger", "ghost"]
    );
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

  it("Form accepts any child except the three that genuinely break it", () => {
    // This used to assert a six-entry `accepts` whitelist. That whitelist was
    // replaced by a `rejects` list because it refused 127 of the library's
    // components — NumberInput, DatePicker, MultiSelect and every layout
    // wrapper included — so the test has to move with it: an `accepts` of
    // `undefined` now means "everything", which is the point.
    const s = starterRegistry.Form.slots;
    expect(s.type).toBe("list");
    if (s.type === "list") {
      expect(s.accepts).toBeUndefined();
      // Nested <form> is dropped by the HTML parser; AppShell is the page frame
      // a Form lives inside; InspectorPanel is position:fixed and renders
      // nothing until a URL param is set.
      expect(s.rejects).toEqual(expect.arrayContaining(["Form", "AppShell", "InspectorPanel"]));
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

  it("Chart's data + series are authorable arrays, NOT actionPickers", () => {
    // The inverse of what this test used to assert. It froze the bug in place:
    // `actionPicker`'s only output is `{ action: "navigate" | "workflow", … }`,
    // and writing that into an array-typed prop makes validateProps' step-3
    // coercion replace the whole prop with `[]`. A Chart whose data and series
    // are both picked from the action menu is a Chart with no data and no
    // series — the control emptied the props it existed to fill. `json` can
    // express the real shape, and the defaults are seeded so a Chart dropped
    // from the palette draws something instead of empty axes.
    const props = starterRegistry.Chart.props;
    expect(Object.values(props).some(p => p.control === "actionPicker")).toBe(false);
    for (const name of ["data", "series"] as const) {
      expect(props[name].type, name).toBe("array");
      expect(props[name].control, name).toBe("json");
      expect(Array.isArray(props[name].default), name).toBe(true);
      expect((props[name].default as unknown[]).length, name).toBeGreaterThan(0);
    }
  });

  it("actionPicker is used by exactly one prop in the whole registry", () => {
    // Button.onClick is the only prop whose schema slot IS a NavActionDescriptor
    // (`onClick: z.unknown()`, documented as such in Button.schema.ts) and whose
    // component knows how to read one. 35 other props were wired to the same
    // control and every one of them was a shape ActionPicker cannot emit — an
    // array of columns, a `{ label, href }` CTA, a record of default values.
    // See docs/editor-audit/input-components-2.md.
    const found: string[] = [];
    for (const [cName, entry] of Object.entries(starterRegistry)) {
      for (const [pName, p] of Object.entries(entry.props)) {
        if (p.control === "actionPicker") found.push(`${cName}.${pName}`);
      }
    }
    expect(found).toEqual(["Button.onClick"]);
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
    // Button.variant, widened to the component's real five-value enum — the
    // digest is what the LLM composer reads, so `danger` has to appear here or
    // generated pages still cannot ask for a destructive button.
    const d = registryDigest(starterRegistry);
    expect(d).toMatch(/variant:primary\|secondary\|accent\|danger\|ghost/);
  });
});
