import { describe, it, expect, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { NavigatorProvider } from "@tentoroforge/renderer";
import { Card } from "../src/components/Card/Card";
import { CardProps } from "../src/components/Card/Card.schema";

// A card grid is how most designs present records, but the only clickable card
// was an unstyled Container: a collection of Cards could not offer what a Table
// offers through `rowActions`, and LabConnect's /labs was refused six times for
// listing labs nobody could open.
describe("Card — a card that shows a record can open it", () => {
  const nav = () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn() });

  it("pushes its route on the navigator, not the window", () => {
    const navigator = nav();
    const { getByRole } = render(
      <NavigatorProvider value={navigator}>
        <Card title="City Labs" navigate="/labs/lab-1">rating 4.6</Card>
      </NavigatorProvider>,
    );
    fireEvent.click(getByRole("link"));
    expect(navigator.push).toHaveBeenCalledWith("/labs/lab-1");
  });

  it("opens on Enter and Space, because a link surface owes a keyboard that", () => {
    const navigator = nav();
    const { getByRole } = render(
      <NavigatorProvider value={navigator}>
        <Card navigate="/labs/lab-1">City Labs</Card>
      </NavigatorProvider>,
    );
    fireEvent.keyDown(getByRole("link"), { key: "Enter" });
    fireEvent.keyDown(getByRole("link"), { key: " " });
    expect(navigator.push).toHaveBeenCalledTimes(2);
  });

  it("keeps its card chrome — the look is untouched, only the box changes", () => {
    const { getByText, container } = render(
      <NavigatorProvider value={nav()}>
        <Card title="City Labs" footer="Open until 9pm" navigate="/labs/lab-1">rating 4.6</Card>
      </NavigatorProvider>,
    );
    expect(getByText("City Labs")).toBeTruthy();
    expect(getByText("Open until 9pm")).toBeTruthy();
    expect(container.querySelector("[data-card]")).toBeTruthy();
  });

  it("is an ordinary card when it opens nothing", () => {
    const { container } = render(<Card title="City Labs">rating 4.6</Card>);
    expect(container.querySelector("[role=link]")).toBeNull();
    expect(container.querySelector("[data-card]")).toBeTruthy();
  });

  it("declares the prop, so the composer may write it", () => {
    expect(CardProps.safeParse({ navigate: "/labs/lab-1" }).success).toBe(true);
    expect(CardProps.safeParse({ navigateTo: "/labs/lab-1" }).success).toBe(false);
  });
});
