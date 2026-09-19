import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { Form } from "../src/components/Form/Form";
import { FileUpload } from "../src/components/FileUpload/FileUpload";
import { Table } from "../src/components/Table/Table";

// An `image` field is uploaded, stored, and submitted as the stored file's id —
// the value the column holds and the embedding is computed from. A FileUpload
// with `search` is the page's image query: the uploaded id goes to the URL's
// `image`, which the page's op:"similar" source ranks records against.

const STORED = "0f8fad5b-d9cb-469f-a165-70867728950e";

function png(): File {
  return new File([new Uint8Array([137, 80, 78, 71])], "chair.png", { type: "image/png" });
}

describe("an image field and the image search box", () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({
      id: STORED, url: `/api/files/${STORED}`, filename: "chair.png", contentType: "image/png", size: 4,
    }), { status: 200 })) as any;
    window.history.replaceState({}, "", "/products");
  });
  afterEach(() => vi.restoreAllMocks());

  it("a Form's file field submits the stored file's id", async () => {
    const dispatch = vi.fn();
    const { container, getByText } = render(
      <Form workflow="WF-001" __dispatch={dispatch} submitLabel="Create"
        fields={[{ kind: "text", name: "name", label: "Name" },
                 { kind: "file", name: "photo", label: "Photo", required: true, accept: "image/*" }] as any} />,
    );
    fireEvent.change(container.querySelector('input[name="name"]')!, { target: { value: "Red chair" } });
    const picker = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(picker.accept).toBe("image/*");
    fireEvent.change(picker, { target: { files: [png()] } });
    await waitFor(() => expect(getByText("· ✓")).toBeTruthy());   // stored, not just chosen
    fireEvent.click(getByText("Create"));
    await waitFor(() => expect(dispatch).toHaveBeenCalled());
    expect(dispatch.mock.calls[0][0]).toBe("WF-001");
    expect(dispatch.mock.calls[0][1]).toMatchObject({ name: "Red chair", photo: STORED });
  });

  it("a search upload writes the image to the URL and shows what is being searched for", async () => {
    const heard: string[] = [];
    const onUrl = (e: Event) => heard.push((e as CustomEvent).detail.key);
    window.addEventListener("forge:urlstate", onUrl);
    const { container, findByAltText, getByText } = render(<FileUpload name="image" search accept="image/*" />);
    fireEvent.change(container.querySelector('input[type="file"]')!, { target: { files: [png()] } });
    const shown = await findByAltText("The image being searched for");
    expect(new URL(window.location.href).searchParams.get("image")).toBe(STORED);
    expect(heard).toContain("image");                    // the host re-resolves the page
    expect(shown.getAttribute("src")).toBe(`/api/files/preview?src=${STORED}`);
    fireEvent.click(getByText("Clear"));
    expect(new URL(window.location.href).searchParams.get("image")).toBeNull();
    window.removeEventListener("forge:urlstate", onUrl);
  });

  it("a search upload does not submit into a form around it", () => {
    const { container } = render(<form><FileUpload name="image" search /></form>);
    expect(container.querySelector('input[type="hidden"]')).toBeNull();
  });

  it("an image column shows a stored file through the preview route, and a URL as itself", () => {
    const { container } = render(
      <Table columns={[{ key: "photo", label: "Photo", format: "image" }]}
        rows={[{ id: "a", photo: STORED }, { id: "b", photo: "https://cdn.example/x.png" }]} />,
    );
    const srcs = Array.from(container.querySelectorAll("img")).map((i) => i.getAttribute("src"));
    expect(srcs).toEqual([`/api/files/preview?src=${STORED}`, "https://cdn.example/x.png"]);
  });
});
