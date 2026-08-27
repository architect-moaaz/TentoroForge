import { describe, it, expect } from "vitest";
import { resolveBinding, evalExpression } from "../src/runtime/bindings";

const data = { products: { items: [{ id: 1, name: "Widget" }] } };

describe("resolveBinding", () => {
  it("walks dotted paths and array indices", () => {
    expect(resolveBinding({ source: "products", path: "items[0].name" }, { data })).toBe("Widget");
  });
  it("returns undefined when source missing", () => {
    expect(resolveBinding({ source: "missing", path: "x" }, { data })).toBeUndefined();
  });
});

describe("evalExpression", () => {
  it("evaluates simple comparisons via FEEL-lite", () => {
    expect(evalExpression("user.role == 'admin'", { user: { role: "admin" } })).toBe(true);
    expect(evalExpression("user.role == 'admin'", { user: { role: "viewer" } })).toBe(false);
  });
  it("returns false on evaluation error and logs (not throws)", () => {
    const v = evalExpression("user..bad", {});
    expect(v).toBe(false);
  });

  it("resolves array-index paths via walkPath (feel-lite can't parse arr[0])", () => {
    const ctx = { recentInterviews: [{ interviewerName: "Ana" }, { interviewerName: "Ben" }] };
    expect(evalExpression("recentInterviews[0].interviewerName", ctx)).toBe("Ana");
    expect(evalExpression("recentInterviews[1].interviewerName", ctx)).toBe("Ben");
  });

  it("returns undefined for an out-of-range array index", () => {
    const ctx = { recentInterviews: [{ interviewerName: "Ana" }] };
    expect(evalExpression("recentInterviews[9].interviewerName", ctx)).toBeUndefined();
  });

  it("still evaluates real expressions via feel-lite", () => {
    expect(evalExpression("2 + 3", {})).toBe(5);
  });

  it("still resolves pure-dotted paths via feel-lite", () => {
    expect(evalExpression("a.b", { a: { b: 7 } })).toBe(7);
  });
});
