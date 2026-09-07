// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from "vitest";
import { resolveLayoutBox, resolveNodeBox } from "./layout-box";

/**
 * Six canvas features measured a node and each carried its own copy of this
 * walk. They had already drifted: Canvas.tsx looked exactly ONE level down and
 * did not check whether that child was itself `display: contents`, so a
 * component that nests a second wrapper had `draggable` set on another boxless
 * element and could not be dragged at all.
 *
 * The nested case is the one the divergence was hiding in, so it is asserted
 * first.
 */

function el(html: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = html;
  document.body.appendChild(host);
  return host.firstElementChild as HTMLElement;
}

beforeEach(() => { document.body.innerHTML = ""; });

describe("resolveLayoutBox", () => {
  it("walks past a SECOND nested contents wrapper — the case the old copy missed", () => {
    const node = el(
      `<span style="display:contents" data-node-id="n1">
         <span style="display:contents"><b id="real">x</b></span>
       </span>`,
    );
    expect(resolveLayoutBox(node)?.id).toBe("real");
  });

  it("returns the element itself when it already generates a box", () => {
    const node = el(`<div id="me" style="display:block"><b>x</b></div>`);
    expect(resolveLayoutBox(node)?.id).toBe("me");
  });

  it("walks one contents wrapper", () => {
    const node = el(`<span style="display:contents"><i id="real">x</i></span>`);
    expect(resolveLayoutBox(node)?.id).toBe("real");
  });

  it("returns the FIRST box in document order when a wrapper has several children", () => {
    const node = el(
      `<span style="display:contents"><i id="first">a</i><i id="second">b</i></span>`,
    );
    expect(resolveLayoutBox(node)?.id).toBe("first");
  });

  it("returns null when the subtree is contents all the way down", () => {
    // A real state on this canvas: a component that renders nothing at all.
    // Reporting "no box" is correct; inventing one would draw an overlay over
    // whatever happens to be underneath.
    const node = el(`<span style="display:contents"><span style="display:contents"></span></span>`);
    expect(resolveLayoutBox(node)).toBeNull();
  });

  it("is null-safe", () => {
    expect(resolveLayoutBox(null)).toBeNull();
  });
});

describe("resolveNodeBox", () => {
  it("scopes the lookup to the canvas root and resolves through the wrapper", () => {
    const canvas = el(
      `<div data-canvas-root>
         <span style="display:contents" data-node-id="n1"><b id="real">x</b></span>
       </div>`,
    );
    expect(resolveNodeBox(canvas, "n1")?.id).toBe("real");
    expect(resolveNodeBox(canvas, "nope")).toBeNull();
    expect(resolveNodeBox(null, "n1")).toBeNull();
  });
});
