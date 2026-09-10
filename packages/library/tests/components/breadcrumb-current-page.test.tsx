import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { Breadcrumb } from "../../src/components/Breadcrumb/Breadcrumb";

/**
 * "No currentPageAuto option — every breadcrumb has to be hand-authored per
 * page even though the editor knows the page's route."
 *
 * The last crumb is always "where I am", so the same trail was copied onto
 * every page with one word changed, and it went stale silently the moment a
 * route was renamed. The two things worth pinning are that it is OFF unless
 * asked for, and that it refuses to duplicate a trail somebody already finished
 * by hand.
 */

function at(path: string) {
  window.history.replaceState({}, "", path);
}

const TRAIL = [
  { label: "Items", href: "/items" },
  { label: "Widget A", href: "/items/1" },
];

describe("Breadcrumb.currentPageAuto", () => {
  beforeEach(() => at("/"));

  it("is off by default — no crumb appears that was not authored", async () => {
    at("/items/1/edit");
    render(<Breadcrumb items={TRAIL} />);
    expect(screen.queryByText("Edit")).toBeNull();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("appends a crumb labelled from the route's last segment", async () => {
    at("/items/1/edit");
    render(<Breadcrumb items={TRAIL} currentPageAuto />);
    const crumb = await screen.findByText("Edit");
    expect(crumb).toHaveAttribute("aria-current", "page");
    // and it is text, not a link — you do not link to the page you are on.
    expect(crumb.tagName).toBe("SPAN");
  });

  it("humanises a multi-word segment the same way a field key is humanised", async () => {
    at("/items/stock-intake");
    render(<Breadcrumb items={TRAIL} currentPageAuto />);
    expect(await screen.findByText("Stock Intake")).toBeInTheDocument();
  });

  it("does not duplicate a trail that already ends at the current page", async () => {
    at("/items/1");
    render(<Breadcrumb items={TRAIL} currentPageAuto />);
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
  });

  it("does not append after a trail whose last crumb is already unlinked", async () => {
    at("/items/1/edit");
    render(
      <Breadcrumb
        items={[{ label: "Items", href: "/items" }, { label: "Editing" }]}
        currentPageAuto
      />,
    );
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
  });

  it("resolves under a preview base path — the crumb is the page, not the prefix", async () => {
    at("/p/proj1/items/1/edit");
    render(<Breadcrumb items={TRAIL} currentPageAuto />);
    expect(await screen.findByText("Edit")).toBeInTheDocument();
  });
});
