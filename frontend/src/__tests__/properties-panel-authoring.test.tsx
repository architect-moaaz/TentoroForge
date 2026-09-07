/**
 * Phase 3a — docs/editor-audit/input-components-2.md D1, "the round-1
 * Select.options fix never reached the panel".
 *
 * PropertiesPanel matched six prop NAMES (data/rows/options/items/entries/
 * records) and, for those, rendered BindingControl *instead of* whatever control
 * the registry declared — and suppressed the bind toggle too. So converting
 * `Select.options` to `type:"array", control:"json"` was correct in the registry
 * and invisible in the editor: the seeded defaults still rendered, but the user
 * had no way to edit the option list. The ~26 array props converted alongside it
 * would have been shadowed the same way.
 *
 * The rule now: a prop whose registry type the panel can AUTHOR (array/object)
 * gets its control AND the bind toggle. Only props with no authoring UI (still
 * typed action/binding) surface the data picker directly.
 */
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { starterRegistry } from "@forge/registry";
import { PropertiesPanelInner } from "@/components/properties/PropertiesPanel";
import { useEditorStore } from "@/lib/editor-store";

vi.mock("next/navigation", () => ({ useParams: () => ({ projectId: "p1" }) }));

function seed(node: unknown) {
  useEditorStore.setState({
    artifacts: {
      pageSchemas: {
        home: {
          schemaVersion: "2", id: "home", route: "/",
          root: { id: "root", type: "Stack", children: [node] },
          dataSources: [],
        },
      },
      navFlow: {
        version: "1.0", initialPage: "home",
        pages: [{ id: "home", route: "/", title: "Home",
                  schemaFile: "src/schemas/home.json", params: [] }],
        transitions: [], guards: {},
      },
      tokens: {},
    } as never,
    selectedNodeIds: ["probe"], selectedNodeId: "probe",
    currentPageId: "home", undoStack: [], redoStack: [], lastError: null,
  });
}

function nodeProps(): Record<string, unknown> {
  const a = useEditorStore.getState().artifacts as never as {
    pageSchemas: { home: { root: { children: Array<{ props?: Record<string, unknown> }> } } };
  };
  return a.pageSchemas.home.root.children[0].props ?? {};
}

/** The BindingControl dropdown — the control that used to shadow everything. */
const dataPickers = () => screen.queryAllByTitle("Bind this prop to a data field");

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404 })) as never);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useEditorStore.setState({
    artifacts: null, selectedNodeIds: [], selectedNodeId: null,
    undoStack: [], redoStack: [], lastError: null,
  });
});

describe("an array-typed prop renders its own control AND a bind toggle", () => {
  it("the registry still types Select.options as an authorable array", () => {
    // If this flips back to action/actionPicker the panel is not the thing at fault.
    expect(starterRegistry.Select.props.options.type).toBe("array");
  });

  it("Select.options gets the row editor, not the data-source dropdown", () => {
    seed({ id: "probe", type: "Select", props: {} });
    render(<PropertiesPanelInner />);
    // The registry default is [{value:"one",…},{value:"two",…}] — editable rows.
    expect((screen.getByLabelText("options row 1 value") as HTMLInputElement).value).toBe("one");
    expect((screen.getByLabelText("options row 2 label") as HTMLInputElement).value)
      .toBe("Option two");
    // Exactly one data picker on this node — the `bind` prop's. Before the fix
    // `options` had one too, and no control of its own.
    expect(dataPickers()).toHaveLength(1);
  });

  it("and the bind toggle is no longer suppressed for it", () => {
    seed({ id: "probe", type: "Select", props: {} });
    render(<PropertiesPanelInner />);
    const toggle = screen.getByLabelText(/^options: literal value/);
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    // Authoring OR binding — clicking through reaches the picker the old code
    // showed unconditionally.
    fireEvent.click(toggle);
    expect(screen.queryByLabelText("options row 1 value")).toBeNull();
    expect(screen.getByLabelText(/^options: bound to data/)).toBeTruthy();
    expect(dataPickers()).toHaveLength(2);
  });

  it("editing a row writes the whole array back to the schema", () => {
    seed({ id: "probe", type: "RadioGroup", props: {} });
    render(<PropertiesPanelInner />);
    const cell = screen.getByLabelText("options row 1 label");
    fireEvent.change(cell, { target: { value: "First choice" } });
    fireEvent.blur(cell);
    expect(nodeProps().options).toEqual([
      { value: "one", label: "First choice" },
      { value: "two", label: "Option two" },
    ]);
  });
});

describe("props the panel cannot author keep the direct data picker", () => {
  it("ResourceTimeline.items (type: binding) shows the dropdown and no toggle", () => {
    seed({ id: "probe", type: "ResourceTimeline", props: {} });
    render(<PropertiesPanelInner />);
    expect(screen.queryByLabelText(/^items: literal value/)).toBeNull();
    expect(screen.queryByLabelText("items row 1 value")).toBeNull();
    // `items` and `resources` are both binding-typed data props.
    expect(dataPickers().length).toBeGreaterThanOrEqual(2);
  });

  it("Textarea.rows is still a number field, not a data source", () => {
    // The pre-existing numeric carve-out: `rows` means row COUNT here.
    seed({ id: "probe", type: "Textarea", props: {} });
    render(<PropertiesPanelInner />);
    expect((screen.getByLabelText("rows") as HTMLInputElement).type).toBe("number");
  });
});

describe("Phase 7 — required props are marked, and the bind toggle has a name", () => {
  it("marks the props the component contract says it cannot render without", () => {
    seed({ id: "probe", type: "Select", props: {} });
    render(<PropertiesPanelInner />);
    // Select: name, label, options are required; `bind` is not.
    expect(screen.getAllByText("required")).toHaveLength(3);
    expect(screen.getByTitle(/^options is required/)).toBeTruthy();
  });

  it("says nothing for a component with no required props", () => {
    seed({ id: "probe", type: "AppShell", props: {}, children: [] });
    render(<PropertiesPanelInner />);
    expect(screen.queryAllByText("required")).toHaveLength(0);
  });

  it("every bind toggle names its prop and the action", () => {
    seed({ id: "probe", type: "RadioGroup", props: {} });
    render(<PropertiesPanelInner />);
    for (const p of ["name", "label", "options", "orientation", "required", "disabled"]) {
      expect(screen.getByLabelText(`${p}: literal value — click to bind to data`)).toBeTruthy();
    }
  });
});
