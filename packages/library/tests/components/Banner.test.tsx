import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Banner } from "../../src/components/Banner/Banner";
import { BannerProps } from "../../src/components/Banner/Banner.schema";

describe("Banner", () => {
  it("renders title and message with the variant", () => {
    render(<Banner variant="warning" title="Heads up" message="Maintenance at 9pm" />);
    expect(screen.getByText("Heads up")).toBeInTheDocument();
    expect(screen.getByText("Maintenance at 9pm")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveAttribute("data-variant", "warning");
  });
  it("can be dismissed when dismissible", async () => {
    const onDismiss = vi.fn();
    render(<Banner title="Bye" message="x" dismissible onDismiss={onDismiss} />);
    await userEvent.click(screen.getByRole("button", { name: /dismiss/i }));
    expect(onDismiss).toHaveBeenCalled();
  });
  it("validates props", () => {
    expect(() => BannerProps.parse({ message: "X" })).not.toThrow();
    expect(() => BannerProps.parse({})).not.toThrow();
  });
});
