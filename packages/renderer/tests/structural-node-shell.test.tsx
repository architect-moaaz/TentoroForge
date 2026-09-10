// @vitest-environment jsdom
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render } from "@testing-library/react";
import { renderNode } from "../src/runtime/dispatch";
import { DesignTimeProvider } from "../src/client/DesignTime";
import { __resetSlotWarningsForTests } from "../src/nodes/slot/Slot";

/**
 * THE FOUR NODES THE EDITOR COULD NOT SEE.
 *
 * Repeat, Conditional, DataBoundary and Slot were dispatched ahead of the
 * `data-node-id` tagging every other node type gets, so a palette drop
 * committed to disk and emitted no element at all. Everything else followed
 * from that: no selection, so no Properties panel, so no way to bind them; no
 * drop target, because drop resolution walks `closest("[data-node-id]")`; and
 * no empty-node hint, because the hint measures a box.
 *
 * The assertion that matters is the ATTRIBUTE, not "something rendered" — these
 * nodes did render a fragment; a fragment is just not addressable.
 */

const ctx: any = { data: {}, user: undefined };
const TYPES = ["Repeat", "Conditional", "DataBoundary", "Slot"] as const;

function nodeOf(type: string) {
  return type === "Slot"
    ? { id: `${type.toLowerCase()}-1`, type, props: { name: "default" } }
    : { id: `${type.toLowerCase()}-1`, type, props: {}, children: [] };
}

beforeEach(() => {
  __resetSlotWarningsForTests();
  vi.restoreAllMocks();
});

describe("structural nodes are addressable", () => {
  for (const type of TYPES) {
    it(`${type} emits its data-node-id at runtime`, () => {
      const { container } = render(<>{renderNode(nodeOf(type), ctx)}</>);
      const el = container.querySelector(`[data-node-id="${type.toLowerCase()}-1"]`);
      expect(el).not.toBeNull();
      expect(el!.getAttribute("data-structural-node")).toBe(type);
    });

    it(`${type} stays layout-neutral outside an authoring surface`, () => {
      // A shipped page must not move by a pixel: the wrapper generates no box.
      const { container } = render(<>{renderNode(nodeOf(type), ctx)}</>);
      const el = container.querySelector<HTMLElement>(`[data-node-id="${type.toLowerCase()}-1"]`);
      expect(el!.style.display).toBe("contents");
    });

    it(`${type} becomes a real, labelled box inside a design-time surface`, () => {
      const { container } = render(
        <DesignTimeProvider>{renderNode(nodeOf(type), ctx)}</DesignTimeProvider>,
      );
      const el = container.querySelector<HTMLElement>(`[data-node-id="${type.toLowerCase()}-1"]`);
      expect(el!.style.display).toBe("block");
      expect(parseInt(el!.style.minHeight, 10)).toBeGreaterThan(0);
      // It says which node it is — the author had no other way to tell.
      expect(el!.textContent).toContain(type);
    });
  }

  it("a configured Repeat still renders its items, inside the shell", () => {
    const node = {
      id: "repeat-1",
      type: "Repeat",
      props: { source: "rows", as: "row", keyPath: "id" },
      children: [{ id: "t1", type: "Text", props: { content: "hello" } }],
    };
    const { container } = render(
      <>{renderNode(node, { data: { rows: [{ id: 1 }, { id: 2 }] }, user: undefined } as any)}</>,
    );
    const shell = container.querySelector('[data-node-id="repeat-1"]');
    expect(shell).not.toBeNull();
    expect(shell!.querySelectorAll("[data-repeat-item]")).toHaveLength(2);
  });
});

describe("Slot's warning is not a flood", () => {
  it("warns once per slot name however many times it renders", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    for (let i = 0; i < 5; i++) {
      render(<>{renderNode(nodeOf("Slot"), ctx)}</>);
    }
    const unfilled = warn.mock.calls.filter((c) => String(c[0]).includes("unfilled slot"));
    // Was 4-6 messages PER RENDER PASS from a single node; one audit session
    // captured 168 console messages of which nearly all were this line, which
    // buried every other warning a developer would have gone looking for.
    expect(unfilled).toHaveLength(1);
    // A different slot name is different information and still warns.
    render(<>{renderNode({ id: "s2", type: "Slot", props: { name: "sidebar" } }, ctx)}</>);
    expect(
      warn.mock.calls.filter((c) => String(c[0]).includes("unfilled slot")),
    ).toHaveLength(2);
  });
});

describe("a blank Conditional.when is unset, not false", () => {
  const kids = [{ id: "t", type: "Text", props: { content: "body" } }];

  it("renders children when `when` is an empty string", () => {
    // Presence was tested with `"when" in props`, so a condition the author
    // typed and then CLEARED counted as present-and-falsy and the children
    // vanished — with no way back except knowing the box had to be refilled.
    // The `Sparkline.color` rule, one node over.
    const { container } = render(
      <>{renderNode({ id: "c", type: "Conditional", props: { when: "  " }, children: kids }, ctx)}</>,
    );
    expect(container.textContent).toContain("body");
  });

  it("renders children when there is no `when` at all", () => {
    const { container } = render(
      <>{renderNode({ id: "c", type: "Conditional", props: {}, children: kids }, ctx)}</>,
    );
    expect(container.textContent).toContain("body");
  });

  it("still hides the branch for a condition that is genuinely false", () => {
    for (const when of ["false", 0, null, false] as any[]) {
      const { container } = render(
        <>{renderNode({ id: "c", type: "Conditional", props: { when }, children: kids }, ctx)}</>,
      );
      expect(container.textContent, `when=${JSON.stringify(when)}`).not.toContain("body");
    }
  });
});
