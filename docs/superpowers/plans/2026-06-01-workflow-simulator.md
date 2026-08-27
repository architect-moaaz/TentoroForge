# Workflow Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Simulate" mode to the Workflows tab that runs a real workflow through the actual backend runtime engine, renders the real workflow graph, greys out completed nodes as they execute, and prompts for input wherever the engine pauses.

**Architecture:** Frontend-heavy orchestration over endpoints that already exist in `backend/routers/workflows.py`. All execution is the real `WorkflowRuntimeEngine` (no fake simulation). Testable logic lives in pure modules under `frontend/src/lib/workflow-sim/` plus a Zustand store; React components are thin shells over them. Realtime = poll the instance + logs while running, and reveal node-status changes through an animation queue. Replaces the fake `WorkflowTester.tsx`.

**Tech Stack:** Next.js + TypeScript, Zustand, `@xyflow/react` (React Flow), Vitest (logic/store tests only — the frontend has no testing-library, so components are verified manually). Backend: FastAPI + the existing runtime engine.

**Reference spec:** `docs/superpowers/specs/2026-06-01-workflow-simulator-design.md`

---

## Conventions confirmed from the codebase

- API client: `import { api } from "@/lib/api"` → `api.get<T>(path)`, `api.post<T>(path, body)`. Throws `ApiError(status, message, code)`.
- Project-scoped base path: `/api/projects/${projectId}`.
- Tests: Vitest, run with `npx vitest run <path>` from `frontend/`. Pattern: import store via `@/...`, `beforeEach(() => store.getState().reset())`. No DOM/testing-library — **do not** write component render tests.
- Backend response shapes (from `backend/schemas/workflow.py`):
  - `WorkflowInstanceResponse`: `id, project_id, workflow_id, workflow_name, status, current_node_ids: string[]|null, variables: object|null, initiated_by, error_message, started_at, completed_at, created_at`.
  - `WorkflowInstanceDetailResponse` = instance + `tasks: TaskInstanceResponse[]`.
  - `TaskInstanceResponse`: `id, workflow_instance_id, node_id, node_label, task_type, status, assignee_id, assignee_type, input_data, output_data, due_at, completed_at, error_message, created_at`.
  - `NodeExecutionLogResponse`: `id, workflow_instance_id, node_id, node_type, node_label, status ('started'|'completed'|'failed'|'skipped'), input_snapshot, output_snapshot, error_message, started_at, completed_at, duration_ms`.
- Endpoints (under `/api/projects/${projectId}`):
  - `POST /workflows/start` body `{workflow_id, variables, initiated_by?}` → `WorkflowInstanceResponse`
  - `GET /workflow-instances/${id}` → `WorkflowInstanceDetailResponse`
  - `GET /workflow-instances/${id}/logs` → `NodeExecutionLogResponse[]`
  - `POST /tasks/${taskId}/complete` body `{output_data}` → task
  - `POST /workflow-instances/${id}/cancel`
- Frontend types (`frontend/src/types/workflow.ts`): `WorkflowDefinition { id, name, processVariables?: ProcessVariable[], definition: { trigger, nodes: WorkflowNodeSerialized[], edges: WorkflowEdgeSerialized[] } }`, `ProcessVariable { name, type, defaultValue?, description?, required? }`, `WorkflowNodeSerialized { id, type, position, data }`, `WorkflowEdgeSerialized { id, source, target, sourceHandle?, targetHandle?, data? }`.
- `WorkflowCanvas` (`frontend/src/components/workflow/WorkflowCanvas.tsx`) already accepts `activeNodeId?: string | null`. We add `nodeStatuses` + `takenEdgeIds`.

---

## File Structure

**New (frontend):**
- `frontend/src/lib/workflow-sim/types.ts` — TS types mirroring the API + sim state.
- `frontend/src/lib/workflow-sim/sim-api.ts` — `SimApi` interface + `realSimApi(projectId)` concrete impl over `api`.
- `frontend/src/lib/workflow-sim/node-status.ts` — pure: logs+instance → node status map + taken edges.
- `frontend/src/lib/workflow-sim/trigger-form.ts` — pure: definition → trigger field specs + value coercion.
- `frontend/src/lib/workflow-sim/task-form.ts` — pure: task → input field spec + output_data builder.
- `frontend/src/stores/workflow-sim.ts` — Zustand store: the run state machine + reveal queue.
- `frontend/src/components/workflow/simulator/WorkflowSimulator.tsx` — orchestrator.
- `frontend/src/components/workflow/simulator/TriggerInputForm.tsx` — trigger form (thin).
- `frontend/src/components/workflow/simulator/TaskInputPanel.tsx` — paused-task form (thin).

**Modified:**
- `frontend/src/components/workflow/WorkflowCanvas.tsx` — add `nodeStatuses`/`takenEdgeIds` props → overlay.
- `frontend/src/components/workflow/nodes/WorkflowNode.tsx` — render status from injected node data.
- `frontend/src/components/workflow/WorkflowPanel.tsx` — add Simulate mode, mount `WorkflowSimulator`, remove `WorkflowTester` usage.
- `backend/routers/workflows.py` — only if Task 8 confirms a `fire-timer` endpoint is needed.

**Test files (Vitest):**
- `frontend/src/lib/workflow-sim/node-status.test.ts`
- `frontend/src/lib/workflow-sim/trigger-form.test.ts`
- `frontend/src/lib/workflow-sim/task-form.test.ts`
- `frontend/src/stores/workflow-sim.test.ts`
- (backend) `backend/tests/test_timer_fastforward.py` — only if Task 8 adds an endpoint.

---

## Task 1: Sim types + injectable API boundary

**Files:**
- Create: `frontend/src/lib/workflow-sim/types.ts`
- Create: `frontend/src/lib/workflow-sim/sim-api.ts`

No test (pure type/declaration glue; exercised by later tested modules).

- [ ] **Step 1: Create `types.ts`**

```typescript
// frontend/src/lib/workflow-sim/types.ts
export type LogStatus = "started" | "completed" | "failed" | "skipped";

export interface WorkflowInstanceDTO {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: "created" | "running" | "waiting" | "completed" | "failed" | "cancelled";
  current_node_ids: string[] | null;
  variables: Record<string, unknown> | null;
  error_message: string | null;
}

export interface TaskDTO {
  id: string;
  node_id: string;
  node_label: string | null;
  task_type: string;
  status: string; // pending | assigned | active | completed | ...
  input_data: Record<string, unknown> | null;
  output_data: Record<string, unknown> | null;
}

export interface InstanceDetailDTO extends WorkflowInstanceDTO {
  tasks: TaskDTO[];
}

export interface NodeLogDTO {
  id: string;
  node_id: string;
  node_type: string;
  node_label: string | null;
  status: LogStatus;
  output_snapshot: Record<string, unknown> | null;
  error_message: string | null;
  started_at: string;
  completed_at: string | null;
  duration_ms: number | null;
}

/** Visual status painted on each node in the canvas overlay. */
export type NodeVisualStatus = "pending" | "active" | "done" | "failed";

/** High-level state of a simulator run. */
export type RunPhase =
  | "idle"
  | "starting"
  | "running"
  | "awaitingInput"
  | "completed"
  | "failed"
  | "cancelled";
```

