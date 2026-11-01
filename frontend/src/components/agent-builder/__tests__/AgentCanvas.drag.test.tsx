/**
 * Dragging on the diagram: what the canvas tells the page, and when.
 *
 * Dragging a box used to feel stuck on a real agent. Every mouse move of the drag was reported to the whole builder page,
 * which re-rendered everything (and re-read every box's settings) several times per move: on a 30-box agent that was
 * about 50 ms of work per move, so the drag crawled. Now a box moves on the canvas alone while it is held, and the page
 * is told ONCE, when it is dropped. A box dropped from the palette lands where the pointer is in the drawing, however the
 * drawing is zoomed or moved.
 *
 * React Flow itself is replaced by a stand-in that records what it was given, so the test can send the same messages it
 * sends during a real drag (a position change with `dragging` on for each move, one with it off at the drop).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import React from "react";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

const rf: { props: any } = { props: null };
vi.mock("@xyflow/react", async () => {
  const actual = await vi.importActual<any>("@xyflow/react");
  return {
    ...actual,
    ReactFlow: (props: any) => {
      rf.props = props;
      return <div data-testid="rf" />;
    },
    Background: () => null,
    Controls: () => null,
    MiniMap: () => null,
  };
});

import { AgentCanvas } from "../AgentCanvas";

const box = (id: string, x: number, y: number) => ({
  id,
  type: "tool",
  position: { x, y },
  data: { label: id, nodeType: "tool", config: { tool_name: id } },
});
const NODES = [box("t1", 0, 0), box("t2", 300, 0)] as any;

let container: HTMLDivElement;
let root: Root;
const reported = vi.fn();

beforeEach(() => {
  reported.mockReset();
  rf.props = null;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function mount() {
  await act(async () => {
    root.render(<AgentCanvas initialNodes={NODES} initialEdges={[]} onNodesChange={reported} />);
  });
}
const send = (changes: unknown[]) => act(async () => { rf.props.onNodesChange(changes); });
const move = (x: number, y: number, dragging = true) => send([{ type: "position", id: "t1", position: { x, y }, dragging }]);
const lastReport = () => reported.mock.calls.at(-1)![0] as Array<{ id: string; position: { x: number; y: number }; dragging?: boolean }>;
const t1 = (list: Array<{ id: string; position: { x: number; y: number }; dragging?: boolean }>) => list.find((n) => n.id === "t1")!;

describe("dragging a box", () => {
  it("reports the drawing once when it opens, then says nothing for as long as a box is held", async () => {
    await mount();
    expect(reported).toHaveBeenCalledTimes(1);
    for (let i = 1; i <= 40; i++) await move(i * 3, i * 2);
    expect(reported, "forty mouse moves, still one report").toHaveBeenCalledTimes(1);
  });

  it("moves the box on the canvas for every move, so the drag itself stays live", async () => {
    await mount();
    await move(30, 20);
    expect(t1(rf.props.nodes).position).toEqual({ x: 30, y: 20 });
    await move(90, 60);
    expect(t1(rf.props.nodes).position).toEqual({ x: 90, y: 60 });
    expect(reported).toHaveBeenCalledTimes(1);
  });

  it("tells the page once when the box is dropped, with the place it was dropped", async () => {
    await mount();
    for (let i = 1; i <= 10; i++) await move(i * 10, i * 5);
    await send([{ type: "position", id: "t1", dragging: false }]); // what React Flow sends when the button is let go
    expect(reported).toHaveBeenCalledTimes(2);
    expect(t1(lastReport()).position).toEqual({ x: 100, y: 50 });
    expect(t1(lastReport()).dragging).toBe(false);
  });

  it("still reports at once for what is not a drag: removing a box, selecting one", async () => {
    await mount();
    await send([{ type: "remove", id: "t2" }]);
    expect(reported).toHaveBeenCalledTimes(2);
    expect(lastReport().map((n) => n.id)).toEqual(["t1"]);
    await send([{ type: "select", id: "t1", selected: true }]);
    expect(reported).toHaveBeenCalledTimes(3);
  });

  it("does not report a half-finished drag when something else changes in the middle of it", async () => {
    await mount();
    await move(10, 10);
    await send([{ type: "select", id: "t2", selected: true }]); // another box picked up while t1 is held
    expect(reported, "t1 is still held: wait for the drop").toHaveBeenCalledTimes(1);
    await send([{ type: "position", id: "t1", dragging: false }]);
    expect(reported).toHaveBeenCalledTimes(2);
  });
});

describe("dropping a box from the palette", () => {
  const drop = (x: number, y: number, type = "tool") =>
    act(async () => {
      rf.props.onDrop({
        preventDefault() {},
        dataTransfer: { getData: (k: string) => (k === "application/agent-node-type" ? type : "Tool") },
        clientX: x,
        clientY: y,
      });
    });
  const added = () => lastReport().find((n: any) => n.id.startsWith("agent_node_")) as any;

  it("lands where the pointer is in the DRAWING, however the drawing is zoomed or moved", async () => {
    await mount();
    // the drawing is zoomed to 2x and moved by (-100, -50): the pointer at screen (400, 300) is at (250, 175) in the drawing
    await act(async () => rf.props.onInit({ screenToFlowPosition: ({ x, y }: { x: number; y: number }) => ({ x: x / 2 + 50, y: y / 2 + 25 }) }));
    await drop(400, 300);
    expect(added().position, "centred on the pointer: half a box (80, 20) to the left and above").toEqual({ x: 250 - 80, y: 175 - 20 });
    expect(added().type).toBe("tool");
  });

  it("falls back to the canvas's own edge when the drawing is not ready yet", async () => {
    await mount();
    await drop(400, 300);
    expect(added().position).toEqual({ x: 400 - 80, y: 300 - 20 });
  });

  it("ignores a drag that was not one of the palette's boxes", async () => {
    await mount();
    await act(async () => rf.props.onDrop({ preventDefault() {}, dataTransfer: { getData: () => "" }, clientX: 10, clientY: 10 }));
    expect(reported).toHaveBeenCalledTimes(1);
  });
});
