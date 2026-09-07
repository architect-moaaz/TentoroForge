import { describe, it, expect } from "vitest";
import { starterRegistry } from "@forge/registry";
import { validateDrop } from "@/components/canvas/hooks/useDrop";
import { hintFor, missingContentProp } from "@/components/canvas/empty-hints";

const ALL_NAMES = Object.keys(starterRegistry as Record<string, unknown>);

// =============================================================================
// Report #8 — "i cannot add every component inside the form only input field"
// =============================================================================
//
// `Form.slots.accepts` was a 6-name whitelist frozen at the size the library was
// when it was written, so it refused 127 of 133 palette components including
// every form control added since. It is now a `rejects` list stating the actual
// invariant. These tests pin BOTH halves: what must now be allowed, and the
// three things that must still be refused.

describe("Form containment (report #8)", () => {
  const accepts = (child: string) => validateDrop("Form", child, 0).ok;

  it("accepts every form control in the library", () => {
    const controls = [
      "Input", "Textarea", "Select", "Checkbox", "Switch", "RadioGroup",
      "NumberInput", "MoneyInput", "DatePicker", "DateRangePicker", "TimePicker",
      "ColorPicker", "Combobox", "MultiSelect", "Cascader", "MaskedInput",
      "Slider", "SegmentedControl", "FileUpload", "KeyValueInput", "InputOTP",
      "Rating", "SearchInput", "Button",
    ];
    expect(controls.filter((c) => !accepts(c))).toEqual([]);
  });

  it("accepts the layout wrappers a real form needs to arrange its fields", () => {
    const wrappers = ["Stack", "Row", "Grid", "Container", "Section", "Card", "Cluster", "Divider"];
    expect(wrappers.filter((w) => !accepts(w))).toEqual([]);
  });

  it("still refuses a nested Form — the HTML parser drops it silently", () => {
    expect(validateDrop("Form", "Form", 0)).toEqual({
      ok: false, reason: "Form does not allow Form",
    });
  });

  it("still refuses the page frame and the fixed inspector", () => {
    expect(accepts("AppShell")).toBe(false);
    expect(accepts("InspectorPanel")).toBe(false);
  });

  it("refuses exactly three components and nothing else", () => {
    // The point of the change: a whitelist silently refuses every component
    // added to the library afterwards; a rejects list cannot.
    const refused = ALL_NAMES.filter((n) => !accepts(n));
    expect(refused.sort()).toEqual(["AppShell", "Form", "InspectorPanel"]);
  });
});

// =============================================================================
// Report #9 — "Every thing i open it shows a blank space and how does user know
// what do do with it"
// =============================================================================

describe("empty-node hints (report #9)", () => {
  it("tells the user to drop something into an empty container", () => {
    for (const c of ["Card", "Stack", "Grid", "Container", "Section", "Form"]) {
      expect(hintFor(c, {})).toMatch(/Drag a component in here/);
      expect(hintFor(c, {})).toContain(c);
    }
  });

  it("names the prop that has to be filled in for a data-driven leaf", () => {
    expect(missingContentProp("Table", {})).toBe("columns");
    expect(hintFor("Table", {})).toMatch(/set “columns”/);
    expect(hintFor("Chart", {})).toMatch(/set “data”/);
  });

  it("stops naming the prop once it is filled in", () => {
    expect(missingContentProp("Table", { columns: [{ key: "a" }] })).not.toBe("columns");
  });

  it("falls back to the registry description so the user at least knows what it is", () => {
    // Sparkline has no content-bearing control prop, and the audit lists it as
    // one of the 10 that render an empty box with default props.
    const hint = hintFor("Sparkline", {});
    expect(hint).toMatch(/^Sparkline — /);
    expect(hint!.length).toBeGreaterThan("Sparkline — ".length);
  });

  it("produces a usable hint for every palette component", () => {
    // The report is explicitly "this is about all component", so a gap here is
    // the defect, not an edge case. GridCell is the one deliberate exception:
    // GridGuides already outlines every cell of a fixed grid.
    const missing = ALL_NAMES.filter((n) => n !== "GridCell" && !hintFor(n, {}));
    expect(missing).toEqual([]);
  });

  it("says nothing for editor-created grid cells", () => {
    expect(hintFor("GridCell", {})).toBeNull();
  });

  it("says nothing for a type the registry has never heard of", () => {
    expect(hintFor("NotAComponent", {})).toBeNull();
  });
});
