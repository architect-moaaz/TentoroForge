// Runtime rule-set engine test (condition→action). Exercises the REAL engine +
// feel-lite via setRules(). Run: esbuild-bundle then node (see run-rule-tests.sh)
// — it needs bundling because engine.ts imports ../feel-lite.
import assert from "node:assert/strict";
import { setRules, evaluateRuleSet, evaluateFormRules } from "../rules/engine.ts";

setRules([
  // salience 0: reject big amounts
  { id: "1", name: "reject-big", rule_type: "condition_action", model_name: "Invoice", is_active: true,
    config: { source: "manual", whenFeel: "amount > 1000",
      then: [{ id: "a", type: "show_error", message: "over 1000 needs approver" }], otherwise: [],
      scope: "entity", salience: 0 } },
  // salience 10 (runs FIRST): default status when blank
  { id: "2", name: "default-status", rule_type: "condition_action", model_name: "Invoice", is_active: true,
    config: { source: "manual", whenFeel: "true",
      then: [{ id: "b", type: "set_default", field: "status", valueMode: "literal", value: "draft" }], otherwise: [],
      scope: "entity", salience: 10 } },
  // form-only: hide approver for small amounts
  { id: "3", name: "hide-approver", rule_type: "condition_action", model_name: "Invoice", is_active: true,
    config: { source: "manual", whenFeel: "amount <= 1000",
      then: [{ id: "c", type: "set_visibility", field: "approver", visible: false }], otherwise: [],
      scope: "entity", salience: 0 } },
  // set_field (formula) — computed total
  { id: "4", name: "compute-total", rule_type: "condition_action", model_name: "Invoice", is_active: true,
    config: { source: "manual", whenFeel: "true",
      then: [{ id: "d", type: "set_field", field: "total", valueMode: "formula", value: "qty * price" }], otherwise: [],
      scope: "server", salience: 0 } },
  // scope=form must NOT run server-side
  { id: "5", name: "form-only-error", rule_type: "condition_action", model_name: "Invoice", is_active: true,
    config: { source: "manual", whenFeel: "true",
      then: [{ id: "e", type: "show_error", message: "should not appear server-side" }], otherwise: [],
      scope: "form", salience: 0 } },
]);

// Big amount → rejected, status defaulted, total computed, form-scope error absent
const big = await evaluateRuleSet("Invoice", "create", { amount: 5000, qty: 3, price: 10 });
assert.deepEqual(big.errors, ["over 1000 needs approver"], "big should reject");
assert.equal(big.patches.status, "draft", "status defaulted");
assert.equal(big.patches.total, 30, "total = qty*price");

// Small amount → no error, approver hidden (form hint), status defaulted
const small = await evaluateRuleSet("Invoice", "create", { amount: 50, qty: 1, price: 5 });
assert.equal(small.errors.length, 0, "small should not reject");
assert.ok(small.formHints.some((h) => h.field === "approver" && h.hidden === true), "approver hidden");

// set_default must NOT overwrite an existing value
const withStatus = await evaluateRuleSet("Invoice", "create", { amount: 10, status: "sent", qty: 1, price: 1 });
assert.equal(withStatus.patches.status, undefined, "default must not overwrite existing status");

// evaluateFormRules: patches + hints only, no errors/side-effects, includes form-scope
const form = await evaluateFormRules("Invoice", { amount: 50, qty: 2, price: 4 });
assert.ok(form.formHints.some((h) => h.field === "approver" && h.hidden === true), "form: approver hidden");
assert.equal((form as any).errors, undefined, "form result carries no errors key");

console.log("rule-set engine: ALL ASSERTIONS PASS ✅");

// ── Table-name path (workflow db_insert uses the table name, not the model) ──
import { evaluateRuleSetForTable, entityNameForTable } from "../rules/engine.ts";
// The rules above target model "Invoice"; a workflow inserts into table "invoices".
const byTable = await evaluateRuleSetForTable("invoices", "create", { amount: 5000, qty: 1, price: 2 });
assert.deepEqual(byTable.errors, ["over 1000 needs approver"], "table 'invoices' resolves to model 'Invoice'");
assert.equal(byTable.patches.status, "draft", "table path applies patches");
// A table with no matching rule is a pure no-op.
const noRule = await evaluateRuleSetForTable("widgets", "create", { amount: 9999 });
assert.deepEqual(noRule, { patches: {}, errors: [], formHints: [], sideEffects: [] }, "unmatched table no-ops");
assert.equal(await entityNameForTable("invoices"), "Invoice", "invoices → Invoice");
assert.equal(await entityNameForTable("widgets"), undefined, "widgets → (none)");
console.log("table-path resolution: PASS ✅");

