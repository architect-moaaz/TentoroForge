import { describe, it, expect, vi } from "vitest";
import { render, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { Button } from "../src/components/Button/Button";

describe("a Button's args and the form around it", () => {
  it("sends the form's values with the args on top, args winning on a shared name", async () => {
    const dispatch = vi.fn();
    const { getByText } = render(
      <form>
        <input name="reason" defaultValue="Late refund" />
        <input name="decision" defaultValue="from-the-form" />
        <Button label="Approve" workflow="FLOW-019"
                args={{ decision: "APPROVED" }} __dispatch={dispatch} />
      </form>,
    );
    fireEvent.click(getByText("Approve"));
    await waitFor(() => expect(dispatch).toHaveBeenCalled());
    expect(dispatch).toHaveBeenCalledWith("FLOW-019", { reason: "Late refund", decision: "APPROVED" });
  });
});
