import { describe, it, expect } from "vitest";
import { renderNode } from "../src/runtime/dispatch";
import { renderToString } from "react-dom/server";

/**
 * Repeat resolved its collection from `node.bind` or `props.source` only.
 * Producers wrote three other shapes, and each one rendered an empty list
 * with no error anywhere: 81 of 339 Repeat nodes across the output corpus
 * (24%) drew nothing.
 *
 *   props.bind         55 nodes — 43 of them mustache-wrapped, "{{orders}}"
 *   props.dataSource   18 nodes — the shape our own LLM exemplar taught
 *   nothing at all      8 nodes — genuinely unauthored, still an error
 *
 * The renderer is the single consumer of a contract with many producers
 * (deterministic emitters, LLM page authoring, the A2UI binder), so it is
 * the one place a fix reaches all of them — including apps already shipped.
 * Each alias below is a shape measured in the corpus, not a hypothetical.
 */

const ORDERS = [{ id: 1, ref: "PO-1" }, { id: 2, ref: "PO-2" }];
const ctx = { data: { orders: ORDERS } } as any;

const repeat = (extra: Record<string, unknown>) => ({
  id: "rep",
  type: "Repeat",
  ...extra,
  children: [{ id: "row", type: "Text", bind: { source: "order", path: "ref" } }],
});

const bothRows = (node: unknown) => {
  const html = renderToString(renderNode(node as any, ctx));
  return html.includes("PO-1") && html.includes("PO-2");
};

describe("Repeat source resolution", () => {
  it("resolves node.bind — the canonical v2 shape", () => {
    expect(bothRows(repeat({ bind: "orders", props: { as: "order" } }))).toBe(true);
  });

  it("resolves props.source — the canonical v1 shape", () => {
    expect(bothRows(repeat({ props: { source: "orders", as: "order" } }))).toBe(true);
  });

  it("resolves props.bind — 55 nodes in the corpus, e.g. purchase-orders.json", () => {
    expect(bothRows(repeat({ props: { bind: "orders", as: "order" } }))).toBe(true);
  });

  it("strips mustache braces — 43 of those 55 are written '{{orders}}'", () => {
    expect(bothRows(repeat({ props: { bind: "{{orders}}", as: "order" } }))).toBe(true);
  });

  it("resolves props.dataSource — the shape our own exemplar taught", () => {
    expect(bothRows(repeat({ props: { dataSource: "orders", as: "order" } }))).toBe(true);
  });

  it("prefers node.bind when a producer wrote two shapes at once", () => {
    const node = repeat({ bind: "orders", props: { dataSource: "ghosts", as: "order" } });
    expect(bothRows(node)).toBe(true);
  });

  it("still renders nothing when no shape names a source", () => {
    const html = renderToString(renderNode(repeat({ props: { as: "order" } }) as any, ctx));
    expect(html).not.toContain("PO-1");
  });

  it("renders nothing when the named source is absent from ctx.data", () => {
    const html = renderToString(renderNode(repeat({ bind: "missing" }) as any, ctx));
    expect(html).not.toContain("PO-1");
  });
});
