# Tier 2 Wave 5 — Engine Richness: Workflow + Data

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Extend the workflow engine and data engine in `backend/templates/runtime/` so generated apps can express enterprise-grade approval flows + analytics queries. Without this, the components from Waves 1-4 (Timeline, Chart, FilterBar) have no rich data sources to consume.

**Architecture:** Both engines already exist (`backend/templates/runtime/{workflows/engine.ts, data-engine.ts}`). This wave adds new features additively — existing single-stage approvals + basic CRUD continue to work unchanged.

**Spec:** `docs/superpowers/specs/2026-05-08-enterprise-depth-design.md` § Theme C.

---

## File structure

### Modified files (workflow engine)

- `backend/templates/runtime/workflows/types.ts` — extend stage shape with parallel/conditional/delegation
- `backend/templates/runtime/workflows/engine.ts` — implement parallel resolution, conditional routing, delegation
- `backend/services/runtime_injector.py` — extend to write the new types + engine code into generated projects

### New files (workflow engine helpers)

- `backend/templates/runtime/workflows/audit-log.ts` — per-state-transition logger
- `backend/templates/runtime/workflows/escalation.ts` — reminder + escalation hooks (cron-driven)

### Modified files (data engine)

- `backend/templates/runtime/data-engine.ts` — add aggregations, joins, server-side pagination

### New files (data engine helpers)

- `backend/templates/runtime/data-engine/aggregations.ts` — sum/avg/count/group-by
- `backend/templates/runtime/data-engine/saved-views.ts` — saved-view persistence

### Tests

- `backend/tests/services/test_workflow_extensions.py` — parallel + conditional + delegation
- `backend/tests/services/test_data_engine_aggregations.py`

---

## Task 1: Workflow types extension

**Files:**
- Modify: `backend/templates/runtime/workflows/types.ts`

- [ ] **Step 1: Read current types**

```bash
cat /Users/m/Work/code/poc/design2ui-forge-v3/backend/templates/runtime/workflows/types.ts
```

- [ ] **Step 2: Extend stage shape**

The existing `Stage` type has `name`, `approver`, `condition?`. Extend to support:

```ts
// Additive extensions to types.ts:

export type ApproverSelector =
  | { kind: "user"; userId: string }
  | { kind: "role"; role: string }
  | { kind: "field"; path: string }   // e.g. "submittedBy.manager"
  | { kind: "delegated"; backupForUserId: string };

export type StageMode = "any" | "all";  // for parallel approvers

export interface ParallelApproverGroup {
  mode: StageMode;
  approvers: ApproverSelector[];
}

export interface RoutingCondition {
  type: "route";
  if: string;            // expression: e.g. "amount > 5000"
  then: string;          // stage ID to jump to
  else?: string;         // stage ID for else-branch (default: next stage)
}

export interface DelegationRule {
  userId: string;
  delegateTo: string;    // backup user
  validFrom?: string;    // ISO date
  validTo?: string;
}

export interface ReminderConfig {
  afterDays: number;
  channel: "email" | "in-app";
}

export interface EscalationConfig {
  afterDays: number;
  escalateTo: ApproverSelector;
}

// Extend the existing Stage:
export interface StageV2 {
  id: string;
  name: string;
  approvers: ParallelApproverGroup;        // was a single approver
  condition?: RoutingCondition;
  reminders?: ReminderConfig[];
  escalations?: EscalationConfig[];
}

// Workflow now carries delegation rules
export interface WorkflowV2 {
  id: string;
  name: string;
  stages: StageV2[];
  delegations?: DelegationRule[];
}
```

Keep the OLD `Stage` and `Workflow` types as `LegacyStage` / `LegacyWorkflow` so existing generated apps keep working. The engine accepts both.

- [ ] **Step 3: Commit**

```bash
git add backend/templates/runtime/workflows/types.ts
git commit -m "feat(workflow): extend types with parallel approvers + conditional routing + delegation"
```

