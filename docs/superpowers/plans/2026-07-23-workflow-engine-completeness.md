# Workflow Engine Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the open items surfaced by the 2026-07-23 workflow-subsystem audit — regression-proof the coverage fixes shipped in commit `213a787`, migrate AI nodes off flat-field editors onto contract-driven ones, and give the escalation and join nodes real runtime semantics.

**Framing:** This is Tentoro's workflow engine, not a BPMN or DMN implementation. The decision node evaluates *rule tables* (our syntax, not standards-defined). The escalation node attaches a *policy* (`slaHours`, `escalateTo`) to the preceding human task — not a boundary event. The join node is a single-instance arrival barrier — a Tentoro workflow is a single instance, and that's the shape we want.

**Architecture:** Extend the existing `actionContracts.ts` catalog to cover AI nodes; add a unit-test harness under `backend/templates/runtime/workflows/__tests__/` so the runtime template stops silently drifting from the panel; extend `persistPendingTask` to pick up the escalation-policy scratch that `case "escalation"` already writes to `ctx.variables.__escalationPolicy`; give `case "join"` an in-context arrival counter so it holds until N branches arrive before continuing. Live E2E regenerates a target app and exercises every previously-broken node type.

**Tech Stack:** TypeScript (Vitest for runtime tests), React + Zod for editor changes, existing Drizzle schema for `workflow_tasks`, no new dependencies.

---

## Vocabulary

