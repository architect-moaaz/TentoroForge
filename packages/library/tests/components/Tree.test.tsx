import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Tree } from "../../src/components/Tree/Tree";
import { TreeProps } from "../../src/components/Tree/Tree.schema";

const data = [
  { label: "Site", value: "site", children: [
    { label: "Gate A", value: "a" },
    { label: "Gate B", value: "b" },
  ]},
];

describe("Tree", () => {
  it("renders root nodes and hides collapsed children initially", () => {
    render(<Tree items={data} />);
    expect(screen.getByText("Site")).toBeInTheDocument();
    expect(screen.queryByText("Gate A")).toBeNull();
  });
  it("expands a node to reveal children when its toggle is clicked", () => {
    render(<Tree items={data} />);
    fireEvent.click(screen.getByRole("button", { name: /expand Site/i }));
    expect(screen.getByText("Gate A")).toBeInTheDocument();
    expect(screen.getByText("Gate B")).toBeInTheDocument();
  });
  it("fires onSelect with a leaf value", () => {
    const onSelect = vi.fn();
    render(<Tree items={data} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /expand Site/i }));
    fireEvent.click(screen.getByText("Gate A"));
    expect(onSelect).toHaveBeenCalledWith("a");
  });
  it("validates props", () => {
    expect(() => TreeProps.parse({ items: data })).not.toThrow();
    expect(() => TreeProps.parse({})).not.toThrow();
  });
});
