// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { z } from "zod";
import { renderNode } from "../src/runtime/dispatch";

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * docs/editor-audit/input-components-2.md finding #8 — "a node in render-error
 * state cannot be selected".
 *
 * The editor resolves a canvas click by walking up to the nearest
 * [data-node-id]. The error placeholder carried `data-invalid-node` but no id,
 * so clicking the red box selected the PARENT: the one node the author had just
 * broken was the one node they could not open in the Properties panel to fix,
 * and the only route back was the layer tree.
 */

function Boom({ sidebar }: { sidebar?: unknown }): React.ReactNode {
  // Reproduces the AppShell case from containment.md: an object reaching child
  // position. React names the object's KEYS in the message but not the prop.
  return <div>{sidebar as React.ReactNode}</div>;
}

function Leaf({ label }: { label: string }) {
  return <span>{label}</span>;
}

const anyProps = z.object({}).passthrough();
const registry = {
  has: (name: string) => name === "Boom" || name === "Leaf",
  get: (name: string) =>
    name === "Boom"
      ? { name, component: Boom, propsSchema: anyProps }
      : name === "Leaf"
        ? { name, component: Leaf, propsSchema: anyProps }
        : undefined,
  validateProps: (_name: string, props: unknown) => (props ?? {}) as Record<string, unknown>,
} as any;
const ctx = { data: {}, registry };

function crashTree(props: Record<string, unknown>) {
  return {
    id: "root",
    type: "Stack",
    props: {},
    children: [
      { id: "broken-node", type: "Boom", props },
      { id: "sib", type: "Leaf", props: { label: "SIBLING SURVIVES" } },
    ],
  };
}

function renderOnClient(tree: unknown) {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host, {
    // React logs the caught error; silence it so the run stays readable.
    onUncaughtError: () => {},
    onCaughtError: () => {},
  });
  act(() => {
    root.render(renderNode(tree as any, ctx) as any);
  });
  return {
    host,
    cleanup: () => {
      act(() => root.unmount());
      host.remove();
    },
  };
}

describe("NodeErrorBoundary placeholder is a selectable node", () => {
  it("carries the crashed node's data-node-id", () => {
    const { host, cleanup } = renderOnClient(crashTree({ sidebar: { action: "navigate" } }));
    const placeholder = host.querySelector('[data-invalid-node="Boom"]');
    expect(placeholder).toBeTruthy();
    // The whole point: the editor's hit-test finds an id here.
    expect(placeholder!.getAttribute("data-node-id")).toBe("broken-node");
    cleanup();
  });

  it("names the prop that threw, so the author learns WHAT broke", () => {
    const { host, cleanup } = renderOnClient(crashTree({ sidebar: { action: "navigate" } }));
    const placeholder = host.querySelector('[data-invalid-node="Boom"]') as HTMLElement;
    expect(placeholder.getAttribute("data-failing-prop")).toBe("sidebar");
    expect(placeholder.textContent).toContain("sidebar");
    // The pre-existing label is kept — other tests and the editor read it.
    expect(placeholder.textContent).toContain("Boom: render error");
    expect(host.textContent).toContain("SIBLING SURVIVES");
    cleanup();
  });

  it("still renders (with the raw message) when no prop can be blamed", () => {
    function Thrower(): React.ReactNode {
      throw new Error("kaboom from nowhere");
    }
    const localRegistry = {
      has: (n: string) => n === "Thrower",
      get: (n: string) => (n === "Thrower" ? { name: n, component: Thrower, propsSchema: anyProps } : undefined),
      validateProps: (_n: string, p: unknown) => (p ?? {}) as Record<string, unknown>,
    } as any;
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host, { onUncaughtError: () => {}, onCaughtError: () => {} });
    act(() => {
      root.render(
        renderNode(
          { id: "solo", type: "Thrower", props: {} } as any,
          { data: {}, registry: localRegistry },
        ) as any,
      );
    });
    const placeholder = host.querySelector('[data-invalid-node="Thrower"]') as HTMLElement;
    expect(placeholder.getAttribute("data-node-id")).toBe("solo");
    expect(placeholder.getAttribute("data-failing-prop")).toBeNull();
    expect(placeholder.textContent).toContain("kaboom from nowhere");
    act(() => root.unmount());
    host.remove();
  });
});
