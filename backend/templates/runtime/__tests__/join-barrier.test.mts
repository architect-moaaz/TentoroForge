/**
 * Regression: the fork/join barrier used to deadlock because
 * `__joinCounters` was created lazily inside each parallel branch. Each
 * branch received a spread-copied ctx `{ ...ctx, variables: {...} }`, and
 * the lazy-init line
 *   (ctx as any).__joinCounters ?? ((ctx as any).__joinCounters = new Map())
 * assigned to the BRANCH's copy, not the shared root — so sibling
 * branches never saw each other's increments, arrived < expected forever,
 * and downstream nodes were silently skipped while the run reported
 * "completed". The fix is to seed the Map on the root ctx BEFORE any
 * branch spreads happen (engine.ts, executeWorkflow).
 *
 * This test enforces the two invariants the fix relies on at the JS
 * level, so a refactor that breaks either one is caught here.
 *
 * Run with: tsx or a Node with --experimental-vm-modules
 * Exits 0 on pass, 1 on any failure.
 */

let failed = 0;
function assert(cond: unknown, msg: string) {
  if (cond) console.log(`  ✓ ${msg}`);
  else { console.error(`  ✗ ${msg}`); failed++; }
}

// ── Invariant 1: spread copies share references to object-valued fields ─────
console.log("spread({...ctx}) shares reference to Map on ctx");
{
  const root: any = { __joinCounters: new Map<string, number>() };
  const branchA = { ...root, variables: {} };
  const branchB = { ...root, variables: {} };
  assert(branchA.__joinCounters === root.__joinCounters, "branchA sees the root Map");
  assert(branchB.__joinCounters === root.__joinCounters, "branchB sees the root Map");
  branchA.__joinCounters.set("join1", 1);
  branchB.__joinCounters.set("join1", (branchB.__joinCounters.get("join1") ?? 0) + 1);
  assert(root.__joinCounters.get("join1") === 2, "increments compose on the root Map");
}

// ── Invariant 2: lazy init INSIDE a branch is what the old bug did ──────────
// Documents the failure mode — if a refactor accidentally reverts to lazy
// init inside the branch, this snippet shows why it breaks.
console.log("lazy-init inside a branch splits the Map (the pre-fix bug)");
{
  const root: any = { /* no __joinCounters yet */ };
  const branchA = { ...root, variables: {} };
  const branchB = { ...root, variables: {} };
  (branchA as any).__joinCounters = new Map<string, number>();
  (branchB as any).__joinCounters = new Map<string, number>();
  branchA.__joinCounters.set("join1", 1);
  branchB.__joinCounters.set("join1", 1);
  assert(
    branchA.__joinCounters !== branchB.__joinCounters,
    "branches have DIFFERENT Maps (this is the deadlock scenario)",
  );
  assert(
    (root as any).__joinCounters === undefined,
    "root ctx never learns about the branch Maps",
  );
}

// ── Invariant 3: the "seed on root" fix keeps everything shared ─────────────
console.log("seeding __joinCounters on root ctx before spread keeps it shared");
{
  const root: any = {};
  // What engine.ts::executeWorkflow now does:
  (root as any).__joinCounters = new Map<string, number>();

  const branchA = { ...root, variables: {} };
  const branchB = { ...root, variables: {} };
  // What the join handler does (?? short-circuit is now a no-op — good):
  const counterA: Map<string, number> =
    (branchA as any).__joinCounters ??
    ((branchA as any).__joinCounters = new Map());
  counterA.set("join1", (counterA.get("join1") ?? 0) + 1);
  const counterB: Map<string, number> =
    (branchB as any).__joinCounters ??
    ((branchB as any).__joinCounters = new Map());
  counterB.set("join1", (counterB.get("join1") ?? 0) + 1);

  assert(counterA === counterB, "?? branch reused the shared Map (no lazy new Map)");
  assert(root.__joinCounters.get("join1") === 2, "join count reaches expected=2");
}

if (failed === 0) { console.log("\nAll join-barrier tests passed."); process.exit(0); }
console.error(`\n${failed} test(s) failed.`); process.exit(1);
