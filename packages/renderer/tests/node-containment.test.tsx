// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup, renderToString } from "react-dom/server";
import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { z } from "zod";
import { renderNode } from "../src/runtime/dispatch";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * docs/editor-audit/containment.md finding #1 — "Setting AppShell.sidebar /
 * topbar / actions / rightRail from the Properties panel blanks the ENTIRE
 * page". Two independent defects, both covered here:
 *
 *  (a) the value reached React's child position at all — nothing converted the
 *      schema sub-tree the prop is typed as (NodeV2Ref) into rendered nodes,
 *      and validateProps has no coercion rule for a union mismatch, so an
 *      action object from the panel survived verbatim;
 *  (b) NodeErrorBoundary did not contain the throw, because react-dom/server
 *      (Fizz) never invokes getDerivedStateFromError — the only containment
 *      unit it understands is a Suspense boundary.
 */

// A stand-in for AppShell: renders a "slot" prop in child position, exactly as
// packages/library/src/components/AppShell/AppShell.tsx does with {sidebar}.
function SlotHost({ sidebar, children }: { sidebar?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div data-slot-host>
      {sidebar ? <aside data-slot-aside>{sidebar}</aside> : null}
      <main>{children}</main>
    </div>
  );
}

function Boom(): React.ReactNode {
  throw new Error("component blew up during render");
}

function Leaf({ label }: { label: string }) {
  return <span data-leaf>{label}</span>;
}

const anyProps = z.object({}).passthrough();

const registry = {
  has: (name: string) => name === "AppShell" || name === "Boom" || name === "Leaf",
  get: (name: string) =>
    name === "AppShell"
      ? { name, component: SlotHost, propsSchema: anyProps }
      : name === "Boom"
        ? { name, component: Boom, propsSchema: anyProps }
        : name === "Leaf"
          ? { name, component: Leaf, propsSchema: anyProps }
          : undefined,
  // Deliberately permissive — mirrors the real registry's best-effort step 3,
  // which hands an un-coercible union mismatch straight back through.
  validateProps: (_name: string, props: unknown) => (props ?? {}) as Record<string, unknown>,
} as any;

const ctx = { data: {}, registry };

function page(sidebar: unknown) {
  return {
    id: "root",
    type: "Stack",
    props: {},
    children: [
      { id: "shell", type: "AppShell", props: { sidebar }, children: [] },
      { id: "sib", type: "Leaf", props: { label: "SIBLING SURVIVES" } },
    ],
  };
}

describe("AppShell slot props — a bad prop must never blank the page", () => {
  it("renders a labelled placeholder for the action object the panel used to write", () => {
    const html = renderToStaticMarkup(
      renderNode(page({ action: "navigate", trigger: "" }) as any, ctx) as any,
    );
    expect(html).toContain("SIBLING SURVIVES");
    expect(html).toContain('data-invalid-node="AppShell.sidebar"');
    expect(html).toContain("not renderable");
  });

  it("renders a schema sub-tree — the feature the registry description promises", () => {
    const html = renderToStaticMarkup(
      renderNode(
        page({ id: "nav", type: "Leaf", props: { label: "NAV SUBTREE" } }) as any,
        ctx,
      ) as any,
    );
    expect(html).toContain("NAV SUBTREE");
    expect(html).not.toContain("not renderable");
  });

  it("renders an ARRAY of schema sub-trees", () => {
    const html = renderToStaticMarkup(
      renderNode(
        page([
          { id: "a", type: "Leaf", props: { label: "ONE" } },
          { id: "b", type: "Leaf", props: { label: "TWO" } },
        ]) as any,
        ctx,
      ) as any,
    );
    expect(html).toContain("ONE");
    expect(html).toContain("TWO");
  });

  it("still passes a plain string through as text", () => {
    const html = renderToStaticMarkup(renderNode(page("JUST TEXT") as any, ctx) as any);
    expect(html).toContain("JUST TEXT");
    expect(html).not.toContain("not renderable");
  });
});

const crashTree = {
  id: "root",
  type: "Stack",
  props: {},
  children: [
    { id: "boom", type: "Boom", props: {} },
    { id: "sib", type: "Leaf", props: { label: "SIBLING SURVIVES" } },
  ],
};

describe("NodeErrorBoundary contains a render crash during SERVER rendering", () => {
  it("keeps the document instead of throwing out of the renderer", () => {
    // Before the Suspense boundary was added inside NodeErrorBoundary this
    // threw straight out of renderToStaticMarkup — Fizz never runs
    // getDerivedStateFromError — and Next replaced <body> with its error
    // template. Now the throw is confined to the one boundary: the crashed
    // node leaves its (invisible) fallback behind and every sibling renders.
    const html = renderToStaticMarkup(renderNode(crashTree as any, ctx) as any);
    expect(html).toContain("SIBLING SURVIVES");
    expect(html).toContain('data-node-pending="Boom"');
  });

  it("contains the same crash under renderToString (the streaming path)", () => {
    const html = renderToString(renderNode(crashTree as any, ctx) as any);
    expect(html).toContain("SIBLING SURVIVES");
    expect(html).toContain('data-node-pending="Boom"');
  });

  it("the fallback is invisible, so a merely-SUSPENDING node never flashes an error box", () => {
    // AppShell suspends under Next's streaming SSR; an error-styled fallback
    // would paint a red "render error" box on every healthy one.
    const html = renderToStaticMarkup(renderNode(crashTree as any, ctx) as any);
    expect(html).not.toContain("render error");
  });
});

describe("NodeErrorBoundary paints the labelled placeholder on the CLIENT", () => {
  it("shows one placeholder for the crashed node and keeps its siblings", () => {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host, {
      // React logs the caught error; silence it so the run stays readable.
      onUncaughtError: () => {},
      onCaughtError: () => {},
    });
    act(() => {
      root.render(renderNode(crashTree as any, ctx) as any);
    });
    expect(host.querySelector('[data-invalid-node="Boom"]')).toBeTruthy();
    expect(host.textContent).toContain("Boom: render error");
    expect(host.textContent).toContain("SIBLING SURVIVES");
    act(() => root.unmount());
    host.remove();
  });
});
