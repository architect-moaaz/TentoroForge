import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import * as React from "react";
import { Slider } from "../src/components/Slider/Slider";
import { Rating } from "../src/components/Rating/Rating";
import { ColorPicker } from "../src/components/ColorPicker/ColorPicker";
import { TimePicker } from "../src/components/TimePicker/TimePicker";
import { MaskedInput } from "../src/components/MaskedInput/MaskedInput";

/**
 * ONE state contract for every input — see src/util/useFieldValue.ts.
 *
 * Half the input library used to be dead when rendered from a page schema:
 * fully controlled components waiting on a `value`/`onChange` pair that nothing
 * supplies. Verified live before the fix — Slider set to 75 reverted to 0,
 * Rating's 4th star filled 0 stars, ColorPicker set to #ff0000 reverted to
 * #000000 while React logged the read-only-field warning.
 *
 * The contract these pin down:
 *   1. No props at all      → self-managing, the user can change it.
 *   2. `value`, no onChange → `value` is a declarative SEED; still editable.
 *   3. value AND onChange   → controlled; the parent owns it.
 *   4. `defaultValue`       → the schema's prefill channel.
 */

describe("input state contract — self-managing when nothing owns the value", () => {
  it("Slider moves and stays moved", () => {
    const { container } = render(<Slider name="s" label="Value" />);
    const el = container.querySelector('input[type="range"]') as HTMLInputElement;
    fireEvent.change(el, { target: { value: "75" } });
    expect((container.querySelector('input[type="range"]') as HTMLInputElement).value).toBe("75");
  });

  it("Rating fills stars on click", () => {
    const { getByLabelText, container } = render(<Rating name="r" label="Score" />);
    fireEvent.click(getByLabelText("Rate 4"));
    const pressed = [...container.querySelectorAll("button")].filter(
      (b) => b.getAttribute("aria-pressed") === "true",
    );
    expect(pressed).toHaveLength(4);
  });

  it("Rating click on the current value clears it", () => {
    // Otherwise a rating can be raised and lowered but never withdrawn.
    const { getByLabelText, container } = render(<Rating name="r" defaultValue={3} />);
    fireEvent.click(getByLabelText("Rate 3"));
    expect(container.querySelectorAll('button[aria-pressed="true"]')).toHaveLength(0);
  });

  it("ColorPicker accepts a new colour", () => {
    const { getByTestId } = render(<ColorPicker name="c" label="Brand" />);
    const el = getByTestId("color-input") as HTMLInputElement;
    fireEvent.change(el, { target: { value: "#ff0000" } });
    expect((getByTestId("color-input") as HTMLInputElement).value).toBe("#ff0000");
  });

  it("TimePicker keeps what was typed", () => {
    const { container } = render(<TimePicker name="t" label="Start" />);
    const el = container.querySelector('input[type="time"]') as HTMLInputElement;
    fireEvent.change(el, { target: { value: "09:30" } });
    expect((container.querySelector('input[type="time"]') as HTMLInputElement).value).toBe("09:30");
  });

  it("MaskedInput applies its mask when nobody owns the state", () => {
    // The mask previously only ran when a parent happened to control the value,
    // so the component's entire purpose was inert standalone.
    const { container } = render(<MaskedInput name="m" mask="###-####" />);
    const el = container.querySelector('input[type="text"]') as HTMLInputElement;
    fireEvent.change(el, { target: { value: "5551234" } });
    expect((container.querySelector('input[type="text"]') as HTMLInputElement).value).toBe("555-1234");
  });
});

describe("input state contract — `value` without `onChange` is a SEED, not ownership", () => {
  it("Slider shows the seed but still moves", () => {
    // Gating on `value !== undefined` alone is what produced "the toggle that
    // cannot be toggled": a registry default arrives, the component decides it
    // is controlled, and waits forever for a parent that does not exist.
    const { container } = render(<Slider name="s" value={40} />);
    const el = container.querySelector('input[type="range"]') as HTMLInputElement;
    expect(el.value).toBe("40");
    fireEvent.change(el, { target: { value: "60" } });
    expect((container.querySelector('input[type="range"]') as HTMLInputElement).value).toBe("60");
  });

  it("ColorPicker shows the seed but still changes", () => {
    const { getByTestId } = render(<ColorPicker name="c" value="#3366ff" />);
    expect((getByTestId("color-input") as HTMLInputElement).value).toBe("#3366ff");
    fireEvent.change(getByTestId("color-input"), { target: { value: "#00ff00" } });
    expect((getByTestId("color-input") as HTMLInputElement).value).toBe("#00ff00");
  });
});

