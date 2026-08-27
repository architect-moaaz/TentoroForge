// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";
import { WorkflowDispatcherProvider, WorkflowDispatcherContext } from "../src/client/WorkflowDispatcher";
import { useContext } from "react";

function Probe() {
  const dispatch = useContext(WorkflowDispatcherContext);
  dispatch?.("foo", { x: 1 });
  return null;
}

describe("WorkflowDispatcherProvider", () => {
  it("provides a dispatch function to descendants", () => {
    const fn = vi.fn();
    render(<WorkflowDispatcherProvider dispatch={fn}><Probe /></WorkflowDispatcherProvider>);
    expect(fn).toHaveBeenCalledWith("foo", { x: 1 });
  });
});
