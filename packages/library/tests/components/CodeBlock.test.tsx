import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { CodeBlock } from "../../src/components/CodeBlock/CodeBlock";
import { CodeBlockProps } from "../../src/components/CodeBlock/CodeBlock.schema";

describe("CodeBlock", () => {
  it("renders the code and the language label", () => {
    render(<CodeBlock code="const x = 1;" language="ts" />);
    expect(screen.getByText("const x = 1;")).toBeInTheDocument();
    expect(screen.getByText("ts")).toBeInTheDocument();
  });
  it("copies the code to the clipboard when the copy button is clicked", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<CodeBlock code="hello()" />);
    fireEvent.click(screen.getByRole("button", { name: /copy/i }));
    expect(writeText).toHaveBeenCalledWith("hello()");
  });
  it("hides the copy button when showCopy is false", () => {
    render(<CodeBlock code="x" showCopy={false} />);
    expect(screen.queryByRole("button", { name: /copy/i })).toBeNull();
  });
  it("validates props", () => {
    expect(() => CodeBlockProps.parse({ code: "x", language: "py" })).not.toThrow();
    expect(() => CodeBlockProps.parse({})).not.toThrow();
  });
});
