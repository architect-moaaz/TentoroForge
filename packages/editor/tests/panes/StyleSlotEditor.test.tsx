import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StyleSlotEditor } from "../../src/panes/Properties/StyleSlotEditor";
import type { TokenGroups } from "@tentoroforge/library";

/** Fixture theme with at least one leaf in each scope. */
const fixtureTheme: TokenGroups = {
  color: {
    primary: { "500": "#3b82f6" },
  },
  spacing: {
    "4": "1rem",
  },
  radius: {
    md: "0.375rem",
  },
  shadow: {
    sm: "0 1px 2px rgba(0,0,0,0.05)",
  },
  typography: {
    base: "1rem",
  },
} as unknown as TokenGroups;

describe("StyleSlotEditor", () => {
  // Test 1: All five sections render when value is undefined
  it("renders all five sections when value is undefined", () => {
    render(
      <StyleSlotEditor value={undefined} onChange={vi.fn()} theme={fixtureTheme} />
    );

    const container = document.querySelector("[data-style-slot-editor]");
    expect(container).not.toBeNull();

    // Check section headings are present
    expect(screen.getByText("Background")).toBeTruthy();
    expect(screen.getByText("Padding")).toBeTruthy();
    expect(screen.getByText("Radius")).toBeTruthy();
    expect(screen.getByText("Shadow")).toBeTruthy();
    expect(screen.getByText("Motion")).toBeTruthy();
  });

  // Test 2: Selecting a padding token calls onChange("padding", ...)
  it("selecting a padding token calls onChange(\"padding\", token-ref)", async () => {
    const handleChange = vi.fn();
    render(
      <StyleSlotEditor value={undefined} onChange={handleChange} theme={fixtureTheme} />
    );

    const user = userEvent.setup();
    const paddingSelect = screen.getByRole("combobox", { name: /padding/i });
    await user.selectOptions(paddingSelect, "tokens.spacing.4");

    expect(handleChange).toHaveBeenCalledWith("padding", "tokens.spacing.4");
  });

  // Test 3: Selecting a radius token calls onChange("radius", ...)
  it("selecting a radius token calls onChange(\"radius\", token-ref)", async () => {
    const handleChange = vi.fn();
    render(
      <StyleSlotEditor value={undefined} onChange={handleChange} theme={fixtureTheme} />
    );

    const user = userEvent.setup();
    const radiusSelect = screen.getByRole("combobox", { name: /radius/i });
    await user.selectOptions(radiusSelect, "tokens.radius.md");

    expect(handleChange).toHaveBeenCalledWith("radius", "tokens.radius.md");
  });

  // Test 4: Switching motion calls onChange("motion", ...)
  it("switching motion calls onChange(\"motion\", value)", async () => {
    const handleChange = vi.fn();
    render(
      <StyleSlotEditor value={undefined} onChange={handleChange} theme={fixtureTheme} />
    );

    const user = userEvent.setup();
    const motionSelect = screen.getByRole("combobox", { name: /motion/i });
    await user.selectOptions(motionSelect, "fade-in");

    expect(handleChange).toHaveBeenCalledWith("motion", "fade-in");
  });

  // Test 5: Setting background to solid via type switcher calls onChange("background", {...})
  it("setting background to solid calls onChange(\"background\", solid-object)", async () => {
    const handleChange = vi.fn();
    render(
      <StyleSlotEditor value={undefined} onChange={handleChange} theme={fixtureTheme} />
    );

    const user = userEvent.setup();
    const bgTypeSelect = screen.getByRole("combobox", { name: /background type/i });
    await user.selectOptions(bgTypeSelect, "solid");

    expect(handleChange).toHaveBeenCalledWith("background", {
      type: "solid",
      value: "tokens.color.primary.500",
    });
  });

  // Test 6 (Bonus): Sections render in documented order by DOM position
  it("sections render in documented order: background, padding, radius, shadow, motion", () => {
    render(
      <StyleSlotEditor value={undefined} onChange={vi.fn()} theme={fixtureTheme} />
    );

    const container = document.querySelector("[data-style-slot-editor]")!;

    // Collect data-token-picker attributes in DOM order
    const pickers = Array.from(
      container.querySelectorAll("[data-token-picker]")
    ).map((el) => el.getAttribute("data-token-picker"));

    // spacing (padding), radius, shadow — in that order
    expect(pickers).toEqual(["spacing", "radius", "shadow"]);

    // BackgroundEditor comes before the first TokenPicker (background section is first)
    const bgEditor = container.querySelector("[data-background-editor]");
    const firstPicker = container.querySelector("[data-token-picker]");
    expect(
      bgEditor!.compareDocumentPosition(firstPicker!) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();

    // MotionEditor comes after all token pickers
    const motionEditor = container.querySelector("[data-motion-editor]");
    const lastPicker = [...container.querySelectorAll("[data-token-picker]")].at(-1);
    expect(
      lastPicker!.compareDocumentPosition(motionEditor!) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });
});
