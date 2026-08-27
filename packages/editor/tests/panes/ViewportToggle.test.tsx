import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ViewportToggle } from "../../src/panes/Canvas/ViewportToggle";
import { createEditorStore } from "../../src/state/store";

describe("ViewportToggle", () => {
  it("starts at desktop", () => {
    const store = createEditorStore();
    render(<ViewportToggle store={store} />);
    expect(screen.getByRole("radio", { name: /desktop/i })).toBeChecked();
  });

  it("switching updates viewport state", async () => {
    const store = createEditorStore();
    render(<ViewportToggle store={store} />);
    await userEvent.click(screen.getByRole("radio", { name: /mobile/i }));
    expect(store.getState().viewport).toBe("mobile");
  });
});
