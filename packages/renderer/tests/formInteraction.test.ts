import { describe, it, expect } from "vitest";
import {
  INTERACTION_FUNCTIONS,
  evaluateComputed,
  extractFormulaVars,
  computedEvalOrder,
  type FieldInteraction,
} from "../src/runtime/formInteraction";

describe("INTERACTION_FUNCTIONS", () => {
  const { daysBetween, hoursBetween, sum, min, max, round, abs, ceil, floor, ifElse } =
    INTERACTION_FUNCTIONS;

  it("daysBetween returns whole days end - start", () => {
    expect(daysBetween("2026-07-14", "2026-07-18")).toBe(4);
  });
  it("daysBetween accepts Date objects", () => {
    expect(daysBetween(new Date("2026-07-14"), new Date("2026-07-16"))).toBe(2);
  });
  it("daysBetween returns 0 when a date is missing or invalid", () => {
    expect(daysBetween("2026-07-14", "")).toBe(0);
    expect(daysBetween(undefined, "2026-07-18")).toBe(0);
    expect(daysBetween("not-a-date", "2026-07-18")).toBe(0);
  });
  it("hoursBetween returns whole hours", () => {
    expect(hoursBetween("2026-07-14T00:00:00Z", "2026-07-14T05:00:00Z")).toBe(5);
    expect(hoursBetween("2026-07-14", "")).toBe(0);
  });
  it("sum coerces strings and ignores NaN/missing", () => {
    expect(sum(1, 2, 3)).toBe(6);
    expect(sum("1", "2", 3)).toBe(6);
    expect(sum(1, "oops", undefined, 4)).toBe(5);
    expect(sum()).toBe(0);
  });
  it("min / max ignore invalid, default to 0 when empty", () => {
    expect(min(3, 1, 2)).toBe(1);
    expect(max(3, 1, 2)).toBe(3);
    expect(min("x", undefined)).toBe(0);
    expect(max()).toBe(0);
  });
  it("round respects digits (default 0)", () => {
    expect(round(3.14159, 2)).toBe(3.14);
    expect(round(3.6)).toBe(4);
    expect(round("2.345", 2)).toBe(2.35);
    expect(round(undefined)).toBe(0);
  });
  it("abs / ceil / floor coerce and degrade to 0", () => {
    expect(abs(-5)).toBe(5);
    expect(abs("-2")).toBe(2);
    expect(ceil(1.1)).toBe(2);
    expect(floor(1.9)).toBe(1);
    expect(abs("nope")).toBe(0);
  });
  it("ifElse picks by truthiness", () => {
    expect(ifElse(true, "a", "b")).toBe("a");
    expect(ifElse(0, "a", "b")).toBe("b");
    expect(ifElse("", 1, 2)).toBe(2);
  });
});

describe("evaluateComputed", () => {
  it("evaluates the spec rental example (rate * daysBetween)", () => {
    expect(
      evaluateComputed("ratePerDay * daysBetween(startDate, endDate)", {
        ratePerDay: 5,
        startDate: "2026-07-14",
        endDate: "2026-07-18",
      }),
    ).toBe(20);
  });
  it("evaluates qty * unitPrice", () => {
    expect(evaluateComputed("qty * unitPrice", { qty: 3, unitPrice: 4 })).toBe(12);
  });
  it("evaluates subtotal + tax", () => {
    expect(evaluateComputed("subtotal + tax", { subtotal: 100, tax: 8 })).toBe(108);
  });
  it("supports round(x, 2)", () => {
    expect(evaluateComputed("round(x, 2)", { x: 3.14159 })).toBe(3.14);
  });
  it("supports sum(a, b, c)", () => {
    expect(evaluateComputed("sum(a, b, c)", { a: 1, b: 2, c: 3 })).toBe(6);
  });
  it("supports nested function calls", () => {
    expect(
      evaluateComputed("round(sum(a, b) / 3, 2)", { a: 10, b: 0 }),
    ).toBeCloseTo(3.33, 2);
  });
  it("treats a missing variable as 0 without throwing", () => {
    // unitPrice missing → 0 → product 0
    expect(evaluateComputed("qty * unitPrice", { qty: 3 })).toBe(0);
    expect(() => evaluateComputed("qty * unitPrice", { qty: 3 })).not.toThrow();
  });
  it("coerces numeric string field values", () => {
    expect(evaluateComputed("qty * unitPrice", { qty: "3", unitPrice: "4" })).toBe(12);
  });
  it("returns null (never throws) on garbage formula", () => {
    expect(() => evaluateComputed("* * )(", {})).not.toThrow();
    expect(evaluateComputed("", {})).toBeNull();
  });
});