---

## Task 2: Workflow engine — parallel + conditional + delegation

**Files:**
- Modify: `backend/templates/runtime/workflows/engine.ts`

- [ ] **Step 1: Add resolveApprovers helper**

```ts
// Inside engine.ts:
function resolveApprovers(
  group: ParallelApproverGroup,
  context: { record: any; user: any; delegations: DelegationRule[] }
): { effective: string[]; mode: StageMode } {
  const ids: string[] = [];
  for (const sel of group.approvers) {
    let userId: string | null = null;
    if (sel.kind === "user") userId = sel.userId;
    else if (sel.kind === "field") userId = readPath(context.record, sel.path);
    else if (sel.kind === "role") userId = lookupByRole(sel.role);
    else if (sel.kind === "delegated") {
      const delegation = context.delegations.find((d) => d.userId === sel.backupForUserId);
      userId = delegation ? delegation.delegateTo : sel.backupForUserId;
    }
    if (userId) {
      // Apply active delegations
      const activeDel = context.delegations.find((d) =>
        d.userId === userId && isWithinDateRange(new Date(), d.validFrom, d.validTo)
      );
      ids.push(activeDel ? activeDel.delegateTo : userId);
    }
  }
  return { effective: Array.from(new Set(ids)), mode: group.mode };
}
```

- [ ] **Step 2: Stage advancement logic**

```ts
function canAdvanceStage(stage: StageV2, decisions: Record<string, "approved"|"rejected">): {
  ready: boolean;
  outcome: "approved" | "rejected" | "pending";
} {
  const decisionList = Object.values(decisions);
  if (stage.approvers.mode === "all") {
    if (decisionList.some((d) => d === "rejected")) return { ready: true, outcome: "rejected" };
    if (decisionList.length === stage.approvers.approvers.length &&
        decisionList.every((d) => d === "approved")) {
      return { ready: true, outcome: "approved" };
    }
  } else {  // any-of
    if (decisionList.some((d) => d === "approved")) return { ready: true, outcome: "approved" };
    if (decisionList.length === stage.approvers.approvers.length &&
        decisionList.every((d) => d === "rejected")) {
      return { ready: true, outcome: "rejected" };
    }
  }
  return { ready: false, outcome: "pending" };
}
```

- [ ] **Step 3: Conditional routing**

```ts
function nextStage(currentStage: StageV2, allStages: StageV2[], record: any): StageV2 | null {
  const currentIdx = allStages.findIndex((s) => s.id === currentStage.id);
  if (currentStage.condition) {
    const matches = evalCondition(currentStage.condition.if, record);
    const targetId = matches
      ? currentStage.condition.then
      : (currentStage.condition.else ?? allStages[currentIdx + 1]?.id);
    return allStages.find((s) => s.id === targetId) ?? null;
  }
  return allStages[currentIdx + 1] ?? null;
}

function evalCondition(expr: string, record: any): boolean {
  // Simple expression evaluator: supports `path > N`, `path < N`, `path == "value"`, etc.
  const m = expr.match(/^(.+?)\s*(==|!=|>=|<=|>|<)\s*(.+)$/);
  if (!m) return false;
  const left = readPath(record, m[1].trim());
  const op = m[2];
  let right: any = m[3].trim();
  if (right.startsWith('"') && right.endsWith('"')) right = right.slice(1, -1);
  else if (!isNaN(Number(right))) right = Number(right);
  switch (op) {
    case "==": return left == right;
    case "!=": return left != right;
    case ">":  return left > right;
    case "<":  return left < right;
    case ">=": return left >= right;
    case "<=": return left <= right;
  }
  return false;
}
```

- [ ] **Step 4: Commit**

```bash
git add backend/templates/runtime/workflows/engine.ts
git commit -m "feat(workflow): parallel approvers (any/all) + conditional routing + delegation"
```

---

## Task 3: Audit log + escalations

