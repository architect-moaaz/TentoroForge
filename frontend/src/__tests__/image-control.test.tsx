/**
 * ImageControl — the parts of drag-and-drop that a shell cannot exercise.
 *
 * A real browser drag still needs a human (see the report), but the drop
 * HANDLER, the validation gate in front of the upload, and every visible
 * failure path are ordinary functions and are pinned here. The one thing these
 * tests are really guarding is that a refused file is refused OUT LOUD and
 * never reaches the network — a silent drop is the failure mode that makes the
 * editor look broken.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";

// vi.mock is hoisted above every import, so the factory's dependencies have to
// be hoisted with it — a plain `const` above would still be in the temporal
// dead zone when the factory runs.
const { upload, FakeApiError } = vi.hoisted(() => {
  class FakeApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
      this.name = "ApiError";
    }
  }
  return { upload: vi.fn(), FakeApiError };
});
vi.mock("@/lib/api", () => ({
  api: { upload: (...a: unknown[]) => upload(...a) },
  ApiError: FakeApiError,
}));

import { ImageControl } from "@/components/properties/PropControls/ImageControl";
import { starterRegistry } from "@forge/registry";
import { PropertiesPanelInner } from "@/components/properties/PropertiesPanel";
import { useEditorStore } from "@/lib/editor-store";

const realImage = globalThis.Image;

/** jsdom never loads an <img>, so the dimension reader needs a stand-in. */
function stubImage(width: number, height: number, fail = false) {
  globalThis.Image = class {
    naturalWidth = width;
    naturalHeight = height;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    set src(_v: string) {
      setTimeout(() => (fail ? this.onerror?.() : this.onload?.()), 0);
    }
  } as unknown as typeof Image;
}

function makeFile(name: string, type: string, size: number): File {
  const f = new File(["x"], name, { type });
  Object.defineProperty(f, "size", { value: size });
  return f;
}

function drop(file: File | null, uri = "") {
  fireEvent.drop(screen.getByTestId("image-dropzone"), {
    dataTransfer: { files: file ? [file] : [], getData: () => uri },
  });
}

beforeEach(() => {
  upload.mockReset();
  stubImage(200, 200);
});
afterEach(() => {
  cleanup();
  globalThis.Image = realImage;
});

describe("ImageControl — the URL text path still works", () => {
  it("shows the current url and commits an edit to it", () => {
    const onChange = vi.fn();
    render(
      <ImageControl label="photoUrl" value="/api/asset/p/figma/a.png" onChange={onChange}
        imageShape="url" nodeType="Avatar" nodeProps={{ size: "md" }} projectId="p" />,
    );
    const box = screen.getByLabelText("photoUrl URL") as HTMLInputElement;
    expect(box.value).toBe("/api/asset/p/figma/a.png");
    fireEvent.change(box, { target: { value: "https://cdn.example/x.png" } });
    // Commit is on blur / Enter, not per keystroke — see the undo-storm test
    // below for why.
    fireEvent.blur(box);
    expect(onChange).toHaveBeenCalledWith("https://cdn.example/x.png");
  });

  /**
   * Regression — docs/editor-audit/panels.md logs this box under the same
   * per-keystroke defect as the Tokens and Bindings tabs: editor-store pushes
   * one undo entry per dispatch and re-arms the 500 ms autosave on each, so
   * typing a URL cost one undo entry per character and every half-typed prefix
   * was written into the schema as a real image url.
   */
  it("dispatches NOTHING while typing and exactly once on blur", () => {
    const onChange = vi.fn();
    render(
      <ImageControl label="photoUrl" value="" onChange={onChange}
        imageShape="url" nodeType="Avatar" nodeProps={{ size: "md" }} projectId="p" />,
    );
    const box = screen.getByLabelText("photoUrl URL") as HTMLInputElement;
    for (const v of ["h", "ht", "htt", "http", "https://a.png"]) {
      fireEvent.change(box, { target: { value: v } });
    }
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.blur(box);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("https://a.png");
  });

  it("Escape abandons the edit without writing anything", () => {
    const onChange = vi.fn();
    render(
      <ImageControl label="photoUrl" value="/keep.png" onChange={onChange}
        imageShape="url" nodeType="Avatar" nodeProps={{ size: "md" }} projectId="p" />,
    );
    const box = screen.getByLabelText("photoUrl URL") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "/throwaway.png" } });
    fireEvent.keyDown(box, { key: "Escape" });
    fireEvent.blur(box);
    expect(onChange).not.toHaveBeenCalled();
    expect(box.value).toBe("/keep.png");
  });

  it("wraps a typed url in Hero.backgroundImage's { url, overlay } shape", () => {
    const onChange = vi.fn();
    render(
      <ImageControl label="backgroundImage" value={undefined} onChange={onChange}
        imageShape="overlay" nodeType="Hero" nodeProps={{}} projectId="p" />,
    );
    const box = screen.getByLabelText("backgroundImage URL");
    fireEvent.change(box, { target: { value: "https://cdn.example/bg.jpg" } });
    fireEvent.blur(box);
    expect(onChange).toHaveBeenCalledWith({ url: "https://cdn.example/bg.jpg", overlay: 0.4 });
  });
});

