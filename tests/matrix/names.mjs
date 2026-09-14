/**
 * The sweep order: every component, grouped by category, input first and
 * navigation last (as requested). Nothing is dropped — the counts are asserted
 * so a component cannot silently fall out of the run.
 */
import { starterRegistry } from "@forge/registry";
import { writeFileSync } from "node:fs";

// `layout` is deliberately out of scope for this pass (user's call), so it is
// EXCLUDED here rather than silently filtered later — the run prints what it
// skipped so "133" never quietly becomes "113" without a reason.
const ORDER = ["input", "display", "data", "feedback", "navigation"];
const SKIPPED = ["layout"];

const byCat = {};
for (const [name, e] of Object.entries(starterRegistry)) {
  (byCat[e.category] ??= []).push(name);
}

const known = [...ORDER, ...SKIPPED];
const unknown = Object.keys(byCat).filter((c) => !known.includes(c));
if (unknown.length) throw new Error(`category in neither ORDER nor SKIPPED: ${unknown.join(", ")}`);

const names = [];
for (const cat of ORDER) {
  const list = (byCat[cat] ?? []).sort();
  console.log(`${cat.padEnd(11)} ${String(list.length).padStart(3)}`);
  names.push(...list);
}

const total = Object.keys(starterRegistry).length;
const skippedCount = SKIPPED.reduce((n, c) => n + (byCat[c]?.length ?? 0), 0);
for (const c of SKIPPED) console.log(`${(c + " (skipped)").padEnd(11)} ${String(byCat[c]?.length ?? 0).padStart(3)}`);
if (names.length + skippedCount !== total) {
  throw new Error(`ordered ${names.length} + skipped ${skippedCount} != registry ${total}`);
}

writeFileSync("tests/e2e/.auth/components.json", JSON.stringify(names), "utf-8");
console.log(`${"TOTAL".padEnd(11)} ${String(names.length).padStart(3)}  -> tests/e2e/.auth/components.json`);
console.log(`first: ${names[0]}   last: ${names[names.length - 1]}`);
