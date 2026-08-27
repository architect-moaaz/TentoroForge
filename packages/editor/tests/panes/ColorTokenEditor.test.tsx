import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ColorTokenEditor } from "../../src/panes/Theme/ColorTokenEditor";

describe("ColorTokenEditor", () => {
  it("renders both color picker and text input", () => {
    render(<ColorTokenEditor name="primary.500" value="#3b82f6" onChange={() => {}} />);
    expect(screen.getByLabelText(/^primary\.500$/)).toHaveValue("#3b82f6");          // text
    expect(screen.getByLabelText(/primary\.500.*color/i)).toHaveAttribute("type", "color"); // picker
  });

  it("changes propagate from picker to onChange", async () => {
    const onChange = vi.fn();
    render(<ColorTokenEditor name="primary.500" value="#3b82f6" onChange={onChange} />);
    const picker = screen.getByLabelText(/primary\.500.*color/i);
    fireEvent.input(picker, { target: { value: "#ff0000" } });
    expect(onChange).toHaveBeenCalledWith("#ff0000");
  });
});