describe("extractFormulaVars", () => {
  it("returns field refs but NOT function names", () => {
    expect(
      extractFormulaVars("ratePerDay * daysBetween(startDate, endDate)"),
    ).toEqual(["ratePerDay", "startDate", "endDate"]);
  });
  it("dedupes and preserves first-appearance order", () => {
    expect(extractFormulaVars("a + b + a * c")).toEqual(["a", "b", "c"]);
  });
  it("ignores numeric literals and string contents", () => {
    expect(extractFormulaVars("qty * 2 + 'label'")).toEqual(["qty"]);
  });
  it("collapses dotted refs to their root", () => {
    expect(extractFormulaVars("result.address")).toEqual(["result"]);
  });
});

describe("computedEvalOrder", () => {
  const F = (
    name: string,
    formula?: string,
  ): { name: string; interaction?: FieldInteraction } =>
    formula ? { name, interaction: { computed: { formula } } } : { name };

  it("orders a computed field after the computed field it depends on", () => {
    const order = computedEvalOrder([
      F("qty"),
      F("price"),
      F("total", "subtotal + tax"),
      F("subtotal", "qty * price"),
      F("tax"),
    ]);
    // Only computed fields are returned; subtotal must come before total.
    expect(order).toContain("subtotal");
    expect(order).toContain("total");
    expect(order.indexOf("subtotal")).toBeLessThan(order.indexOf("total"));
  });

  it("returns only computed fields", () => {
    const order = computedEvalOrder([
      F("qty"),
      F("subtotal", "qty * price"),
    ]);
    expect(order).toEqual(["subtotal"]);
  });

  it("is cycle-safe: a <-> b terminates and returns both", () => {
    const order = computedEvalOrder([
      F("a", "b + 1"),
      F("b", "a + 1"),
    ]);
    expect(order.sort()).toEqual(["a", "b"]);
  });

  it("handles an empty field list", () => {
    expect(computedEvalOrder([])).toEqual([]);
  });
});

describe("evalExpression (calculator display eval)", () => {
  const { evalExpression } = INTERACTION_FUNCTIONS;

  it("returns empty for empty/undefined", () => {
    expect(evalExpression("")).toBe("");
    expect(evalExpression(undefined)).toBe("");
  });

  it("basic four-function arithmetic", () => {
    expect(evalExpression("2+3")).toBe("5");
    expect(evalExpression("10-4")).toBe("6");
    expect(evalExpression("6*7")).toBe("42");
    expect(evalExpression("15/3")).toBe("5");
  });

  it("respects operator precedence", () => {
    expect(evalExpression("2+3*4")).toBe("14");
    expect(evalExpression("(2+3)*4")).toBe("20");
    expect(evalExpression("100-10/2")).toBe("95");
  });

  it("handles decimals", () => {
    expect(evalExpression("1.5+2.25")).toBe("3.75");
    expect(evalExpression("0.1+0.2")).toBe("0.3"); // float-noise trim
  });

  it("handles unicode operator glyphs (× ÷ −)", () => {
    expect(evalExpression("6×7")).toBe("42");
    expect(evalExpression("20÷4")).toBe("5");
    expect(evalExpression("10−3")).toBe("7");
  });

  it("handles unary minus at start / after '('", () => {
    expect(evalExpression("-5+3")).toBe("-2");
    expect(evalExpression("-(2+3)")).toBe("-5");
    // Mid-expression negation "5*-2" isn't a natural keypad input
    // (users hit "5 × ( - 2 )" or "5 × +/- 2"); use explicit parens instead:
    expect(evalExpression("5*(-2)")).toBe("-10");
  });

  it("returns 'Error' on divide by zero", () => {
    expect(evalExpression("5/0")).toBe("Error");
    expect(evalExpression("10%0")).toBe("Error");
  });

  it("returns 'Error' on unbalanced parens", () => {
    expect(evalExpression("(2+3")).toBe("Error");
    expect(evalExpression("2+3)")).toBe("Error");
  });

  it("returns 'Error' on non-arithmetic input", () => {
    expect(evalExpression("2+alert(1)")).toBe("Error"); // no JS injection
    expect(evalExpression("2+abc")).toBe("Error");
    expect(evalExpression("Math.PI")).toBe("Error");
  });

  it("handles the classic '8+3' example", () => {
    expect(evalExpression("8+3")).toBe("11");
  });

  it("modulo works", () => {
    expect(evalExpression("10%3")).toBe("1");
  });
});
