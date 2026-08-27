import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { List } from "../../src/components/List/List";
import { ListProps } from "../../src/components/List/List.schema";

describe("List", () => {
  it("renders item titles and subtitles", () => {
    render(<List items={[{ title: "Gate A", subtitle: "Open" }, { title: "Gate B", subtitle: "Closed" }]} />);
    expect(screen.getByText("Gate A")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText("Gate B")).toBeInTheDocument();
  });
  it("fires onItemClick with the item index", () => {
    const onItemClick = vi.fn();
    render(<List items={[{ title: "X" }, { title: "Y" }]} onItemClick={onItemClick} />);
    fireEvent.click(screen.getByText("Y"));
    expect(onItemClick).toHaveBeenCalledWith(1);
  });
  it("validates props", () => {
    expect(() => ListProps.parse({ items: [{ title: "A" }], divided: true })).not.toThrow();
    expect(() => ListProps.parse({})).not.toThrow();
  });
});
