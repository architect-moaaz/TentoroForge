import { describe, expect, it } from "vitest";
import { buildRuleGraph, fieldsRead, lightUp, neighbourhood } from "@/lib/rules-graph";
import type { StudioCatalogue, StudioView } from "@/lib/rules-studio";

const catalogue = {
  entities: [{ id: "ENTITY-001", name: "Expense", fields: [
    { name: "amount", type: "number", enumValues: [], required: true },
    { name: "category", type: "enum", enumValues: ["travel", "meals", "office"], required: true },
    { name: "status", type: "enum", enumValues: ["submitted", "approved"], required: false },
    { name: "managerNote", type: "string", enumValues: [], required: false },
  ] }],
  workflows: [{ id: "FLOW-002", name: "Approve" }],
  requirements: [],
} as unknown as StudioCatalogue;

const view = (rule: object, kind = "condition_action", extra: object = {}) => ({
  rule, kind, entityName: "Expense", enabled: true, enforced: true, revision: "r", origin: "editor", runs: "everywhere",
  gates: [], requirements: [], ...extra,
}) as unknown as StudioView;

const gate = view({ id: "RULE-001", name: "Positive amount", when: "amount <= 0",
                    then: [{ type: "show_error", message: "Above zero." }] }, "condition_action",
                  { usages: { steps: [{ workflow: "FLOW-002", name: "Approve" }], starts: [], saves: [] } });
const note = view({ id: "RULE-002", name: "Note above 5000", when: "amount > 5000 and previous.status = \"approved\"",
                    then: [{ type: "set_required", field: "managerNote" }],
                    otherwise: [{ type: "set_required", field: "managerNote", required: false }] });
const table = view({ id: "RULE-007", name: "Category by amount", table: { hitPolicy: "F",
                     inputs: [{ name: "amount" }], outputs: [{ name: "category" }],
                     rules: [{ inputEntries: ["> 1000"], outputEntries: ["office"] }] } }, "decision_table");
const written = view({ id: "RULE-009", name: "Keep receipts", statement: "…" }, "statement");

describe("the rules map", () => {
  it("reads the record's own fields from a condition, previous.x included, never words or quoted text", () => {
    const f = new Set(["amount", "status", "category"]);
    expect(fieldsRead('amount > 5 and previous.status = "category" and not(user.role = "x")', f)).toEqual(["amount", "status"]);
  });

  it("draws reads → rules → writes, refusals, hints and workflows; written rules are left out", () => {
    const g = buildRuleGraph([gate, note, table, written], catalogue, "Expense");
    const ids = g.nodes.map((n) => n.id).sort();
    expect(ids).toEqual(["hint:managerNote", "read:amount", "read:status", "refuse:RULE-001:then", "rule:RULE-001",
                         "rule:RULE-002", "rule:RULE-007", "wf:FLOW-002", "write:category"].sort());
    const e = (s: string, t: string) => g.edges.find((x) => x.source === s && x.target.startsWith(t));
    expect(e("read:amount", "rule:RULE-007")?.branch).toBe("always");
    expect(e("rule:RULE-007", "write:category")?.branch).toBe("table");
    expect(e("rule:RULE-001", "wf:FLOW-002")?.label).toBe("extra check in");
    expect(g.edges.filter((x) => x.source === "rule:RULE-002").map((x) => x.branch).sort()).toEqual(["otherwise", "then"]);
    // Laid out left to right: a field it reads sits left of the rule, a field it writes right of it.
    const at = (id: string) => g.nodes.find((n) => n.id === id)!.x;
    expect(at("read:amount")).toBeLessThan(at("rule:RULE-007"));
    expect(at("rule:RULE-007")).toBeLessThan(at("write:category"));
  });

  it("hovering a field shows the rules on it and their whole chain", () => {
    const g = buildRuleGraph([gate, note, table], catalogue, "Expense");
    const n = neighbourhood(g, "read:status");
    expect(n.nodes.has("rule:RULE-002") && n.nodes.has("hint:managerNote")).toBe(true);
    expect(n.nodes.has("rule:RULE-007")).toBe(false);
  });

  it("lights the path a save took: the branch each rule acted on, in the order it fired", () => {
    const g = buildRuleGraph([gate, note, table], catalogue, "Expense");
    const light = lightUp(g, [gate, note, table], {
      ok: true, problems: [], refused: true, errors: ["Above zero."], patches: { category: "office" }, record: { amount: -5 },
      trace: [
        { id: "RULE-001", name: "", kind: "condition_action", fires: true, held: true },
        { id: "RULE-002", name: "", kind: "condition_action", fires: true, held: false },
        { id: "RULE-007", name: "", kind: "decision_table", fires: true, matched: [] },
      ],
    });
    expect([light.rules.get("RULE-001"), light.rules.get("RULE-002"), light.rules.get("RULE-007")]).toEqual(["held", "missed", "missed"]);
    const carried = [...light.edges.keys()];
    expect(carried.some((id) => id.includes("refuse:RULE-001"))).toBe(true);
    expect(g.edges.filter((x) => x.ruleId === "RULE-002" && light.edges.has(x.id) && x.branch !== "always").map((x) => x.branch)).toEqual(["otherwise"]);
    expect(g.edges.some((x) => x.ruleId === "RULE-007" && x.branch === "table" && light.edges.has(x.id))).toBe(false);
    expect(light.written.get("category")).toBe("office");
    expect(light.edges.get(g.edges.find((x) => x.target.startsWith("refuse:"))!.id)).toBe(0);
  });
});
