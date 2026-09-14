/** Break the Tier-1 ledger into buckets a human can act on. */
import { readFileSync } from "node:fs";

const L = JSON.parse(readFileSync("tests/matrix/tier1-ledger.json", "utf-8"));
const count = (arr, key) => arr.reduce((m, c) => (m[c[key]] = (m[c[key]] ?? 0) + 1, m), {});

console.log("=== HARNESS-BLOCKED (my harness, NOT a product defect) ===");
const hb = L.filter((c) => c.status === "HARNESS-BLOCKED");
const hbSeen = new Set();
for (const c of hb) {
  const k = `${c.component} :: ${String(c.detail).slice(0, 80)}`;
  if (hbSeen.has(k)) continue;
  hbSeen.add(k);
  console.log("  ", k);
}

console.log("\n=== BIND-FAILED ===");
for (const c of L.filter((c) => c.status === "BIND-FAILED")) {
  console.log(`   ${String(c.component).padEnd(22)} prop=${String(c.prop).padEnd(16)} bound=${String(c.bound).slice(0, 46)}`);
}

console.log("\n=== STYLE observability by key ===");
const byKey = {};
for (const c of L.filter((c) => c.cell === "style")) {
  byKey[c.styleKey] ??= { APPLIED: 0, "APPLIED-DESCENDANT": 0, "NOT-OBSERVED": 0, "WRITE-LOST": 0, "HARNESS-BLOCKED": 0 };
  byKey[c.styleKey][c.status] = (byKey[c.styleKey][c.status] ?? 0) + 1;
}
for (const [k, v] of Object.entries(byKey)) {
  console.log(`   ${k.padEnd(11)} applied=${String(v.APPLIED).padStart(3)}  descendant=${String(v["APPLIED-DESCENDANT"]).padStart(3)}  NOT-OBSERVED=${String(v["NOT-OBSERVED"]).padStart(3)}  write-lost=${v["WRITE-LOST"] ?? 0}`);
}

console.log("\n=== components where ALL 11 style keys were NOT-OBSERVED ===");
const byComp = {};
for (const c of L.filter((c) => c.cell === "style")) {
  byComp[c.component] ??= [];
  byComp[c.component].push(c.status);
}
const allMiss = Object.entries(byComp)
  .filter(([, ss]) => ss.length === 11 && ss.every((s) => s === "NOT-OBSERVED"))
  .map(([n]) => n);
console.log(`   ${allMiss.length} components: ${allMiss.join(", ")}`);

console.log("\n=== style writes that never reached the artifact (WRITE-LOST) ===");
const wl = L.filter((c) => c.status === "WRITE-LOST");
console.log(`   ${wl.length}`);
