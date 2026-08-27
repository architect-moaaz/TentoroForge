import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DescriptionList } from "../../src/components/DescriptionList/DescriptionList";
import { DescriptionListProps } from "../../src/components/DescriptionList/DescriptionList.schema";

describe("DescriptionList", () => {
  it("renders term/description pairs", () => {
    render(<DescriptionList items={[{ term: "Status", description: "Active" }, { term: "Owner", description: "Jane" }]} />);
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Jane")).toBeInTheDocument();
  });
  it("reflects orientation in a data attribute", () => {
    const { container } = render(<DescriptionList orientation="horizontal" items={[{ term: "A", description: "1" }]} />);
    expect(container.querySelector("[data-description-list]")?.getAttribute("data-orientation")).toBe("horizontal");
  });
  it("validates props", () => {
    expect(() => DescriptionListProps.parse({ items: [{ term: "A", description: "B" }] })).not.toThrow();
    expect(() => DescriptionListProps.parse({})).not.toThrow();
  });
});
