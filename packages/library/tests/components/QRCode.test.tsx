import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QRCode } from "../../src/components/QRCode/QRCode";
import { QRCodeProps } from "../../src/components/QRCode/QRCode.schema";

describe("QRCode", () => {
  it("renders an SVG QR code for the value", () => {
    const { container } = render(<QRCode value="https://tentoro.example/gate/42" />);
    const wrapper = container.querySelector("[data-qr-code]");
    expect(wrapper).not.toBeNull();
    expect(wrapper!.querySelector("svg")).not.toBeNull();
  });
  it("renders an optional label", () => {
    render(<QRCode value="x" label="Scan to check in" />);
    expect(screen.getByText("Scan to check in")).toBeInTheDocument();
  });
  it("validates props", () => {
    expect(() => QRCodeProps.parse({ value: "x", size: 200 })).not.toThrow();
    expect(() => QRCodeProps.parse({})).not.toThrow();
  });
});
