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
import { hintFor, schemaMissingProp } from "@/components/canvas/empty-hints";
import { starterRegistry } from "@forge/registry";

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

/**
 * Audit rows 27–29 — the hint must name the prop the COMPONENT requires.
 *
 * Row 27 is the reason these assert the prop NAME and not merely that a hint
 * appeared: Stepper's hint read "set 'bind'" — a real hint, on a real empty
 * node, naming the one prop (`z.string().optional()`) that was never the
 * problem. Any test that only checked for the presence of a hint passed
 * against that bug.
 *
 * These read the answer off the component's own Zod schema via the live
 * library registry, so they keep working when a component's schema changes and
 * they cover components nobody has thought to write a case for.
 */
describe("hintFor — names the prop the component's own schema requires", () => {
  it("names a required list prop, not an optional scalar that happens to be declared", () => {
    // StepperProps: steps (required array) · bind (optional string).
    expect(hintFor("Stepper", {})).toBe(
      "Stepper — set “steps” in the Properties panel.",
    );
    expect(hintFor("Stepper", {})).not.toContain("bind");
  });

  it("names the content list even when its schema default is []", () => {
    // Row 28: these five have no *required* prop — `items` defaults to [] —
    // so the old code fell through to the palette blurb and named no prop.
    for (const [type, prop] of [
      ["Carousel", "items"],
      ["DescriptionList", "items"],
      ["List", "items"],
      ["Tree", "items"],
      ["ValidationChecklist", "items"],
      ["Lightbox", "images"],
    ] as const) {
      expect(hintFor(type, {})).toBe(
        `${type} — set “${prop}” in the Properties panel.`,
      );
    }
  });

  it("never falls back to the palette description while a prop is missing", () => {
    // "Carousel — Slideshow with prev/next and dots." was the reported string.
    expect(hintFor("Carousel", {})).not.toContain("Slideshow");
  });

  it("stops naming a prop once the user has filled it", () => {
    expect(hintFor("Stepper", { steps: [{ label: "One" }] })).not.toContain("steps");
  });

  it("says so plainly when the required prop has no control in the panel", () => {
    // Swept, not enumerated: every leaf in the registry whose schema names a
    // missing prop the Properties panel has no control for. Those are registry
    // gaps (ROUTED, not patched here) and the hint must not send the user
    // hunting for a control that does not exist.
    const gaps: string[] = [];
    for (const [type, entry] of Object.entries(starterRegistry as Record<string, any>)) {
      if (entry?.slots?.type && entry.slots.type !== "leaf") continue;
      const prop = schemaMissingProp(type, {});
      if (!prop) continue;
      if (Object.prototype.hasOwnProperty.call(entry?.props ?? {}, prop)) continue;
      gaps.push(type);
      expect(hintFor(type, {})).toBe(
        `${type} — needs “${prop}”, which has no control yet.`,
      );
    }
    // Not an assertion about how many gaps there are — just a record of them.
    if (gaps.length) console.log(`[no-control-for-required-prop] ${gaps.join(", ")}`);
  });

  it("never invents a hint for a type the palette does not know", () => {
    expect(hintFor("__NotARealComponent__", {})).toBeNull();
  });

  it("prefers a required list over a required scalar declared before it", () => {
    // Ranking, not declaration order: BulkActionBar declares selectedCount
    // (defaulted number) before actions (required, .min(1) array).
    expect(hintFor("BulkActionBar", {})).toContain("actions");
  });
});

describe("EmptyNodeHints — zero-area nodes", () => {
  it("annotates a node with no box instead of skipping it", () => {
    // Row 29: Lightbox laid out 960x0 and Dialog 0x0, so the overlay's
    // "too small to annotate" guard dropped them — the two nodes that most
    // needed a marker were the only ones that never got one. The rule is
    // geometric: any empty node smaller than the minimum hint box is padded
    // out to one, whatever the component is.
    const ZERO = { left: 30, top: 40, width: 0, height: 0, right: 30, bottom: 40, x: 30, y: 40, toJSON() {} };
    const prev = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function (this: Element) {
      return (this === host ? HOST_RECT : ZERO) as DOMRect;
    };
    try {
      seed({ id: "lb-1", type: "Lightbox", props: {} });
      host.innerHTML = `<div data-node-id="lb-1"></div>`;
      renderOverlay();
      const hint = host.querySelector("[data-empty-hint]") as HTMLElement;
      expect(hint).not.toBeNull();
      expect(hint.textContent).toContain("images");
      // Padded to a readable minimum, positioned where the node is.
      expect(hint.style.left).toBe("26px");
      expect(hint.style.top).toBe("34px");
      expect(parseFloat(hint.style.width)).toBeGreaterThanOrEqual(120);
      expect(parseFloat(hint.style.height)).toBeGreaterThanOrEqual(16);
      expect(hint.hasAttribute("data-empty-hint-ghost")).toBe(true);
      // Still inert — a marker for an invisible node must not start eating
      // the drops the canvas underneath it is there to receive.
      expect(hint.className).toContain("pointer-events-none");
    } finally {
      Element.prototype.getBoundingClientRect = prev;
    }
  });

  it("leaves a node that already has a real box at its own size", () => {
    seed({ id: "lb-2", type: "Lightbox", props: {} });
    host.innerHTML = `<div data-node-id="lb-2"></div>`;
    renderOverlay();
    const hint = host.querySelector("[data-empty-hint]") as HTMLElement;
    expect(hint.style.width).toBe("400px");
    expect(hint.style.height).toBe("120px");
    expect(hint.hasAttribute("data-empty-hint-ghost")).toBe(false);
  });
});
