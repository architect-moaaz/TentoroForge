import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Transfer } from "../../src/components/Transfer/Transfer";
import { TransferProps } from "../../src/components/Transfer/Transfer.schema";

const opts = [{ value: "a", label: "Alpha" }, { value: "b", label: "Bravo" }, { value: "c", label: "Charlie" }];

describe("Transfer", () => {
  it("renders all options on the available side initially", () => {
    render(<Transfer options={opts} />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Charlie")).toBeInTheDocument();
  });
  it("moves an item to the selected side and fires onChange", () => {
    const onChange = vi.fn();
    render(<Transfer options={opts} onChange={onChange} />);
    fireEvent.click(screen.getByText("Bravo"));            // select it
    fireEvent.click(screen.getByRole("button", { name: /move right/i }));
    expect(onChange).toHaveBeenCalledWith(["b"]);
  });
  it("respects an initial selected prop", () => {
    render(<Transfer options={opts} selected={["a"]} />);
    const selectedPanel = screen.getByTestId("transfer-selected");
    expect(selectedPanel).toHaveTextContent("Alpha");
  });
  it("validates props", () => {
    expect(() => TransferProps.parse({ options: opts, selected: ["a"] })).not.toThrow();
    expect(() => TransferProps.parse({})).not.toThrow();
  });
});
