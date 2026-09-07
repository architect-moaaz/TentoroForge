import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  SliderNode, TimePickerNode, ColorPickerNode, RatingNode, InputOTPNode,
} from "@tentoroforge/schema";
import { Slider } from "../src/components/Slider/Slider";
import { SliderProps } from "../src/components/Slider/Slider.schema";
import { TimePicker } from "../src/components/TimePicker/TimePicker";
import { TimePickerProps } from "../src/components/TimePicker/TimePicker.schema";
import { ColorPicker } from "../src/components/ColorPicker/ColorPicker";
import { ColorPickerProps } from "../src/components/ColorPicker/ColorPicker.schema";
import { Rating } from "../src/components/Rating/Rating";
import { RatingProps } from "../src/components/Rating/Rating.schema";
import { InputOTP } from "../src/components/InputOTP/InputOTP";
import { InputOTPProps } from "../src/components/InputOTP/InputOTP.schema";

/**
 * docs/editor-audit/input-components-2.md finding #7 — "validators on every
 * input, not just some".
 *
 * `validators` (required/min/max/pattern/message) was expressible on Input,
 * Select, Textarea, Checkbox and DatePicker and simply absent from
 * Slider/TimePicker/ColorPicker/Rating/InputOTP — so "this field is required"
 * could be said about a text box and not about a rating. Two halves are tested:
 * the prop VALIDATES (otherwise the strict node schema rejects the page and the
 * component schema strips it), and the component HONOURS at least `required`.
 */

const required = { validators: { required: true } };

describe("the `validators` prop validates on the five inputs that lacked it", () => {
  it("passes the .strict() NODE schemas", () => {
    expect(SliderNode.safeParse({ type: "Slider", props: { name: "s", ...required } }).success).toBe(true);
    expect(TimePickerNode.safeParse({ type: "TimePicker", props: { name: "t", label: "T", ...required } }).success).toBe(true);
    expect(ColorPickerNode.safeParse({ type: "ColorPicker", props: { name: "c", ...required } }).success).toBe(true);
    expect(RatingNode.safeParse({ type: "Rating", props: { name: "r", ...required } }).success).toBe(true);
    expect(InputOTPNode.safeParse({ type: "InputOTP", props: { name: "o", ...required } }).success).toBe(true);
  });

  it("survives the component prop schemas instead of being stripped", () => {
    for (const schema of [SliderProps, TimePickerProps, ColorPickerProps, RatingProps, InputOTPProps]) {
      const parsed = schema.parse({ name: "f", validators: { required: true, message: "Pick one" } }) as any;
      expect(parsed.validators).toEqual({ required: true, message: "Pick one" });
    }
  });

  it("keeps the whole vocabulary, not just `required`", () => {
    const parsed = SliderNode.safeParse({
      type: "Slider",
      props: { name: "s", validators: { required: true, min: 1, max: 9, pattern: "\\d+", message: "nope" } },
    });
    expect(parsed.success).toBe(true);
    // ...and still rejects a field nobody defined, so the vocabulary stays one.
    expect(SliderNode.safeParse({ type: "Slider", props: { name: "s", validators: { minLength: 3 } } }).success).toBe(false);
  });
});

describe("the components honour validators.required", () => {
  it("TimePicker puts `required` on the time input the browser can enforce", () => {
    const { container } = render(<TimePicker name="t" label="Start" validators={{ required: true }} />);
    expect(container.querySelector('input[type="time"]')!.hasAttribute("required")).toBe(true);
    expect(container.textContent).toContain("*");
  });

  it("InputOTP requires EVERY digit box — a partial code is never valid", () => {
    const { container } = render(<InputOTP name="o" label="Code" length={4} validators={{ required: true }} />);
    const boxes = Array.from(container.querySelectorAll("input"));
    expect(boxes).toHaveLength(4);
    expect(boxes.every((b) => b.hasAttribute("required"))).toBe(true);
  });

  it("Slider and ColorPicker mark the field without faking an enforceable constraint", () => {
    // Both controls always carry a value, so a browser `required` could never
    // fail; the mark and aria-required are the honest half.
    const slider = render(<Slider name="s" label="Volume" validators={{ required: true }} />);
    expect(slider.container.querySelector('input[type="range"]')!.getAttribute("aria-required")).toBe("true");
    expect(slider.container.textContent).toContain("*");

    const color = render(<ColorPicker name="c" label="Brand" validators={{ required: true }} />);
    expect(color.container.querySelector('input[type="color"]')!.getAttribute("aria-required")).toBe("true");
    expect(color.container.textContent).toContain("*");
  });

  it("Rating marks the star group as required", () => {
    render(<Rating name="r" label="Score" validators={{ required: true }} />);
    expect(screen.getByRole("group", { name: "Score" }).getAttribute("aria-required")).toBe("true");
  });

  it("leaves every one of them unmarked when no validators are given", () => {
    const { container } = render(
      <>
        <TimePicker name="t" label="Start" />
        <ColorPicker name="c" label="Brand" />
        <Slider name="s" label="Volume" />
      </>,
    );
    expect(container.querySelector("[required]")).toBeNull();
    expect(container.querySelector('[aria-required="true"]')).toBeNull();
    expect(container.textContent).not.toContain("*");
  });
});
