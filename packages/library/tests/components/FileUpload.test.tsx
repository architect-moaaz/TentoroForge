import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FileUpload } from "../../src/components/FileUpload/FileUpload";
import { FileUploadProps } from "../../src/components/FileUpload/FileUpload.schema";

describe("FileUpload", () => {
  it("renders a dropzone with the label/hint", () => {
    render(<FileUpload name="doc" label="Upload document" hint="PDF up to 5MB" />);
    expect(screen.getByText("Upload document")).toBeInTheDocument();
    expect(screen.getByText("PDF up to 5MB")).toBeInTheDocument();
  });
  it("emits selected files via onFiles", async () => {
    const onFiles = vi.fn();
    render(<FileUpload name="doc" label="Upload" onFiles={onFiles} />);
    const file = new File(["x"], "a.pdf", { type: "application/pdf" });
    const input = screen.getByTestId("file-upload-input") as HTMLInputElement;
    await userEvent.upload(input, file);
    expect(onFiles).toHaveBeenCalled();
    expect(onFiles.mock.calls[0][0][0].name).toBe("a.pdf");
  });
  it("renders no hidden inputs before anything is uploaded (no clobber)", () => {
    // FormData keeps the LAST value per name — an always-present empty hidden
    // input here erases a sibling control's value for the same field name
    // (the CameraCapture/imageUrl clobber on the Lenshop scan form).
    const { container } = render(<FileUpload name="imageUrl" label="Upload" />);
    expect(container.querySelectorAll('input[type="hidden"]').length).toBe(0);
  });
  it("renders no hidden inputs before upload in multiple mode either", () => {
    const { container } = render(<FileUpload name="docs" label="Upload" multiple />);
    expect(container.querySelectorAll('input[type="hidden"]').length).toBe(0);
  });
  it("validates props", () => {
    expect(() => FileUploadProps.parse({ name: "f", label: "F" })).not.toThrow();
    expect(() => FileUploadProps.parse({})).not.toThrow();
  });
});
