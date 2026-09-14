/**
 * bindProp must survive a null previous value.
 *
 * 87 registry props default to null (Button.onClick, Chart.data, Table.columns,
 * Form.fields, and the `binding` prop of every form input). `typeof null` is
 * "object", so the original guard dereferenced null and threw a TypeError out of
 * applyAction; editor-store caught it, set lastError and discarded the edit —
 * the bind toggle appeared to do nothing on precisely the props users most want
 * to bind.
 *
 * These tests fail against the pre-fix guard and pass after it.
 */
import { describe, it, expect } from "vitest";
import { applyAction } from "../src/apply";

function artifacts(propValue: unknown) {
  return {
    pageSchemas: {
      home: {
        schemaVersion: "2",
        id: "home",
        route: "/",
        root: {
          id: "root",
          type: "Container",
          props: {},
          children: [{ id: "n1", type: "Table", props: { columns: propValue }, children: [] }],
        },
      },
    },
    navFlow: { version: "1.0", initialPage: "home", pages: [], transitions: [], guards: {} },
    tokens: {},
  } as any;
}
const bind = {
  type: "bindProp", pageId: "home", nodeId: "n1", propName: "columns", binding: "rows",
} as any;
const nodeOf = (a: any) => a.pageSchemas.home.root.children[0];

describe("bindProp with a null previous value", () => {
  it("does not throw when the prop is null", () => {
    expect(() => applyAction(artifacts(null), bind)).not.toThrow();
  });

  it("writes the binding", () => {
    const { next } = applyAction(artifacts(null), bind);
    expect(nodeOf(next).props.columns).toEqual({ $binding: "rows" });
  });

  it("offers an inverse that restores the null literal", () => {
    const { inverse } = applyAction(artifacts(null), bind);
    expect(inverse).toMatchObject({
      type: "unbindProp", pageId: "home", nodeId: "n1", propName: "columns", literalValue: null,
    });
    // and that inverse must round-trip
    const { next } = applyAction(artifacts(null), bind);
    const { next: back } = applyAction(next, inverse as any);
    expect(nodeOf(back).props.columns).toBeNull();
  });

  it("still treats a real binding as a binding (no regression)", () => {
    const { inverse } = applyAction(artifacts({ $binding: "old" }), bind);
    expect((inverse as any).type).toBe("updateProp");
  });

  it("still unbinds a plain literal back to its value (no regression)", () => {
    const { inverse } = applyAction(artifacts("literal"), bind);
    expect(inverse).toMatchObject({ type: "unbindProp", literalValue: "literal" });
  });

  it("leaves an undefined prop restored via updateProp (no regression)", () => {
    const { inverse } = applyAction(artifacts(undefined), bind);
    expect((inverse as any).type).toBe("updateProp");
  });
});
