/**
 * Regression: condition/exclusive_gateway nodes used to silently swallow
 * every FEEL-lite eval error and route the run down the else branch —
 * a typo in the expression looked identical to a legitimate false
 * result. And when neither then nor else edges existed the run ended
 * "completed" mid-graph with no complaint. Now the caller surfaces
 * the eval error, records the reason on the log entry, and fails the
 * run when a required branch is missing.
 *
 * Inlines the tiny pure logic (evaluated → edges + error/edge-missing
 * detection) from engine.ts::handleCondition + its caller so we don't
 * need to link the whole runtime.
 *
 * Run with: tsx or node --experimental-vm-modules
 * Exits 0 on pass, 1 on any failure.
 */

let failed = 0;
function assert(cond: unknown, msg: string) {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.error(`  ✗ ${msg}`); failed++; }
}
function assertThrows(fn: () => unknown, re: RegExp, msg: string) {
  try { fn(); }
  catch (e) {
    const em = e instanceof Error ? e.message : String(e);
    if (re.test(em)) { console.log(`  ✓ ${msg}`); return; }
    console.error(`  ✗ ${msg} — got: ${em}`); failed++; return;
  }
  console.error(`  ✗ ${msg} — no throw`); failed++;
}

// ── inline the pure part of handleCondition ─────────────────────────────
type Edge = { source: string; target: string; data?: { edgeType?: string } };
type Node = { id: string; data?: { label?: string } };
type EvaluateExpr = (expr: string, vars: Record<string, unknown>) => unknown;

interface ConditionResult {
  edges: Edge[];
  expression: string;
  evaluated: unknown;
  evalError?: string;
}

function handleCondition(
  node: Node,
  allEdges: Edge[],
  expression: string,
  vars: Record<string, unknown>,
  evaluate: EvaluateExpr,
): ConditionResult {
  let result: unknown;
  let evalError: string | undefined;
  try {
    result = expression ? evaluate(expression, vars) : true;
  } catch (err) {
    result = false;
    evalError = err instanceof Error ? err.message : String(err);
  }
  const edges = result
    ? allEdges.filter(
        (e) =>
          e.data?.edgeType === "then" ||
          e.data?.edgeType === "default" ||
          !e.data?.edgeType,
      )
    : allEdges.filter((e) => e.data?.edgeType === "else");
  return { edges, expression, evaluated: result, evalError };
}

// Match the caller-side policy in engine.ts's switch case.
function callerHandle(
  node: Node,
  allEdges: Edge[],
  expression: string,
  vars: Record<string, unknown>,
  evaluate: EvaluateExpr,
): { taken: Edge[]; logOutput: unknown } {
  const cond = handleCondition(node, allEdges, expression, vars, evaluate);
  const logOutput = {
    expression: cond.expression,
    evaluated: cond.evaluated,
    branch: cond.evaluated ? "then" : "else",
    takenEdges: cond.edges.map((e) => e.target),
  };
  if (cond.evalError) {
    throw new Error(
      `[condition ${node.data?.label || node.id}] expression eval failed: ${cond.evalError} — expression was: ${cond.expression || "(empty)"}`,
    );
  }
  if (cond.edges.length === 0) {
    throw new Error(
      `[condition ${node.data?.label || node.id}] no ${cond.evaluated ? "then/default" : "else"} edge defined — workflow ends silently mid-graph`,
    );
  }
  return { taken: cond.edges, logOutput };
}

const good: EvaluateExpr = (expr, vars) => {
  // Very tiny stand-in: parse `amount > 100`, `status = 'X'`, or a bare bool.
  if (/^\s*true\s*$/.test(expr)) return true;
  if (/^\s*false\s*$/.test(expr)) return false;
  const m = expr.match(/^\s*(\w+)\s*(>|<|=|!=)\s*'?([^']+?)'?\s*$/);
  if (!m) throw new Error(`unparseable: ${expr}`);
  const [, name, op, raw] = m;
  const lhs = vars[name];
  const rhs = /^-?\d+(?:\.\d+)?$/.test(raw) ? Number(raw) : raw;
  switch (op) {
    case ">": return (lhs as number) > (rhs as number);
    case "<": return (lhs as number) < (rhs as number);
    case "=": return lhs === rhs;
    case "!=": return lhs !== rhs;
  }
  return false;
};

