/**
 * TOKENS panel regression test.
 *
 * The live project gh0mlpbp ships the generator's untouched override stub —
 * src/theme/tokens.custom.json = {"color":{},"typography":{},"spacing":{},…} —
 * and Canvas.tsx seeds `artifacts.tokens` from exactly that file. The panel used
 * to render those empty groups directly, so it drew its section headings and
 * nothing else while never hitting the "No tokens loaded." guard. These tests
 * lock in the fix: the panel renders defaultTokens merged UNDER the project
 * overrides, and an edit dispatches an overrides-only updateToken.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { defaultTokens } from "@tentoroforge/library";
import { TokenEditor } from "@/components/editor/TokenEditor";
import { useEditorStore } from "@/lib/editor-store";

/** The exact stub Canvas.tsx seeds for gh0mlpbp. */
const EMPTY_STUB = {
  color: {}, typography: {}, spacing: {},
  radius: {}, shadow: {}, motion: {}, breakpoints: {},
  system: { density: "compact", elevation: "flat", radiusScale: "soft" },
};

function seedTokens(tokens: unknown) {
  useEditorStore.setState({
    artifacts: { pageSchemas: {}, navFlow: { pages: [] }, tokens } as never,
    undoStack: [], redoStack: [],
  });
}

afterEach(() => {
  cleanup();
  useEditorStore.setState({ artifacts: null, undoStack: [], redoStack: [] });
});

describe("TokenEditor — empty override file still lists the real tokens", () => {
  beforeEach(() => seedTokens(EMPTY_STUB));

  it("does NOT show the 'No tokens loaded.' guard (tokens object is truthy)", () => {
    render(<TokenEditor />);
    expect(screen.queryByText("No tokens loaded.")).toBeNull();
  });

  it("lists color swatches from defaultTokens", () => {
    render(<TokenEditor />);
    // color.primary.500 — a default, absent from the override stub.
    const swatch = screen.getByLabelText("color.primary.500") as HTMLInputElement;
    expect(swatch.value).toBe(defaultTokens.color.primary["500"]);
    // The nested `color.text.*` / `color.sidebar.*` groups render too.
    expect((screen.getByLabelText("color.text.primary") as HTMLInputElement).value)
      .toBe(defaultTokens.color.text.primary);
  });

  it("lists nested spacing + motion leaves as text inputs, not [object Object]", () => {
    const { container } = render(<TokenEditor />);
    const values = [...container.querySelectorAll<HTMLInputElement>("input[type=text]")]
      .map((i) => i.value);
    expect(values).toContain("1rem");              // spacing.4
    expect(values).toContain("2rem");              // spacing.semantic.page (nested)
    expect(values).toContain("150ms");             // motion.duration.fast (nested)
    expect(values).not.toContain("[object Object]");
    expect(values.some((v) => v === "NaN")).toBe(false);
  });

  it("lists typography.font under 'Font family' (the panel used to read fontFamily)", () => {
    render(<TokenEditor />);
    expect((screen.getByLabelText("typography.font.body") as HTMLInputElement).value)
      .toBe(defaultTokens.typography.font.body);
    expect((screen.getByLabelText("typography.scale.h1") as HTMLInputElement).value)
      .toBe(defaultTokens.typography.scale.h1);
  });

  it("offers no remove button for default-supplied tokens (nothing to delete)", () => {
    render(<TokenEditor />);
    expect(screen.queryByLabelText("Remove color.primary.500")).toBeNull();
  });
});