Terms used throughout this plan (Tentoro's, not standards):

- **Rule table** — the decision node's config: rows of `[input entries] → [output entries]` with a `hitPolicy` of `first` (stop at match) or `collect` (accumulate all matches). Input entries support `-` (wildcard), equality (`"foo"`), numeric comparisons (`> 5`, `>= 5`, `< 5`, `<= 5`, `!= 5`), and numeric ranges (`[a..b]`). Output entries are literals; the runtime coerces `"true"` → `true`, `"42"` → `42`, etc.
- **Escalation policy** — `{slaHours, escalateTo}` recorded on `ctx.variables.__escalationPolicy` by an escalation node, attached to the next human task's row via `workflow_tasks.escalate_to` + `due_at`. A tick loop reassigns overdue tasks.
- **Arrival barrier** — the join node counts inbound edges and holds until every branch has arrived, then walks downstream once. Single-instance by design.
- **Contract** — declared inputs/outputs per action type in `actionContracts.ts`. Every panel field the user authors is a `ParamContract`; every downstream-reachable value is a declared output.

## Task 1: Regression test harness for engine.ts

**Files:**
- Create: `backend/templates/runtime/workflows/__tests__/engine.test.ts`
- Create: `backend/templates/runtime/workflows/__tests__/tsconfig.json`
- Modify: `backend/templates/runtime/package.json` (add `test` script if missing)

- [ ] **Step 1: Write the failing DMN-eval test**

```typescript
// backend/templates/runtime/workflows/__tests__/engine.test.ts
import { describe, it, expect } from "vitest";
import { executeWorkflow } from "../engine";
import type { WorkflowDefinition } from "../types";

describe("handleDecision (rule table)", () => {
  it("evaluates first-hit rule and writes output to renamed process var", async () => {
    const wf: WorkflowDefinition = {
      id: "wf1", name: "t",
      definition: {
        trigger: { type: "manual" },
        nodes: [
          { id: "trigger", type: "trigger", position: {x:0,y:0}, data: { label: "T", nodeType: "trigger", config: {} } },
          { id: "d1", type: "decision", position: {x:0,y:0}, data: { label: "D", nodeType: "decision", config: {
            decisionTable: {
              inputs: [{ id:"i1", name: "score", variableBinding: "score", type: "number" }],
              outputs: [{ id:"o1", name: "grade", type: "string" }],
              rules: [
                { id:"r1", inputEntries: [">= 90"], outputEntries: ['"A"'] },
                { id:"r2", inputEntries: [">= 70"], outputEntries: ['"B"'] },
                { id:"r3", inputEntries: ["-"],     outputEntries: ['"F"'] },
              ],
              hitPolicy: "first",
            },
            outputMapping: { grade: "letter" },
          }}},
        ],
        edges: [{ id: "e1", source: "trigger", target: "d1" }],
        steps: [],
      },
    };
    const result = await executeWorkflow(wf, { score: 82 });
    expect(result.status).toBe("completed");
    expect(result.output?.letter).toBe("B");
  });
});
```

- [ ] **Step 2: Run test to verify it fails (no vitest yet)**

Run: `cd backend/templates/runtime && npx vitest run workflows/__tests__/engine.test.ts`
Expected: FAIL — "vitest not found" or "Cannot resolve @/db from index.ts".

- [ ] **Step 3: Add a minimal vitest.config.ts + tsconfig scoped to __tests__**

```typescript
// backend/templates/runtime/vitest.config.ts
import { defineConfig } from "vitest/config";
export default defineConfig({
  test: {
    include: ["workflows/__tests__/**/*.test.ts"],
    environment: "node",
  },
  resolve: {
    // Stub the generated-app-only imports so engine.ts compiles.
    // We only exercise the pure code paths (executeNode switch, DMN,
    // FEEL-lite) — no db handlers needed for these tests.
    alias: {
      "@/db": new URL("./__tests__/stubs/db.ts", import.meta.url).pathname,
      "@/db/schema": new URL("./__tests__/stubs/schema.ts", import.meta.url).pathname,
      "@/lib/error_reporter": new URL("./__tests__/stubs/error_reporter.ts", import.meta.url).pathname,
    },
  },
});
```

```typescript
// backend/templates/runtime/__tests__/stubs/db.ts
export const db = { execute: async () => ({ rows: [] }), insert: () => ({ values: () => ({ returning: async () => [] }) }) };
```

Add matching stubs for `schema` and `error_reporter`.

- [ ] **Step 4: Add package + run**

```bash
cd backend/templates/runtime && npm i -D vitest @types/node typescript
npx vitest run workflows/__tests__/engine.test.ts
```
Expected: DMN test PASSES.

- [ ] **Step 5: Add the assignment-pause + set_variable + transform tests**

```typescript
it("assignment node pauses with taskCreated + assigneeRole", async () => {
  const wf = { /* trigger → assignment(role=recruiter) */ } as WorkflowDefinition;
  const r = await executeWorkflow(wf, {});
  expect(r.status).toBe("paused");
  expect((r as any).pendingTask?.taskType).toBe("assignment");
  expect((r as any).pendingTask?.assigneeRole).toBe("recruiter");
});

it("set_variable evaluates config.expression via feel-lite", async () => {
  const wf = { /* trigger → set_variable(name=doubled, expression=x * 2) with x=21 */ } as WorkflowDefinition;
  const r = await executeWorkflow(wf, { x: 21 });
  expect(r.output?.doubled).toBe(42);
});

it("transform accepts config.expression (panel) not just config.transformExpression", async () => {
  const wf = { /* trigger → transform(expression=x + 1) → set_variable(y=result) */ } as WorkflowDefinition;
  const r = await executeWorkflow(wf, { x: 10 });
  expect(r.output?.result).toBe(11);
});
```

Run: `npx vitest run` — all four pass.

- [ ] **Step 6: Commit**

```bash
git add backend/templates/runtime/workflows/__tests__/ backend/templates/runtime/vitest.config.ts backend/templates/runtime/package.json backend/templates/runtime/package-lock.json
git commit -m "test(workflow-engine): regression tests for DMN + assignment pause + set_variable/transform drift fixes"
```

---

## Task 2: Migrate AI node panels to contract-driven ActionProps

**Files:**
- Modify: `frontend/src/components/workflow/NodePropertiesPanel.tsx` (remove AI*Props branches, route AI nodes to `ActionProps`)
- Modify: `frontend/src/components/workflow/actionContracts.ts` (verify AI contracts already declared — they are, from NC-1)
- Delete (or leave, unused): `AIClassifyProps`, `AIExtractProps`, `AIDecideProps`, `AIGenerateProps` — keep the code for one release, gate on a fallback

- [ ] **Step 1: Write the failing test for `ai_generate` panel**

```tsx
// frontend/src/components/workflow/__tests__/NodePropertiesPanel.ai.test.tsx
import { render, screen } from "@testing-library/react";
import { NodePropertiesPanel } from "../NodePropertiesPanel";

it("ai_generate renders the contract Inputs section, not the flat aiTone/aiMaxLength fields", () => {
  render(
    <NodePropertiesPanel
      nodeData={{ label: "Gen", nodeType: "ai_generate", config: { actionType: "ai_generate" } }}
      nodeId="n1"
      allNodes={[]}
      appModel={null}
      onUpdate={() => {}}
      onClose={() => {}}
    />
  );
  // New contract UI shows an "Inputs" label with required rows
  expect(screen.getByText(/Inputs/i)).toBeInTheDocument();
  // Old flat "Tone" label should be gone
  expect(screen.queryByText(/^Tone$/)).toBeNull();
});
```

Run: `cd frontend && npx vitest run src/components/workflow/__tests__/NodePropertiesPanel.ai.test.tsx`
Expected: FAIL — `Tone` label still renders because the panel still routes `ai_generate` to `AIGenerateProps`.

- [ ] **Step 2: Route AI node types through ActionProps**

In `NodePropertiesPanel.tsx`, replace the four AI branches with a single line that folds them into the `action` branch:

```tsx
{(nodeType === "action" ||
  nodeType === "ai_generate" ||
  nodeType === "ai_classify" ||
  nodeType === "ai_extract" ||
  nodeType === "ai_decide") && (
  <ActionProps
    config={{ ...config, actionType: config.actionType || nodeType }}
    appModel={appModel}
    variables={workflowVariables}
    nodeId={nodeId}
    onUpdate={updateConfig}
  />
)}
```

Delete the four AI*Props renderer branches from the type switch above. Keep the AI*Props functions defined for one release so a rollback is a one-line switch flip.

- [ ] **Step 3: Run test to verify it passes**

Run: `npx vitest run src/components/workflow/__tests__/NodePropertiesPanel.ai.test.tsx`
Expected: PASS.

- [ ] **Step 4: Verify AI contracts declare the inputs the runtime uses**

Read `actionContracts.ts` and confirm each of `ai_generate`, `ai_classify`, `ai_extract`, `ai_decide` declares every field the handler in `ai.ts` reads (from earlier audit: `aiInput`, `aiSystemPrompt`, `aiPrompt`, `aiMaxTokens`, `aiTemperature`, `aiModel`, `aiLabels`, `aiConfidenceThreshold`, `aiFileRef`, `aiExtractFields`, `aiContext`, `aiOptions`, `aiRules`). Already declared per NC-1 spec — no edits expected. If any missing, add.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workflow/NodePropertiesPanel.tsx frontend/src/components/workflow/__tests__/NodePropertiesPanel.ai.test.tsx
git commit -m "refactor(workflow-editor): AI nodes use contract-driven ActionProps (drop flat-field drift)"
```

---

## Task 3: Escalation policy pickup — thread onto persistPendingTask

**Files:**
- Modify: `backend/templates/runtime/workflows/index.ts` (`persistPendingTask` reads `__escalationPolicy` from process variables and writes to `workflow_tasks.due_at` + a new `escalate_to` column)
- Modify: `backend/templates/runtime/db/workflow-tasks.schema.ts` (add `escalate_to text` column)
- Modify: `backend/templates/runtime/workflows/escalation.ts` (extend `processEscalations` to also scan `workflow_tasks` for expired `due_at` and route to `escalate_to`)

- [ ] **Step 1: Write the failing test**

```typescript
// backend/templates/runtime/workflows/__tests__/escalation.test.ts
it("workflow with escalation node writes escalate_to on the pending task", async () => {
  // Build wf: trigger → escalation(slaHours=1, escalateTo=admin) → user_task(role=recruiter)
  const wf = /* ... */;
  const result = await executeWorkflow(wf, {});
  expect(result.status).toBe("paused");
  // Simulate persistPendingTask being called; read back the row
  await persistPendingTask(result, "wf-esc", {});
  const rows = await db.execute(`SELECT escalate_to, due_at FROM workflow_tasks WHERE workflow_id='wf-esc'`);
  expect(rows[0].escalate_to).toBe("admin");
  expect(rows[0].due_at).not.toBeNull();
});
```

Run: FAIL — no such column.

- [ ] **Step 2: Add `escalate_to` column to schema**

```typescript
// backend/templates/runtime/db/workflow-tasks.schema.ts
export const forgeWorkflowTasks = pgTable("workflow_tasks", {
  // ... existing columns ...
  escalateTo: text("escalate_to"),
});
```

- [ ] **Step 3: Read `__escalationPolicy` in persistPendingTask**

```typescript
export async function persistPendingTask(...) {
  const policy = (result.output as any)?.__escalationPolicy ??
                 (result as any).pendingTask?.escalationPolicy;
  const escalateTo = policy?.escalateTo || null;
  const slaHours = policy?.slaHours;
  const dueAt = slaHours ? new Date(Date.now() + slaHours * 3600_000).toISOString() : null;
  await db.execute(sql`
    INSERT INTO workflow_tasks (..., escalate_to, due_at)
    VALUES (..., ${escalateTo}, ${dueAt})
  `);
}
```

- [ ] **Step 4: Threading — engine writes __escalationPolicy through to pendingTask.escalationPolicy**

In `engine.ts` `executeWorkflow` return, when packaging `pendingTask`, add:

```typescript
pendingTask: isPaused ? {
  // ... existing fields ...
  escalationPolicy: ctx.variables.__escalationPolicy,
} : undefined,
```

- [ ] **Step 5: Extend processEscalations to route expired tasks**

In `escalation.ts`, add a scan branch:

```typescript
const overdue = await db.execute(sql`
  SELECT id, escalate_to FROM workflow_tasks
  WHERE status='pending' AND due_at IS NOT NULL AND due_at < NOW() AND escalate_to IS NOT NULL
`);
for (const t of (overdue.rows ?? overdue)) {
  await db.execute(sql`UPDATE workflow_tasks SET assignee_role=${t.escalate_to} WHERE id=${t.id}`);
  // Also emit an in-app notification via send_notification handler.
}
```

- [ ] **Step 6: Run tests**

Run: `npx vitest run`
Expected: escalation test PASSES; existing tests still green.

- [ ] **Step 7: Commit**

```bash
git commit -m "feat(workflow-engine): escalation node policy carries to workflow_tasks + processEscalations reroutes on overdue"
```

---

## Task 4: Join as arrival barrier

**Files:**
- Modify: `backend/templates/runtime/workflows/engine.ts` (`case "join"` counts inbound edges and holds until all arrive)

- [ ] **Step 1: Write the failing test**

```typescript
it("join waits for all inbound branches before continuing", async () => {
  // Build wf:
  //   trigger → fork
  //   fork → A (set_variable a=1)
  //   fork → B (set_variable b=2)
  //   A → join
  //   B → join
  //   join → set_variable(sum = a + b)
  const r = await executeWorkflow(wf, {});
  expect(r.output?.sum).toBe(3);  // only true if join waited
});
```

Currently fails because `join` runs the downstream node twice (once per arriving branch), and each downstream run only sees whichever branch's variables merged first.

- [ ] **Step 2: Implement arrival counter**

```typescript
case "join": {
  const inbound = workflow.definition.edges.filter((e) => e.target === node.id);
  const expected = inbound.length;
  const arrivedKey = `__join_${node.id}_arrived`;
  const arrived = (ctx.variables[arrivedKey] as number | undefined) ?? 0;
  ctx.variables[arrivedKey] = arrived + 1;
  if (arrived + 1 < expected) {
    // Not all branches here yet — stop walking; the next branch's
    // arrival will re-enter this node.
    logEntry.output = { joined: false, arrived: arrived + 1, expected };
    nextEdges = [];
  } else {
    logEntry.output = { joined: true, arrived: expected, expected };
    nextEdges = workflow.definition.edges.filter((e) => e.source === node.id);
  }
  break;
}
```

- [ ] **Step 3: Run test**

Run: PASS — `sum: 3` observed.

- [ ] **Step 4: Regression test — parallel_gateway with join**

Add a second test using `parallel_gateway` in place of `fork`. Both should behave identically.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat(workflow-engine): join node holds until every inbound branch arrives (real barrier)"
```

---

## Task 5: Live E2E — regenerate an app and exercise every fixed node type

**Files:**
- Create: `docs/superpowers/e2e/2026-07-23-workflow-coverage.md` (checklist for manual verification)

- [ ] **Step 1: Regenerate a target app**

Trigger a fresh generation via the platform's `/api/generate` (or reuse an existing project's re-emit route). Wait for status = ready.

