import { describe, it, expect } from "vitest";
import { interpolateString, interpolateDeep } from "../src/data/interpolate";
import { evalExpression } from "../src/data/expressions";

describe("re-exported interpolate", () => {
  it("replaces {{path.to.value}}", () => {
    expect(interpolateString("Hello, {{user.name}}!", { user: { name: "Alex" } }))
      .toBe("Hello, Alex!");
  });

  it("walks objects recursively", () => {
    expect(interpolateDeep({ label: "{{a}}", child: { value: "{{b}}" } },
                           { a: "A", b: "B" }))
      .toEqual({ label: "A", child: { value: "B" } });
  });
});

describe("re-exported evalExpression", () => {
  it("evaluates boolean equality", () => {
    expect(evalExpression("status == 'active'", { status: "active" })).toBe(true);
    expect(evalExpression("status == 'active'", { status: "draft" })).toBe(false);
  });

  it("returns false on parse error rather than throwing", () => {
    expect(evalExpression("totally invalid !!", {})).toBe(false);
  });
});