// ── AI-authored rule types now EXECUTE on the write paths ────────────────────
// Previously only condition_action ran here; validation/computed/business (the
// only types the rules AGENT can emit) were silent no-ops. These are the exact
// shapes rules_agent.py produces.
setRules([
  // computed → auto-set a derived field
  { id: "c1", name: "order-total", rule_type: "computed", model_name: "Order", field_name: "total",
    is_active: true, config: { expression: "quantity * unitPrice" } },
  // validation (field min) → reject non-positive quantity
  { id: "v1", name: "qty-positive", rule_type: "validation", model_name: "Order", field_name: "quantity",
    is_active: true, config: { min: 1, errorMessage: "quantity must be at least 1" } },
  // validation (model expression) → reject when total exceeds a cap
  { id: "v2", name: "under-cap", rule_type: "validation", model_name: "Order",
    is_active: true, config: { expression: "total <= 10000", errorMessage: "order over cap" } },
  // business guard with explicit errorMessage → hard reject on create
  { id: "b1", name: "must-have-customer", rule_type: "business", model_name: "Order",
    is_active: true, config: { expression: "customerId != null", trigger: "on_create",
      errorMessage: "customer is required" } as any },
]);

// Valid order: computed total set, no errors
const ok = await evaluateRuleSet("Order", "create", { quantity: 2, unitPrice: 50, customerId: "cus_1" });
assert.equal(ok.patches.total, 100, "computed total = quantity * unitPrice");
assert.deepEqual(ok.errors, [], "valid order has no errors");

// Invalid: quantity 0 (validation min) → rejected
const badQty = await evaluateRuleSet("Order", "create", { quantity: 0, unitPrice: 50, customerId: "cus_1" });
assert.ok(badQty.errors.includes("quantity must be at least 1"), "validation min rejects qty 0");

// Invalid: computed total over cap (validation sees the COMPUTED field) → rejected
const overCap = await evaluateRuleSet("Order", "create", { quantity: 1000, unitPrice: 50, customerId: "cus_1" });
assert.ok(overCap.errors.includes("order over cap"), "validation runs AFTER computed (sees total)");

// Invalid: missing customer (business guard) → rejected
const noCust = await evaluateRuleSet("Order", "create", { quantity: 1, unitPrice: 5 });
assert.ok(noCust.errors.includes("customer is required"), "business guard rejects missing customer");

// Form path: computed total renders live
const orderForm = await evaluateFormRules("Order", { quantity: 3, unitPrice: 7 });
assert.equal(orderForm.patches.total, 21, "form path computes total live");
console.log("AI rule types (computed/validation/business) execute: PASS ✅");

// ── Robust plural table→model resolution (was single-'s' strip only) ─────────
setRules([
  { id: "r1", name: "addr-guard", rule_type: "validation", model_name: "Address",
    is_active: true, config: { expression: "zip != null", errorMessage: "zip required" } },
  { id: "r2", name: "cat-guard", rule_type: "condition_action", model_name: "Category",
    is_active: true, config: { source: "manual", whenFeel: "true", then: [], otherwise: [], scope: "entity", salience: 0 } },
  { id: "r3", name: "status-guard", rule_type: "computed", model_name: "Status", field_name: "slug",
    is_active: true, config: { expression: "1" } },
  { id: "r4", name: "company-guard", rule_type: "validation", model_name: "Company",
    is_active: true, config: { expression: "name != null", errorMessage: "name required" } },
]);
assert.equal(await entityNameForTable("addresses"), "Address", "addresses → Address (es)");
assert.equal(await entityNameForTable("categories"), "Category", "categories → Category (ies→y)");
assert.equal(await entityNameForTable("statuses"), "Status", "statuses → Status (ses, no over-strip)");
assert.equal(await entityNameForTable("companies"), "Company", "companies → Company (ies→y)");
// A validation-only model must resolve from its table on the workflow path.
const addrByTable = await evaluateRuleSetForTable("addresses", "create", { city: "X" });
assert.ok(addrByTable.errors.includes("zip required"), "validation-only model fires via workflow table path");
console.log("robust plural table resolution: PASS ✅");

// ── decision_table rules now EXECUTE (were accepted + stored but inert) ──────
setRules([
  { id: "dt1", name: "discount-tier", rule_type: "decision_table", model_name: "Order", is_active: true,
    config: { source: "manual", table: {
      id: "t1", name: "discount", hitPolicy: "F",
      inputs:  [{ id: "i1", name: "amount", type: "number", variableBinding: "amount" }],
      outputs: [{ id: "o1", name: "discount", type: "number" }],
      rules: [
        { id: "r1", inputEntries: ["> 1000"], outputEntries: ["0.2"] },
        { id: "r2", inputEntries: ["> 500"],  outputEntries: ["0.1"] },
        { id: "r3", inputEntries: ["-"],       outputEntries: ["0"] },
      ],
    } } },
]);
const dtBig = await evaluateRuleSet("Order", "create", { amount: 5000 });
assert.equal(dtBig.patches.discount, 0.2, "amount>1000 → 0.2 (first match wins)");
const dtMid = await evaluateRuleSet("Order", "create", { amount: 750 });
assert.equal(dtMid.patches.discount, 0.1, "amount>500 → 0.1");
const dtLow = await evaluateRuleSet("Order", "create", { amount: 100 });
assert.equal(dtLow.patches.discount, 0, "else → 0");
// resolves + fires from the workflow TABLE path too
const dtByTable = await evaluateRuleSetForTable("orders", "create", { amount: 5000 });
assert.equal(dtByTable.patches.discount, 0.2, "decision table fires via workflow table path");
console.log("decision_table execution: PASS ✅");
