import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Rating } from "../../src/components/Rating/Rating";
import { RatingProps } from "../../src/components/Rating/Rating.schema";

describe("Rating", () => {
  it("renders `max` star buttons", () => {
    render(<Rating name="score" label="Rate it" max={5} />);
    expect(screen.getAllByRole("button")).toHaveLength(5);
  });
  it("fires onChange with the clicked rating", async () => {
    const onChange = vi.fn();
    render(<Rating name="score" label="Rate it" max={5} onChange={onChange} />);
    await userEvent.click(screen.getByRole("button", { name: "Rate 3" }));
    expect(onChange).toHaveBeenCalledWith(3);
  });
  it("marks stars up to the current value as selected", () => {
    render(<Rating name="score" label="Rate it" max={5} value={2} />);
    expect(screen.getByRole("button", { name: "Rate 1" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Rate 2" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Rate 3" })).toHaveAttribute("aria-pressed", "false");
  });
  it("validates props", () => {
    expect(() => RatingProps.parse({ name: "r" })).not.toThrow();
    expect(() => RatingProps.parse({})).not.toThrow();
  });
});
