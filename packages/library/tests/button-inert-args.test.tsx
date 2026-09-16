import { describe, it, expect, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { Button } from "../src/components/Button/Button";

// A Delete on a record page whose record is gone: `args: {record: "{{rec.id}}"}`
// resolved to "". Posted, the engine refused with "WHERE id is empty". The
// control is inert instead — disabled, with the reason on its title.
describe("Button — an empty record arg makes the control inert", () => {
  it("is disabled and does not dispatch when a workflow arg is empty", () => {
    const dispatch = vi.fn();
    const { container } = render(
      <Button label="Delete Record" workflow="FLOW-003" args={{ record: "", id: "" }} __dispatch={dispatch} />,
    );
    const btn = container.querySelector("button")!;
    expect(btn.disabled).toBe(true);
    expect(btn.getAttribute("aria-disabled")).toBe("true");
    expect(btn.getAttribute("title")).toContain("record");
    fireEvent.click(btn);
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("dispatches as before when the arg carries the record", () => {
    const dispatch = vi.fn();
    const { container } = render(
      <Button label="Delete Record" workflow="FLOW-003" args={{ record: "abc-1" }} __dispatch={dispatch} />,
    );
    const btn = container.querySelector("button")!;
    expect(btn.disabled).toBe(false);
    fireEvent.click(btn);
    expect(dispatch).toHaveBeenCalledWith("FLOW-003", { record: "abc-1" });
  });
});