const node: Node = { id: "gate1", data: { label: "check amount" } };

// ── 1. Truthy → then edge; log shows reasoning ─────────────────────────
console.log("truthy result → then edge, log shows evaluated + branch");
{
  const edges: Edge[] = [
    { source: "gate1", target: "approve", data: { edgeType: "then" } },
    { source: "gate1", target: "reject",  data: { edgeType: "else" } },
  ];
  const r = callerHandle(node, edges, "amount > 100", { amount: 500 }, good);
  assert(r.taken.length === 1 && r.taken[0].target === "approve", "took then→approve");
  const log = r.logOutput as any;
  assert(log.evaluated === true, "log shows evaluated=true");
  assert(log.branch === "then", "log shows branch=then");
  assert(Array.isArray(log.takenEdges) && log.takenEdges[0] === "approve",
    "log shows takenEdges targets");
  assert(log.expression === "amount > 100", "log shows expression");
}

// ── 2. Falsy → else edge ───────────────────────────────────────────────
console.log("falsy result → else edge");
{
  const edges: Edge[] = [
    { source: "gate1", target: "approve", data: { edgeType: "then" } },
    { source: "gate1", target: "reject",  data: { edgeType: "else" } },
  ];
  const r = callerHandle(node, edges, "amount > 100", { amount: 50 }, good);
  assert(r.taken.length === 1 && r.taken[0].target === "reject", "took else→reject");
  const log = r.logOutput as any;
  assert(log.evaluated === false && log.branch === "else", "log shows else branch");
}

// ── 3. Eval error → THROW (used to silently route to else) ─────────────
console.log("eval error THROWS with expression + reason (pre-fix: silent false)");
{
  const edges: Edge[] = [
    { source: "gate1", target: "approve", data: { edgeType: "then" } },
    { source: "gate1", target: "reject",  data: { edgeType: "else" } },
  ];
  assertThrows(
    () => callerHandle(node, edges, "unknownVar ~~ 100", {}, good),
    /expression eval failed.*unparseable.*expression was: unknownVar ~~ 100/s,
    "throws with the expression body + the parser's message",
  );
}

// ── 4. Truthy but no then-edge → THROW (pre-fix: run ends silently) ────
console.log("truthy with only else edge → THROW (pre-fix: silent completed)");
{
  const edges: Edge[] = [
    { source: "gate1", target: "reject", data: { edgeType: "else" } },
  ];
  assertThrows(
    () => callerHandle(node, edges, "amount > 100", { amount: 500 }, good),
    /no then\/default edge defined/,
    "throws about missing then/default edge",
  );
}

// ── 5. Falsy but no else-edge → THROW ──────────────────────────────────
console.log("falsy with only then edge → THROW");
{
  const edges: Edge[] = [
    { source: "gate1", target: "approve", data: { edgeType: "then" } },
  ];
  assertThrows(
    () => callerHandle(node, edges, "amount > 100", { amount: 50 }, good),
    /no else edge defined/,
    "throws about missing else edge",
  );
}

// ── 6. Empty expression → treated as true (legacy behavior kept) ───────
console.log("empty expression → treated as true (documented pass-through)");
{
  const edges: Edge[] = [
    { source: "gate1", target: "next", data: { edgeType: "then" } },
  ];
  const r = callerHandle(node, edges, "", {}, good);
  assert((r.logOutput as any).evaluated === true, "empty expr = true");
  assert(r.taken[0].target === "next", "took then→next");
}

// ── 7. Unlabeled edge counts as then/default ───────────────────────────
console.log("unlabeled edge counts as then/default for truthy");
{
  const edges: Edge[] = [{ source: "gate1", target: "next" }]; // no edgeType
  const r = callerHandle(node, edges, "amount > 100", { amount: 500 }, good);
  assert(r.taken.length === 1 && r.taken[0].target === "next", "unlabeled taken");
}

if (failed === 0) { console.log("\nAll condition-log tests passed."); process.exit(0); }
console.error(`\n${failed} test(s) failed.`); process.exit(1);
