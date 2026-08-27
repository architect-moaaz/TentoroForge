import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HoverCard } from "../../src/components/HoverCard/HoverCard";
import { HoverCardProps } from "../../src/components/HoverCard/HoverCard.schema";

describe("HoverCard", () => {
  it("renders the trigger label", () => {
    render(<HoverCard label="@ahmed" title="Ahmed Al-Mansoori" content="Driver since 2021" />);
    expect(screen.getByText("@ahmed")).toBeInTheDocument();
  });
  it("reveals the card content on hover", async () => {
    render(<HoverCard label="@ahmed" title="Ahmed Al-Mansoori" content="Driver since 2021" />);
    await userEvent.hover(screen.getByText("@ahmed"));
    expect(await screen.findByText("Driver since 2021")).toBeInTheDocument();
  });
  it("validates props", () => {
    expect(() => HoverCardProps.parse({ label: "X", content: "Y" })).not.toThrow();
    expect(() => HoverCardProps.parse({})).not.toThrow();
  });
});
