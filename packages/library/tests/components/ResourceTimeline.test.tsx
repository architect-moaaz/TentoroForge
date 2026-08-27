import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { ResourceTimeline } from "../../src/components/ResourceTimeline/ResourceTimeline";
import { ResourceTimelineProps } from "../../src/components/ResourceTimeline/ResourceTimeline.schema";

const rooms = [
  { id: "101", name: "101", sub: "1 King", type: "Standard King" },
  { id: "102", name: "102", sub: "1 King", type: "Standard King" },
  { id: "201", name: "201", sub: "1 Queen", type: "Deluxe Queen" },
];

const reservations = [
  { id: "r1", roomId: "101", start: "2026-07-01", end: "2026-07-04", guest: "D. Okonkwo", status: "Confirmed" },
  { id: "r2", roomId: "102", start: "2026-07-02", end: "2026-07-03", guest: "M. Ferrante", status: "In-house" },
  { id: "r3", roomId: "201", start: "2026-07-05", end: "2026-07-07", guest: "Hold — Corp", status: "Tentative hold" },
];

const common = {
  resources: rooms, items: reservations,
  resourceLabelField: "name", resourceSubField: "sub", resourceGroupField: "type",
  itemResourceField: "roomId", startField: "start", endField: "end",
  titleField: "guest", statusField: "status",
  rangeStart: "2026-07-01", days: 10,
};

describe("ResourceTimeline", () => {
  it("renders a row per resource with its label + sub-label", () => {
    render(<ResourceTimeline {...common} />);
    expect(screen.getByText("101")).toBeInTheDocument();
    expect(screen.getByText("201")).toBeInTheDocument();
    expect(screen.getAllByText("1 King").length).toBe(2);
  });

  it("groups resources under their group field header", () => {
    render(<ResourceTimeline {...common} />);
    expect(screen.getByText("Standard King")).toBeInTheDocument();
    expect(screen.getByText("Deluxe Queen")).toBeInTheDocument();
  });

  it("draws a bar per item with its title", () => {
    render(<ResourceTimeline {...common} />);
    expect(screen.getByText("D. Okonkwo")).toBeInTheDocument();
    expect(screen.getByText("M. Ferrante")).toBeInTheDocument();
  });

  it("positions a bar across the correct day span (gridColumn)", () => {
    render(<ResourceTimeline {...common} />);
    const bar = screen.getByText("D. Okonkwo").closest("[data-timeline-item]") as HTMLElement;
    // start 07-01 = col offset 0 → gridColumn start 2; end 07-04 → 2 + 3 = 5
    expect(bar.style.gridColumn).toBe("2 / 5");
  });

  it("renders holds as a dashed (transparent) bar", () => {
    render(<ResourceTimeline {...common} />);
    const bar = screen.getByText("Hold — Corp").closest("[data-timeline-item]") as HTMLElement;
    expect(bar.style.background).toBe("transparent");
    expect(bar.style.border).toContain("dashed");
  });

  it("shows a status legend for the distinct statuses", () => {
    render(<ResourceTimeline {...common} />);
    const legend = document.querySelector("[data-timeline-legend]") as HTMLElement;
    expect(legend).toBeTruthy();
    expect(within(legend).getByText("Confirmed")).toBeInTheDocument();
  });

  it("clamps items that start before the visible range", () => {
    render(<ResourceTimeline {...common} items={[{ id: "x", roomId: "101", start: "2026-06-28", end: "2026-07-03", guest: "Early", status: "Confirmed" }]} />);
    const bar = screen.getByText("Early").closest("[data-timeline-item]") as HTMLElement;
    // clamped to first column → gridColumn starts at 2
    expect(bar.style.gridColumn.startsWith("2 /")).toBe(true);
  });

  it("renders an empty state when there are no resources", () => {
    render(<ResourceTimeline resources={[]} items={[]} emptyText="Nothing scheduled" />);
    expect(screen.getByText("Nothing scheduled")).toBeInTheDocument();
  });

  it("links bars when itemHref is set", () => {
    render(<ResourceTimeline {...common} itemHref="/reservations/{id}" />);
    const link = screen.getByText("D. Okonkwo").closest("a") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/reservations/r1");
  });

  it("validates props (data-driven + empty)", () => {
    expect(() => ResourceTimelineProps.parse(common)).not.toThrow();
    expect(() => ResourceTimelineProps.parse({})).not.toThrow();
  });
});
