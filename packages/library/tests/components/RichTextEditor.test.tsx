import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { RichTextEditor } from "../../src/components/RichTextEditor/RichTextEditor";
import { RichTextEditorProps } from "../../src/components/RichTextEditor/RichTextEditor.schema";

describe("RichTextEditor", () => {
  it("renders a formatting toolbar and an editable region", () => {
    render(<RichTextEditor label="Notes" />);
    expect(screen.getByRole("button", { name: /bold/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /italic/i })).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });
  it("fires onChange with the editor HTML on input", () => {
    const onChange = vi.fn();
    render(<RichTextEditor onChange={onChange} />);
    const box = screen.getByRole("textbox");
    box.innerHTML = "<b>hi</b>";
    fireEvent.input(box);
    expect(onChange).toHaveBeenCalledWith("<b>hi</b>");
  });
  it("invokes document.execCommand when a toolbar button is pressed", () => {
    const exec = vi.fn();
    // jsdom has no execCommand by default
    (document as any).execCommand = exec;
    render(<RichTextEditor />);
    fireEvent.click(screen.getByRole("button", { name: /bold/i }));
    expect(exec).toHaveBeenCalledWith("bold");
  });
  it("validates props", () => {
    expect(() => RichTextEditorProps.parse({ value: "<p>x</p>" })).not.toThrow();
    expect(() => RichTextEditorProps.parse({})).not.toThrow();
  });
});