- [ ] **Step 2: Author a test workflow through the editor**

Build one workflow containing every previously-broken node type:

```
trigger(manual)
  → set_variable(name="score", expression="42")        # DRIFT-fix
  → decision(scoreBand: <60=fail, else=pass)           # BLOCKER-fix
  → assignment(role="reviewer")                        # BLOCKER-fix
  → transform(expression="score + 1")                  # DRIFT-fix
  → escalation(slaHours=1, escalateTo="admin")         # BLOCKER-fix
  → user_task(role="approver")                         # BROKEN-UX fix
  → end
```

- [ ] **Step 3: Trigger + observe**

Dispatch the workflow via its launcher. Verify:
- Decision node writes `scoreBand="pass"` to process variables (visible in NodeHistoryTab).
- Assignment node creates a `workflow_tasks` row with `assignee_role="reviewer"`.
- Transform node's output flows into subsequent steps.
- Escalation writes `escalate_to="admin"` on the user_task row.
- user_task pauses; completing it resumes and hits `end`.

- [ ] **Step 4: Record findings + link screenshots in the E2E doc**

Populate `docs/superpowers/e2e/2026-07-23-workflow-coverage.md` with pass/fail per node, DB row shots for `workflow_tasks`, and Properties-panel History screenshots.

- [ ] **Step 5: Commit findings**

