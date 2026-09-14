/** Which components ignore which style keys — the actionable candidate list. */
import { readFileSync } from "node:fs";
const L = JSON.parse(readFileSync("tests/matrix/tier1-ledger.json", "utf-8"));

const miss = {};
for (const c of L.filter((c) => c.cell === "style" && c.status === "NOT-OBSERVED")) {
  (miss[c.component] ??= []).push(c.styleKey);
}
const rows = Object.entries(miss).sort((a, b) => b[1].length - a[1].length);
console.log(`components with >=1 unobserved style key: ${rows.length}\n`);

const full = rows.filter(([, ks]) => ks.length >= 4);
console.log(`--- ignore ALL FOUR token-wrapped keys (padding/radius/shadow/background) + maybe motion: ${full.length}`);
for (const [n, ks] of full) console.log(`   ${n.padEnd(22)} ${ks.join(",")}`);

const partial = rows.filter(([, ks]) => ks.length < 4);
console.log(`\n--- partial (${partial.length})`);
for (const [n, ks] of partial) console.log(`   ${n.padEnd(22)} ${ks.join(",")}`);

// Cross-check: do these same components still receive the RAW size keys?
console.log("\n--- sanity: do the 'ignoring' components still apply width?");
const widthOk = new Set(
  L.filter((c) => c.cell === "style" && c.styleKey === "width" &&
                  (c.status === "APPLIED" || c.status === "APPLIED-DESCENDANT"))
   .map((c) => c.component));
const both = full.filter(([n]) => widthOk.has(n)).length;
console.log(`   ${both}/${full.length} of them DO apply width — so the wrapper exists and only the inner styling is missing.`);
