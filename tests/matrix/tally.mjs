/** Exact counts: what was tested, what was found, what is outstanding. */
import { readFileSync } from "node:fs";
import { starterRegistry } from "@forge/registry";

const props = JSON.parse(readFileSync("tests/e2e/sweep-props.json", "utf-8"));
const style = JSON.parse(readFileSync("tests/e2e/sweep-style.json", "utf-8"));
const binds = JSON.parse(readFileSync("tests/e2e/sweep-bindings.json", "utf-8"));
const cls = JSON.parse(readFileSync("tests/e2e/classification.json", "utf-8"));
const t1 = JSON.parse(readFileSync("tests/matrix/tier1-ledger.json", "utf-8"));
const tok = JSON.parse(readFileSync("tests/matrix/tier1-tokens.json", "utf-8"));

const all = Object.entries(starterRegistry);
const inScope = all.filter(([, e]) => e.category !== "layout");
const layout = all.filter(([, e]) => e.category === "layout");
const inScopeProps = inScope.reduce((n, [, e]) => n + Object.keys(e.props ?? {}).length, 0);

const p = (s) => props.rows.filter((r) => r.status === s).length;
const sv = (s) => style.rows.filter((r) => r.status === s).length;

console.log("=== SCOPE ===");
console.log(`registry components           : ${all.length}`);
console.log(`in scope (layout excluded)    : ${inScope.length}   (layout skipped: ${layout.length})`);
console.log(`prop descriptors in scope     : ${inScopeProps}`);
console.log("");

console.log("=== TESTED ===");
console.log(`Tier 1 store-level cells      : ${t1.length}  (props+style+bindings, all 133)`);
console.log(`Tier 1 token cells            : ${tok.length}`);
console.log(`Tier 2 prop rows (real UI)    : ${props.rows.filter((r) => r.prop !== "*").length}`);
console.log(`Tier 2 components, props      : ${new Set(props.rows.map((r) => r.component)).size}`);
console.log(`Tier 2 components, style      : ${style.rows.filter((r) => r.component !== "(design-system)").length}`);
console.log(`Tier 2 binding rows scored    : ${binds.rows.filter((r) => r.status !== "NOT-APPLICABLE").length}`);
console.log(`NO-EFFECT props classified    : ${cls.totals.classified}`);
console.log("");

console.log("=== PROP OUTCOMES (Tier 2, real UI) ===");
console.log(`  works (sentinel visible)    : ${p("WORKS-VISIBLE")}`);
console.log(`  works (values differ)       : ${p("WORKS-DIFFERENTIAL")}`);
console.log(`  no effect -> classified     : ${p("NO-EFFECT")}`);
console.log(`      of which CONFIG         : ${cls.totals.config}`);
console.log(`      of which STATE-DEPENDENT: ${cls.totals.stateDependent}`);
console.log(`      of which CONFIRMED BUG  : ${cls.totals.confirmedBugs}`);
console.log(`      of which REFUTED        : ${cls.totals.refuted}`);
console.log(`      of which UNCLEAR        : ${cls.totals.unclear}`);
console.log(`  deferred to bindings pass   : ${p("DEFERRED")}`);
console.log(`  harness-blocked (not scored): ${p("HARNESS-BLOCKED")}`);
console.log("");

console.log("=== STYLE OUTCOMES ===");
console.log(`  all 11 keys applied         : ${sv("ALL-APPLIED")}`);
console.log(`  none applied                : ${sv("NONE-APPLIED")}`);
console.log(`  partial (motion only)       : ${sv("PARTIAL")}`);
console.log(`  harness-blocked             : ${sv("HARNESS-BLOCKED")}`);
console.log("");

console.log("=== OUTSTANDING ===");
console.log(`  layout components unswept   : ${layout.length}  (${layout.map(([n]) => n).slice(0, 6).join(", ")}…)`);
console.log(`  props needing an uncreated state : ${cls.totals.stateDependent}`);
console.log(`  props unclear from description   : ${cls.totals.unclear}`);
console.log(`  harness-blocked props            : ${p("HARNESS-BLOCKED")}`);
console.log(`  harness-blocked style components : ${sv("HARNESS-BLOCKED")}`);
console.log(`  breakpoints (All/sm/md/lg/xl)    : NOT SWEPT — needs the :6503 scaffold`);
console.log(`  action props clicked             : NOT DONE — wired-check only`);
