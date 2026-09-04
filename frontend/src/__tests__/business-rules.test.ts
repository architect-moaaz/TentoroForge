/**
 * Business Rules — core chain regression tests.
 *
 * Locks down the full path the editor + playground use:
 *   data model (app-model columns + enums)
 *     -> buildFieldMeta            (field-types.ts   — the data-model binding)
 *     -> conditionToFeel(types)    (condition-to-feel.ts — visual tree -> FEEL)
 *     -> evaluateExpression        (feel-lite — the runtime engine)
 *
 * These are the invariants that make rule authoring type-accurate and make the
 * playground agree with the server-side runtime.
 */
import { describe, it, expect } from "vitest";
import {
  fieldCategory,
  operatorsForCategory,
  valueControl,
  buildFieldMeta,
  type FieldCategory,
} from "@/lib/field-types";
import { conditionToFeel, type FieldTypeMap } from "@/lib/condition-to-feel";
import { evaluateExpression } from "@/lib/feel-lite";
import type { ConditionGroup, ConditionNode } from "@/types/rules";

// ---- fixtures mirroring the real app-model (Expense) ------------------------
const EXPENSE_COLUMNS = [
  { name: "id", type: "uuid" },
  { name: "title", type: "varchar" },
  { name: "amount", type: "numeric" },
  { name: "category", type: "expense_category" },
  { name: "status", type: "expense_status" },
  { name: "urgent", type: "boolean" },
  { name: "createdAt", type: "timestamp" },
  { name: "meta", type: "jsonb" },
];
const ENUMS: Record<string, string[]> = {
  expense_status: ["draft", "submitted", "needs_approval", "approved", "rejected"],
  expense_category: ["travel", "meals", "office", "software", "other"],
};
const enumValuesForType = (t: string | undefined) => (t && ENUMS[t]) || null;

const node = (field: string, operator: ConditionNode["operator"], value = ""): ConditionNode =>
  ({ id: `${field}-${operator}`, field, operator, value });
const group = (logic: ConditionGroup["logic"], ...conditions: ConditionGroup["conditions"]): ConditionGroup =>
  ({ id: "g", logic, conditions });

describe("field-types — the data-model binding", () => {
  it("classifies Drizzle column types into categories", () => {
    expect(fieldCategory("numeric")).toBe("number");
    expect(fieldCategory("integer")).toBe("number");
    expect(fieldCategory("varchar")).toBe("string");
    expect(fieldCategory("boolean")).toBe("boolean");
    expect(fieldCategory("timestamp")).toBe("date");
    expect(fieldCategory("jsonb")).toBe("json");
    expect(fieldCategory("weird_type")).toBe("other");
    // a type that names an enum wins over everything
    expect(fieldCategory("expense_status", true)).toBe("enum");
  });

  it("offers only type-correct operators (this is what stops invalid rules)", () => {
    const num = operatorsForCategory("number");
    expect(num).toContain("gt");
    expect(num).not.toContain("contains"); // can't 'contains' a number

    const str = operatorsForCategory("string");
    expect(str).toContain("contains");
    expect(str).toContain("starts_with");

    const en = operatorsForCategory("enum");
    expect(en).toEqual(expect.arrayContaining(["equals", "in"]));
    expect(en).not.toContain("gt"); // enums aren't ordered

    expect(operatorsForCategory("boolean")).toEqual(
      expect.arrayContaining(["equals", "not_equals"]),
    );
    expect(operatorsForCategory("boolean")).not.toContain("contains");
  });

  it("picks the right value control per (category, operator)", () => {
    expect(valueControl("enum", "equals")).toBe("enum");        // dropdown
    expect(valueControl("boolean", "equals")).toBe("boolean");
    expect(valueControl("number", "gt")).toBe("number");
    expect(valueControl("date", "gte")).toBe("date");
    expect(valueControl("string", "is_null")).toBe("none");     // unary -> no value box
    expect(valueControl("enum", "in")).toBe("list");            // comma list
  });

  it("builds field meta from real app-model columns, resolving enums", () => {
    const meta = buildFieldMeta(EXPENSE_COLUMNS, enumValuesForType);
    expect(meta.amount.category).toBe("number");
    expect(meta.title.category).toBe("string");
    expect(meta.urgent.category).toBe("boolean");
    expect(meta.createdAt.category).toBe("date");
    expect(meta.status.category).toBe("enum");
    expect(meta.status.enumValues).toEqual(ENUMS.expense_status);
    expect(meta.category.enumValues).toEqual(ENUMS.expense_category);
    // non-enum columns carry no enum values
    expect(meta.amount.enumValues).toBeUndefined();
  });
});

// field -> category map, exactly how the editor derives it from the data model
const TYPES: FieldTypeMap = Object.fromEntries(
  Object.entries(buildFieldMeta(EXPENSE_COLUMNS, enumValuesForType)).map(
    ([k, v]) => [k, v.category as FieldCategory],
  ),
);