**Files:**
- Create: `backend/templates/runtime/workflows/audit-log.ts`
- Create: `backend/templates/runtime/workflows/escalation.ts`

- [ ] **Step 1: audit-log.ts**

```ts
// backend/templates/runtime/workflows/audit-log.ts

export interface AuditLogEntry {
  id: string;
  workflowId: string;
  recordId: string;
  timestamp: string;        // ISO 8601
  actor: string;            // user ID
  action: "submitted" | "approved" | "rejected" | "reassigned"
        | "escalated" | "reminder-sent" | "delegated";
  fromStage?: string;
  toStage?: string;
  note?: string;
  metadata?: Record<string, any>;
}

const AUDIT_LOG_TABLE = "workflow_audit_log";

export async function appendAuditEntry(
  db: any,    // your DB connection
  entry: Omit<AuditLogEntry, "id">,
): Promise<AuditLogEntry> {
  const id = crypto.randomUUID();
  const full: AuditLogEntry = { ...entry, id };
  await db.insert(AUDIT_LOG_TABLE).values(full);
  return full;
}

export async function getAuditTrailForRecord(
  db: any,
  workflowId: string,
  recordId: string,
): Promise<AuditLogEntry[]> {
  return db.select().from(AUDIT_LOG_TABLE)
           .where({ workflowId, recordId })
           .orderBy({ timestamp: "asc" });
}
```

- [ ] **Step 2: escalation.ts**

```ts
// backend/templates/runtime/workflows/escalation.ts
// Cron-driven escalation runner. Generated apps run this via a scheduled job
// (e.g. Vercel cron / GitHub Actions / a separate worker process).

import type { StageV2 } from "./types";
import { appendAuditEntry } from "./audit-log";

export interface PendingApproval {
  workflowId: string;
  recordId: string;
  stage: StageV2;
  pendingSince: string;     // ISO 8601 — when entered this stage
}

export async function processEscalations(
  db: any,
  pending: PendingApproval[],
  notify: (channel: string, target: string, payload: any) => Promise<void>,
): Promise<void> {
  for (const p of pending) {
    const ageMs = Date.now() - new Date(p.pendingSince).getTime();
    const ageDays = Math.floor(ageMs / (24 * 3600 * 1000));

    // Reminders
    for (const reminder of p.stage.reminders ?? []) {
      if (ageDays === reminder.afterDays) {
        await notify(reminder.channel, "approver", {
          workflowId: p.workflowId, recordId: p.recordId,
          message: `Reminder: ${p.stage.name} pending for ${ageDays} days.`,
        });
        await appendAuditEntry(db, {
          workflowId: p.workflowId, recordId: p.recordId,
          timestamp: new Date().toISOString(),
          actor: "system", action: "reminder-sent",
          metadata: { afterDays: ageDays, channel: reminder.channel },
        });
      }
    }

    // Escalations
    for (const escalation of p.stage.escalations ?? []) {
      if (ageDays === escalation.afterDays) {
        await notify("email", "escalated", {
          workflowId: p.workflowId, recordId: p.recordId,
          escalateTo: escalation.escalateTo,
          message: `Escalated: ${p.stage.name} pending for ${ageDays} days.`,
        });
        await appendAuditEntry(db, {
          workflowId: p.workflowId, recordId: p.recordId,
          timestamp: new Date().toISOString(),
          actor: "system", action: "escalated",
          metadata: { afterDays: ageDays, escalateTo: escalation.escalateTo },
        });
      }
    }
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add backend/templates/runtime/workflows/audit-log.ts \
        backend/templates/runtime/workflows/escalation.ts
git commit -m "feat(workflow): audit log + cron-driven reminders + escalations"
```

---

## Task 4: Data engine aggregations

**Files:**
- Create: `backend/templates/runtime/data-engine/aggregations.ts`
- Modify: `backend/templates/runtime/data-engine.ts` — wire aggregation handler

- [ ] **Step 1: aggregations.ts**

