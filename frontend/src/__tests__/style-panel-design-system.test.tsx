/**
 * STYLE panel — Design System block regression tests.
 *
 * Two bugs are locked in here.
 *
 * 1. The three controls read and wrote `tokens.system.<key>`, a group nothing
 *    consumes. The library reads `tokens.density`, `tokens.elevation` and
 *    `tokens.radius.scale` (packages/library/src/theme/tokens-context.tsx), so
 *    every selection persisted to tokens.custom.json and changed nothing on
 *    screen. These assert the dispatched PATHS, since the path is the whole bug.
 *
 * 2. The option lists had drifted from the library's unions: "cozy" (Density is
 *    compact|comfortable|spacious) and "rounded"/"pill" (RadiusScale is
 *    sharp|soft|round) resolved to `undefined` in the components' class maps.
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup, fireEvent } from "@testing-library/react";
import { defaultTokens } from "@tentoroforge/library";
import { StylePanel } from "@/components/properties/StylePanel";
import { useEditorStore } from "@/lib/editor-store";

function seedTokens(tokens: unknown) {
  useEditorStore.setState({
    artifacts: { pageSchemas: {}, navFlow: { pages: [] }, tokens } as never,
    undoStack: [], redoStack: [],
  });
}

/** The shape live projects carry today — real choices in the dead group. */
const LEGACY = { system: { density: "compact", elevation: "flat", radiusScale: "soft" } };

/** The Design System block is the last three <select>s in the panel; with no
 *  node selected the per-node controls are hidden, so they are the ONLY three.
 *  Positional lookup because the block labels its controls with plain <div>s
 *  rather than <label for=…>, so getByLabelText finds nothing. */
function designSystemSelects(): HTMLSelectElement[] {
  return [...document.querySelectorAll("select")].slice(-3);
}

afterEach(() => {
  cleanup();
  useEditorStore.setState({ artifacts: null, undoStack: [], redoStack: [] });
});

describe("Design System controls write the paths the library reads", () => {
  it.each([
    ["Density", "spacious", ["density"]],
    ["Elevation", "floating", ["elevation"]],
    ["Radius scale", "round", ["radius", "scale"]],
  ] as const)("%s → %s dispatches updateToken at %j", (label, value, path) => {
    seedTokens({ color: {} });
    const batch = vi.spyOn(useEditorStore.getState(), "dispatchBatch");
    render(<StylePanel />);
    const i = ["Density", "Elevation", "Radius scale"].indexOf(label);
    fireEvent.change(designSystemSelects()[i], { target: { value } });
    expect(batch).toHaveBeenCalledWith([
      { type: "updateToken", path: [...path], value },
    ]);
    batch.mockRestore();
  });

  it("shows defaultTokens values when the project overrides nothing", () => {
    seedTokens({ color: {} });
    render(<StylePanel />);
    const selects = designSystemSelects();
    expect(selects[0].value).toBe(defaultTokens.density);
    expect(selects[1].value).toBe(defaultTokens.elevation);
    expect(selects[2].value).toBe(defaultTokens.radius.scale);
  });
});

describe("Design System migrates off the dead `system` group", () => {
  it("displays a legacy value rather than falling back to the default", () => {
    seedTokens({ ...LEGACY });
    render(<StylePanel />);
    const selects = designSystemSelects();
    expect(selects[0].value).toBe("compact"); // from system.density, not "comfortable"
    expect(selects[1].value).toBe("flat");
  });

  it("moves the untouched siblings across and drops the whole group", () => {
    seedTokens({ ...LEGACY });
    const batch = vi.spyOn(useEditorStore.getState(), "dispatchBatch");
    render(<StylePanel />);
    fireEvent.change(designSystemSelects()[0], {
      target: { value: "spacious" },
    });
    expect(batch).toHaveBeenCalledWith([
      { type: "updateToken", path: ["density"], value: "spacious" },
      { type: "updateToken", path: ["elevation"], value: "flat" },
      { type: "updateToken", path: ["radius", "scale"], value: "soft" },
      { type: "removeToken", path: ["system"] },
    ]);
    batch.mockRestore();
  });

  it("keeps a `system` group that holds anything else, removing only our keys", () => {
    seedTokens({ system: { density: "compact", somethingElse: "keep me" } });
    const batch = vi.spyOn(useEditorStore.getState(), "dispatchBatch");
    render(<StylePanel />);
    fireEvent.change(designSystemSelects()[1], {
      target: { value: "floating" },
    });
    expect(batch).toHaveBeenCalledWith([
      { type: "updateToken", path: ["elevation"], value: "floating" },
      { type: "updateToken", path: ["density"], value: "compact" },
      { type: "removeToken", path: ["system", "density"] },
    ]);
    batch.mockRestore();
  });

  it("really lands the value where useDensity/useRadiusScale look for it", () => {
    seedTokens({ ...LEGACY });
    render(<StylePanel />);
    fireEvent.change(designSystemSelects()[2], {
      target: { value: "round" },
    });
    const t = (useEditorStore.getState().artifacts as never as { tokens: any }).tokens;
    expect(t.radius.scale).toBe("round");
    expect(t.density).toBe("compact");   // migrated, not stranded
    expect(t.system).toBeUndefined();    // no stale duplicate left behind
  });
});

describe("Design System option lists match the library's unions", () => {
  it("offers exactly the Density / Elevation / RadiusScale members", () => {
    seedTokens({ color: {} });
    render(<StylePanel />);
    const selects = designSystemSelects();
    expect([...selects[0].options].map((o) => o.value))
      .toEqual(["compact", "comfortable", "spacious"]);
    expect([...selects[1].options].map((o) => o.value))
      .toEqual(["flat", "bordered", "layered", "floating"]);
    expect([...selects[2].options].map((o) => o.value))
      .toEqual(["sharp", "soft", "round"]);
  });
});
