// A rule changed while the app runs is the rule in force — no restart.
// (Its own file: setRules pins the in-memory cache, and this must read disk.)
import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { loadRules, evaluateRuleSet, isRuleSwitchedOff } from "../rules/engine.ts";

const rule = (limit: number) => [{
  id: "RULE-040", name: "urgent", rule_type: "condition_action", model_name: "Task", is_active: true,
  config: { whenFeel: `priority > ${limit}`, then: [{ type: "show_error", message: "Too urgent." }],
            otherwise: [], scope: "entity", salience: 0 },
}];
const dir = await fs.mkdtemp(path.join(os.tmpdir(), "forge-rules-"));
const file = path.join(dir, "blueprint-rules.json");
await fs.writeFile(file, JSON.stringify(rule(3)));
await loadRules(dir);
assert.deepEqual((await evaluateRuleSet("Task", "create", { priority: 5 })).errors, ["Too urgent."]);

// Edited on disk (the Business Rules tab or Smith re-projects the file).
await new Promise((r) => setTimeout(r, 1100));
await fs.writeFile(file, JSON.stringify(rule(8)));
await loadRules(dir);
assert.deepEqual((await evaluateRuleSet("Task", "create", { priority: 5 })).errors, [], "the edited rule is in force");

// Switched off: removed from the file.
await new Promise((r) => setTimeout(r, 1100));
await fs.writeFile(file, "[]");
await loadRules(dir);
assert.deepEqual((await evaluateRuleSet("Task", "create", { priority: 99 })).errors, [], "a removed rule is gone");

// Switched off in the tab: written by name, inactive — never applied, but known as "off".
await new Promise((r) => setTimeout(r, 1100));
await fs.writeFile(file, JSON.stringify([{ ...rule(3)[0], is_active: false, config: { source: "blueprint" } }]));
const loaded = await loadRules(dir);
assert.deepEqual((await evaluateRuleSet("Task", "create", { priority: 99 })).errors, [], "a switched-off rule is not applied");
assert.equal(loaded.some((r) => r.id === "RULE-040"), false, "and is not among the rules in force");
assert.equal(isRuleSwitchedOff("RULE-040"), true, "but is known to be off");
assert.equal(isRuleSwitchedOff("RULE-404"), false, "a rule the app never had is not 'off'");

// Unchanged files are not re-read within the recheck window (cheap on every write).
const t0 = Date.now();
for (let i = 0; i < 200; i++) await loadRules(dir);
assert.ok(Date.now() - t0 < 1000, "200 writes cost no file reads");
console.log("rules-reload: ALL ASSERTIONS PASS ✅");
