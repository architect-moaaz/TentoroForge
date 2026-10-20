// The Business Rules studio's library: a rule read as a sentence, and the
// decision-table model the table editor edits, round-tripped to what is stored.
import { describe, expect, it } from "vitest";
import {
  coerceSample, emptyTable, humanField, ruleSentence, tableFromStored, tableToStored, whenWords,
  type StudioView,
} from "@/lib/rules-studio";

const cat = { entities: [], requirements: [], workflows: [{ id: "FLOW-002", name: "Approve expense" }] } as any;
const view = (rule: any, kind = "condition_action", entityName = "Expense"): StudioView =>
  ({ rule: { id: "RULE-001", name: "x", statement: "", ...rule }, kind, entityName, revision: "r", origin: "editor",
     enabled: true, enforced: true, runs: "everywhere", gates: [], requirements: [] }) as any;

describe("a rule read as a sentence", () => {
  it("says when, the condition in words, then and otherwise", () => {
    const s = ruleSentence(view({
      when: 'amount > 5000 and managerNote = null',
      then: [{ type: "show_error", message: "Add a note." }],
      otherwise: [{ type: "trigger_workflow", workflow: "FLOW-002" }],
    }), cat);
    expect(s).toContain("When an Expense is saved and");
    expect(s).toContain("amount is more than 5000");
    expect(s).toContain("refuse it: “Add a note.”");
    expect(s).toContain("otherwise start “Approve expense”");
  });
  it("says when it fires", () => {
    expect(ruleSentence(view({ on: ["create"], when: "true", then: [{ type: "set_default", field: "status", value: "submitted" }] }), cat))
      .toBe("When an Expense is created, default status to “submitted”.");
    expect(ruleSentence(view({ on: ["update"], when: "true", then: [] }), cat)).toContain("is updated");
  });
  it("says a requirement released as released", () => {
    expect(ruleSentence(view({ when: "amount > 5000", then: [{ type: "set_required", field: "managerNote", required: true }],
                               otherwise: [{ type: "set_required", field: "managerNote", required: false }] }), cat))
      .toBe("When an Expense is saved and amount is more than 5000, require manager note; otherwise stop requiring manager note.");
  });
  it("keeps a condition it cannot put in words as written", () => {
    expect(whenWords("string length(title) > 3")).toBe("“string length(title) > 3”");
    expect(whenWords("")).toBe("always");
  });
  it("describes a table by what it reads, sets and how rows win", () => {
    const s = ruleSentence(view({ table: { hitPolicy: "U", inputs: [{ name: "amount" }], outputs: [{ name: "approverRole" }],
                                           rules: [{ inputEntries: ["-"], outputEntries: ["cfo"] }] } }, "decision_table"), cat);
    expect(s).toBe("When an Expense is saved, set approver role from amount by a table of 1 row (one row may match).");
  });
});

describe("the decision-table model", () => {
  it("round-trips what is stored, filling blank inputs with 'anything'", () => {
    const stored = { hitPolicy: "C", aggregation: "sum",
      inputs: [{ name: "category", variableBinding: "category", type: "string", values: ["travel", "meals"] }],
      outputs: [{ name: "points", variableBinding: "points", type: "number" }],
      rules: [{ inputEntries: ["travel"], outputEntries: ["2"], annotation: "double" }, { inputEntries: [""], outputEntries: ["1"] }] };
    const t = tableFromStored(stored);
    expect(t.hitPolicy).toBe("C");
    expect(t.aggregation).toBe("SUM");
    expect(t.inputs[0].values).toEqual(["travel", "meals"]);
    const back = tableToStored(t);
    expect(back.aggregation).toBe("SUM");
    expect(back.inputs).toEqual([{ name: "category", variableBinding: "category", type: "string", values: ["travel", "meals"] }]);
    expect(back.rules).toEqual([
      { inputEntries: ["travel"], outputEntries: ["2"], annotation: "double" },
      { inputEntries: ["-"], outputEntries: ["1"] },
    ]);
  });
  it("drops the aggregation when the policy is not Collect, and reads an unknown policy as First", () => {
    expect(tableToStored({ ...emptyTable(), hitPolicy: "F", aggregation: "SUM" }).aggregation).toBeUndefined();
    expect(tableFromStored({ hitPolicy: "zz" } as any).hitPolicy).toBe("F");
  });
});

describe("small words", () => {
  it("fields read as words; a sample value is typed", () => {
    expect(humanField("managerNote")).toBe("manager note");
    expect(humanField("created_at")).toBe("created at");
    expect(coerceSample("5000", "number")).toBe(5000);
    expect(coerceSample("true", "boolean")).toBe(true);
    expect(coerceSample("  ", "string")).toBeNull();
    expect(coerceSample("travel", "string")).toBe("travel");
  });
});

describe("a condition row with no field chosen", () => {
  it("says nothing, so it cannot make a rule that never fires", async () => {
    const { conditionToFeel } = await import("@/lib/condition-to-feel");
    const blank = { id: "b", field: "", operator: "equals" as const, value: "" };
    const amount = { id: "a", field: "amount", operator: "gt" as const, value: "200" };
    expect(conditionToFeel({ id: "g", logic: "AND", conditions: [amount, blank] } as any, { amount: "number" } as any)).toBe("amount > 200");
    expect(conditionToFeel({ id: "g", logic: "AND", conditions: [blank, blank] } as any)).toBe("true");
    expect(conditionToFeel(blank as any)).toBe("true");
  });
});