describe("ImageControl — refusals are visible and never hit the network", () => {
  it("refuses a PDF by name and type", async () => {
    render(<ImageControl label="photoUrl" value="" onChange={vi.fn()} imageShape="url" projectId="p" />);
    drop(makeFile("spec.pdf", "application/pdf", 2048));
    expect((await screen.findByRole("alert")).textContent).toMatch(/spec\.pdf isn't an image/);
    expect(upload).not.toHaveBeenCalled();
  });

  it("refuses a file over the 10 MB limit", async () => {
    render(<ImageControl label="photoUrl" value="" onChange={vi.fn()} imageShape="url" projectId="p" />);
    drop(makeFile("huge.png", "image/png", 11 * 1024 * 1024));
    expect((await screen.findByRole("alert")).textContent).toMatch(/limit is 10 MB/);
    expect(upload).not.toHaveBeenCalled();
  });

  it("explains a drop that carried nothing at all", async () => {
    render(<ImageControl label="photoUrl" value="" onChange={vi.fn()} imageShape="url" projectId="p" />);
    drop(null);
    expect((await screen.findByRole("alert")).textContent).toMatch(/carried no file/);
  });

  it("takes a url dragged from another page as a typed url", () => {
    const onChange = vi.fn();
    render(<ImageControl label="photoUrl" value="" onChange={onChange} imageShape="url" projectId="p" />);
    drop(null, "https://cdn.example/dragged.png");
    expect(onChange).toHaveBeenCalledWith("https://cdn.example/dragged.png");
  });

  it("says where to go when there is no project to upload to", async () => {
    render(<ImageControl label="photoUrl" value="" onChange={vi.fn()} imageShape="url" projectId={null} />);
    drop(makeFile("a.png", "image/png", 1024));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Paste a URL instead/);
    expect(upload).not.toHaveBeenCalled();
  });
});

describe("ImageControl — upload", () => {
  it("posts to the project's image endpoint and stores the url it returns", async () => {
    const onChange = vi.fn();
    upload.mockResolvedValue({ url: "/api/asset/gh0mlpbp/figma/uabc.png", file: "uabc.png", media_type: "image/png", bytes: 20166 });
    render(<ImageControl label="photoUrl" value="" onChange={onChange} imageShape="url" projectId="gh0mlpbp" />);
    drop(makeFile("logo.png", "image/png", 20166));

    await waitFor(() => expect(onChange).toHaveBeenCalledWith("/api/asset/gh0mlpbp/figma/uabc.png"));
    expect(upload.mock.calls[0][0]).toBe("/api/projects/gh0mlpbp/images");
    expect(upload.mock.calls[0][1]).toBeInstanceOf(FormData);
  });

  it("shows the backend's own 400 wording rather than a generic failure", async () => {
    upload.mockRejectedValue(new FakeApiError(400, "cat.bmp is not an image — pick a PNG, JPEG, GIF or WebP file."));
    render(<ImageControl label="photoUrl" value="" onChange={vi.fn()} imageShape="url" projectId="p" />);
    drop(makeFile("cat.png", "image/png", 1024));
    expect((await screen.findByRole("alert")).textContent).toMatch(/is not an image/);
  });

  it("surfaces a network failure instead of swallowing it", async () => {
    upload.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<ImageControl label="photoUrl" value="" onChange={vi.fn()} imageShape="url" projectId="p" />);
    drop(makeFile("cat.png", "image/png", 1024));
    expect((await screen.findByRole("alert")).textContent).toMatch(/Couldn't upload cat\.png.*Failed to fetch/);
  });
});

