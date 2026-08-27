import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Cascader } from "../../src/components/Cascader/Cascader";
import { CascaderProps } from "../../src/components/Cascader/Cascader.schema";

const options = [
  { value: "uae", label: "UAE", children: [
    { value: "dxb", label: "Dubai", children: [
      { value: "jebel", label: "Jebel Ali" },
    ]},
  ]},
];

describe("Cascader", () => {
  it("renders the first column", () => {
    render(<Cascader options={options} />);
    expect(screen.getByText("UAE")).toBeInTheDocument();
  });
  it("reveals child columns as parents are clicked and fires onChange with the path on leaf select", () => {
    const onChange = vi.fn();
    render(<Cascader options={options} onChange={onChange} />);
    fireEvent.click(screen.getByText("UAE"));
    fireEvent.click(screen.getByText("Dubai"));
    fireEvent.click(screen.getByText("Jebel Ali"));
    expect(onChange).toHaveBeenCalledWith(["uae", "dxb", "jebel"]);
  });
  it("validates props", () => {
    expect(() => CascaderProps.parse({ options })).not.toThrow();
    expect(() => CascaderProps.parse({})).not.toThrow();
  });
});