```bash
git add docs/superpowers/e2e/2026-07-23-workflow-coverage.md
git commit -m "docs(workflow): E2E coverage report for engine completeness fixes"
```

---

## Task 6: Guard against future drift — panel↔runtime sanity check

**Files:**
- Create: `backend/services/tests/test_workflow_contract_coverage.py`

- [ ] **Step 1: Write the failing coverage test**

```python
# backend/services/tests/test_workflow_contract_coverage.py
import json, re, pathlib

def test_every_actiontype_in_palette_has_a_contract():
    types_ts = pathlib.Path("frontend/src/types/workflow.ts").read_text()
    contracts_ts = pathlib.Path("frontend/src/components/workflow/actionContracts.ts").read_text()
    palette = set(re.findall(r'actionType:\s*"([^"]+)"', types_ts))
    contracts = set(re.findall(r'^\s*(\w+):\s*\{', contracts_ts, flags=re.M))
    missing = palette - contracts
    assert not missing, f"palette actionTypes without a contract: {missing}"

def test_engine_switch_covers_every_palette_nodetype():
    types_ts = pathlib.Path("frontend/src/types/workflow.ts").read_text()
    engine_ts = pathlib.Path("backend/templates/runtime/workflows/engine.ts").read_text()
    palette_types = set(re.findall(r'type:\s*"([^"]+)"', types_ts))
    engine_cases = set(re.findall(r'case\s+"(\w+)":', engine_ts))
    missing = palette_types - engine_cases - {"end_event"}  # end_event handled by end
    assert not missing, f"palette node types with no engine case: {missing}"
```

