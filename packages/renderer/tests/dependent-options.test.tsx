/**
 * A Select whose options depend on a sibling keeps, per option, the value of
 * the column the sibling is matched on — so the city list can narrow to its
 * state without another fetch. Without `dependsOn`, nothing extra travels.
 */
import { describe, it, expect } from "vitest";
import { renderToString } from "react-dom/server";
import * as React from "react";
import { renderNode, type DispatchContext } from "../src/runtime/dispatch";

function makeCtx(data: Record<string, unknown>): DispatchContext {
  const Select = (props: any) =>
    React.createElement("div", {
      "data-options": (props.options ?? []).map((o: any) => o.value).join(";"),
      "data-depends": props.dependsOn ? JSON.stringify(props.dependsOn) : "none",
    });
  const registry = {
    has: (t: string) => t === "Select",
    get: () => ({ component: Select, propsSchema: undefined }),
    validateProps: (_t: string, props: any) => props,
  };
  return { data, registry } as any;
}

const node = (extra: Record<string, unknown>) => ({
  id: "city", type: "Select",
  props: { name: "city", label: "City", options: [{ value: "x", label: "x" }],
           optionsFrom: { source: "cities", value: "id", label: "name", ...extra } },
});

const cities = [{ id: "c1", name: "Austin", stateId: "TX" }, { id: "c2", name: "Boston", stateId: "MA" }];

describe("dependent options", () => {
  it("keeps each option's parent key when the source depends on a sibling", () => {
    const html = renderToString(renderNode(node({ dependsOn: { field: "state", column: "stateId" } }) as any, makeCtx({ cities })) as any);
    expect(html).toContain('data-options="c1;c2"');
    expect(html).toContain("&quot;field&quot;:&quot;state&quot;");
    expect(html).toContain("&quot;c1&quot;:&quot;TX&quot;");
  });
  it("adds nothing without a dependency", () => {
    const html = renderToString(renderNode(node({}) as any, makeCtx({ cities })) as any);
    expect(html).toContain('data-depends="none"');
  });
});
