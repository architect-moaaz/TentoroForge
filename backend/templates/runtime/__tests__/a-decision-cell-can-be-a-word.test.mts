/**
 * A decision table's output cell written as a word is that word.
 *
 * Authors write `Severe` or `GeneralManager+AMIR`, not `"Severe"`. The engine
 * read every unquoted cell as a formula, each word as an unknown variable, and
 * the output came back null: CARES (kkb5mzo3, 2026-11-10) wrote null over a
 * case's severityTier and the insert failed. A cell that names a field the
 * record has, or is a real formula, is still worked out.
 *
 * Runs the SHIPPED rules/engine.ts and feel-lite.
 */
import { installHarness, ok, eqJson, done } from "./_harness.mts";

installHarness();   // engine and feel-lite import their siblings without extensions
const { setRules, evaluateRuleSet } = await import("../rules/engine.ts");

const table = (outputs: string[]) => ({
  id: "dt", name: "severity", rule_type: "decision_table", model_name: "Case", is_active: true,
  config: { source: "manual", table: {
    id: "t", name: "severity", hitPolicy: "F",
    inputs: [{ id: "i1", name: "score", type: "number", variableBinding: "score" }],
    outputs: [
      { id: "o1", name: "severityTier", type: "string" },
      { id: "o2", name: "approver", type: "string" },
      { id: "o3", name: "fee", type: "number" },
    ],
    rules: [{ id: "r1", inputEntries: ["-"], outputEntries: outputs }],
  } },
});

const run = async (outputs: string[], record: Record<string, unknown> = {}) => {
  setRules([table(outputs) as any]);
  return (await evaluateRuleSet("Case", "create", { score: 9, ...record })).patches;
};

let p = await run(["Severe", "GeneralManager+AMIR", "-"]);
eqJson(p.severityTier, "Severe", "a bare word is that word, not an unknown variable");
eqJson(p.approver, "GeneralManager+AMIR", "names joined by + are that text");
p = await run(["High-Risk", "Ops Lead", "-"]);
eqJson(p.severityTier, "High-Risk", "names joined by - are that text");
eqJson(p.approver, "Ops Lead", "words with a space are that text");

p = await run(['"Severe"', "'Mild'", "12.5"]);
eqJson([p.severityTier, p.approver, p.fee], ["Severe", "Mild", 12.5], "quoted text and numbers as before");
p = await run(["true", "false", "-"]);
eqJson([p.severityTier, p.approver], [true, false], "true and false as before");

p = await run(["owner", "owner + \" (lead)\"", "score * 10"], { owner: "Amir" });
eqJson(p.severityTier, "Amir", "a word that names a field on the record is that field's value");
eqJson(p.approver, "Amir (lead)", "a formula on a field is worked out");
eqJson(p.fee, 90, "arithmetic is worked out");
p = await run(['if score > 5 then "Severe" else "Mild"', "-", "-"]);
eqJson(p.severityTier, "Severe", "an if is worked out");
p = await run(["-", "-", "discount * 2"]);
ok(typeof p.fee !== "string", "a formula on an absent number is still worked out, not turned into text");

done("decision-cell");
