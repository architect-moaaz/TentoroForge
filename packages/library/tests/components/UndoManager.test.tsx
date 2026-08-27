/**
 * UndoManager — Spec E Wave 1.
 *
 * Sanity-check the event-bus contract: pushing `forge:undo:push`
 * renders a toast; clicking Undo fires the callback + removes it;
 * an empty queue renders nothing.
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, cleanup, fireEvent, act } from "@testing-library/react";
import * as React from "react";

import { UndoManager } from "../../src/components/UndoManager/UndoManager";

function pushEntry(id: string, label: string, undo: () => void) {
  act(() => {
    window.dispatchEvent(
      new CustomEvent("forge:undo:push", {
        detail: { id, label, undo },
      }),
    );
  });
}

describe("UndoManager", () => {
  afterEach(() => cleanup());

  it("renders nothing when the queue is empty", () => {
    const { container } = render(<UndoManager timeoutMs={0} />);
    expect(container.querySelector("[data-forge-undo-manager]")).toBeNull();
  });

  it("shows a toast when an undo entry is pushed", () => {
    const { container, getByText } = render(<UndoManager timeoutMs={0} />);
    pushEntry("u1", "Task moved", () => {});
    expect(container.querySelector("[data-forge-undo-manager]")).not.toBeNull();
    expect(getByText("Task moved")).toBeTruthy();
  });

  it("clicking Undo invokes the callback and dismisses the toast", () => {
    const spy = vi.fn();
    const { container, getByText } = render(<UndoManager timeoutMs={0} />);
    pushEntry("u2", "Row deleted", spy);
    fireEvent.click(getByText("Undo"));
    expect(spy).toHaveBeenCalledOnce();
    expect(container.querySelector("[data-forge-undo-manager]")).toBeNull();
  });

  it("labelPrefix is prepended when present", () => {
    const { getByText } = render(
      <UndoManager timeoutMs={0} labelPrefix="Done:" />,
    );
    pushEntry("u3", "moved 3 items", () => {});
    expect(getByText("Done: moved 3 items")).toBeTruthy();
  });
});
