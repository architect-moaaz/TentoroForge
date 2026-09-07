/**
 * Report #9 — "Every thing i open it shows a blank space and how does user know
 * what do do with it… This is not a particular component this is about all
 * component."
 *
 * The overlay is an editor affordance, so it is tested the way GridGuides'
 * geometry is: mount it over a hand-built canvas whose nodes are seeded into the
 * real editor store, and assert on the boxes it draws.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import * as React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { useEditorStore } from "@/lib/editor-store";
import { EmptyNodeHints } from "@/components/canvas/EmptyNodeHints";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
if (!(globalThis as any).ResizeObserver) {
  (globalThis as any).ResizeObserver = class {
    observe() {} unobserve() {} disconnect() {}
  };
}
// jsdom lays nothing out, so every getBoundingClientRect() is 0x0 and the
// overlay would discard every hint as too small to annotate. Give elements a
// plausible box.
//
// The CANVAS gets a DIFFERENT box from the nodes inside it. Hints are
// positioned in the canvas's own coordinate space (`rect.left - hostRect.left`),
// so a single shared rect would make that subtraction always zero and the
// geometry assertion below would pass no matter what the component computed.
const RECT = { left: 10, top: 20, width: 400, height: 120, right: 410, bottom: 140, x: 10, y: 20, toJSON() {} };
const HOST_RECT = { left: 4, top: 6, width: 900, height: 700, right: 904, bottom: 706, x: 4, y: 6, toJSON() {} };
Element.prototype.getBoundingClientRect = function (this: Element) {
  return (this === host ? HOST_RECT : RECT) as DOMRect;
};

let host: HTMLDivElement;
let mount: HTMLDivElement;
let root: Root;

/** Seed the store with one page whose root is `nodes[0]`. */
function seed(rootNode: any) {
  useEditorStore.setState({
    artifacts: { pageSchemas: { P1: { id: "P1", root: rootNode } }, navFlow: {}, tokens: {} } as any,
    currentPageId: "P1",
  });
}

/**
 * Hints are PORTALLED INTO THE CANVAS, not rendered inline in the React root.
 *
 * That is the fix for "if i scroll the page every thing jiggles": the canvas
 * sits inside nested scrollers, so a hint positioned anywhere else drifts off
 * the box it labels the moment anything scrolls. Living inside the scrolled
 * content means the browser carries them for free. Querying `host` here is
 * therefore part of the assertion, not an implementation detail — a hint that
 * turned up in `mount` would be the old, broken arrangement.
 */
function labels(): string[] {
  return Array.from(host.querySelectorAll("[data-empty-hint]")).map(
    (el) => el.textContent ?? "",
  );
}

beforeEach(() => {
  host = document.createElement("div");
  mount = document.createElement("div");
  document.body.append(host, mount);
  root = createRoot(mount);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  mount.remove();
});

function renderOverlay() {
  const ref = { current: host } as React.RefObject<HTMLElement | null>;
  act(() => { root.render(<EmptyNodeHints canvasRef={ref} />); });
}

describe("EmptyNodeHints", () => {
  it("labels an empty container with what it is and what to do", () => {
    seed({ id: "card-1", type: "Card", props: {}, children: [] });
    host.innerHTML = `<div data-node-id="card-1"></div>`;
    renderOverlay();
    expect(labels()).toEqual(["Card — empty. Drag a component in here."]);
  });

  it("names the prop for a leaf that renders an empty box", () => {
    seed({
      id: "stack-1", type: "Stack", props: {},
      children: [{ id: "t-1", type: "Table", props: {} }],
    });
    host.innerHTML =
      `<div data-node-id="stack-1"><div data-node-id="t-1"></div></div>`;
    renderOverlay();
    // The Stack is NOT labelled even though it is visually blank: it contains a
    // node, and that node reports itself. One label, on the thing that is
    // actually missing content.
    expect(labels()).toEqual(["Table — set “columns” in the Properties panel."]);
  });

  it("says nothing about a node that is already rendering something", () => {
    seed({ id: "h-1", type: "Heading", props: { text: "Inventory" } });
    host.innerHTML = `<div data-node-id="h-1"><h1>Inventory</h1></div>`;
    renderOverlay();
    expect(labels()).toEqual([]);
  });

  it("counts non-text ink as content — an Avatar's img is not a blank box", () => {
    seed({ id: "a-1", type: "Avatar", props: {} });
    host.innerHTML = `<div data-node-id="a-1"><img alt="" /></div>`;
    renderOverlay();
    expect(labels()).toEqual([]);
  });

  it("leaves the editor-created grid cells to GridGuides", () => {
    seed({
      id: "g-1", type: "Grid", props: { rows: 2 },
      children: [{ id: "c-1", type: "GridCell", props: {}, children: [] }],
    });
    host.innerHTML = `<div data-node-id="g-1"><div data-node-id="c-1"></div></div>`;
    renderOverlay();
    expect(labels()).toEqual([]);
  });

  it("never writes to the store — demo content cannot reach a saved schema", () => {
    // The whole reason this is an overlay and not drop-time default props:
    // autosave persists store.artifacts to src/schemas/<page>.json and the
    // generator builds the app from those files. Nothing here may touch them.
    seed({ id: "card-1", type: "Card", props: {}, children: [] });
    const before = JSON.stringify(useEditorStore.getState().artifacts);
    host.innerHTML = `<div data-node-id="card-1"></div>`;
    renderOverlay();
    expect(labels().length).toBe(1);
    expect(JSON.stringify(useEditorStore.getState().artifacts)).toBe(before);
  });

  it("draws over the node's own box and cannot swallow a click or a drop", () => {
    seed({ id: "card-1", type: "Card", props: {}, children: [] });
    host.innerHTML = `<div data-node-id="card-1"></div>`;
    renderOverlay();
    const hint = host.querySelector("[data-empty-hint]") as HTMLElement;
    expect(hint).not.toBeNull();
    // Nothing may render outside the canvas — a hint in the React root would
    // paint over the Properties panel and the toolbar.
    expect(mount.querySelector("[data-empty-hint]")).toBeNull();
    expect(hint.className).toContain("pointer-events-none");
    // Absolute, in the CANVAS's coordinate space: node (10, 20) inside a canvas
    // whose own box starts at (4, 6) sits at (6, 14). Not viewport coordinates,
    // and with NO scroll term — the hint is inside the scrolled content, so the
    // browser already moves it and adding the offset would double-count.
    expect(hint.className).toContain("absolute");
    expect(hint.style.left).toBe("6px");
    expect(hint.style.top).toBe("14px");
    expect(hint.style.width).toBe("400px");
    expect(hint.style.height).toBe("120px");
  });
});