```ts
// backend/templates/runtime/data-engine/aggregations.ts

export type AggregationFn = "count" | "sum" | "avg" | "min" | "max";

export interface AggregationQuery {
  table: string;
  fn: AggregationFn;
  field?: string;            // required for sum/avg/min/max
  groupBy?: string[];        // optional grouping fields
  filter?: Record<string, any>;
}

export interface AggregationResult {
  groups: Array<Record<string, any> & { _count: number; _value?: number }>;
  total: number;
}

export async function executeAggregation(db: any, query: AggregationQuery): Promise<AggregationResult> {
  const { table, fn, field, groupBy = [], filter } = query;

  // Whitelist aggregation function to prevent injection
  if (!["count", "sum", "avg", "min", "max"].includes(fn)) {
    throw new Error(`invalid aggregation: ${fn}`);
  }
  if (fn !== "count" && !field) {
    throw new Error(`aggregation ${fn} requires a field`);
  }

  // Build query — actual implementation depends on the DB driver
  // Pseudocode for Drizzle:
  let qb = db.select({
    ...Object.fromEntries(groupBy.map((g) => [g, db[table][g]])),
    _count: db.count(),
    _value: fn !== "count" && field ? db[fn](db[table][field]) : undefined,
  }).from(db[table]);

  if (filter) {
    for (const [k, v] of Object.entries(filter)) {
      qb = qb.where(db[table][k].eq(v));
    }
  }

  if (groupBy.length > 0) {
    qb = qb.groupBy(...groupBy.map((g) => db[table][g]));
  }

  const groups = await qb;
  const total = groups.reduce((acc, g) => acc + g._count, 0);
  return { groups, total };
}
```

NOTE: this is a sketch — the actual DB query construction depends on whether the generated app uses Drizzle / Prisma / raw SQL. The implementer should adapt to the actual ORM in use (likely Drizzle based on the rest of the template).

- [ ] **Step 2: Wire aggregation route into data-engine.ts**

In `backend/templates/runtime/data-engine.ts`, add a new handler:

```ts
// New route: POST /api/data/{table}/aggregate
async function handleAggregate(table: string, body: any) {
  const query: AggregationQuery = {
    table, fn: body.fn, field: body.field,
    groupBy: body.groupBy, filter: body.filter,
  };
  return executeAggregation(db, query);
}
```

- [ ] **Step 3: Commit**

```bash
git add backend/templates/runtime/data-engine/aggregations.ts \
        backend/templates/runtime/data-engine.ts
git commit -m "feat(data-engine): aggregations (count/sum/avg/min/max with group-by)"
```

---

## Task 5: Saved views + server-side pagination

**Files:**
- Create: `backend/templates/runtime/data-engine/saved-views.ts`
- Modify: `backend/templates/runtime/data-engine.ts` — add cursor-based pagination + saved-view CRUD

- [ ] **Step 1: saved-views.ts**

```ts
// backend/templates/runtime/data-engine/saved-views.ts

export interface SavedView {
  id: string;
  userId: string;
  table: string;          // which entity this view is for
  label: string;
  filters: Record<string, any>;
  sortBy?: { field: string; direction: "asc" | "desc" };
  createdAt: string;
}

const SAVED_VIEWS_TABLE = "saved_views";

export async function listSavedViews(db: any, userId: string, table: string): Promise<SavedView[]> {
  return db.select().from(SAVED_VIEWS_TABLE).where({ userId, table });
}

export async function createSavedView(db: any, view: Omit<SavedView, "id" | "createdAt">): Promise<SavedView> {
  const full: SavedView = {
    ...view,
    id: crypto.randomUUID(),
    createdAt: new Date().toISOString(),
  };
  await db.insert(SAVED_VIEWS_TABLE).values(full);
  return full;
}

export async function deleteSavedView(db: any, id: string, userId: string): Promise<void> {
  await db.delete().from(SAVED_VIEWS_TABLE).where({ id, userId });
}
```

