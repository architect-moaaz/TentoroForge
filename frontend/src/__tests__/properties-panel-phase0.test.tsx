/**
 * Phase 0 regressions in the Properties panel.
 *
 *  1. docs/editor-audit/panels.md — "a breakpoint override on a prop with no
 *     base value renders raw JSON". writePropAtBp wrapped a non-default-bp edit
 *     as { default: currentRaw, [bp]: value }; with the prop unset currentRaw
 *     was undefined, the key vanished on JSON.stringify, and the schema held
 *     the base-less envelope { lg: "…" } that the engine printed verbatim.
 *
 *  2. docs/editor-audit/containment.md #1 — the four AppShell composition slots
 *     were wired to `actionPicker`, whose only output is an action object;
 *     AppShell renders those props in React child position, so picking any
 *     action blanked the entire page.
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { starterRegistry } from "@forge/registry";
import { PropertiesPanelInner } from "@/components/properties/PropertiesPanel";
import { JsonControl } from "@/components/properties/PropControls";
import { useEditorStore } from "@/lib/editor-store";

function seed(node: unknown) {
  useEditorStore.setState({
    artifacts: {
      pageSchemas: {
        home: {
          schemaVersion: "2", id: "home", route: "/",
          root: { id: "root", type: "Stack", children: [node] },
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

/** Click the BreakpointSwitcher's `lg` button. */
function switchToLg() {
  fireEvent.click(screen.getByTitle("Override for LG+"));
}

afterEach(() => {
  cleanup();
  useEditorStore.setState({
    artifacts: null, selectedNodeIds: [], selectedNodeId: null,
    undoStack: [], redoStack: [], lastError: null,
  });
});

describe("Properties panel — a breakpoint override never leaves a base-less envelope", () => {
  it("seeds `default` from the registry default when the prop was unset", () => {
    seed({ id: "probe", type: "Badge", props: {} });
    render(<PropertiesPanelInner />);
    switchToLg();
    fireEvent.change(screen.getByLabelText("content"), { target: { value: "ONLYLGBADGE" } });
    const written = nodeProps().content as Record<string, unknown>;
    expect(written).toMatchObject({ lg: "ONLYLGBADGE" });
    expect(Object.keys(written)).toContain("default");
    expect(written.default).toBe(starterRegistry.Badge.props.content.default);
    // The whole point: JSON round-tripping keeps the base, so the resolver
    // never has to fall through to the envelope.
    expect(JSON.parse(JSON.stringify(written))).toHaveProperty("default");
  });

  it("keeps an existing base value as the base", () => {
    seed({ id: "probe", type: "Badge", props: { content: "BASE" } });
    render(<PropertiesPanelInner />);
    switchToLg();
    fireEvent.change(screen.getByLabelText("content"), { target: { value: "LGONLY" } });
    expect(nodeProps().content).toEqual({ default: "BASE", lg: "LGONLY" });
  });

  it("a default-breakpoint edit still writes a plain literal", () => {
    seed({ id: "probe", type: "Badge", props: {} });
    render(<PropertiesPanelInner />);
    fireEvent.change(screen.getByLabelText("content"), { target: { value: "PLAIN" } });
    expect(nodeProps().content).toBe("PLAIN");
  });
});

describe("AppShell composition slots — the panel can no longer write a crashing value", () => {
  it("registry routes all four slots to the JSON control, not actionPicker", () => {
    for (const p of ["sidebar", "topbar", "actions", "rightRail"] as const) {
      expect(starterRegistry.AppShell.props[p].control).toBe("json");
    }
  });

  it("the panel renders a JSON textarea for AppShell.sidebar", () => {
    seed({ id: "probe", type: "AppShell", props: {}, children: [] });
    render(<PropertiesPanelInner />);
    expect(screen.getByLabelText("sidebar JSON")).toBeTruthy();
    // The ActionPicker's type dropdown — the control that wrote the crashing
    // value — is gone from this node's panel.
    expect(screen.queryByText("Navigate")).toBeNull();
  });

  it("commits a schema sub-tree as a parsed object on blur", () => {
    seed({ id: "probe", type: "AppShell", props: {}, children: [] });
    render(<PropertiesPanelInner />);
    const box = screen.getByLabelText("sidebar JSON");
    fireEvent.change(box, {
      target: { value: '{"id":"nav","type":"SideNav","props":{}}' },
    });
    fireEvent.blur(box);
    expect(nodeProps().sidebar).toEqual({ id: "nav", type: "SideNav", props: {} });
  });
});

describe("JsonControl — parse-or-refuse, commit-on-blur", () => {
  it("writes nothing while typing", () => {
    const onChange = vi.fn();
    render(<JsonControl label="sidebar" value={undefined} onChange={onChange} />);
    const box = screen.getByLabelText("sidebar JSON");
    for (const v of ['{', '{"t', '{"type"', '{"type":"X"}']) {
      fireEvent.change(box, { target: { value: v } });
    }
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(box);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ type: "X" });
  });

  it("refuses unparseable JSON, surfaces the error, and commits nothing", () => {
    const onChange = vi.fn();
    render(<JsonControl label="sidebar" value={undefined} onChange={onChange} />);
    const box = screen.getByLabelText("sidebar JSON");
    fireEvent.change(box, { target: { value: '{"type": ' } });
    fireEvent.blur(box);
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("Not saved");
  });

  it("an emptied box clears the prop", () => {
    const onChange = vi.fn();
    render(<JsonControl label="sidebar" value={{ type: "SideNav" }} onChange={onChange} />);
    const box = screen.getByLabelText("sidebar JSON");
    fireEvent.change(box, { target: { value: "  " } });
    fireEvent.blur(box);
    expect(onChange).toHaveBeenCalledWith(undefined);
  });
});
