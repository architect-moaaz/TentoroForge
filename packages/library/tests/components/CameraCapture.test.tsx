import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CameraCapture } from "../../src/components/CameraCapture/CameraCapture";
import { CameraCaptureProps } from "../../src/components/CameraCapture/CameraCapture.schema";

describe("CameraCapture", () => {
  beforeEach(() => {
    const fakeStream = { getTracks: () => [{ stop: vi.fn() }] };
    (navigator as any).mediaDevices = { getUserMedia: vi.fn().mockResolvedValue(fakeStream) };
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ({ drawImage: vi.fn() })) as any;
    HTMLCanvasElement.prototype.toDataURL = vi.fn(() => "data:image/png;base64,AAA");
  });
  it("shows the label and a Start Camera control initially", () => {
    render(<CameraCapture label="Capture Truck Photo" />);
    expect(screen.getByText("Capture Truck Photo")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start camera/i })).toBeInTheDocument();
  });
  it("requests the webcam and reveals a capture control when started", async () => {
    render(<CameraCapture />);
    fireEvent.click(screen.getByRole("button", { name: /start camera/i }));
    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ video: true });
    await waitFor(() => expect(screen.getByRole("button", { name: /capture photo/i })).toBeInTheDocument());
  });
  it("captures a frame and emits a data URL", async () => {
    const onCapture = vi.fn();
    render(<CameraCapture onCapture={onCapture} />);
    fireEvent.click(screen.getByRole("button", { name: /start camera/i }));
    await waitFor(() => screen.getByRole("button", { name: /capture photo/i }));
    fireEvent.click(screen.getByRole("button", { name: /capture photo/i }));
    expect(onCapture).toHaveBeenCalledWith("data:image/png;base64,AAA");
  });
  it("validates props", () => {
    expect(() => CameraCaptureProps.parse({ label: "x" })).not.toThrow();
    expect(() => CameraCaptureProps.parse({})).not.toThrow();
  });
});