describe("ImageControl — dimensions", () => {
  it("reports the image's real pixel size once it decodes", async () => {
    stubImage(1600, 900);
    render(<ImageControl label="photoUrl" value="/api/asset/p/figma/a.png" onChange={vi.fn()} imageShape="url" />);
    expect(await screen.findByText(/1600 x 900 px/)).toBeTruthy();
  });

  it("tells the user how the Avatar slot will treat it", async () => {
    stubImage(400, 100);
    render(
      <ImageControl label="photoUrl" value="/a.png" onChange={vi.fn()} imageShape="url"
        nodeType="Avatar" nodeProps={{ size: "lg" }} />,
    );
    expect(await screen.findByText(/Slot renders at 64x64 \(cover\)/)).toBeTruthy();
    expect(screen.getByText(/sides will be cropped/)).toBeTruthy();
  });

  it("says the image could not be read when it fails to decode", async () => {
    stubImage(0, 0, true);
    render(<ImageControl label="photoUrl" value="https://nope/x.png" onChange={vi.fn()} imageShape="url" />);
    expect(await screen.findByText(/couldn't load that image/i)).toBeTruthy();
  });
});

/**
 * The wiring, not the component. A control nobody selects is a control nobody
 * has — and the selection runs through the REGISTRY (`descriptor.control`),
 * which is the whole reason "which props are image-valued" is declared there
 * instead of in a name list here.
 */
describe("registry → panel wiring", () => {
  const IMAGE_PROPS: Array<[string, string, string]> = [
    ["Avatar", "photoUrl", "url"],
    ["Avatar", "src", "url"],
    ["PersonCard", "avatarUrl", "url"],
    ["Hero", "backgroundImage", "overlay"],
    ["Hero", "media", "media"],
  ];

  it.each(IMAGE_PROPS)("%s.%s is declared control:image with imageShape:%s", (comp, prop, shape) => {
    const d = (starterRegistry as any)[comp].props[prop];
    expect(d.control).toBe("image");
    expect(d.imageShape).toBe(shape);
  });

  it("every control:image prop in the whole registry declares a shape", () => {
    for (const [name, entry] of Object.entries(starterRegistry as any)) {
      for (const [prop, d] of Object.entries((entry as any).props as Record<string, any>)) {
        if (d.control === "image") {
          expect(d.imageShape, `${name}.${prop}`).toBeTruthy();
        }
      }
    }
  });

  it("renders the drop target for Avatar.photoUrl, with the slot size from the sibling size prop", async () => {
    const node = { id: "av1", type: "Avatar", props: { name: "Ada", photoUrl: "/a.png", size: "lg" } };
    useEditorStore.setState({
      artifacts: {
        pageSchemas: { home: { root: { id: "r", type: "Stack", children: [node] } } },
      } as any,
      selectedNodeIds: ["av1"],
      selectedNodeId: "av1",
      projectId: "gh0mlpbp",
    });
    stubImage(400, 100);
    render(<PropertiesPanelInner />);

    expect(screen.getAllByTestId("image-dropzone").length).toBeGreaterThan(0);
    // 64x64 is Avatar's lg (h-16) — proof the panel handed the control the
    // owning node's OTHER props, not just the value being edited.
    expect(await screen.findByText(/Slot renders at 64x64/)).toBeTruthy();
  });

  it("does not turn a plain text prop into a drop target", () => {
    const node = { id: "av2", type: "Avatar", props: { name: "Ada" } };
    useEditorStore.setState({
      artifacts: { pageSchemas: { home: { root: { id: "r", type: "Stack", children: [node] } } } } as any,
      selectedNodeIds: ["av2"], selectedNodeId: "av2", projectId: "p",
    });
    render(<PropertiesPanelInner />);
    // Avatar has two image props (photoUrl, src) and no more.
    expect(screen.getAllByTestId("image-dropzone")).toHaveLength(2);
  });
});