- [ ] **Step 2: Create `sim-api.ts` (injectable boundary)**

```typescript
// frontend/src/lib/workflow-sim/sim-api.ts
import { api } from "@/lib/api";
import type { InstanceDetailDTO, NodeLogDTO, WorkflowInstanceDTO } from "./types";

/** The set of backend calls the simulator needs. Injectable so the store is testable. */
export interface SimApi {
  start(workflowId: string, variables: Record<string, unknown>): Promise<WorkflowInstanceDTO>;
  getInstance(instanceId: string): Promise<InstanceDetailDTO>;
  getLogs(instanceId: string): Promise<NodeLogDTO[]>;
  completeTask(taskId: string, outputData: Record<string, unknown>): Promise<unknown>;
  cancel(instanceId: string): Promise<unknown>;
}

export function realSimApi(projectId: string): SimApi {
  const base = `/api/projects/${projectId}`;
  return {
    start: (workflowId, variables) =>
      api.post<WorkflowInstanceDTO>(`${base}/workflows/start`, {
        workflow_id: workflowId,
        variables,
      }),
    getInstance: (instanceId) =>
      api.get<InstanceDetailDTO>(`${base}/workflow-instances/${instanceId}`),
    getLogs: (instanceId) =>
      api.get<NodeLogDTO[]>(`${base}/workflow-instances/${instanceId}/logs`),
    completeTask: (taskId, outputData) =>
      api.post(`${base}/tasks/${taskId}/complete`, { output_data: outputData }),
    cancel: (instanceId) =>
      api.post(`${base}/workflow-instances/${instanceId}/cancel`, {}),
  };
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/workflow-sim/types.ts frontend/src/lib/workflow-sim/sim-api.ts
git commit -m "feat(workflow-sim): sim types + injectable SimApi boundary"
```

---

## Task 2: Node-status mapper (pure, TDD)

Maps execution logs + the instance's `current_node_ids` to a per-node visual status and the set of "taken" edge ids.

**Files:**
- Create: `frontend/src/lib/workflow-sim/node-status.ts`
- Test: `frontend/src/lib/workflow-sim/node-status.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/workflow-sim/node-status.test.ts
import { describe, it, expect } from "vitest";
import { computeNodeStatuses, computeTakenEdges } from "./node-status";
import type { NodeLogDTO } from "./types";

function log(node_id: string, status: NodeLogDTO["status"], at: string): NodeLogDTO {
  return {
    id: `${node_id}-${status}`, node_id, node_type: "action", node_label: node_id,
    status, output_snapshot: null, error_message: null, started_at: at,
    completed_at: status === "started" ? null : at, duration_ms: 1,
  };
}

describe("computeNodeStatuses", () => {
  it("marks completed and skipped logs as done", () => {
    const s = computeNodeStatuses([log("a", "completed", "1"), log("b", "skipped", "2")], []);
    expect(s).toEqual({ a: "done", b: "done" });
  });

  it("marks a failed log as failed", () => {
    expect(computeNodeStatuses([log("a", "failed", "1")], [])).toEqual({ a: "failed" });
  });

  it("uses the latest log per node by started_at", () => {
    const s = computeNodeStatuses([log("a", "started", "1"), log("a", "completed", "2")], []);
    expect(s.a).toBe("done");
  });

  it("forces current (paused) nodes to active even if a stale log exists", () => {
    const s = computeNodeStatuses([log("a", "started", "1")], ["a"]);
    expect(s.a).toBe("active");
  });

  it("marks a current node with no log as active", () => {
    expect(computeNodeStatuses([], ["x"])).toEqual({ x: "active" });
  });
});

describe("computeTakenEdges", () => {
  it("returns edges whose source is done and target has been reached", () => {
    const statuses = { a: "done", b: "active" } as const;
    const edges = [
      { id: "e1", source: "a", target: "b" },
      { id: "e2", source: "a", target: "c" }, // c not reached
    ];
    expect(computeTakenEdges(statuses, edges)).toEqual(["e1"]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/workflow-sim/node-status.test.ts`
Expected: FAIL — "computeNodeStatuses is not a function" (module missing).

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/src/lib/workflow-sim/node-status.ts
import type { NodeLogDTO, NodeVisualStatus } from "./types";

function mapLogStatus(s: NodeLogDTO["status"]): NodeVisualStatus {
  if (s === "failed") return "failed";
  if (s === "started") return "active";
  return "done"; // completed | skipped
}

/** Latest-log-wins per node; current (paused) nodes are forced to "active". */
export function computeNodeStatuses(
  logs: NodeLogDTO[],
  currentNodeIds: string[],
): Record<string, NodeVisualStatus> {
  const out: Record<string, NodeVisualStatus> = {};
  const latestAt: Record<string, string> = {};
  for (const l of logs) {
    if (!(l.node_id in latestAt) || l.started_at >= latestAt[l.node_id]) {
      latestAt[l.node_id] = l.started_at;
      out[l.node_id] = mapLogStatus(l.status);
    }
  }
  for (const nid of currentNodeIds) out[nid] = "active";
  return out;
}