describe("TokenEditor — project overrides win and edits stay overrides-only", () => {
  it("renders the project's override on top of the default", () => {
    seedTokens({ ...EMPTY_STUB, color: { primary: { "500": "#92400e" } } });
    render(<TokenEditor />);
    expect((screen.getByLabelText("color.primary.500") as HTMLInputElement).value)
      .toBe("#92400e");
    // Sibling defaults survive the merge (deep, not group-level replace).
    expect((screen.getByLabelText("color.primary.600") as HTMLInputElement).value)
      .toBe(defaultTokens.color.primary["600"]);
    // An override IS removable.
    expect(screen.getByLabelText("Remove color.primary.500")).toBeTruthy();
  });

  it("editing a default dispatches updateToken and writes ONLY that path", () => {
    seedTokens(EMPTY_STUB);
    const dispatch = vi.spyOn(useEditorStore.getState(), "dispatch");
    render(<TokenEditor />);
    const swatch = screen.getByLabelText("color.primary.500");
    fireEvent.change(swatch, { target: { value: "#123456" } });
    // Commit is on blur (or after the drag debounce) — see the undo-storm
    // tests below for why the colour picker no longer writes per change event.
    fireEvent.blur(swatch);
    expect(dispatch).toHaveBeenCalledWith({
      type: "updateToken", path: ["color", "primary", "500"], value: "#123456",
    });
    dispatch.mockRestore();
  });

  it("a spacing edit stores the CSS string, not Number()'d NaN", () => {
    seedTokens(EMPTY_STUB);
    render(<TokenEditor />);
    const spacing = screen.getByLabelText("spacing.4");
    fireEvent.change(spacing, { target: { value: "1.5rem" } });
    fireEvent.blur(spacing);
    const stored = (useEditorStore.getState().artifacts as never as {
      tokens: { spacing: Record<string, unknown> };
    }).tokens.spacing;
    expect(stored["4"]).toBe("1.5rem");
    // The override document stayed an override document — the untouched
    // defaults were NOT materialised into it (which would freeze them on disk).
    expect(Object.keys(stored)).toEqual(["4"]);
  });
});

/**
 * Regression — docs/editor-audit/panels.md, "Tokens: every input dispatches per
 * keystroke → undo/save storm". editor-store pushes ONE undo entry per dispatch
 * and each dirty transition re-arms the 500 ms autosave, so a text field wired
 * straight to `onChange` cost one undo entry and one save arm per character,
 * and `<input type="color">` cost one per pixel of drag inside the OS picker.
 */
describe("TokenEditor — one undo entry per edit, not per keystroke", () => {
  it("a text token dispatches NOTHING while typing and exactly once on blur", () => {
    seedTokens(EMPTY_STUB);
    const dispatch = vi.spyOn(useEditorStore.getState(), "dispatch");
    render(<TokenEditor />);
    const field = screen.getByLabelText("spacing.4");
    for (const v of ["1", "1.", "1.2", "1.25", "1.25r", "1.25re", "1.25rem"]) {
      fireEvent.change(field, { target: { value: v } });
    }
    expect(dispatch).not.toHaveBeenCalled();
    fireEvent.blur(field);
    expect(dispatch).toHaveBeenCalledTimes(1);
    expect(dispatch).toHaveBeenCalledWith({
      type: "updateToken", path: ["spacing", "4"], value: "1.25rem",
    });
    dispatch.mockRestore();
  });

  it("Enter commits the text token without waiting for a click elsewhere", () => {
    seedTokens(EMPTY_STUB);
    render(<TokenEditor />);
    const field = screen.getByLabelText("radius.md") as HTMLInputElement;
    fireEvent.change(field, { target: { value: "0.75rem" } });
    fireEvent.keyDown(field, { key: "Enter" });
    fireEvent.blur(field); // jsdom does not blur() from the keydown handler
    const stored = (useEditorStore.getState().artifacts as never as {
      tokens: { radius: Record<string, unknown> };
    }).tokens.radius;
    expect(stored.md).toBe("0.75rem");
  });

  it("Escape abandons the edit — nothing reaches the store", () => {
    seedTokens(EMPTY_STUB);
    const dispatch = vi.spyOn(useEditorStore.getState(), "dispatch");
    render(<TokenEditor />);
    const field = screen.getByLabelText("spacing.4") as HTMLInputElement;
    fireEvent.change(field, { target: { value: "99rem" } });
    fireEvent.keyDown(field, { key: "Escape" });
    fireEvent.blur(field);
    expect(dispatch).not.toHaveBeenCalled();
    dispatch.mockRestore();
  });

  it("a colour DRAG collapses to a single dispatch instead of one per tick", () => {
    vi.useFakeTimers();
    try {
      seedTokens(EMPTY_STUB);
      const dispatch = vi.spyOn(useEditorStore.getState(), "dispatch");
      render(<TokenEditor />);
      const swatch = screen.getByLabelText("color.primary.500");
      for (const v of ["#111111", "#222222", "#333333", "#444444", "#555555"]) {
        fireEvent.change(swatch, { target: { value: v } });
      }
      expect(dispatch).not.toHaveBeenCalled();
      vi.advanceTimersByTime(250);
      expect(dispatch).toHaveBeenCalledTimes(1);
      expect(dispatch).toHaveBeenCalledWith({
        type: "updateToken", path: ["color", "primary", "500"], value: "#555555",
      });
      dispatch.mockRestore();
    } finally {
      vi.useRealTimers();
    }
  });
});
