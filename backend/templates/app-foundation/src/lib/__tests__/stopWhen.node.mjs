// Standalone Node smoke test for stopWhen's evaluator.
//
// No test-runner setup in app-foundation, and adding vitest to a
// generated app just to run this would inflate every user's node_modules.
// Instead: the evaluator is pure, plain JS, and Node can execute it
// directly after a two-line TS-strip (drop `: type` bits).
//
// Run:  node backend/templates/app-foundation/src/lib/__tests__/stopWhen.node.mjs
//
// Exits with code 0 on success, 1 with the first failing case's details on
// failure. CI can invoke it the same way; a shell hook can wire it in.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const SOURCE = resolve(HERE, "..", "stopWhen.ts");
const raw = readFileSync(SOURCE, "utf8");

// Strip TypeScript's type annotations so plain Node can eval the module.
// Narrow substitutions only — this file is intentionally simple JS with
// three type annotations. Adding more type-heavy code here means updating
// this stripper.
const js = raw
  .replace(/: Record<string, unknown>/g, "")
  .replace(/: string/g, "")
  .replace(/: boolean/g, "")
  .replace(/: unknown/g, "")
  .replace(/ as Record<string, unknown>/g, "")
  .replace(/ as [A-Z][\w<>,\s]*/g, "")
  .replace(/export /g, "");

// eslint-disable-next-line no-new-func
const mod = new Function(`${js}; return { evalStopWhen, resolvePath };`)();
const { evalStopWhen } = mod;

const cases = [
  // strict equality — string
  ["scan.status === 'completed'", { scan: { status: "completed" } }, true],
  ["scan.status === 'completed'", { scan: { status: "processing" } }, false],
  // strict inequality
  ["scan.status !== 'completed'", { scan: { status: "processing" } }, true],
  ["scan.status !== 'completed'", { scan: { status: "completed" } }, false],
  // loose equality
  ["scan.status == 'completed'", { scan: { status: "completed" } }, true],
  ["scan.status == 'completed'", { scan: { status: "failed" } }, false],
  // IN — matches / doesn't match
  ["scan.status IN ('completed','failed')", { scan: { status: "completed" } }, true],
  ["scan.status IN ('completed','failed')", { scan: { status: "failed" } }, true],
  ["scan.status IN ('completed','failed')", { scan: { status: "processing" } }, false],
  // IN — with spaces
  ["scan.status IN ( 'a' , 'b' , 'c' )", { scan: { status: "b" } }, true],
  // IN — double-quoted
  ["scan.status IN (\"done\", \"skip\")", { scan: { status: "done" } }, true],
  // IS NOT NULL — non-null value passes, null/undefined/empty fail
  ["scan.result IS NOT NULL", { scan: { result: "x" } }, true],
  ["scan.result IS NOT NULL", { scan: { result: null } }, false],
  ["scan.result IS NOT NULL", { scan: {} }, false],
  ["scan.result IS NOT NULL", { scan: { result: "" } }, false],
  // IS NULL — the complement
  ["scan.result IS NULL", { scan: { result: null } }, true],
  ["scan.result IS NULL", { scan: {} }, true],
  ["scan.result IS NULL", { scan: { result: "x" } }, false],
  // negation
  ["!scan", {}, true],
  ["!scan", { scan: null }, true],
  ["!scan", { scan: { status: "x" } }, false],
  // deep path
  ["scan.details.matched === 'yes'", { scan: { details: { matched: "yes" } } }, true],
  ["scan.details.matched === 'yes'", { scan: { details: {} } }, false],
  // empty / missing / mistyped ⇒ return false (safer to keep polling)
  ["", { scan: {} }, false],
  ["   ", { scan: {} }, false],
  ["complete gibberish here", { scan: {} }, false],
  // top-level (no dot) path
  ["done === 'yes'", { done: "yes" }, true],
];

let failed = 0;
for (const [expr, data, want] of cases) {
  const got = evalStopWhen(expr, data);
  if (got !== want) {
    failed++;
    console.error(
      `FAIL  expr=${JSON.stringify(expr)}\n      data=${JSON.stringify(data)}\n      want=${want}  got=${got}`
    );
  }
}

if (failed) {
  console.error(`\n${failed}/${cases.length} stopWhen cases failed`);
  process.exit(1);
}
console.log(`OK  ${cases.length} stopWhen cases passed`);