/** An edge is "taken" when its source completed and its target has been reached. */
export function computeTakenEdges(
  statuses: Record<string, NodeVisualStatus>,
  edges: { id: string; source: string; target: string }[],
): string[] {
  const reached = (s?: NodeVisualStatus) => s === "done" || s === "active" || s === "failed";
  return edges
    .filter((e) => statuses[e.source] === "done" && reached(statuses[e.target]))
    .map((e) => e.id);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/workflow-sim/node-status.test.ts`
Expected: PASS (5 + 1 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/workflow-sim/node-status.ts frontend/src/lib/workflow-sim/node-status.test.ts
git commit -m "feat(workflow-sim): node-status + taken-edge mapper (TDD)"
```

---

## Task 3: Trigger-form extraction (pure, TDD)

Derives the trigger input form from a workflow's `processVariables`, with value coercion. JSON fallback is handled by the component (Task 10) when `fields` is empty.

**Files:**
- Create: `frontend/src/lib/workflow-sim/trigger-form.ts`
- Test: `frontend/src/lib/workflow-sim/trigger-form.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/workflow-sim/trigger-form.test.ts
import { describe, it, expect } from "vitest";
import { extractTriggerFields, coerceTriggerValues } from "./trigger-form";

const def = {
  id: "w", name: "W",
  processVariables: [
    { name: "days", type: "number", required: true },
    { name: "reason", type: "string", defaultValue: "PTO" },
    { name: "urgent", type: "boolean" },
  ],
  definition: { trigger: {}, nodes: [], edges: [] },
} as any;

describe("extractTriggerFields", () => {
  it("maps processVariables to field specs with defaults", () => {
    const fields = extractTriggerFields(def);
    expect(fields).toEqual([
      { name: "days", type: "number", required: true, defaultValue: undefined, description: undefined },
      { name: "reason", type: "string", required: false, defaultValue: "PTO", description: undefined },
      { name: "urgent", type: "boolean", required: false, defaultValue: undefined, description: undefined },
    ]);
  });

  it("returns [] when there are no processVariables", () => {
    expect(extractTriggerFields({ ...def, processVariables: undefined })).toEqual([]);
  });
});

describe("coerceTriggerValues", () => {
  it("coerces raw string inputs by declared type", () => {
    const fields = extractTriggerFields(def);
    const out = coerceTriggerValues(fields, { days: "3", reason: "Trip", urgent: "true" });
    expect(out).toEqual({ days: 3, reason: "Trip", urgent: true });
  });

  it("omits empty optional fields and applies defaults", () => {
    const fields = extractTriggerFields(def);
    const out = coerceTriggerValues(fields, { days: "1", reason: "", urgent: "" });
    expect(out).toEqual({ days: 1, reason: "PTO" });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/workflow-sim/trigger-form.test.ts`
Expected: FAIL — module/exports missing.

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/src/lib/workflow-sim/trigger-form.ts
import type { WorkflowDefinition } from "@/types/workflow";

export interface FieldSpec {
  name: string;
  type: "string" | "number" | "boolean" | "object" | "array" | "date";
  required: boolean;
  defaultValue: unknown;
  description: string | undefined;
}

export function extractTriggerFields(def: WorkflowDefinition): FieldSpec[] {
  const vars = def.processVariables ?? [];
  return vars.map((v) => ({
    name: v.name,
    type: v.type,
    required: !!v.required,
    defaultValue: v.defaultValue,
    description: v.description,
  }));
}

function coerce(type: FieldSpec["type"], raw: unknown): unknown {
  if (type === "number") return Number(raw);
  if (type === "boolean") return raw === true || raw === "true";
  if (type === "object" || type === "array") {
    return typeof raw === "string" ? JSON.parse(raw) : raw;
  }
  return raw;
}

/** Build the `variables` payload: coerce by type, drop empty optionals, apply defaults. */
export function coerceTriggerValues(
  fields: FieldSpec[],
  raw: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = raw[f.name];
    const isEmpty = v === undefined || v === null || v === "";
    if (isEmpty) {
      if (f.defaultValue !== undefined) out[f.name] = f.defaultValue;
      continue;
    }
    out[f.name] = coerce(f.type, v);
  }
  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/workflow-sim/trigger-form.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/workflow-sim/trigger-form.ts frontend/src/lib/workflow-sim/trigger-form.test.ts
git commit -m "feat(workflow-sim): trigger-form field extraction + coercion (TDD)"
```

---

## Task 4: Task-input form spec + output builder (pure, TDD)

Given a paused task, produce the input field spec (approval vs generic) and build the `output_data` payload.

**Files:**
- Create: `frontend/src/lib/workflow-sim/task-form.ts`
- Test: `frontend/src/lib/workflow-sim/task-form.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/lib/workflow-sim/task-form.test.ts
import { describe, it, expect } from "vitest";
import { taskFormSpec, buildTaskOutput } from "./task-form";
import type { TaskDTO } from "./types";

function task(task_type: string, input_data: Record<string, unknown> | null = null): TaskDTO {
  return {
    id: "t1", node_id: "n1", node_label: "L", task_type, status: "pending",
    input_data, output_data: null,
  };
}

describe("taskFormSpec", () => {
  it("returns a decision + comment form for approval tasks", () => {
    const spec = taskFormSpec(task("approval"));
    expect(spec.kind).toBe("approval");
    expect(spec.fields.map((f) => f.name)).toEqual(["decision", "comment"]);
  });

  it("uses declared expectedOutputs from input_data when present", () => {
    const spec = taskFormSpec(task("user_task", { expectedOutputs: [{ name: "amount", type: "number" }] }));
    expect(spec.kind).toBe("fields");
    expect(spec.fields).toEqual([{ name: "amount", type: "number", required: false }]);
  });

  it("falls back to a raw JSON form when nothing is declared", () => {
    const spec = taskFormSpec(task("assignment"));
    expect(spec.kind).toBe("json");
  });
});

describe("buildTaskOutput", () => {
  it("maps approve/reject to a structured approval output", () => {
    expect(buildTaskOutput(taskFormSpec(task("approval")), { decision: "approved", comment: "ok" }))
      .toEqual({ decision: "approved", approved: true, comment: "ok" });
  });

  it("passes through field values for a fields form", () => {
    const spec = taskFormSpec(task("user_task", { expectedOutputs: [{ name: "amount", type: "number" }] }));
    expect(buildTaskOutput(spec, { amount: "42" })).toEqual({ amount: 42 });
  });

  it("parses raw JSON for a json form", () => {
    expect(buildTaskOutput(taskFormSpec(task("assignment")), { __json: '{"x":1}' })).toEqual({ x: 1 });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/workflow-sim/task-form.test.ts`
Expected: FAIL — exports missing.

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/src/lib/workflow-sim/task-form.ts
import type { TaskDTO } from "./types";

export interface TaskField {
  name: string;
  type: "string" | "number" | "boolean" | "select";
  required: boolean;
  options?: string[];
}

export type TaskFormSpec =
  | { kind: "approval"; fields: TaskField[] }
  | { kind: "fields"; fields: TaskField[] }
  | { kind: "json"; fields: TaskField[] };

export function taskFormSpec(task: TaskDTO): TaskFormSpec {
  if (task.task_type === "approval") {
    return {
      kind: "approval",
      fields: [
        { name: "decision", type: "select", required: true, options: ["approved", "rejected"] },
        { name: "comment", type: "string", required: false },
      ],
    };
  }
  const declared = (task.input_data?.expectedOutputs as { name: string; type: string }[] | undefined) ?? null;
  if (declared && declared.length > 0) {
    return {
      kind: "fields",
      fields: declared.map((d) => ({
        name: d.name,
        type: (["string", "number", "boolean"].includes(d.type) ? d.type : "string") as TaskField["type"],
        required: false,
      })),
    };
  }
  return { kind: "json", fields: [] };
}

function coerce(type: TaskField["type"], raw: unknown): unknown {
  if (type === "number") return Number(raw);
  if (type === "boolean") return raw === true || raw === "true";
  return raw;
}

export function buildTaskOutput(spec: TaskFormSpec, values: Record<string, unknown>): Record<string, unknown> {
  if (spec.kind === "json") {
    const raw = (values.__json as string) ?? "{}";
    return JSON.parse(raw);
  }
  if (spec.kind === "approval") {
    const decision = values.decision as string;
    return { decision, approved: decision === "approved", comment: (values.comment as string) ?? "" };
  }
  const out: Record<string, unknown> = {};
  for (const f of spec.fields) {
    if (values[f.name] !== undefined && values[f.name] !== "") out[f.name] = coerce(f.type, values[f.name]);
  }
  return out;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/workflow-sim/task-form.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/workflow-sim/task-form.ts frontend/src/lib/workflow-sim/task-form.test.ts
git commit -m "feat(workflow-sim): task input form spec + output builder (TDD)"
```

---

## Task 5: Simulation store — start → running → awaiting/completed (TDD)

The Zustand store is the run state machine. The `SimApi` is injected (default `realSimApi`) so tests use a fake. Polling is driven by an explicit `poll()` method the component calls on an interval; reveal animation is an explicit `revealNext()` so timing is testable without timers.

**Files:**
- Create: `frontend/src/stores/workflow-sim.ts`
- Test: `frontend/src/stores/workflow-sim.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/stores/workflow-sim.test.ts
import { describe, it, expect, beforeEach } from "vitest";
import { useWorkflowSim } from "@/stores/workflow-sim";
import type { SimApi } from "@/lib/workflow-sim/sim-api";
import type { InstanceDetailDTO, NodeLogDTO, WorkflowInstanceDTO } from "@/lib/workflow-sim/types";

function makeApi(overrides: Partial<SimApi> = {}): SimApi {
  return {
    start: async () => ({ id: "i1", workflow_id: "w", workflow_name: "W", status: "running", current_node_ids: [], variables: {}, error_message: null }),
    getInstance: async () => ({ id: "i1", workflow_id: "w", workflow_name: "W", status: "running", current_node_ids: [], variables: {}, error_message: null, tasks: [] }),
    getLogs: async () => [],
    completeTask: async () => ({}),
    cancel: async () => ({}),
    ...overrides,
  };
}
const inst = (o: Partial<InstanceDetailDTO>): InstanceDetailDTO => ({ id: "i1", workflow_id: "w", workflow_name: "W", status: "running", current_node_ids: [], variables: {}, error_message: null, tasks: [], ...o });
const log = (node_id: string, status: NodeLogDTO["status"]): NodeLogDTO => ({ id: node_id + status, node_id, node_type: "action", node_label: node_id, status, output_snapshot: null, error_message: null, started_at: node_id, completed_at: node_id, duration_ms: 1 });

describe("useWorkflowSim", () => {
  beforeEach(() => useWorkflowSim.getState().reset());

  it("starts idle", () => {
    expect(useWorkflowSim.getState().phase).toBe("idle");
  });

  it("start() creates an instance and enters running", async () => {
    const api = makeApi();
    await useWorkflowSim.getState().start(api, "w", { days: 3 });
    expect(useWorkflowSim.getState().phase).toBe("running");
    expect(useWorkflowSim.getState().instanceId).toBe("i1");
  });

  it("poll() queues new logs for reveal and reflects completion", async () => {
    const api = makeApi({
      getInstance: async () => inst({ status: "completed" }),
      getLogs: async () => [log("a", "completed"), log("b", "completed")],
    });
    const s = useWorkflowSim.getState();
    await s.start(api, "w", {});
    await useWorkflowSim.getState().poll(api);
    // logs are queued, not yet revealed
    expect(useWorkflowSim.getState().pendingReveal).toEqual(["a", "b"]);
    expect(useWorkflowSim.getState().nodeStatuses).toEqual({});
    // drain the reveal queue
    useWorkflowSim.getState().revealNext();
    useWorkflowSim.getState().revealNext();
    expect(useWorkflowSim.getState().nodeStatuses).toEqual({ a: "done", b: "done" });
    // completion is recognised once queue drains
    expect(useWorkflowSim.getState().phase).toBe("completed");
  });

  it("poll() enters awaitingInput when the engine pauses with a task", async () => {
    const api = makeApi({
      getInstance: async () => inst({ status: "waiting", current_node_ids: ["appr"], tasks: [{ id: "t1", node_id: "appr", node_label: "Approve", task_type: "approval", status: "pending", input_data: null, output_data: null }] }),
      getLogs: async () => [log("a", "completed")],
    });
    await useWorkflowSim.getState().start(api, "w", {});
    await useWorkflowSim.getState().poll(api);
    useWorkflowSim.getState().revealNext(); // reveal "a"
    expect(useWorkflowSim.getState().phase).toBe("awaitingInput");
    expect(useWorkflowSim.getState().activeTask?.id).toBe("t1");
  });

  it("start() failure sets phase failed with an error", async () => {
    const api = makeApi({ start: async () => { throw new Error("boom"); } });
    await useWorkflowSim.getState().start(api, "w", {});
    expect(useWorkflowSim.getState().phase).toBe("failed");
    expect(useWorkflowSim.getState().error).toContain("boom");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/stores/workflow-sim.test.ts`
Expected: FAIL — store missing.

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/src/stores/workflow-sim.ts
import { create } from "zustand";
import type { SimApi } from "@/lib/workflow-sim/sim-api";
import type { InstanceDetailDTO, NodeLogDTO, NodeVisualStatus, RunPhase, TaskDTO } from "@/lib/workflow-sim/types";
import { computeNodeStatuses } from "@/lib/workflow-sim/node-status";

const ACTIVE_TASK_STATUSES = new Set(["pending", "assigned", "active"]);

interface SimState {
  phase: RunPhase;
  instanceId: string | null;
  instance: InstanceDetailDTO | null;
  logs: NodeLogDTO[];
  nodeStatuses: Record<string, NodeVisualStatus>;
  pendingReveal: string[]; // node ids queued for staggered reveal
  activeTask: TaskDTO | null;
  variables: Record<string, unknown>;
  error: string | null;

  reset(): void;
  start(api: SimApi, workflowId: string, variables: Record<string, unknown>): Promise<void>;
  poll(api: SimApi): Promise<void>;
  revealNext(): void;
}

const INITIAL = {
  phase: "idle" as RunPhase,
  instanceId: null,
  instance: null,
  logs: [],
  nodeStatuses: {},
  pendingReveal: [],
  activeTask: null,
  variables: {},
  error: null,
};

/** Recompute phase/activeTask once the reveal queue is empty (all known nodes shown). */
function settle(get: () => SimState, set: (p: Partial<SimState>) => void) {
  const { pendingReveal, instance } = get();
  if (pendingReveal.length > 0 || !instance) return;
  const pausedTask = instance.tasks.find((t) => ACTIVE_TASK_STATUSES.has(t.status)) ?? null;
  if (instance.status === "completed") set({ phase: "completed", activeTask: null });
  else if (instance.status === "failed") set({ phase: "failed", activeTask: null, error: instance.error_message ?? "Workflow failed" });
  else if (instance.status === "cancelled") set({ phase: "cancelled", activeTask: null });
  else if (instance.status === "waiting" && pausedTask) set({ phase: "awaitingInput", activeTask: pausedTask });
  else set({ phase: "running", activeTask: null });
}

export const useWorkflowSim = create<SimState>((set, get) => ({
  ...INITIAL,

  reset: () => set({ ...INITIAL }),

  start: async (api, workflowId, variables) => {
    set({ ...INITIAL, phase: "starting" });
    try {
      const inst = await api.start(workflowId, variables);
      set({ phase: "running", instanceId: inst.id, variables: inst.variables ?? {} });
    } catch (e) {
      set({ phase: "failed", error: e instanceof Error ? e.message : String(e) });
    }
  },

  poll: async (api) => {
    const { instanceId } = get();
    if (!instanceId) return;
    try {
      const [instance, logs] = await Promise.all([api.getInstance(instanceId), api.getLogs(instanceId)]);
      // Queue node ids that appear in logs but are not yet revealed.
      const known = new Set(Object.keys(get().nodeStatuses));
      const queued = new Set(get().pendingReveal);
      const fresh = logs.map((l) => l.node_id).filter((id) => !known.has(id) && !queued.has(id));
      set({
        instance,
        logs,
        variables: instance.variables ?? {},
        pendingReveal: [...get().pendingReveal, ...dedupe(fresh)],
      });
      settle(get, set);
    } catch (e) {
      set({ phase: "failed", error: e instanceof Error ? e.message : String(e) });
    }
  },

  revealNext: () => {
    const { pendingReveal, logs, instance } = get();
    if (pendingReveal.length === 0) return;
    const [head, ...rest] = pendingReveal;
    const statuses = computeNodeStatuses(
      logs.filter((l) => l.node_id === head || head in get().nodeStatuses),
      instance?.current_node_ids ?? [],
    );
    set({
      nodeStatuses: { ...get().nodeStatuses, ...computeNodeStatuses(logs.filter((l) => l.node_id === head), []) },
      pendingReveal: rest,
    });
    void statuses;
    settle(get, set);
  },
}));

function dedupe(ids: string[]): string[] {
  return Array.from(new Set(ids));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/stores/workflow-sim.test.ts`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/workflow-sim.ts frontend/src/stores/workflow-sim.test.ts
git commit -m "feat(workflow-sim): run state machine store with reveal queue (TDD)"
```

---

## Task 6: Store — submit task input (resume) (TDD)

**Files:**
- Modify: `frontend/src/stores/workflow-sim.ts` (add `submitTask`)
- Modify: `frontend/src/stores/workflow-sim.test.ts` (add cases)

- [ ] **Step 1: Add the failing test**

```typescript
// append inside describe("useWorkflowSim", ...) in workflow-sim.test.ts
it("submitTask() completes the task and returns to running", async () => {
  let completedWith: any = null;
  const api = makeApi({
    completeTask: async (taskId, output) => { completedWith = { taskId, output }; return {}; },
    getInstance: async () => inst({ status: "running", current_node_ids: [], tasks: [] }),
    getLogs: async () => [log("a", "completed")],
  });
  const s = useWorkflowSim.getState();
  await s.start(api, "w", {});
  // simulate being paused on a task
  useWorkflowSim.setState({ phase: "awaitingInput", activeTask: { id: "t1", node_id: "appr", node_label: "A", task_type: "approval", status: "pending", input_data: null, output_data: null } });
  await useWorkflowSim.getState().submitTask(api, { decision: "approved", comment: "" });
  expect(completedWith.taskId).toBe("t1");
  expect(completedWith.output).toEqual({ decision: "approved", approved: true, comment: "" });
  // after submit it polls; drain reveal then it should be running again
  while (useWorkflowSim.getState().pendingReveal.length) useWorkflowSim.getState().revealNext();
  expect(useWorkflowSim.getState().phase).toBe("running");
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/stores/workflow-sim.test.ts -t submitTask`
Expected: FAIL — `submitTask is not a function`.

- [ ] **Step 3: Implement `submitTask`**

Add to the `SimState` interface:

```typescript
  submitTask(api: SimApi, values: Record<string, unknown>): Promise<void>;
```

Add to the store body (after `revealNext`):

```typescript
  submitTask: async (api, values) => {
    const task = get().activeTask;
    if (!task) return;
    const { taskFormSpec, buildTaskOutput } = await import("@/lib/workflow-sim/task-form");
    const spec = taskFormSpec(task);
    const output = buildTaskOutput(spec, values);
    set({ phase: "running", activeTask: null });
    try {
      await api.completeTask(task.id, output);
      await get().poll(api);
    } catch (e) {
      set({ phase: "failed", error: e instanceof Error ? e.message : String(e) });
    }
  },
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/stores/workflow-sim.test.ts`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/workflow-sim.ts frontend/src/stores/workflow-sim.test.ts
git commit -m "feat(workflow-sim): submitTask resumes the run (TDD)"
```

---

## Task 7: Store — cancel/reset + timer fast-forward (TDD)

Fast-forward = when paused on a timer task, complete it immediately with empty output. We detect a timer task by `task_type` in a known set.

**Files:**
- Modify: `frontend/src/stores/workflow-sim.ts` (add `cancel`, `fastForwardTimer`, and auto-detect)
- Modify: `frontend/src/stores/workflow-sim.test.ts`

- [ ] **Step 1: Add the failing tests**

```typescript
it("cancel() cancels the instance and sets phase cancelled", async () => {
  let cancelled = false;
  const api = makeApi({ cancel: async () => { cancelled = true; return {}; } });
  await useWorkflowSim.getState().start(api, "w", {});
  await useWorkflowSim.getState().cancel(api);
  expect(cancelled).toBe(true);
  expect(useWorkflowSim.getState().phase).toBe("cancelled");
});

it("isTimerTask identifies timer/wait task types", () => {
  const { isTimerTask } = require("@/stores/workflow-sim");
  expect(isTimerTask({ task_type: "timer_event" } as any)).toBe(true);
  expect(isTimerTask({ task_type: "wait" } as any)).toBe(true);
  expect(isTimerTask({ task_type: "approval" } as any)).toBe(false);
});

it("fastForwardTimer completes the timer task with empty output", async () => {
  let completedWith: any = null;
  const api = makeApi({ completeTask: async (id, o) => { completedWith = { id, o }; return {}; }, getInstance: async () => inst({ status: "completed", tasks: [] }), getLogs: async () => [] });
  await useWorkflowSim.getState().start(api, "w", {});
  useWorkflowSim.setState({ phase: "awaitingInput", activeTask: { id: "tm", node_id: "t", node_label: "Wait", task_type: "timer_event", status: "pending", input_data: null, output_data: null } });
  await useWorkflowSim.getState().fastForwardTimer(api);
  expect(completedWith).toEqual({ id: "tm", o: {} });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/stores/workflow-sim.test.ts -t "cancel|timer"`
Expected: FAIL — `cancel`/`fastForwardTimer`/`isTimerTask` missing.

- [ ] **Step 3: Implement**

Add exported helper near top of `workflow-sim.ts`:

```typescript
import type { TaskDTO } from "@/lib/workflow-sim/types";
const TIMER_TASK_TYPES = new Set(["timer_event", "timer", "wait"]);
export function isTimerTask(task: Pick<TaskDTO, "task_type">): boolean {
  return TIMER_TASK_TYPES.has(task.task_type);
}
```

Add to the `SimState` interface:

```typescript
  cancel(api: SimApi): Promise<void>;
  fastForwardTimer(api: SimApi): Promise<void>;
```

Add to the store body:

```typescript
  cancel: async (api) => {
    const { instanceId } = get();
    if (!instanceId) { set({ phase: "cancelled" }); return; }
    try { await api.cancel(instanceId); } catch { /* best effort */ }
    set({ phase: "cancelled", activeTask: null });
  },

  fastForwardTimer: async (api) => {
    const task = get().activeTask;
    if (!task) return;
    set({ phase: "running", activeTask: null });
    try {
      await api.completeTask(task.id, {});
      await get().poll(api);
    } catch (e) {
      set({ phase: "failed", error: e instanceof Error ? e.message : String(e) });
    }
  },
```

> Note: `settle()` should auto-fast-forward unattended is NOT done here — fast-forward is invoked by the component (Task 11) when it detects `isTimerTask(activeTask)`, so the user sees the "timer skipped" marker. This keeps the store deterministic for tests.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/stores/workflow-sim.test.ts`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/stores/workflow-sim.ts frontend/src/stores/workflow-sim.test.ts
git commit -m "feat(workflow-sim): cancel + timer fast-forward (TDD)"
```

---

## Task 8: Backend — verify timer fast-forward path

Confirm `POST /tasks/{id}/complete` accepts a `timer_event` task (so the frontend fast-forward works with no backend change). Add a thin endpoint only if it rejects timer tasks.

**Files:**
- Inspect: `backend/runtime/engine.py` (`complete_task`, ~line 102), `backend/routers/workflows.py` (`/tasks/{task_id}/complete`, ~line 799)
- Possibly create: `backend/tests/test_timer_fastforward.py` + endpoint in `backend/routers/workflows.py`

- [ ] **Step 1: Inspect `complete_task` status guard**

Run: `cd backend && grep -n "status" runtime/engine.py | sed -n '1,40p'` and read `complete_task` (lines ~102-160).
Determine whether it rejects tasks whose `task_type == "timer_event"` or whose status isn't `pending|assigned|active`. Timer tasks are created with a status (check `task_executor.py`). 

- [ ] **Step 2: Decide**
  - **If `complete_task` accepts the timer task's status** → no backend change. Mark this task done; the frontend `fastForwardTimer` (Task 7) already calls `completeTask`. Skip steps 3-5.
  - **If it rejects timer tasks** → add a dedicated endpoint (steps 3-5).

- [ ] **Step 3 (conditional): Write the failing backend test**

```python
# backend/tests/test_timer_fastforward.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_fire_timer_completes_timer_task(seeded_timer_instance, client: AsyncClient, project_id):
    # seeded_timer_instance: a WorkflowInstance paused on a timer_event task (fixture)
    task_id = seeded_timer_instance.timer_task_id
    res = await client.post(f"/api/projects/{project_id}/tasks/{task_id}/fire-timer")
    assert res.status_code == 200
    assert res.json()["status"] in ("completed", "running", "waiting")
```

Run: `cd backend && python -m pytest tests/test_timer_fastforward.py -v`
Expected: FAIL — 404 (endpoint missing). *(If the `seeded_timer_instance` fixture doesn't exist, add it in `conftest.py` mirroring the existing workflow-instance fixtures; reuse the engine to start a workflow whose first node is a timer.)*

- [ ] **Step 4 (conditional): Implement the endpoint**

Add to `backend/routers/workflows.py` near the existing `/tasks/{task_id}/complete` route:

```python
@router.post("/projects/{project_id}/tasks/{task_id}/fire-timer")
async def fire_timer(project_id: uuid.UUID, task_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Simulator-only: immediately resume a paused timer/wait task as if it elapsed."""
    engine = WorkflowRuntimeEngine(db)
    instance = await engine.complete_task(task_id=str(task_id), output_data={}, output_dir=None, force=True)
    return WorkflowInstanceResponse.model_validate(instance)
```

If `complete_task` has no `force` param, add one (default `False`) that bypasses the `task_type`/status guard for timer tasks only. Keep the change minimal and commented.

Run: `cd backend && python -m pytest tests/test_timer_fastforward.py -v`
Expected: PASS.

- [ ] **Step 5 (conditional): Update the frontend SimApi**

If the endpoint was added, change `fastForwardTimer` to call it instead of `completeTask`: add `fireTimer(taskId)` to `SimApi`/`realSimApi` (`POST .../tasks/${taskId}/fire-timer`) and have `fastForwardTimer` call `api.fireTimer(task.id)`. Re-run `cd frontend && npx vitest run src/stores/workflow-sim.test.ts` (update the timer test's fake api accordingly) — Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(workflow-sim): confirm/enable timer fast-forward path"
```

---

## Task 9: Canvas overlay — paint node statuses + taken edges

Extend the reused canvas to accept simulator overlay data. Keep all existing editor behavior intact.

**Files:**
- Modify: `frontend/src/components/workflow/WorkflowCanvas.tsx`
- Modify: `frontend/src/components/workflow/nodes/WorkflowNode.tsx`

No unit test (component; verified manually in Task 12). Keep changes additive.

- [ ] **Step 1: Add props to `WorkflowCanvas`**

In `interface WorkflowCanvasProps` add:

```typescript
  /** Simulator overlay: node id → visual status. When set, nodes render that status. */
  nodeStatuses?: Record<string, "pending" | "active" | "done" | "failed">;
  /** Simulator overlay: edge ids that have been traversed (highlighted). */
  takenEdgeIds?: string[];
  /** When true, disables editing interactions (simulator is read-only). */
  readOnly?: boolean;
```

- [ ] **Step 2: Inject status into each node's data + style taken edges**

Where the canvas maps serialized nodes → React Flow `Node[]`, merge `data.simStatus = nodeStatuses?.[node.id] ?? undefined`. Where it maps edges, set `animated: takenEdgeIds?.includes(edge.id)` and `style: takenEdgeIds?.includes(edge.id) ? { stroke: "#f59e0b", strokeWidth: 2 } : undefined`. When `readOnly`, pass `nodesDraggable={false}`, `nodesConnectable={false}`, `elementsSelectable={true}` to `<ReactFlow>` and skip `onConnect`/add handlers.

- [ ] **Step 3: Render status in `WorkflowNode`**

In `WorkflowNode.tsx`, read `data.simStatus`. Apply, on the node container, the existing status-ring styles already present (idle/running/completed/failed at ~lines 101-106) using this mapping: `active → running ring`, `done → completed ring + 60% opacity + line-through label`, `failed → failed ring`, `pending → 40% opacity`, `undefined → default`. Do not change layout/labels — only ring/opacity/label decoration.

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors in these two files.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workflow/WorkflowCanvas.tsx frontend/src/components/workflow/nodes/WorkflowNode.tsx
git commit -m "feat(workflow-sim): canvas overlay for node statuses + taken edges"
```

---

## Task 10: Trigger + task input forms (components)

Thin components over the pure modules from Tasks 3-4.

**Files:**
- Create: `frontend/src/components/workflow/simulator/TriggerInputForm.tsx`
- Create: `frontend/src/components/workflow/simulator/TaskInputPanel.tsx`

No unit test (components; verified in Task 12).

- [ ] **Step 1: `TriggerInputForm.tsx`**

```tsx
"use client";
import { useState } from "react";
import type { WorkflowDefinition } from "@/types/workflow";
import { extractTriggerFields, coerceTriggerValues } from "@/lib/workflow-sim/trigger-form";

export function TriggerInputForm({ def, onRun }: { def: WorkflowDefinition; onRun: (variables: Record<string, unknown>) => void; }) {
  const fields = extractTriggerFields(def);
  const [values, setValues] = useState<Record<string, string>>({});
  const [json, setJson] = useState("{}");

  const submit = () => {
    if (fields.length === 0) { onRun(JSON.parse(json || "{}")); return; }
    onRun(coerceTriggerValues(fields, values));
  };

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium">Trigger inputs</h4>
      {fields.length === 0 ? (
        <textarea className="w-full border rounded p-2 font-mono text-xs" rows={5} value={json} onChange={(e) => setJson(e.target.value)} />
      ) : (
        fields.map((f) => (
          <label key={f.name} className="block text-sm">
            <span>{f.name}{f.required ? " *" : ""}</span>
            {f.type === "boolean" ? (
              <input type="checkbox" checked={values[f.name] === "true"} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.checked ? "true" : "" }))} />
            ) : (
              <input className="w-full border rounded p-1" type={f.type === "number" ? "number" : "text"} value={values[f.name] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [f.name]: e.target.value }))} />
            )}
          </label>
        ))
      )}
      <button className="bg-blue-600 text-white rounded px-3 py-1.5 text-sm" onClick={submit}>▶ Run</button>
    </div>
  );
}
```

- [ ] **Step 2: `TaskInputPanel.tsx`**

```tsx
"use client";
import { useState } from "react";
import type { TaskDTO } from "@/lib/workflow-sim/types";
import { taskFormSpec } from "@/lib/workflow-sim/task-form";

export function TaskInputPanel({ task, onSubmit }: { task: TaskDTO; onSubmit: (values: Record<string, unknown>) => void; }) {
  const spec = taskFormSpec(task);
  const [values, setValues] = useState<Record<string, string>>({});
  const set = (k: string, v: string) => setValues((s) => ({ ...s, [k]: v }));

  return (
    <div className="border-2 border-amber-400 bg-amber-50 rounded p-3 space-y-2">
      <div className="font-medium text-amber-800 text-sm">⏸ Input required · {task.node_label ?? task.node_id}</div>
      {spec.kind === "json" ? (
        <textarea className="w-full border rounded p-2 font-mono text-xs" rows={4} placeholder="{}" value={values.__json ?? ""} onChange={(e) => set("__json", e.target.value)} />
      ) : (
        spec.fields.map((f) => (
          <label key={f.name} className="block text-sm">
            <span>{f.name}{f.required ? " *" : ""}</span>
            {f.type === "select" ? (
              <select className="w-full border rounded p-1" value={values[f.name] ?? ""} onChange={(e) => set(f.name, e.target.value)}>
                <option value="">—</option>
                {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            ) : (
              <input className="w-full border rounded p-1" type={f.type === "number" ? "number" : "text"} value={values[f.name] ?? ""} onChange={(e) => set(f.name, e.target.value)} />
            )}
          </label>
        ))
      )}
      <button className="bg-amber-600 text-white rounded px-3 py-1.5 text-sm w-full" onClick={() => onSubmit(values)}>Submit &amp; continue ▸</button>
    </div>
  );
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/workflow/simulator/TriggerInputForm.tsx frontend/src/components/workflow/simulator/TaskInputPanel.tsx
git commit -m "feat(workflow-sim): trigger + task input form components"
```

---

## Task 11: `WorkflowSimulator` orchestrator + wire into Workflows tab

Ties store + canvas + forms together; drives polling and reveal via intervals; replaces `WorkflowTester`.

**Files:**
- Create: `frontend/src/components/workflow/simulator/WorkflowSimulator.tsx`
- Modify: `frontend/src/components/workflow/WorkflowPanel.tsx`

- [ ] **Step 1: `WorkflowSimulator.tsx`**

```tsx
"use client";
import { useEffect, useMemo, useRef } from "react";
import { WorkflowCanvas } from "@/components/workflow/WorkflowCanvas";
import { TriggerInputForm } from "./TriggerInputForm";
import { TaskInputPanel } from "./TaskInputPanel";
import { useWorkflowSim, isTimerTask } from "@/stores/workflow-sim";
import { realSimApi } from "@/lib/workflow-sim/sim-api";
import { computeTakenEdges } from "@/lib/workflow-sim/node-status";
import type { WorkflowDefinition } from "@/types/workflow";

const POLL_MS = 800;
const REVEAL_MS = 250;

export function WorkflowSimulator({ projectId, def }: { projectId: string; def: WorkflowDefinition }) {
  const api = useMemo(() => realSimApi(projectId), [projectId]);
  const s = useWorkflowSim();
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const revealRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Reset when switching workflows.
  useEffect(() => { useWorkflowSim.getState().reset(); }, [def.id]);

  // Poll while running/waiting.
  useEffect(() => {
    const running = s.phase === "running" || s.phase === "awaitingInput";
    if (running && !pollRef.current) pollRef.current = setInterval(() => useWorkflowSim.getState().poll(api), POLL_MS);
    if (!running && pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [s.phase, api]);

  // Drain the reveal queue on a steady cadence (staggered greying).
  useEffect(() => {
    if (!revealRef.current) revealRef.current = setInterval(() => useWorkflowSim.getState().revealNext(), REVEAL_MS);
    return () => { if (revealRef.current) { clearInterval(revealRef.current); revealRef.current = null; } };
  }, []);

  // Auto fast-forward timer tasks (after they surface as activeTask).
  useEffect(() => {
    if (s.phase === "awaitingInput" && s.activeTask && isTimerTask(s.activeTask)) {
      void useWorkflowSim.getState().fastForwardTimer(api);
    }
  }, [s.phase, s.activeTask, api]);

  const takenEdges = computeTakenEdges(s.nodeStatuses, def.definition.edges);
  const human = s.phase === "awaitingInput" && s.activeTask && !isTimerTask(s.activeTask);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-2 border-b text-sm">
        <span className="font-medium">{def.name}</span>
        <button className="bg-white border rounded px-2 py-1" onClick={() => useWorkflowSim.getState().cancel(api)}>↻ Reset</button>
        <span className="ml-auto text-xs px-2 py-0.5 rounded-full bg-gray-100">{s.phase}{s.error ? ` — ${s.error}` : ""}</span>
      </div>
      <div className="flex flex-1 min-h-0">
        <div className="flex-1 min-w-0">
          <WorkflowCanvas
            initialNodes={def.definition.nodes}
            initialEdges={def.definition.edges}
            nodeStatuses={s.nodeStatuses}
            takenEdgeIds={takenEdges}
            activeNodeId={s.activeTask?.node_id ?? null}
            readOnly
          />
        </div>
        <div className="w-72 border-l p-3 overflow-auto space-y-3">
          {s.phase === "idle" && <TriggerInputForm def={def} onRun={(vars) => useWorkflowSim.getState().start(api, def.id, vars)} />}
          {human && s.activeTask && (
            <TaskInputPanel task={s.activeTask} onSubmit={(vals) => useWorkflowSim.getState().submitTask(api, vals)} />
          )}
          <div className="border-t pt-2">
            <div className="text-xs font-medium mb-1">Execution log</div>
            <ul className="text-xs space-y-0.5">
              {s.logs.map((l) => (
                <li key={l.id} className={l.status === "failed" ? "text-red-600" : "text-gray-600"}>
                  {l.status === "completed" ? "✓" : l.status === "failed" ? "✗" : "•"} {l.node_label ?? l.node_id}
                  {l.error_message ? ` — ${l.error_message}` : ""}
                </li>
              ))}
            </ul>
          </div>
          <details className="text-xs">
            <summary className="cursor-pointer">Variables</summary>
            <pre className="bg-gray-50 p-2 rounded overflow-auto">{JSON.stringify(s.variables, null, 2)}</pre>
          </details>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire into `WorkflowPanel.tsx`, remove `WorkflowTester`**

In `WorkflowPanel.tsx`: replace the import and usage of `WorkflowTester` with `WorkflowSimulator`. Where the editor previously opened the tester, render `<WorkflowSimulator projectId={projectId} def={currentWorkflowDefinition} />` (use the same `projectId` the panel already has and the currently-selected workflow definition). Add a "Simulate" button/toggle in the editor toolbar that shows the simulator for the selected workflow. Delete `frontend/src/components/workflow/WorkflowTester.tsx`.

- [ ] **Step 3: Confirm nothing else imports the deleted file**

Run: `cd frontend && grep -rn "WorkflowTester" src | grep -v node_modules`
Expected: no matches (besides the removal). If other files import it, repoint them to `WorkflowSimulator` or remove.

- [ ] **Step 4: Typecheck + all logic tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/lib/workflow-sim src/stores/workflow-sim.test.ts`
Expected: no new type errors; all sim tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/workflow/simulator/WorkflowSimulator.tsx frontend/src/components/workflow/WorkflowPanel.tsx
git rm frontend/src/components/workflow/WorkflowTester.tsx
git commit -m "feat(workflow-sim): WorkflowSimulator orchestrator; replace fake WorkflowTester"
```

---

## Task 12: Manual end-to-end verification

No code; prove the feature works against the real engine.

- [ ] **Step 1: Ensure services are up**

Run: `lsof -tnP -iTCP:5432 -sTCP:LISTEN >/dev/null && echo pg-ok` ; backend on 6500, frontend on 6501. (Use `./start-all.sh` if needed.)

- [ ] **Step 2: Open a project that has a workflow with an approval node**

In the browser at `http://localhost:6501`, log in (`admin@example.com` / `password123`), open a project, go to the **Workflows** tab, select a workflow, click **Simulate**.

- [ ] **Step 3: Run and observe**

Fill the trigger form, click Run. Verify: nodes grey out in order; the run pauses at the approval node (highlighted, "Input required"); the right rail shows the approval form.

- [ ] **Step 4: Provide input and finish**

Submit "approved"; verify the run resumes, remaining nodes complete, status becomes `completed`. If the workflow has a timer node, verify it auto-fast-forwards (no real wait) and a log entry appears.

- [ ] **Step 5: Error + reset paths**

Trigger a failing path (e.g. a node that errors) and confirm the node turns red with the error in the rail. Click Reset and confirm a fresh run starts clean.

- [ ] **Step 6: Final commit (if any tweaks)**

```bash
git add -A && git commit -m "chore(workflow-sim): manual verification fixes"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** select workflow + trigger form (Tasks 3,10,11) · real engine execution (Tasks 1,5,6,8) · render actual graph (Task 9 reuses editor canvas) · grey out completed nodes realtime (Tasks 2,5,9,11) · provide input where required (Tasks 4,6,10,11) · timers fast-forward (Tasks 7,8,11) · error handling (Tasks 5,9,11) · replace fake tester (Task 11). All covered.
- **Placeholders:** none — every code step has concrete code; Task 8 is explicitly conditional with both branches specified.
- **Type consistency:** `SimApi` methods (`start/getInstance/getLogs/completeTask/cancel`) are used identically in store + tests; `NodeVisualStatus` values (`pending/active/done/failed`) match across node-status, store, and canvas; `TaskFormSpec.kind` (`approval/fields/json`) consistent across task-form + `TaskInputPanel`.
- **Known assumption to verify in Task 8:** whether `complete_task` accepts timer tasks; plan handles both outcomes.
