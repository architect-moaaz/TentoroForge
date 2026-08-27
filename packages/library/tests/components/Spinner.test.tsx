import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Spinner } from "../../src/components/Spinner/Spinner";
import { SpinnerProps } from "../../src/components/Spinner/Spinner.schema";

describe("Spinner", () => {
  it("renders a status role with an accessible label", () => {
    render(<Spinner label="Loading data" />);
    expect(screen.getByRole("status", { name: "Loading data" })).toBeInTheDocument();
  });
  it("defaults to a generic Loading label", () => {
    render(<Spinner />);
    expect(screen.getByRole("status", { name: /loading/i })).toBeInTheDocument();
  });
  it("validates props", () => {
    expect(() => SpinnerProps.parse({ label: "X", size: "lg" })).not.toThrow();
    expect(() => SpinnerProps.parse({})).not.toThrow();
  });
});
