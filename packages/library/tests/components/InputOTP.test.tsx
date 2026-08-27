import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { InputOTP } from "../../src/components/InputOTP/InputOTP";
import { InputOTPProps } from "../../src/components/InputOTP/InputOTP.schema";

describe("InputOTP", () => {
  it("renders `length` single-character inputs", () => {
    render(<InputOTP name="otp" label="Code" length={4} />);
    expect(screen.getAllByRole("textbox")).toHaveLength(4);
  });
  it("assembles entered characters and fires onChange with the full value", () => {
    const onChange = vi.fn();
    render(<InputOTP name="otp" label="Code" length={4} onChange={onChange} />);
    const inputs = screen.getAllByRole("textbox");
    fireEvent.change(inputs[0], { target: { value: "1" } });
    fireEvent.change(inputs[1], { target: { value: "2" } });
    fireEvent.change(inputs[2], { target: { value: "3" } });
    fireEvent.change(inputs[3], { target: { value: "4" } });
    expect(onChange).toHaveBeenLastCalledWith("1234");
  });
  it("validates props", () => {
    expect(() => InputOTPProps.parse({ name: "o", length: 6 })).not.toThrow();
    expect(() => InputOTPProps.parse({})).not.toThrow();
  });
});
