import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TokenPicker } from "../../../src/panes/Properties/style/TokenPicker";
import type { TokenGroups } from "@tentoroforge/library";

// Minimal fixture theme with two color groups and some spacing
const fixtureTheme: TokenGroups = {
  color: {
    primary: { "400": "#60a5fa", "500": "#3b82f6" },
    surface: { "0": "#ffffff" },
  },
  spacing: {
    "4": "1rem",
    semantic: { section: "4rem" },
  },
  radius: { md: "0.5rem" },
  shadow: { sm: "0 1px 2px rgba(0,0,0,.05)" },
  typography: { font: { body: "Inter, sans-serif" } },
} as unknown as TokenGroups;

describe("TokenPicker (style/)", () => {
  it("renders all leaf token refs as option values for the given scope", () => {
    render(
      <TokenPicker
        scope="color"
        value={undefined}
        onChange={vi.fn()}
        theme={fixtureTheme}
      />
    );

    // All leaves should appear as options
    const select = screen.getByRole("combobox");
    const values = Array.from(select.querySelectorAll("option"))
      .map((o) => (o as HTMLOptionElement).value)
      .filter(Boolean); // exclude the blank "—" option

    expect(values).toContain("tokens.color.primary.400");
    expect(values).toContain("tokens.color.primary.500");
    expect(values).toContain("tokens.color.surface.0");
    expect(values).toHaveLength(3); // exactly the three leaves
  });

  it("calls onChange with the full ref when an option is selected", async () => {
    const handleChange = vi.fn();
    render(
      <TokenPicker
        scope="color"
        value={undefined}
        onChange={handleChange}
        theme={fixtureTheme}
      />
    );

    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox"), "tokens.color.primary.500");

    expect(handleChange).toHaveBeenCalledWith("tokens.color.primary.500");
  });

  it("calls onChange(undefined) when the empty — option is selected", async () => {
    const handleChange = vi.fn();
    render(
      <TokenPicker
        scope="color"
        value="tokens.color.primary.500"
        onChange={handleChange}
        theme={fixtureTheme}
      />
    );

    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox"), "");

    expect(handleChange).toHaveBeenCalledWith(undefined);
  });

  it("renders disabled with placeholder when theme[scope] exists but is empty", () => {
    const emptyTheme: TokenGroups = {
      color: {},
    } as unknown as TokenGroups;

    render(
      <TokenPicker
        scope="color"
        value={undefined}
        onChange={vi.fn()}
        theme={emptyTheme}
        placeholder="(no tokens)"
      />
    );

    const select = screen.getByRole("combobox");
    expect(select).toBeDisabled();
    // Only the placeholder option — no leaf options
    const options = Array.from(select.querySelectorAll("option"));
    expect(options).toHaveLength(1);
    expect(options[0].textContent).toBe("(no tokens)");
  });

  it("renders disabled with placeholder when theme is null", () => {
    render(
      <TokenPicker
        scope="color"
        value={undefined}
        onChange={vi.fn()}
        theme={null}
        placeholder="No project theme"
      />
    );

    const select = screen.getByRole("combobox");
    expect(select).toBeDisabled();
    expect(select).toHaveTextContent("No project theme");
  });

  it("renders a color swatch with aria-hidden when scope is color, and swatch updates on re-render", () => {
    const { rerender } = render(
      <TokenPicker
        scope="color"
        value="tokens.color.primary.500"
        onChange={vi.fn()}
        theme={fixtureTheme}
      />
    );

    // Swatch should be present and aria-hidden
    const swatches = document.querySelectorAll("[aria-hidden='true']");
    expect(swatches).toHaveLength(1);
    const swatch = swatches[0] as HTMLElement;
    // jsdom normalizes hex → rgb(). Capture the background for comparison.
    const bgFor500 = swatch.style.background;
    expect(bgFor500).toBeTruthy(); // something is set

    // Re-render with a different color token — swatch background must change
    rerender(
      <TokenPicker
        scope="color"
        value="tokens.color.primary.400"
        onChange={vi.fn()}
        theme={fixtureTheme}
      />
    );

    const updatedSwatch = document.querySelectorAll("[aria-hidden='true']")[0] as HTMLElement;
    const bgFor400 = updatedSwatch.style.background;
    // The two resolved colors are different tokens, so backgrounds must differ
    expect(bgFor400).not.toBe(bgFor500);
    expect(bgFor400).toBeTruthy();
  });
});