describe("input state contract — controlled requires BOTH value and onChange", () => {
  it("Slider defers to the parent and does not self-update", () => {
    const onChange = vi.fn();
    const { container } = render(<Slider name="s" value={30} onChange={onChange} />);
    fireEvent.change(container.querySelector('input[type="range"]')!, { target: { value: "90" } });
    expect(onChange).toHaveBeenCalledWith(90);
    // Parent owns it and did not re-render, so the displayed value is unchanged.
    expect((container.querySelector('input[type="range"]') as HTMLInputElement).value).toBe("30");
  });

  it("Rating reports the click to its parent", () => {
    const onChange = vi.fn();
    const { getByLabelText } = render(<Rating name="r" value={1} onChange={onChange} />);
    fireEvent.click(getByLabelText("Rate 5"));
    expect(onChange).toHaveBeenCalledWith(5);
  });

  it("ColorPicker reports the change to its parent", () => {
    const onChange = vi.fn();
    const { getByTestId } = render(<ColorPicker name="c" value="#000000" onChange={onChange} />);
    fireEvent.change(getByTestId("color-input"), { target: { value: "#123456" } });
    expect(onChange).toHaveBeenCalledWith("#123456");
  });
});

describe("input state contract — declarative defaultValue", () => {
  it("seeds each field from the schema's prefill", () => {
    const { container } = render(<Slider name="s" defaultValue={65} />);
    expect((container.querySelector('input[type="range"]') as HTMLInputElement).value).toBe("65");

    const cp = render(<ColorPicker name="c" defaultValue="#abcdef" />);
    expect((cp.getByTestId("color-input") as HTMLInputElement).value).toBe("#abcdef");

    const tp = render(<TimePicker name="t" defaultValue="14:45" />);
    expect((tp.container.querySelector('input[type="time"]') as HTMLInputElement).value).toBe("14:45");
  });

  it("re-seeds when the prop changes, so a Properties-panel edit moves the canvas", () => {
    // Without this the useState initialiser has already run and editing
    // `defaultValue` in the editor does nothing visible.
    const { container, rerender } = render(<Slider name="s" defaultValue={10} />);
    rerender(<Slider name="s" defaultValue={80} />);
    expect((container.querySelector('input[type="range"]') as HTMLInputElement).value).toBe("80");
  });

  it("does not clobber what the user typed between panel edits", () => {
    const { container, rerender } = render(<TimePicker name="t" defaultValue="08:00" />);
    fireEvent.change(container.querySelector('input[type="time"]')!, { target: { value: "11:15" } });
    rerender(<TimePicker name="t" defaultValue="08:00" />);
    expect((container.querySelector('input[type="time"]') as HTMLInputElement).value).toBe("11:15");
  });
});

describe("input state contract — form serialization", () => {
  it("Rating carries its value into FormData (it had NO named control at all)", () => {
    const { container } = render(
      <form data-testid="f"><Rating name="score" defaultValue={4} /></form>,
    );
    const hidden = container.querySelector('input[type="hidden"][name="score"]') as HTMLInputElement;
    expect(hidden).not.toBeNull();
    expect(new FormData(container.querySelector("form")!).get("score")).toBe("4");
  });

  it("Slider RANGE mode submits its pair (both inputs were nameless)", () => {
    const { container } = render(
      <form><Slider name="band" range defaultValue={[20, 80] as never} /></form>,
    );
    expect(new FormData(container.querySelector("form")!).get("band")).toBe("20,80");
  });

  it("Slider single mode still submits through its own named input", () => {
    const { container } = render(<form><Slider name="qty" defaultValue={7} /></form>);
    expect(new FormData(container.querySelector("form")!).get("qty")).toBe("7");
  });
});
