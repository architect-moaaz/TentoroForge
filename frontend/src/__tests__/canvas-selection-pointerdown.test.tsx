/**
 * Regression — audit log, "DropdownMenu · 2. The node cannot be selected in the
 * editor, so its Props panel is unreachable."
 *
 * Repro from the report: click the trigger on the canvas → the runtime menu
 * opens and the Properties panel still reads "Select a node on the canvas to
 * edit its props", every time. With no layers panel, such a node can never be
 * configured, restyled or deleted once it is dropped.
 *
 * The cause is not in that component and the fix is not keyed to it. Overlay
 * primitives open on POINTER-DOWN and then set `pointer-events: none` on the
 * body while open, so the later `click` the canvas selected on no longer has
 * the node in its target chain. Selection therefore runs on pointer-down in the
 * capture phase, ahead of any runtime handler, for every node on the canvas.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import * as React from "react";
import { render, cleanup, fireEvent } from "@testing-library/react";
import { useEditorStore } from "@/lib/editor-store";
import {
  useCanvasClick,
  useCanvasPointerDown,
} from "@/components/canvas/hooks/useSelection";

// jsdom ships no PointerEvent, and testing-library then falls back to a bare
// Event whose `button` is undefined — which would make the right-button case
// below untestable. A MouseEvent subclass is enough: it carries `button` and
// the modifier flags, which is all the canvas reads.
if (typeof window !== "undefined" && !(window as any).PointerEvent) {
  (window as any).PointerEvent = class extends MouseEvent {};
}

/**
 * The canvas root, wired exactly as Canvas.tsx wires it. A paraphrase would
 * prove nothing, so the handlers come from the real hooks.
 */
function CanvasHarness({
  runtimeHandlers,
}: {
  runtimeHandlers: {
    onPointerDown: () => void;
    onMouseDown: () => void;
    onClick: () => void;
  };
}) {
  const onClick = useCanvasClick();
  const onPointerDownCapture = useCanvasPointerDown();
  return (
    <div
      data-canvas-root
      onClick={onClick}
      onPointerDownCapture={onPointerDownCapture}
      onMouseDownCapture={onPointerDownCapture}
    >
      {/* Stands in for any component that acts on pointer-down — a menu
          trigger, a popover, a combobox. Nothing here names one. */}
      <div data-node-id="node-1">
        <button type="button" data-testid="trigger" {...runtimeHandlers}>
          Actions
        </button>
      </div>
      <div data-testid="bare-canvas" style={{ height: 20 }} />
    </div>
  );
}

function handlers() {
  return {
    onPointerDown: vi.fn(),
    onMouseDown: vi.fn(),
    onClick: vi.fn(),
  };
}

beforeEach(() => {
  useEditorStore.getState().clearSelection();
});
afterEach(cleanup);

describe("canvas selection — pointer-down, capture phase", () => {
  it("selects the node on pointer-down, before the component can react", () => {
    const h = handlers();
    const { getByTestId } = render(<CanvasHarness runtimeHandlers={h} />);
    fireEvent.pointerDown(getByTestId("trigger"), { button: 0 });
    expect(useEditorStore.getState().selectedNodeId).toBe("node-1");
  });

  it("keeps the runtime handler from firing — the menu never opens while editing", () => {
    const h = handlers();
    const { getByTestId } = render(<CanvasHarness runtimeHandlers={h} />);
    fireEvent.pointerDown(getByTestId("trigger"), { button: 0 });
    fireEvent.mouseDown(getByTestId("trigger"), { button: 0 });
    expect(h.onPointerDown).not.toHaveBeenCalled();
    expect(h.onMouseDown).not.toHaveBeenCalled();
  });

  it("still selects when the click that follows has lost the node (body pointer-events: none)", () => {
    // The exact failure mode: an open overlay makes the body inert, so the
    // click lands somewhere with no [data-node-id] above it. Selection must
    // already have happened.
    const h = handlers();
    const { getByTestId } = render(<CanvasHarness runtimeHandlers={h} />);
    fireEvent.pointerDown(getByTestId("trigger"), { button: 0 });
    expect(useEditorStore.getState().selectedNodeId).toBe("node-1");
    fireEvent.click(getByTestId("bare-canvas"));
    // The stray click clears, as a click on bare canvas always has — but the
    // node was reachable, which is what the report said it never was.
    expect(useEditorStore.getState().selectedNodeId).toBeNull();
  });

  it("honours the same modifiers as click", () => {
    const h = handlers();
    const { getByTestId } = render(<CanvasHarness runtimeHandlers={h} />);
    fireEvent.pointerDown(getByTestId("trigger"), { button: 0 });
    fireEvent.pointerDown(getByTestId("trigger"), { button: 0, metaKey: true });
    // ctrl/cmd toggles, so the second press removes it again.
    expect(useEditorStore.getState().selectedNodeIds ?? []).not.toContain("node-1");
  });

  it("leaves the right button alone — a context menu must still reach the browser", () => {
    const h = handlers();
    const { getByTestId } = render(<CanvasHarness runtimeHandlers={h} />);
    fireEvent.pointerDown(getByTestId("trigger"), { button: 2 });
    expect(useEditorStore.getState().selectedNodeId).toBeNull();
  });

  it("does not swallow pointer-down on bare canvas — drags from the background still start", () => {
    const h = handlers();
    const { getByTestId } = render(<CanvasHarness runtimeHandlers={h} />);
    fireEvent.pointerDown(getByTestId("bare-canvas"), { button: 0 });
    expect(useEditorStore.getState().selectedNodeId).toBeNull();
  });
});