- [ ] **Step 2: Run — should PASS post-fixes**

Run: `/usr/local/bin/python3 -m pytest backend/services/tests/test_workflow_contract_coverage.py -v`

If it fails, that means a new palette entry was added without a matching contract/engine case — the intended future-proofing.

- [ ] **Step 3: Commit**

```bash
git commit -m "test(workflow): CI guard so palette additions can't ship without engine + contract coverage"
```

---

## Out of scope (deferred)

Real new features, not BPMN-purity hedges:

- **Sub-workflow calls** — invoke another workflow by id with mapped inputs/outputs. Needs a `sub_workflow` node type + a nested execution context.
- **Loop nodes** — map over an array with per-iteration inputs. Needs iteration state on the context and a way to fan out results.
- **Rollback handlers** — on failure, undo prior steps. Needs a compensating-action registry per handler.
- **Escalation as a policy on a user_task node** — instead of (or in addition to) a standalone escalation node, expose `slaHours` + `escalateTo` directly on `user_task` / `approval` / `assignment` in the panel. Task 3 already writes to `workflow_tasks.escalate_to`; this is just a UI shortcut.
- **AI node History tab wiring** — NC-5 shipped for `action` nodes only; extend the `nodeType === "action"` gate to also fire for `ai_*` nodes in a follow-up (trivial — the Task 2 refactor makes the AI nodes execute through the same `handleAction` path already).