describe("condition-to-feel — visual tree -> FEEL", () => {
  it("compiles the demo rule with number typing (value stays bare)", () => {
    expect(conditionToFeel(node("amount", "gt", "1000"), TYPES)).toBe("amount > 1000");
  });

  it("always quotes enum/string values (never coerces to a number)", () => {
    expect(conditionToFeel(node("status", "equals", "needs_approval"), TYPES))
      .toBe('status = "needs_approval"');
    // the classic bug: a numeric-looking STRING must stay quoted
    expect(conditionToFeel(node("title", "equals", "01234"), TYPES)).toBe('title = "01234"');
  });

  it("auto-detects types when no data model is present (free-text fallback)", () => {
    expect(conditionToFeel(node("amount", "gt", "1000"))).toBe("amount > 1000");
    expect(conditionToFeel(node("status", "equals", "draft"))).toBe('status = "draft"');
    expect(conditionToFeel(node("urgent", "equals", "true"))).toBe("urgent = true");
  });

  it("never injects a bare 0 for an empty number box", () => {
    expect(conditionToFeel(node("amount", "equals", ""), TYPES)).toBe('amount = ""');
  });

  it("compiles AND / OR / NOT groups", () => {
    expect(conditionToFeel(group("AND", node("amount", "gt", "1000"), node("urgent", "equals", "true")), TYPES))
      .toBe("(amount > 1000 and urgent = true)");
    expect(conditionToFeel(group("OR", node("amount", "gt", "1000"), node("urgent", "equals", "true")), TYPES))
      .toBe("(amount > 1000 or urgent = true)");
    expect(conditionToFeel(group("NOT", node("urgent", "equals", "true")), TYPES))
      .toBe("not(urgent = true)");
  });

  it("compiles list, null and string operators", () => {
    expect(conditionToFeel(node("status", "in", "draft, approved"), TYPES))
      .toBe('status in ["draft", "approved"]');
    expect(conditionToFeel(node("status", "not_in", "draft"), TYPES))
      .toBe('not(status in ["draft"])');
    expect(conditionToFeel(node("title", "is_null"), TYPES)).toBe("title = null");
    expect(conditionToFeel(node("title", "is_not_null"), TYPES)).toBe("title != null");
    expect(conditionToFeel(node("title", "contains", "taxi"), TYPES)).toBe('contains(title, "taxi")');
  });

  it("emits the UNDERSCORE starts_with/ends_with form (parses on backend too)", () => {
    expect(conditionToFeel(node("title", "starts_with", "UBER"), TYPES))
      .toBe('starts_with(title, "UBER")');
    expect(conditionToFeel(node("title", "ends_with", "2024"), TYPES))
      .toBe('ends_with(title, "2024")');
  });

  it("an empty condition means 'always fires' (true)", () => {
    expect(conditionToFeel(null)).toBe("true");
    expect(conditionToFeel(group("AND"))).toBe("true");
  });
});

describe("end-to-end — compile then actually evaluate (the playground path)", () => {
  const run = (expr: ReturnType<typeof conditionToFeel> | string, record: Record<string, unknown>) =>
    evaluateExpression(expr as string, record as never);

  it("the demo rule: amount > 1000 fires at 1500, not at 500", () => {
    const feel = conditionToFeel(node("amount", "gt", "1000"), TYPES);
    expect(run(feel, { amount: 1500, status: "submitted" })).toBe(true);
    expect(run(feel, { amount: 500, status: "submitted" })).toBe(false);
    expect(run(feel, { amount: 1000, status: "submitted" })).toBe(false); // boundary
  });

  it("enum equality evaluates against a real record", () => {
    const feel = conditionToFeel(node("status", "equals", "needs_approval"), TYPES);
    expect(run(feel, { status: "needs_approval" })).toBe(true);
    expect(run(feel, { status: "draft" })).toBe(false);
  });

  it("AND group evaluates (amount + enum category)", () => {
    const feel = conditionToFeel(
      group("AND", node("amount", "gt", "1000"), node("category", "equals", "travel")),
      TYPES,
    );
    expect(run(feel, { amount: 1500, category: "travel" })).toBe(true);
    expect(run(feel, { amount: 1500, category: "meals" })).toBe(false);
    expect(run(feel, { amount: 500, category: "travel" })).toBe(false);
  });

  it("the underscore starts_with alias actually evaluates (front/back parity)", () => {
    const feel = conditionToFeel(node("title", "starts_with", "UBER"), TYPES);
    expect(run(feel, { title: "UBER trip to airport" })).toBe(true);
    expect(run(feel, { title: "Lyft trip" })).toBe(false);
  });

  it("in-list evaluates", () => {
    const feel = conditionToFeel(node("status", "in", "submitted, needs_approval"), TYPES);
    expect(run(feel, { status: "needs_approval" })).toBe(true);
    expect(run(feel, { status: "draft" })).toBe(false);
  });

  it("an empty condition evaluates to true (rule always fires)", () => {
    expect(run(conditionToFeel(null), { amount: 1 })).toBe(true);
  });
});

describe("conditionToFeel: the acting user is a reference, not a string", () => {
  // `ownerId = "user.id"` compiles cleanly and then matches nothing, forever —
  // the failure mode a row-access rule cannot afford.
  it("passes user.<field> through bare", () => {
    expect(conditionToFeel(node("ownerId", "equals", "user.id"))).toBe(
      "ownerId = user.id",
    );
  });

  it("passes it through on a string-typed field too", () => {
    expect(
      conditionToFeel(node("ownerId", "equals", "user.id"), { ownerId: "string" }),
    ).toBe("ownerId = user.id");
  });

  it("still quotes anything else that contains a dot", () => {
    expect(conditionToFeel(node("host", "equals", "example.com"))).toBe(
      'host = "example.com"',
    );
  });

  it("does not pass through a reference to another table", () => {
    // A row rule compiles to a predicate over one table; `order.total` would
    // be refused at read time, which is far later than here.
    expect(conditionToFeel(node("total", "equals", "order.total"))).toBe(
      'total = "order.total"',
    );
  });
});
