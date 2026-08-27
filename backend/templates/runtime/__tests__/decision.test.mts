/**
 * Standalone tests for the rule-table evaluator (decision.ts).
 *
 * The decision node was inert before commit 213a787 — its config had
 * no case in the engine's switch, so the workflow walked past without
 * evaluating any rules. These tests lock in the syntax the engine now
 * honors so a regression can't sneak back in.
 *
 * Run (Node 25+ with built-in type stripping):
 *   cd backend/templates/runtime && \
 *   node --experimental-strip-types __tests__/decision.test.mts
 * Exits 0 on pass, 1 on any failure. No package.json, no vitest —
 * matches the standalone-inline pattern established by
 * build-where.test.mts / resolve-aggregate.test.mts.
 */

import {
  evaluateDecision,
  matchesEntry,
  coerceLiteral,
} from "../workflows/decision.ts";

// ── minimal test harness ────────────────────────────────────────────

let passed = 0;
let failed = 0;

function assertEq<T>(actual: T, expected: T, name: string): void {
  const ok =
    actual === expected ||
    JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed++;
    console.log(`  ✓ ${name}`);
  } else {
    failed++;
    console.log(`  ✗ ${name}`);
    console.log(`      expected: ${JSON.stringify(expected)}`);
    console.log(`      actual:   ${JSON.stringify(actual)}`);
  }
}

// ── matchesEntry — the input-entry mini-grammar ─────────────────────

console.log("matchesEntry:");
assertEq(matchesEntry(42, "-"),       true,  'wildcard "-" matches anything');
assertEq(matchesEntry("x", ""),       true,  'empty entry matches anything');
assertEq(matchesEntry("foo", "foo"),  true,  "bare string equality");
assertEq(matchesEntry("foo", '"foo"'), true, "quoted string equality");
assertEq(matchesEntry("foo", "bar"),  false, "string inequality");
assertEq(matchesEntry(90, ">= 90"),   true,  ">= boundary");
assertEq(matchesEntry(89, ">= 90"),   false, ">= below");
assertEq(matchesEntry(10, "< 10"),    false, "< boundary");
assertEq(matchesEntry(9, "< 10"),     true,  "< below");
assertEq(matchesEntry(5, "!= 5"),     false, "!= equal");
assertEq(matchesEntry(6, "!= 5"),     true,  "!= differ");
assertEq(matchesEntry(50, "[10..60]"),true,  "range middle");
assertEq(matchesEntry(10, "[10..60]"),true,  "range low boundary");
assertEq(matchesEntry(60, "[10..60]"),true,  "range high boundary");
assertEq(matchesEntry(9,  "[10..60]"),false, "range below");
assertEq(matchesEntry("hi", ">= 90"), false, "compare on non-number → no match");

// ── coerceLiteral — output-entry text → typed value ─────────────────

console.log("coerceLiteral:");
assertEq(coerceLiteral("42"),        42,      "int");
assertEq(coerceLiteral("3.14"),      3.14,    "float");
assertEq(coerceLiteral("true"),      true,    "bool true");
assertEq(coerceLiteral("false"),     false,   "bool false");
assertEq(coerceLiteral("null"),      null,    "null literal");
assertEq(coerceLiteral('"quoted"'),  "quoted","quoted string");
assertEq(coerceLiteral("bare"),      "bare",  "bare identifier stays string");
assertEq(coerceLiteral(42),          42,      "already a number");

// ── evaluateDecision — the whole rule table ─────────────────────────

console.log("evaluateDecision — first-hit + numeric rules:");
{
  const cfg = {
    decisionTable: {
      inputs: [{ name: "score", variableBinding: "score", type: "number" }],
      outputs: [{ name: "grade", type: "string" }],
      rules: [
        { inputEntries: [">= 90"], outputEntries: ['"A"'] },
        { inputEntries: [">= 70"], outputEntries: ['"B"'] },
        { inputEntries: ["-"],     outputEntries: ['"F"'] },
      ],
      hitPolicy: "first",
    },
  };
  const ctx = { variables: { score: 82 } };
  const res = evaluateDecision(cfg, ctx);
  assertEq(res.fired, 1, "one rule fired");
  assertEq(ctx.variables.grade, "B", "grade B assigned to process var");
}

console.log("evaluateDecision — outputMapping renames output on write:");
{
  const cfg = {
    decisionTable: {
      inputs:  [{ name: "score", variableBinding: "score" }],
      outputs: [{ name: "grade" }],
      rules:   [{ inputEntries: [">= 90"], outputEntries: ['"A"'] }],
      hitPolicy: "first",
    },
    outputMapping: { grade: "letter" },
  };
  const ctx = { variables: { score: 95 } };
  evaluateDecision(cfg, ctx);
  assertEq(ctx.variables.letter, "A", "written under mapped name");
  assertEq(ctx.variables.grade, undefined, "original name NOT written when mapped");
}

console.log("evaluateDecision — hitPolicy=collect accumulates all matches:");
{
  const cfg = {
    decisionTable: {
      inputs: [{ name: "age", variableBinding: "age" }],
      outputs: [{ name: "tag" }],
      rules: [
        { inputEntries: [">= 18"], outputEntries: ['"adult"'] },
        { inputEntries: [">= 65"], outputEntries: ['"senior"'] },
      ],
      hitPolicy: "collect",
    },
  };
  const ctx = { variables: { age: 70 } };
  const res = evaluateDecision(cfg, ctx);
  assertEq(res.fired, 2, "both rules fired");
  assertEq(Array.isArray(res.outputs), true, "collect returns an array of outcomes");
}

console.log("evaluateDecision — no table = skipped, no throw:");
{
  const res = evaluateDecision({}, { variables: {} });
  assertEq(res.skipped, true, "no decisionTable → skipped");
}

console.log("evaluateDecision — falls through to wildcard rule when no numeric match:");
{
  const cfg = {
    decisionTable: {
      inputs:  [{ name: "score", variableBinding: "score" }],
      outputs: [{ name: "grade" }],
      rules: [
        { inputEntries: [">= 90"], outputEntries: ['"A"'] },
        { inputEntries: ["-"],     outputEntries: ['"F"'] },
      ],
      hitPolicy: "first",
    },
  };
  const ctx = { variables: { score: 40 } };
  evaluateDecision(cfg, ctx);
  assertEq(ctx.variables.grade, "F", "wildcard row fired");
}

// ── report ──────────────────────────────────────────────────────────

console.log("");
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
