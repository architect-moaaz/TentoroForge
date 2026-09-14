/**
 * Cross-check the two independent style channels.
 *
 * Tier 1 drove the editor STORE in jsdom and measured which components never
 * apply padding/radius/shadow/background/motion. Tier 2 drove the real Style tab
 * in Chromium. They share no code path beyond the product itself, so agreement
 * between them is genuine corroboration; disagreement is a lead to investigate,
 * not a result to report.
 */
import { readFileSync } from "node:fs";

const t1 = JSON.parse(readFileSync("tests/matrix/tier1-ledger.json", "utf-8"));
const t2 = JSON.parse(readFileSync("tests/e2e/sweep-style.json", "utf-8"));

// Tier 1: components where the four token-wrapped keys were never observed.
const t1Miss = {};
for (const c of t1.filter((c) => c.cell === "style" && c.status === "NOT-OBSERVED")) {
  (t1Miss[c.component] ??= new Set()).add(c.styleKey);
}
const t1Drop = new Set(
  Object.entries(t1Miss)
    .filter(([, keys]) => ["padding", "radius", "shadow", "background"].every((k) => keys.has(k)))
    .map(([n]) => n));

// Tier 2: components whose Style-tab edits produced nothing.
const t2Drop = new Set(
  t2.rows.filter((r) => r.status === "NONE-APPLIED").map((r) => r.component));
const t2Partial = t2.rows.filter((r) => r.status === "PARTIAL");
const t2Blocked = t2.rows.filter((r) => r.status === "HARNESS-BLOCKED").map((r) => r.component);

const both = [...t1Drop].filter((n) => t2Drop.has(n)).sort();
const onlyT1 = [...t1Drop].filter((n) => !t2Drop.has(n)).sort();
const onlyT2 = [...t2Drop].filter((n) => !t1Drop.has(n)).sort();

console.log(`Tier 1 (jsdom, store)   : ${t1Drop.size} components drop all four token-wrapped keys`);
console.log(`Tier 2 (browser, real UI): ${t2Drop.size} components applied NOTHING`);
console.log("");
console.log(`AGREED BY BOTH CHANNELS  : ${both.length}`);
console.log(`   ${both.join(", ") || "(none)"}`);
console.log("");
console.log(`Tier 1 only (needs a look): ${onlyT1.length}`);
console.log(`   ${onlyT1.join(", ") || "(none)"}`);
console.log("");
console.log(`Tier 2 only (needs a look): ${onlyT2.length}`);
console.log(`   ${onlyT2.join(", ") || "(none)"}`);
console.log("");
console.log(`PARTIAL in Tier 2        : ${t2Partial.length}`);
for (const p of t2Partial) console.log(`   ${String(p.component).padEnd(22)} missing: ${p.missing}`);
console.log("");
console.log(`HARNESS-BLOCKED (not scored): ${t2Blocked.length}  ${t2Blocked.join(", ")}`);
const info = t2.rows.find((r) => r.status === "INFO");
if (info) console.log(`\nDesign System trio: ${JSON.stringify(info)}`);