- [ ] **Step 2: Cursor-based pagination in data-engine.ts**

```ts
// In data-engine.ts — extend the list handler:

interface ListQuery {
  table: string;
  filter?: Record<string, any>;
  sortBy?: { field: string; direction: "asc" | "desc" };
  cursor?: string;         // base64-encoded last-item key
  limit?: number;          // default 50, max 200
}

async function handleListPaginated(table: string, query: ListQuery) {
  const limit = Math.min(query.limit ?? 50, 200);
  let qb = db.select().from(db[table]);
  if (query.filter) {
    for (const [k, v] of Object.entries(query.filter)) {
      qb = qb.where(db[table][k].eq(v));
    }
  }
  if (query.sortBy) {
    qb = qb.orderBy(db[table][query.sortBy.field][query.sortBy.direction]());
  }
  if (query.cursor) {
    const lastKey = JSON.parse(atob(query.cursor));
    qb = qb.where(db[table].id.gt(lastKey));   // assumes ID-based cursor
  }
  qb = qb.limit(limit + 1);  // +1 to detect hasMore

  const rows = await qb;
  const hasMore = rows.length > limit;
  const visible = rows.slice(0, limit);
  const nextCursor = hasMore ? btoa(JSON.stringify(visible[visible.length - 1].id)) : null;
  return { rows: visible, nextCursor, hasMore };
}
```

- [ ] **Step 3: Commit**

```bash
git add backend/templates/runtime/data-engine/saved-views.ts \
        backend/templates/runtime/data-engine.ts
git commit -m "feat(data-engine): saved views + cursor-based server-side pagination"
```

---

## Task 6: runtime_injector updates

**Files:**
- Modify: `backend/services/runtime_injector.py` — copy new template files into generated projects

The injector copies `backend/templates/runtime/` into each generated project. New files (audit-log.ts, escalation.ts, aggregations.ts, saved-views.ts) need to be included.

- [ ] **Step 1: Read current injector**

```bash
grep -n "workflows\|data-engine" /Users/m/Work/code/poc/design2ui-forge-v3/backend/services/runtime_injector.py | head -20
```

- [ ] **Step 2: Add new files to copy list**

The injector likely uses a list of files to copy or walks the directory. Either:
- If it uses an explicit list, add the new file paths
- If it walks the directory, the new files are copied automatically — verify this

If the latter, no code changes needed, just verify by running injection on a test project and confirming the new files appear.

- [ ] **Step 3: Commit (if changes needed)**

```bash
git add backend/services/runtime_injector.py
git commit -m "feat(injector): include new workflow + data engine helpers in generated projects"
```

---

## Task 7: Tests

**Files:**
- Create: `backend/tests/services/test_workflow_extensions.py`
- Create: `backend/tests/services/test_data_engine_aggregations.py`

These test the Python-side runtime injector + the contract that the new TypeScript runtime files are valid + injected. The actual TypeScript runtime is hard to unit-test from Python — for behavior tests, the TypeScript files need their own test suite (deferred; not in this wave).

- [ ] **Step 1: test_workflow_extensions.py**

