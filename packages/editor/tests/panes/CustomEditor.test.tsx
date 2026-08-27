import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CustomEditor } from "../../src/panes/Properties/CustomEditor";

function makeNode(overrides: {
  id?: string;
  html?: string;
  tailwind?: string;
  label?: string;
} = {}) {
  return {
    id: overrides.id ?? "node-1",
    props: {
      html: overrides.html ?? "",
      tailwind: overrides.tailwind ?? "",
      label: overrides.label ?? "",
    },
  };
}

describe("CustomEditor", () => {
  it("renders title 'Edit Custom Block' and three input controls", () => {
    render(
      <CustomEditor
        node={makeNode()}
        onSave={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    expect(screen.getByText("Edit Custom Block")).toBeInTheDocument();
    // label input
    expect(screen.getByLabelText(/Label/i)).toBeInTheDocument();
    // HTML textarea
    expect(screen.getByLabelText(/^HTML$/i)).toBeInTheDocument();
    // Tailwind input
    expect(screen.getByLabelText(/Tailwind classes/i)).toBeInTheDocument();
  });

  it("pre-fills inputs with values from node.props", () => {
    const node = makeNode({ html: "<h1>Hello</h1>", tailwind: "p-4 bg-red-100", label: "My Block" });
    render(<CustomEditor node={node} onSave={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByLabelText(/^HTML$/i)).toHaveValue("<h1>Hello</h1>");
    expect(screen.getByLabelText(/Tailwind classes/i)).toHaveValue("p-4 bg-red-100");
    expect(screen.getByLabelText(/Label/i)).toHaveValue("My Block");
  });

  it("calls onSave with updated html when Save is clicked", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    const node = makeNode({ html: "<p>old</p>", tailwind: "p-2", label: "lbl" });
    render(<CustomEditor node={node} onSave={onSave} onCancel={vi.fn()} />);

    const htmlArea = screen.getByLabelText(/^HTML$/i);
    await user.clear(htmlArea);
    await user.type(htmlArea, "<p>new content</p>");
    await user.click(screen.getByRole("button", { name: /^Save$/i }));

    expect(onSave).toHaveBeenCalledTimes(1);
    const arg = onSave.mock.calls[0][0];
    expect(arg.html).toBe("<p>new content</p>");
    // tailwind and label unchanged
    expect(arg.tailwind).toBe("p-2");
    expect(arg.label).toBe("lbl");
  });

  it("calls onCancel and does NOT call onSave when Cancel is clicked", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    const onCancel = vi.fn();
    render(<CustomEditor node={makeNode()} onSave={onSave} onCancel={onCancel} />);

    await user.click(screen.getByRole("button", { name: /^Cancel$/i }));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("also calls onCancel when close button (✕) is clicked", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(<CustomEditor node={makeNode()} onSave={vi.fn()} onCancel={onCancel} />);

    await user.click(screen.getByRole("button", { name: /Close custom editor/i }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("preview block updates as user types in HTML field", async () => {
    const user = userEvent.setup();
    const node = makeNode({ html: "" });
    render(<CustomEditor node={node} onSave={vi.fn()} onCancel={vi.fn()} />);

    const htmlArea = screen.getByLabelText(/^HTML$/i);
    await user.type(htmlArea, "<p>live preview text</p>");

    // The preview should now contain the typed text
    const preview = await screen.findByText("live preview text");
    expect(preview).toBeInTheDocument();
  });

  it("preview strips <script> tags injected via HTML field", async () => {
    const user = userEvent.setup();
    const node = makeNode({ html: "" });
    const { container } = render(<CustomEditor node={node} onSave={vi.fn()} onCancel={vi.fn()} />);

    const htmlArea = screen.getByLabelText(/^HTML$/i);
    await user.type(htmlArea, "<script>alert('xss')</script><span>safe</span>");

    // The safe span content renders in the preview
    const safeEl = await screen.findByText("safe");
    expect(safeEl).toBeInTheDocument();

    // Find the preview block (the div rendered by dangerouslySetInnerHTML, not the textarea)
    // The preview div is the element containing "safe" — it must have no <script> inside it
    const previewBlock = safeEl.closest("div") as HTMLElement;
    expect(previewBlock.querySelectorAll("script").length).toBe(0);
    // The actual DOM node text should not include the script content
    expect(previewBlock.innerHTML).not.toContain("<script>");
  });

  it("has correct ARIA attributes (role=dialog, aria-labelledby, aria-modal)", () => {
    const { container } = render(
      <CustomEditor node={makeNode()} onSave={vi.fn()} onCancel={vi.fn()} />
    );
    const dialog = container.querySelector('[data-custom-editor]');
    expect(dialog).not.toBeNull();
    expect(dialog!.getAttribute("role")).toBe("dialog");
    expect(dialog!.getAttribute("aria-labelledby")).toBe("custom-editor-title");
    expect(dialog!.getAttribute("aria-modal")).toBe("true");
    expect(container.querySelector("#custom-editor-title")).not.toBeNull();
  });

  it("calls onSave with original props verbatim when Save is clicked without changing any field", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    const node = makeNode({ html: "<p>original</p>", tailwind: "p-4 bg-white", label: "MyLabel" });
    render(<CustomEditor node={node} onSave={onSave} onCancel={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /^Save$/i }));

    expect(onSave).toHaveBeenCalledTimes(1);
    const arg = onSave.mock.calls[0][0];
    expect(arg.html).toBe("<p>original</p>");
    expect(arg.tailwind).toBe("p-4 bg-white");
    expect(arg.label).toBe("MyLabel");
  });
});
