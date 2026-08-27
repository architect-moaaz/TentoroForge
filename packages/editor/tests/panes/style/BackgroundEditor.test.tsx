import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { useState as useReactState } from "react";
import userEvent from "@testing-library/user-event";
import { BackgroundEditor } from "../../../src/panes/Properties/style/BackgroundEditor";
import type { BackgroundT } from "@tentoroforge/schema";
import type { TokenGroups } from "@tentoroforge/library";

/** Stateful wrapper so controlled-input tests actually re-render on change. */
function StatefulBackgroundEditor({
  initial,
  onChangeSpy,
  theme,
}: {
  initial: BackgroundT | undefined;
  onChangeSpy: (v: BackgroundT | undefined) => void;
  theme: TokenGroups | null;
}) {
  const [value, setValue] = useReactState<BackgroundT | undefined>(initial);
  return (
    <BackgroundEditor
      value={value}
      onChange={(v) => {
        setValue(v);
        onChangeSpy(v);
      }}
      theme={theme}
    />
  );
}

const fixtureTheme: TokenGroups = {
  color: {
    primary: { "400": "#60a5fa", "500": "#3b82f6", "600": "#2563eb" },
  },
  spacing: {},
  radius: {},
  shadow: {},
  typography: {},
} as unknown as TokenGroups;

describe("BackgroundEditor", () => {
  it("shows (none) in type switcher and no variant controls when value is undefined", () => {
    render(
      <BackgroundEditor value={undefined} onChange={vi.fn()} theme={fixtureTheme} />
    );

    const typeSelect = screen.getByRole("combobox", { name: /background type/i });
    expect(typeSelect).toHaveValue("(none)");

    // No variant-specific sections
    expect(document.querySelector("[data-bg-variant]")).toBeNull();
  });

  it("calls onChange with solid default when type is switched to solid", async () => {
    const handleChange = vi.fn();
    render(
      <BackgroundEditor value={undefined} onChange={handleChange} theme={fixtureTheme} />
    );

    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox", { name: /background type/i }), "solid");

    expect(handleChange).toHaveBeenCalledWith({
      type: "solid",
      value: "tokens.color.primary.500",
    });
  });

  it("re-emits full gradient object when `from` changes, preserving `to` and `angle`", async () => {
    const handleChange = vi.fn();
    const gradientValue: BackgroundT = {
      type: "gradient",
      from: "tokens.color.primary.400",
      to: "tokens.color.primary.600",
      angle: 90,
    };

    render(
      <BackgroundEditor
        value={gradientValue}
        onChange={handleChange}
        theme={fixtureTheme}
      />
    );

    const user = userEvent.setup();
    // "gradient from" picker
    const fromSelect = screen.getByRole("combobox", { name: /gradient from/i });
    await user.selectOptions(fromSelect, "tokens.color.primary.500");

    expect(handleChange).toHaveBeenCalledWith({
      type: "gradient",
      from: "tokens.color.primary.500",
      to: "tokens.color.primary.600",
      angle: 90,
    });
  });

  it("re-emits with new url when url input changes, and allows empty string", async () => {
    const handleChange = vi.fn();
    const imageValue: BackgroundT = {
      type: "image",
      url: "",
    };

    // Use the stateful wrapper so the controlled input actually re-renders on change
    render(
      <StatefulBackgroundEditor
        initial={imageValue}
        onChangeSpy={handleChange}
        theme={fixtureTheme}
      />
    );

    const user = userEvent.setup();
    const urlInput = screen.getByRole("textbox", { name: /image url/i });
    await user.type(urlInput, "/static/hero.jpg");

    // Last call should have the full typed url
    const lastCall = handleChange.mock.calls.at(-1)?.[0] as BackgroundT;
    expect(lastCall).toMatchObject({ type: "image", url: "/static/hero.jpg" });
  });

  it("shows four pattern options and preserves optional color when name changes", async () => {
    const handleChange = vi.fn();
    const patternValue: BackgroundT = {
      type: "pattern",
      name: "dots",
      color: "tokens.color.primary.400",
    };

    render(
      <BackgroundEditor value={patternValue} onChange={handleChange} theme={fixtureTheme} />
    );

    const patternSelect = screen.getByRole("combobox", { name: /pattern name/i });
    const options = Array.from(patternSelect.querySelectorAll("option")).map(
      (o) => (o as HTMLOptionElement).value
    );
    expect(options).toEqual(["dots", "grid", "noise", "mesh"]);

    const user = userEvent.setup();
    await user.selectOptions(patternSelect, "mesh");

    expect(handleChange).toHaveBeenCalledWith({
      type: "pattern",
      name: "mesh",
      color: "tokens.color.primary.400",
    });
  });

  it("switching from gradient to solid emits the solid seed default, not gradient fields", async () => {
    const handleChange = vi.fn();
    const gradientValue: BackgroundT = {
      type: "gradient",
      from: "tokens.color.primary.400",
      to: "tokens.color.primary.600",
      angle: 45,
    };

    render(
      <BackgroundEditor value={gradientValue} onChange={handleChange} theme={fixtureTheme} />
    );

    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox", { name: /background type/i }), "solid");

    expect(handleChange).toHaveBeenCalledWith({
      type: "solid",
      value: "tokens.color.primary.500",
    });
    // Must not contain gradient-specific fields
    const emitted = handleChange.mock.calls[0][0] as BackgroundT;
    expect(emitted).not.toHaveProperty("from");
    expect(emitted).not.toHaveProperty("to");
    expect(emitted).not.toHaveProperty("angle");
  });
});
