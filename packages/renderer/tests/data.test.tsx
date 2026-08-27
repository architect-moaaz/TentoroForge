import { describe, it, expect } from "vitest";
import { renderNode } from "../src/runtime/dispatch";
import { renderToString } from "react-dom/server";

const ctx = {
  data: { products: { items: [{ id: 1, name: "A" }, { id: 2, name: "B" }] } },
  user: { role: "admin" },
} as any;

describe("Repeat", () => {
  it("renders one child per item with item scope", () => {
    const node = {
      id: "rep",
      type: "Repeat",
      props: { source: "products", path: "items", as: "item", keyPath: "id" },
      children: [
        { id: "row", type: "Text", bind: { source: "item", path: "name" } },
      ],
    };
    const html = renderToString(renderNode(node as any, ctx));
    expect(html).toContain("A");
    expect(html).toContain("B");
  });
});

describe("Conditional", () => {
  it("renders children when expression is true", () => {
    const node = {
      id: "c",
      type: "Conditional",
      props: { when: "user.role == 'admin'" },
      children: [{ id: "t", type: "Text", props: { content: "admin-only" } }],
    };
    const html = renderToString(renderNode(node as any, ctx));
    expect(html).toContain("admin-only");
  });

  it("renders else branch when false", () => {
    const node = {
      id: "c",
      type: "Conditional",
      props: { when: "user.role == 'admin'" },
      children: [{ id: "t", type: "Text", props: { content: "admin" } }],
      else: [{ id: "u", type: "Text", props: { content: "user" } }],
    };
    const html = renderToString(renderNode(node as any, { ...ctx, user: { role: "viewer" } }));
    expect(html).toContain("user");
    expect(html).not.toContain("admin");
  });

  it("does not crash when props are missing entirely", () => {
    // Regression — LLM-generated schemas sometimes emit Conditional with
    // no props at all. The renderer previously crashed with
    // 'Cannot read properties of undefined (reading "when")'.
    const node = {
      id: "c",
      type: "Conditional",
      // no props
      children: [{ id: "t", type: "Text", props: { content: "fallback" } }],
    };
    const html = renderToString(renderNode(node as any, ctx));
    // Without a condition we render the children unconditionally.
    expect(html).toContain("fallback");
  });

  it("accepts `condition` prop as alias for `when`", () => {
    // The LLM occasionally emits {condition: '...'} instead of {when: '...'}.
    // Renderer accepts either to avoid hard-failing the whole page.
    const node = {
      id: "c",
      type: "Conditional",
      props: { condition: "user.role == 'admin'" },
      children: [{ id: "t", type: "Text", props: { content: "admin-only" } }],
    };
    const html = renderToString(renderNode(node as any, ctx));
    expect(html).toContain("admin-only");
  });

  it("does not crash when props is an empty object", () => {
    const node = {
      id: "c",
      type: "Conditional",
      props: {},
      children: [{ id: "t", type: "Text", props: { content: "fallback" } }],
    };
    const html = renderToString(renderNode(node as any, ctx));
    expect(html).toContain("fallback");
  });
});

describe("DataBoundary", () => {
  it("renders children normally", () => {
    const node = {
      id: "db",
      type: "DataBoundary",
      props: { fallback: "Error!" },
      children: [{ id: "t", type: "Text", props: { content: "loaded" } }],
    };
    const html = renderToString(renderNode(node as any, ctx));
    expect(html).toContain("loaded");
  });

  it("renders fallback on error", () => {
    const node = {
      id: "db",
      type: "DataBoundary",
      props: { fallback: "Could not load." },
      children: [{ id: "bad", type: "UNKNOWN_THROWS", props: {} }],
    };
    // DataBoundary catches sync render errors
    const html = renderToString(renderNode(node as any, ctx));
    expect(html).toContain("Could not load.");
  });
});

describe("React key discipline — LLM-composed schemas without ids", () => {
  // Regression: page_composer's LLM output arrives without per-node ids.
  // DataBoundary + Conditional used to plain-.map() their children into
  // a fragment, so React fired "unique key" (missing) and — when two
  // siblings collapsed to the same fallback — "encountered two children
  // with the same key" errors in the browser console.
  //
  // These tests spy on console.error while rendering an id-less schema
  // and assert no key warning fires.
  function captureConsoleErrors(fn: () => void): string[] {
    const errs: string[] = [];
    const orig = console.error;
    console.error = (...args: unknown[]) => {
      errs.push(args.map(a => String(a)).join(" "));
    };
    try { fn(); } finally { console.error = orig; }
    return errs;
  }

  it("DataBoundary renders id-less siblings without a key warning", () => {
    const node = {
      id: "db",
      type: "DataBoundary",
      children: [
        { type: "Text", props: { content: "one" } },
        { type: "Text", props: { content: "two" } },
        { type: "Text", props: { content: "three" } },
      ],
    };
    const errs = captureConsoleErrors(() => {
      renderToString(renderNode(node as any, ctx));
    });
    expect(errs.some(e => /unique "key" prop|same key/i.test(e))).toBe(false);
  });

  it("Conditional (when-branch) renders id-less siblings without a key warning", () => {
    const node = {
      type: "Conditional",
      props: { when: "user.role == 'admin'" },
      children: [
        { type: "Text", props: { content: "a" } },
        { type: "Text", props: { content: "b" } },
      ],
    };
    const errs = captureConsoleErrors(() => {
      renderToString(renderNode(node as any, ctx));
    });
    expect(errs.some(e => /unique "key" prop|same key/i.test(e))).toBe(false);
  });

  it("Conditional (branches, first-match) renders id-less siblings without a key warning", () => {
    const node = {
      type: "Conditional",
      props: {
        branches: [
          {
            if: "user.role == 'admin'",
            node: [
              { type: "Text", props: { content: "x" } },
              { type: "Text", props: { content: "y" } },
            ],
          },
        ],
      },
    };
    const errs = captureConsoleErrors(() => {
      renderToString(renderNode(node as any, ctx));
    });
    expect(errs.some(e => /unique "key" prop|same key/i.test(e))).toBe(false);
  });

  it("Conditional (no-condition fallback) renders id-less children without warning", () => {
    const node = {
      type: "Conditional",
      // no props → renders children unconditionally
      children: [
        { type: "Text", props: { content: "p" } },
        { type: "Text", props: { content: "q" } },
      ],
    };
    const errs = captureConsoleErrors(() => {
      renderToString(renderNode(node as any, ctx));
    });
    expect(errs.some(e => /unique "key" prop|same key/i.test(e))).toBe(false);
  });
});
