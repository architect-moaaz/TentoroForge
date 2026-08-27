import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CustomNodePreview } from "../../../src/panes/Canvas/CustomNodePreview";

function makeNode(overrides: {
  id?: string;
  html?: string;
  tailwind?: string;
  label?: string;
} = {}) {
  return {
    id: overrides.id ?? "node-1",
    props: {
      html: overrides.html,
      tailwind: overrides.tailwind,
      label: overrides.label,
    },
  };
}

describe("CustomNodePreview", () => {
  it("renders sanitised HTML and strips <script>", () => {
    const node = makeNode({ html: '<p>hi</p><script>alert(1)</script>' });
    const { container } = render(<CustomNodePreview node={node} />);
    // <p>hi</p> survives
    expect(container.querySelector("p")).not.toBeNull();
    expect(container.querySelector("p")!.textContent).toBe("hi");
    // <script> is stripped
    expect(container.querySelector("script")).toBeNull();
    expect(container.innerHTML).not.toContain("alert(1)");
  });

  it("renders empty-state hint when html is missing", () => {
    const node = makeNode({ html: undefined });
    render(<CustomNodePreview node={node} />);
    expect(
      screen.getByText(/Empty Custom block — click "Edit" to add content/i)
    ).toBeInTheDocument();
  });

  it("renders empty-state hint when html is an empty string", () => {
    const node = makeNode({ html: "" });
    render(<CustomNodePreview node={node} />);
    expect(
      screen.getByText(/Empty Custom block — click "Edit" to add content/i)
    ).toBeInTheDocument();
  });

  it("shows the label in the chip when props.label is set", () => {
    const node = makeNode({ label: "My Widget" });
    render(<CustomNodePreview node={node} />);
    expect(screen.getByRole("button")).toHaveTextContent(/My Widget/);
  });

  it("falls back to 'Custom' in the chip when label is not set", () => {
    const node = makeNode({ label: undefined });
    render(<CustomNodePreview node={node} />);
    expect(screen.getByRole("button")).toHaveTextContent(/Custom/);
  });

  it("clicking the chip fires onEdit", async () => {
    const user = userEvent.setup();
    const onEdit = vi.fn();
    const node = makeNode({ label: "Clickable" });
    render(<CustomNodePreview node={node} onEdit={onEdit} />);
    await user.click(screen.getByRole("button"));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it("does not throw when onEdit is not provided and chip is clicked", async () => {
    const user = userEvent.setup();
    const node = makeNode({ label: "No handler" });
    render(<CustomNodePreview node={node} />);
    // Should not throw
    await user.click(screen.getByRole("button"));
  });

  it("html-injecting div has pointer-events: none style", () => {
    const node = makeNode({ html: "<p>test</p>" });
    const { container } = render(<CustomNodePreview node={node} />);
    // Find the inner div that holds the sanitised HTML
    const innerDiv = container.querySelector('[style*="pointer-events: none"]');
    expect(innerDiv).not.toBeNull();
  });

  it("sets data-node-id and data-custom-preview on wrapper", () => {
    const node = makeNode({ id: "custom-abc", html: "<b>x</b>" });
    const { container } = render(<CustomNodePreview node={node} />);
    const wrapper = container.querySelector('[data-custom-preview]');
    expect(wrapper).not.toBeNull();
    expect(wrapper!.getAttribute("data-node-id")).toBe("custom-abc");
  });
});