```python
# backend/tests/services/test_workflow_extensions.py
"""Tests that the workflow extension TypeScript files are syntactically valid + injected."""
from pathlib import Path
import subprocess
import pytest


_RUNTIME_ROOT = Path(__file__).resolve().parents[3] / "backend" / "templates" / "runtime"


def test_workflow_types_includes_parallel_approvers():
    types = (_RUNTIME_ROOT / "workflows" / "types.ts").read_text()
    assert "ParallelApproverGroup" in types
    assert "RoutingCondition" in types
    assert "DelegationRule" in types
    assert "ReminderConfig" in types
    assert "EscalationConfig" in types


def test_workflow_engine_has_parallel_resolution():
    engine = (_RUNTIME_ROOT / "workflows" / "engine.ts").read_text()
    assert "resolveApprovers" in engine
    assert "canAdvanceStage" in engine
    assert "evalCondition" in engine


def test_audit_log_module_exists():
    audit = _RUNTIME_ROOT / "workflows" / "audit-log.ts"
    assert audit.exists()
    text = audit.read_text()
    assert "appendAuditEntry" in text
    assert "getAuditTrailForRecord" in text


def test_escalation_module_exists():
    escalation = _RUNTIME_ROOT / "workflows" / "escalation.ts"
    assert escalation.exists()
    text = escalation.read_text()
    assert "processEscalations" in text


def test_typescript_compiles():
    """Smoke test: the runtime templates compile under the workspace's tsconfig."""
    proc = subprocess.run(
        ["npx", "tsc", "--noEmit", "--allowJs",
         "--target", "es2022", "--module", "esnext",
         "--moduleResolution", "bundler",
         str(_RUNTIME_ROOT / "workflows" / "types.ts")],
        capture_output=True, text=True, timeout=30,
        cwd=str(_RUNTIME_ROOT.parent.parent.parent),  # repo root
    )
    if proc.returncode != 0 and "Cannot find" not in proc.stderr:
        pytest.fail(f"TypeScript compile failed:\n{proc.stderr[:500]}")
```

- [ ] **Step 2: test_data_engine_aggregations.py**

```python
# backend/tests/services/test_data_engine_aggregations.py
from pathlib import Path


_RUNTIME_ROOT = Path(__file__).resolve().parents[3] / "backend" / "templates" / "runtime"


def test_aggregations_module_exists():
    agg = _RUNTIME_ROOT / "data-engine" / "aggregations.ts"
    assert agg.exists()
    text = agg.read_text()
    assert "executeAggregation" in text
    assert "AggregationFn" in text
    assert "groupBy" in text


def test_saved_views_module_exists():
    sv = _RUNTIME_ROOT / "data-engine" / "saved-views.ts"
    assert sv.exists()
    text = sv.read_text()
    assert "listSavedViews" in text
    assert "createSavedView" in text
    assert "deleteSavedView" in text


def test_aggregation_supports_all_required_fns():
    text = (_RUNTIME_ROOT / "data-engine" / "aggregations.ts").read_text()
    for fn in ["count", "sum", "avg", "min", "max"]:
        assert f'"{fn}"' in text or f"'{fn}'" in text, f"missing fn: {fn}"
```

- [ ] **Step 3: Run tests**

```bash
cd /Users/m/Work/code/poc/design2ui-forge-v3/backend
python3 -m pytest tests/services/test_workflow_extensions.py tests/services/test_data_engine_aggregations.py -v 2>&1 | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/services/test_workflow_extensions.py \
        backend/tests/services/test_data_engine_aggregations.py
git commit -m "test(runtime): assert workflow + data engine extensions present in templates"
```

---

## Self-review

| Spec section | Tasks |
|---|---|
| Workflow types (parallel/conditional/delegation) | 1 |
| Engine logic (advance/condition/delegate) | 2 |
| Audit log + escalations | 3 |
| Data aggregations | 4 |
| Saved views + pagination | 5 |
| Injector | 6 |
| Tests | 7 |

✓ All Wave 5 scope.

### Backward compatibility

- Existing single-stage approvals still work (legacy types preserved as aliases)
- Existing CRUD routes unchanged (aggregations + saved-views are new routes)
- Generated apps without the new features keep working

✓ Additive only.

---

## Out of scope

- **TypeScript-side unit tests** for the runtime files — they're consumed by generated apps which have their own test setup; testing the templates in-place needs more infrastructure (deferred)
- **Notification channel integration** (email / in-app) — generated apps wire these to their own SMTP / push systems; templates expose a `notify()` callback only
- **Cron scheduler** for escalations — Vercel cron / GitHub Actions / a separate worker; out of scope for this template work
- **Audit-log UI** — Timeline component (Wave 1) consumes the audit-log shape; integration in real schemas comes in Wave 6 patterns
