import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Switch } from "../../src/components/Switch/Switch";
import { Checkbox } from "../../src/components/Checkbox/Checkbox";
import { RadioGroup } from "../../src/components/RadioGroup/RadioGroup";

/**
 * User report #6: "Switch, Radio, checkbox — They take the complete size, it
 * should be exactly what is required and also, switch is also not working
 * properly."
 *
 * Two distinct defects, one test file:
 *  - the roots were block-level `flex` divs, so they spanned the parent (and
 *    were stretched again by any flex-column parent's default items-stretch);
 *  - `checked` / `value` were treated as CONTROLLED even with no handler, which
 *    is React's read-only input — dead controls. The palette hands Switch a
 *    `checked: false` default prop and never a handler, so every dropped Switch
 *    was frozen off.
 */

describe("intrinsic sizing — Switch / Checkbox / RadioGroup", () => {
  const roots = () => [
    render(<Switch name="a" label="Enabled" />).container.firstChild as HTMLElement,
    render(<Checkbox name="b" label="Agree" />).container.firstChild as HTMLElement,
    render(<RadioGroup name="c" label="Pick" options={[{ value: "x", label: "X" }]} />)
      .container.firstChild as HTMLElement,
  ];

  it("does not let the root span its parent", () => {
    for (const root of roots()) {
      const cls = root.className;
      // w-fit is the part that actually beats `align-items: stretch`; the rest
      // is belt-and-braces for parents that stretch explicitly.
      expect(cls).toContain("w-fit");
      expect(cls).toContain("self-start");
      expect(cls).toContain("max-w-full");
      // The old full-width root — a bare block-level flex container.
      expect(cls.startsWith("flex ")).toBe(false);
    }
  });

  it("still lets the Style panel override the width (inline style wins)", () => {
    const { container } = render(
      <Switch name="a" label="Enabled" style={{ width: "300px" }} />,
    );
    expect((container.firstChild as HTMLElement).style.width).toBe("300px");
  });
});

describe("Switch — the registry's own default props must produce a live toggle", () => {
  it("toggles when dropped with the registry defaults (checked, no onChange)", () => {
    render(<Switch name="active" label="Enabled" checked={false} />);
    const sw = screen.getByRole("switch");
    expect(sw).toHaveAttribute("aria-checked", "false");
    fireEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "true");
    fireEvent.click(sw);
    expect(sw).toHaveAttribute("aria-checked", "false");
  });

  it("carries its live value into the enclosing form under `name`", () => {
    const { container } = render(<Switch name="active" label="Enabled" checked={false} />);
    const hidden = () => container.querySelector('input[name="active"]') as HTMLInputElement;
    expect(hidden().value).toBe("false");
    fireEvent.click(screen.getByRole("switch"));
    expect(hidden().value).toBe("true");
  });

  it("follows a Properties-panel edit of `checked` while uncontrolled", () => {
    const { rerender } = render(<Switch name="a" label="E" checked={false} />);
    rerender(<Switch name="a" label="E" checked />);
    expect(screen.getByRole("switch")).toHaveAttribute("aria-checked", "true");
  });

  it("stays controlled when a handler IS supplied", () => {
    const onChange = vi.fn();
    render(<Switch name="a" label="E" checked={false} onChange={onChange} />);
    const sw = screen.getByRole("switch");
    fireEvent.click(sw);
    expect(onChange).toHaveBeenCalledWith(true);
    // The parent owns the value: without a write-back the switch must not move.
    expect(sw).toHaveAttribute("aria-checked", "false");
  });
});

describe("Checkbox / RadioGroup — no handler means uncontrolled, not read-only", () => {
  it("a Checkbox with a declarative `checked` can still be ticked", () => {
    render(<Checkbox name="agree" label="I agree" checked={false} />);
    const cb = screen.getByLabelText("I agree") as HTMLInputElement;
    expect(cb.checked).toBe(false);
    fireEvent.click(cb);
    expect(cb.checked).toBe(true);
  });

  it("a RadioGroup with a declarative `value` can still be changed", () => {
    render(
      <RadioGroup
        name="size"
        label="Size"
        value="s"
        options={[{ value: "s", label: "Small" }, { value: "l", label: "Large" }]}
      />,
    );
    const large = screen.getByLabelText("Large") as HTMLInputElement;
    expect((screen.getByLabelText("Small") as HTMLInputElement).checked).toBe(true);
    fireEvent.click(large);
    expect(large.checked).toBe(true);
  });
});
