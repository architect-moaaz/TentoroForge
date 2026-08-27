import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ImportModal } from "../../src/panes/Figma/ImportModal";

const VALID_URL =
  "https://www.figma.com/design/abc123/My-Design?node-id=1-2&t=xyz";

const CANNED_SCHEMA = {
  root: { id: "n1", type: "Box", children: [] },
};

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("ImportModal", () => {
  it("renders nothing when open=false", () => {
    const { container } = render(
      <ImportModal open={false} onClose={vi.fn()} onImport={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders dialog when open=true", () => {
    render(<ImportModal open onClose={vi.fn()} onImport={vi.fn()} />);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Figma URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Save path")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Extract" })).toBeInTheDocument();
  });

  it("shows error for invalid URL", async () => {
    render(<ImportModal open onClose={vi.fn()} onImport={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Figma URL"), "https://not-figma.com");
    await userEvent.click(screen.getByRole("button", { name: "Extract" }));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("alert").textContent).toMatch(/invalid figma url/i);
  });

  it("shows 'Extracting…' then schema preview on success", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ schema: CANNED_SCHEMA }), { status: 200 })
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ImportModal open onClose={vi.fn()} onImport={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Figma URL"), VALID_URL);
    await userEvent.type(screen.getByLabelText("Save path"), "products/imported");
    await userEvent.click(screen.getByRole("button", { name: "Extract" }));

    await waitFor(() =>
      expect(screen.getByText(/extracted successfully/i)).toBeInTheDocument()
    );
    expect(screen.getByRole("button", { name: "Save as page" })).toBeInTheDocument();
  });

  it("shows API error when response contains error field", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({ schema: null, error: "MCP tools not yet bound" }),
          { status: 200 }
        )
      )
    );

    render(<ImportModal open onClose={vi.fn()} onImport={vi.fn()} />);
    await userEvent.type(screen.getByLabelText("Figma URL"), VALID_URL);
    await userEvent.click(screen.getByRole("button", { name: "Extract" }));

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toMatch(/MCP tools not yet bound/i)
    );
  });

  it("calls onImport with schema + savePath and onClose when Save clicked", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ schema: CANNED_SCHEMA }), { status: 200 })
      )
    );
    const onImport = vi.fn();
    const onClose = vi.fn();

    render(
      <ImportModal open onClose={onClose} onImport={onImport} />
    );
    await userEvent.type(screen.getByLabelText("Figma URL"), VALID_URL);
    await userEvent.type(screen.getByLabelText("Save path"), "pages/imported");
    await userEvent.click(screen.getByRole("button", { name: "Extract" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save as page" })).toBeInTheDocument()
    );
    await userEvent.click(screen.getByRole("button", { name: "Save as page" }));

    expect(onImport).toHaveBeenCalledWith(CANNED_SCHEMA, "pages/imported");
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when Cancel button clicked", async () => {
    const onClose = vi.fn();
    render(<ImportModal open onClose={onClose} onImport={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when backdrop clicked", async () => {
    const onClose = vi.fn();
    render(<ImportModal open onClose={onClose} onImport={vi.fn()} />);
    const backdrop = screen.getByRole("dialog");
    await userEvent.click(backdrop);
    expect(onClose).toHaveBeenCalled();
  });
});
