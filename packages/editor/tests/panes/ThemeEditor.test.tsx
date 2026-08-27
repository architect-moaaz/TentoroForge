import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeEditor } from "../../src/panes/Theme/ThemeEditor";
import { createEditorStore } from "../../src/state/store";

const tokens = {
  colors: { "primary.500": "#3b82f6", "neutral.0": "#ffffff" },
  spacing: { "spacing.4": "1rem" },
} as any;

describe("ThemeEditor", () => {
  it("renders one row per token grouped by category", () => {
    const store = createEditorStore();
    store.getState().loadTheme(tokens, "default");
    render(<ThemeEditor store={store} onSave={() => {}} />);
    expect(screen.getByText("primary.500")).toBeInTheDocument();
    expect(screen.getByText("spacing.4")).toBeInTheDocument();
    expect(screen.getByText(/colors/i)).toBeInTheDocument();
    // Note: /spacing/i matches both the group header ("spacing") and the token name ("spacing.4"),
    // so we use getAllByText to assert at least one match exists.
    expect(screen.getAllByText(/spacing/i).length).toBeGreaterThan(0);
  });

  it("editing a color token dispatches setTokenValue", async () => {
    const store = createEditorStore();
    store.getState().loadTheme(tokens, "default");
    render(<ThemeEditor store={store} onSave={() => {}} />);
    // Use exact label match to get text input (not the color picker)
    const colorInput = screen.getByLabelText("primary.500") as HTMLInputElement;
    await userEvent.clear(colorInput);
    await userEvent.type(colorInput, "#ff0000");
    expect(store.getState().theme!.colors["primary.500"]).toBe("#ff0000");
  });

  it("save button calls onSave", async () => {
    const store = createEditorStore();
    store.getState().loadTheme(tokens, "default");
    const onSave = vi.fn();
    render(<ThemeEditor store={store} onSave={onSave} />);
    await userEvent.click(screen.getByRole("button", { name: /save theme/i }));
    expect(onSave).toHaveBeenCalled();
  });
});
