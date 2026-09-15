/**
 * THE WHOLE CHAIN, IN ONE TEST: click bind in the editor → the value renders.
 *
 * Every layer of this was already covered and the feature was still broken,
 * because each layer was tested against its own idea of what a binding is. The
 * reducer had a test asserting it wrote `{$binding}`. The renderer had tests
 * asserting it resolved `{{expr}}`. Both passed. Nothing asked whether the
 * thing the reducer WROTE was the thing the renderer READ — and it wasn't, so
 * binding a prop in the editor produced a node that rendered a render-error
 * placeholder, and autosave then wrote that into the generated app.
 *
 * So this test starts at the real reducer, takes whatever it produces without
 * looking at it, and hands that to the real renderer. It cannot pass unless the
 * two agree, and no amount of per-layer green can fake it.
 */
import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";
import { applyAction } from "@forge/patches";
import { renderNode, type DispatchContext } from "../src/runtime/dispatch";

const PAGE = "home";
const NODE = "t1";

/** A page with one Text node carrying a literal. */
function artifacts(literal: unknown = "Old") {
  return {
    pageSchemas: {
      [PAGE]: {
        id: PAGE,
        route: "/",
        root: {
          id: "root",
          type: "Stack",
          children: [{ id: NODE, type: "Text", props: { content: literal } }],
        },
      },
    },
    navFlow: { pages: [{ id: PAGE, route: "/", title: "Home" }], transitions: [] },
    tokens: {},
  } as never;
}

const nodeOf = (a: any) => a.pageSchemas[PAGE].root.children[0];

const bind = (a: unknown, expr: string) =>
  applyAction(a as never, {
    type: "bindProp", pageId: PAGE, nodeId: NODE, propName: "content", binding: expr,
  } as never).next;

const renderWith = (node: unknown, data: Record<string, unknown>) =>
  renderToString(renderNode(node as never, { data } as DispatchContext) as never);

describe("bind in the editor, resolve in the renderer", () => {
  it("a bound prop renders the DATA, not the expression", () => {
    const bound = bind(artifacts(), "user.name");
    const html = renderWith(nodeOf(bound), { user: { name: "Ada Lovelace" } });
    expect(html).toContain("Ada Lovelace");
    // and the expression itself must be gone — a visible {{user.name}} is the
    // signature of a binding that was written but never resolved.
    expect(html).not.toContain("user.name");
  });

  it("resolves a path into an array element, the shape data sources produce", () => {
    const bound = bind(artifacts(), "invoices[0].customer");
    const html = renderWith(nodeOf(bound), { invoices: [{ customer: "Initech" }] });
    expect(html).toContain("Initech");
  });

  it("re-binding to a different expression follows the data", () => {
    const once = bind(artifacts(), "a.one");
    const twice = bind(once, "b.two");
    const html = renderWith(nodeOf(twice), { a: { one: "FIRST" }, b: { two: "SECOND" } });
    expect(html).toContain("SECOND");
    expect(html).not.toContain("FIRST");
  });

  it("a bind with no expression yet renders nothing, and does not throw", () => {
    // The toggle binds before anything is typed. This must be quiet, not a
    // template that resolves to nothing while still reading as bound.
    const bound = bind(artifacts(), "");
    expect(() => renderWith(nodeOf(bound), {})).not.toThrow();
    expect(renderWith(nodeOf(bound), {})).not.toContain("{{");
  });

  it("an expression naming absent data survives as the literal template", () => {
    // PINNING WHAT IT ACTUALLY DOES, not what one might wish. interpolate.ts
    // leaves an unresolvable whole template intact, and the audit harness
    // depends on exactly that: a visible {{expr}} is how "never resolved" is
    // told apart from "resolved to empty". It does mean an end user can see a
    // raw template when a data source is missing — worth a decision of its own,
    // separate from the binding format, so it is recorded rather than changed.
    const bound = bind(artifacts(), "missing.key");
    expect(renderWith(nodeOf(bound), {})).toContain("{{missing.key}}");
    // Resolved-but-empty is the other case, and it renders nothing at all.
    const empty = bind(artifacts(), "present.key");
    expect(renderWith(nodeOf(empty), { present: { key: "" } })).not.toContain("{{");
  });

  it("binding a prop whose previous value was null does not throw", () => {
    // 87 registry props default to null — Button.onClick, Chart.data,
    // Table.columns and the `binding` prop of every form input among them.
    const bound = bind(artifacts(null), "user.name");
    expect(() => renderWith(nodeOf(bound), { user: { name: "Ada" } })).not.toThrow();
  });

  it("undo puts the literal back, and the literal renders", () => {
    const before = artifacts("Old");
    const { next, inverse } = applyAction(before as never, {
      type: "bindProp", pageId: PAGE, nodeId: NODE, propName: "content", binding: "user.name",
    } as never);
    const restored = applyAction(next, inverse as never).next;
    expect(renderWith(nodeOf(restored), { user: { name: "Ada" } })).toContain("Old");
  });

  it("a page still carrying the legacy object form is not rendered as an object", () => {
    // Pages saved before the format change have `{$binding}` on disk. The
    // load-time migration heals them, but the renderer must not produce
    // something worse than empty if one slips through.
    const legacy = artifacts({ $binding: "user.name" } as never);
    expect(() => renderWith(nodeOf(legacy), { user: { name: "Ada" } })).not.toThrow();
    expect(renderWith(nodeOf(legacy), { user: { name: "Ada" } })).not.toContain("[object Object]");
  });
});
