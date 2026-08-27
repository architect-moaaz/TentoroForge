import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Scanner } from "../../src/components/Scanner/Scanner";
import { ScannerProps } from "../../src/components/Scanner/Scanner.schema";

describe("Scanner", () => {
  it("renders the label and a scan trigger, and fires onScan", () => {
    const onScan = vi.fn();
    render(<Scanner label="RFID Scanner" onScan={onScan} />);
    expect(screen.getByText("RFID Scanner")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /scan/i }));
    expect(onScan).toHaveBeenCalledTimes(1);
  });
  it("shows the scanned value and a success status", () => {
    render(<Scanner value="RF-2024-001234" status="success" statusMessage="RFID Tag Scanned Successfully" />);
    expect(screen.getByText("RF-2024-001234")).toBeInTheDocument();
    const panel = screen.getByTestId("scan-result");
    expect(panel.getAttribute("data-status")).toBe("success");
    expect(screen.getByText(/Scanned Successfully/i)).toBeInTheDocument();
  });
  it("reflects an error status", () => {
    render(<Scanner status="error" statusMessage="No tag detected" />);
    expect(screen.getByTestId("scan-result").getAttribute("data-status")).toBe("error");
    expect(screen.getByText("No tag detected")).toBeInTheDocument();
  });
  it("validates props", () => {
    expect(() => ScannerProps.parse({ deviceType: "rfid", status: "success", value: "x" })).not.toThrow();
    expect(() => ScannerProps.parse({})).not.toThrow();
  });
});
