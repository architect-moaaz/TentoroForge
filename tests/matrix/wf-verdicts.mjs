/** Tally the style-drop classification workflow without dumping transcripts. */
import { readFileSync } from "node:fs";

const JOURNAL = process.argv[2];
const lines = readFileSync(JOURNAL, "utf-8").split("\n").filter(Boolean);

const classify = new Map();   // component -> verdict
const refute = new Map();     // component -> refuted

for (const line of lines) {
  let rec;
  try { rec = JSON.parse(line); } catch { continue; }
  if (rec.type !== "result") continue;
  const v = rec.value ?? rec.result ?? rec.output;
  if (!v || typeof v !== "object") continue;
  if (typeof v.verdict === "string" && v.component) classify.set(v.component, v.verdict);
  if (typeof v.refuted === "boolean" && v.component) refute.set(v.component, v.refuted);
}

const buckets = {};
for (const [c, verdict] of classify) (buckets[verdict] ??= []).push(c);

console.log(`classified: ${classify.size}   refutations run: ${refute.size}\n`);
for (const [k, v] of Object.entries(buckets).sort((a, b) => b[1].length - a[1].length)) {
  console.log(`${k} (${v.length})`);
  console.log(`   ${v.sort().join(", ")}\n`);
}

const realBugs = buckets["REAL-BUG"] ?? [];
const survived = realBugs.filter((c) => refute.get(c) === false);
const killed = realBugs.filter((c) => refute.get(c) === true);
console.log("=".repeat(60));
console.log(`REAL-BUG claimed      : ${realBugs.length}`);
console.log(`  survived refutation : ${survived.length}  -> ${survived.sort().join(", ") || "(none)"}`);
console.log(`  KILLED by refuter   : ${killed.length}  -> ${killed.sort().join(", ") || "(none)"}`);
