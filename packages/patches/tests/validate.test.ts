import { describe, it, expect } from "vitest";
import { validateAll, validateIdUniqueness, validateTokenClosure, validateRegistryClosure } from "../src/validate";

const REGISTRY = { Stack: { props: { gap: {}, padding: {} } } };

function minimal(node: any): any {
  return {
    pageSchemas: {
      home: { schemaVersion: "2", id: "home", root: node },
    },
    navFlow: {
      version: "1.0", initialPage: "home",
      pages: [{ id: "home", route: "/", title: "Home",
                schemaFile: "src/schemas/home.json", params: [] }],
      transitions: [], guards: {},
    },
    tokens: { color: {}, typography: {}, spacing: {}, radius: {},
              shadow: {}, motion: {}, breakpoints: {} },
  };
}

describe("validate", () => {
  it("clean artifacts pass", () => {
    expect(validateAll(minimal({ id: "n1", type: "Stack", props: { gap: "md" } }), REGISTRY)).toEqual([]);
  });
  it("duplicate ids detected", () => {
    const errs = validateIdUniqueness(minimal({
      id: "n1", type: "Stack", children: [
        { id: "x", type: "Stack" }, { id: "x", type: "Stack" },
      ],
    }));
    expect(errs.some(e => /duplicate/.test(e))).toBe(true);
  });
  it("unknown component flagged", () => {
    const errs = validateRegistryClosure(minimal({ id: "n", type: "Bogus" }), REGISTRY);
    expect(errs.some(e => /Bogus/.test(e))).toBe(true);
  });
  it("renderer built-in primitives bypass registry check", () => {
    // Image, Text, Icon, Row, Container, Box are handled directly by
    // dispatch.tsx so they must validate cleanly even when the registry
    // doesn't list them. Regression for the "unknown component 'Image'"
    // commit-rejection bug.
    for (const t of ["Image", "Text", "Icon", "Row", "Stack", "Container", "Box", "Slot", "PageOutlet"]) {
      const errs = validateRegistryClosure(minimal({ id: "n", type: t }), REGISTRY);
      expect(errs).toEqual([]);
    }
  });
  it("raw hex flagged", () => {
    const errs = validateTokenClosure(minimal({ id: "n", type: "Stack", props: { gap: "#FF0000" } }));
    expect(errs.length).toBeGreaterThan(0);
  });
});
