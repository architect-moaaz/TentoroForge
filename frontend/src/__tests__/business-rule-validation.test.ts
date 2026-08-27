import { describe, it, expect } from "vitest";
import {
  validateAction,
  validateConditionActionRule,
  validateDecisionTableRule,
} from "@/lib/business-rule-validation";
import type { RuleAction } from "@/types/business-rules";

const act = (a: Partial<RuleAction>): RuleAction =>
  ({ id: "a1", type: "set_field", ...a }) as RuleAction;

describe("validateAction", () => {
  it("flags a set_field with no field or value", () => {
    const errs = validateAction(act({ type: "set_field" }), "then");
    expect(errs.length).toBe(2); // field + value
  });
  it("passes a complete set_field", () => {
    expect(validateAction(act({ type: "set_field", field: "status", value: "open" }), "then"))
      .toEqual([]);
  });
  it("flags show_error with no message", () => {
    expect(validateAction(act({ type: "show_error" }), "then")).toHaveLength(1);
  });
  it("flags trigger_workflow with no workflow", () => {
    expect(validateAction(act({ type: "trigger_workflow" }), "then")).toHaveLength(1);
  });
  it("passes a lock (set_readonly) with just a field", () => {
    expect(validateAction(act({ type: "set_readonly", field: "total" }), "then")).toEqual([]);
  });
});

describe("validateConditionActionRule", () => {
  it("requires a name, a model, and at least one action", () => {
    const errs = validateConditionActionRule("", null, { then: [], otherwise: [] });
    expect(errs).toContain("Give the rule a name.");
    expect(errs).toContain("Choose the model this rule applies to.");
    expect(errs.some((e) => e.includes("no actions"))).toBe(true);
  });
  it("passes a complete rule", () => {
    const errs = validateConditionActionRule("block-neg", "Invoice", {
      then: [act({ type: "show_error", message: "Amount must be positive" })],
      otherwise: [],
    });
    expect(errs).toEqual([]);
  });
  it("propagates a bad action's error", () => {
    const errs = validateConditionActionRule("r", "Invoice", {
      then: [act({ type: "set_field", field: "", value: "" })],
      otherwise: [],
    });
    expect(errs.length).toBeGreaterThan(0);
  });
});

describe("validateDecisionTableRule", () => {
  it("flags an empty table", () => {
    const errs = validateDecisionTableRule("dt", {
      id: "t", name: "dt", hitPolicy: "U", inputs: [], outputs: [], rules: [],
    });
    expect(errs.length).toBe(3); // inputs + outputs + rules
  });
  it("passes a table with inputs, outputs, and a rule", () => {
    const errs = validateDecisionTableRule("dt", {
      inputs: [{}], outputs: [{}], rules: [{}],
    });
    expect(errs).toEqual([]);
  });
});
