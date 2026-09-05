/**
 * A row template is not a page binding. `rowHref: "/cases/{{id}}"` is
 * filled by the Table from each row; interpolated against the page data,
 * where there is no `id`, the placeholder was dropped and every row opened
 * the list the reader was already on.
 */
import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";
import * as React from "react";
import { renderNode, type DispatchContext } from "../src/runtime/dispatch";

function makeCtx(data: Record<string, unknown>): DispatchContext {
  const Table = (props: any) =>
    React.createElement("div", { "data-rowhref": props.rowHref ?? "none", "data-title": props.title ?? "none",
      "data-actions": JSON.stringify(props.rowActions ?? null) });
  const registry = { has: (t: string) => t === "Table", get: () => ({ component: Table, propsSchema: undefined }), validateProps: (_t: string, p: any) => p };
  return { data, registry } as any;
}

describe("row templates", () => {
  it("leaves rowHref and rowActions for the Table to fill from the row", () => {
    const node = { id: "t", type: "Table", props: { title: "{{card.title}}", rowHref: "/cases/{{id}}", rowActions: [{ label: "Open", navigate: "/cases/{{id}}" }], columns: [], data: "{{cases}}" } };
    const html = renderToString(renderNode(node as any, makeCtx({ card: { title: "Active Cases" }, cases: [] })) as any);
    expect(html).toContain('data-rowhref="/cases/{{id}}"');
    expect((html.match(/\/cases\/\{\{id\}\}/g) ?? []).length).toBe(2);
    expect(html).toContain('data-title="Active Cases"');
  });
});
