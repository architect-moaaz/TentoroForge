import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Tag } from "../../src/components/Tag/Tag";
import { TagProps } from "../../src/components/Tag/Tag.schema";

describe("Tag", () => {
  it("renders the label", () => {
    render(<Tag label="Active" />);
    expect(screen.getByText("Active")).toBeInTheDocument();
  });
  it("shows a remove button only when removable and fires onRemove", () => {
    const onRemove = vi.fn();
    const { rerender } = render(<Tag label="x" />);
    expect(screen.queryByRole("button", { name: /remove/i })).toBeNull();
    rerender(<Tag label="x" removable onRemove={onRemove} />);
    fireEvent.click(screen.getByRole("button", { name: /remove/i }));
    expect(onRemove).toHaveBeenCalledTimes(1);
  });
  it("validates props", () => {
    expect(() => TagProps.parse({ label: "A", variant: "success", removable: true })).not.toThrow();
    expect(() => TagProps.parse({})).not.toThrow();
  });
});
