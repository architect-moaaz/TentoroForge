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

/**
 * User report #7: "check if the fileupload is working."
 *
 * The end-to-end contract is: pick a file → multipart POST to `uploadUrl` →
 * the returned ref's `id` rides into the enclosing <form>'s FormData under
 * `name`, with `originalFilename` / `mimeType` alongside. A generated app gets
 * that endpoint unconditionally (runtime_injector._inject_file_storage writes
 * src/app/api/files/upload/route.ts), so the happy path below is the real one.
 * The editor canvas and the render-scaffold do NOT serve it — those 404s used
 * to be indistinguishable from a broken component, which is the second half of
 * these tests.
 */
describe("FileUpload — end to end", () => {
  const pick = async (name = "a.pdf", type = "application/pdf", bytes = "x") => {
    const file = new File([bytes], name, { type });
    await userEvent.upload(screen.getByTestId("file-upload-input") as HTMLInputElement, file);
  };

  it("uploads and carries the returned id + filename + mimeType into the form", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        id: "file-123", url: "/api/files/file-123",
        filename: "a.pdf", contentType: "application/pdf", size: 1,
      }),
    })) as unknown as typeof fetch;
    vi.stubGlobal("fetch", fetchMock);
    const onUploaded = vi.fn();
    const { container } = render(<FileUpload name="docId" label="Upload" onUploaded={onUploaded} />);
    await pick();

    expect((fetchMock as any).mock.calls[0][0]).toBe("/api/files/upload");
    expect((fetchMock as any).mock.calls[0][1].method).toBe("POST");
    expect(await screen.findByText(/· ✓/)).toBeInTheDocument();
    expect((container.querySelector('input[name="docId"]') as HTMLInputElement).value).toBe("file-123");
    expect((container.querySelector('input[name="originalFilename"]') as HTMLInputElement).value).toBe("a.pdf");
    expect((container.querySelector('input[name="mimeType"]') as HTMLInputElement).value).toBe("application/pdf");
    expect(onUploaded).toHaveBeenCalledWith([expect.objectContaining({ id: "file-123" })]);
    vi.unstubAllGlobals();
  });

  it("says WHICH endpoint is missing when the host does not serve one", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404, json: async () => ({}) })));
    const { container } = render(<FileUpload name="docId" label="Upload" />);
    await pick();
    // The old UI said only "· failed" — identical for a 404, a 500 and a
    // dropped connection, and unanswerable from the canvas.
    expect(await screen.findByText(/no upload endpoint at \/api\/files\/upload/)).toBeInTheDocument();
    // A failed upload must not put a value into the form.
    expect(container.querySelector('input[name="docId"]')).toBeNull();
    vi.unstubAllGlobals();
  });

  it("does not silently swallow a file over maxSizeMb", async () => {
    vi.stubGlobal("fetch", vi.fn());
    render(<FileUpload name="docId" label="Upload" maxSizeMb={1} />);
    // 2 MB against a 1 MB cap. Before this, acceptFiles filtered it out and
    // returned with no state change at all — the control looked dead.
    await pick("big.pdf", "application/pdf", "y".repeat(2 * 1024 * 1024));
    expect(await screen.findByText(/over the 1 MB limit/)).toBeInTheDocument();
    expect((globalThis.fetch as any)).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("omits an empty accept attribute (the registry default)", () => {
    render(<FileUpload name="d" label="Upload" accept="" />);
    expect((screen.getByTestId("file-upload-input") as HTMLInputElement).hasAttribute("accept")).toBe(false);
  });
});
