import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MaskedInput } from "../../src/components/MaskedInput/MaskedInput";
import { MaskedInputProps, applyMask } from "../../src/components/MaskedInput/MaskedInput.schema";

describe("applyMask", () => {
  it("inserts literals between digit placeholders", () => {
    expect(applyMask("123456", "###-###")).toBe("123-456");
  });
  it("stops when digits run out", () => {
    expect(applyMask("12", "###-###")).toBe("12");
  });
  it("strips non-digits from the raw input", () => {
    expect(applyMask("1a2b3c", "##-#")).toBe("12-3");
  });
});

describe("MaskedInput", () => {
  it("formats typed input according to the mask and fires onChange with the masked value", () => {
    const onChange = vi.fn();
    render(<MaskedInput name="phone" label="Phone" mask="###-###" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "123456" } });
    expect(onChange).toHaveBeenCalledWith("123-456");
  });
  it("validates props", () => {
    expect(() => MaskedInputProps.parse({ name: "m", mask: "###" })).not.toThrow();
    expect(() => MaskedInputProps.parse({})).not.toThrow();
  });
});
