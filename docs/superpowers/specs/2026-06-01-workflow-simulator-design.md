# Workflow Simulator — Design Spec

**Date:** 2026-06-01
**Status:** Approved (design) — pending implementation plan
**Scope:** A "Simulate" mode in the Workflows tab that runs a real workflow through the **actual backend runtime engine**, renders the **real workflow graph**, greys out completed nodes as it runs, and prompts for input wherever the engine pauses.

---

## 1. Problem

The current workflow tester (`frontend/src/components/workflow/WorkflowTester.tsx`) is a
**fake client-side simulation**: it walks the node graph with random branch choices and
artificial delays, skips all human-input nodes, and never calls the backend. It cannot be
used to *verify* a workflow.

Meanwhile the backend already has a complete **step-by-step runtime engine**
(`backend/runtime/engine.py`) that executes real workflows, pauses at human-input nodes,
persists state, and logs every node. The gap is a UI that drives that engine and
visualizes the run on the actual workflow graph.

## 2. Goal & non-goals

**Goal:** Let a user select a workflow, fill in the trigger inputs, run it through the real
engine, watch completed nodes grey out on the actual workflow graph in (near) realtime, and
provide input wherever the engine pauses (approvals, assignments, task pools) — so the
workflow is genuinely **verified** end-to-end.

**Non-goals (this iteration):**
- True per-node server-sent streaming (we poll + replay-animate instead).
- Editing the workflow from the simulator (read-only canvas).
- Multi-user / real assignee routing (the operator provides all inputs themselves).
- Honoring real timer durations (timers are fast-forwarded — see §6).

## 3. Key constraint: render the ACTUAL workflow

The simulator MUST show the same graph the user built — same nodes, edges, branch handles,
and layout — not a re-drawn or simplified version. This is achieved **by construction**:
the simulator reuses the editor's exact React Flow components
(`frontend/src/components/workflow/WorkflowCanvas.tsx`,
`.../nodes/WorkflowNode.tsx`, `.../edges/ConditionalEdge.tsx`) and loads the real
definition via `GET /workflows/{id}`, running the same dagre auto-layout. Execution state is
only an **overlay** painted on top (node status colors + taken-branch highlight); there is no
separate drawing that could drift.

## 4. Architecture

Frontend-heavy orchestration over endpoints that already exist in
`backend/routers/workflows.py`:

| Step | Endpoint | Purpose |
|---|---|---|
| start | `POST /api/projects/{pid}/workflows/start` `{workflow_id, variables, initiated_by?}` | Create real `WorkflowInstance`; engine runs first segment, returns instance (status `running`/`waiting`/`completed`) |
| status | `GET /api/projects/{pid}/workflow-instances/{id}` | `status`, `current_node_ids`, variables, tasks |
| logs | `GET /api/projects/{pid}/workflow-instances/{id}/logs` | Per-node logs (id, node_id, node_type, status `started/completed/failed/skipped`, snapshots, duration, error) — drives the greying animation |
| tasks | `GET /api/projects/{pid}/tasks?instance_id={id}` | Paused task(s) needing input |
| resume | `POST /api/projects/{pid}/tasks/{task_id}/complete` `{output_data}` | Provide input, engine continues next segment |
| reset | `POST /api/projects/{pid}/workflow-instances/{id}/cancel` | Cancel current run |

Engine reference (read-only dependency, no changes expected):
`WorkflowRuntimeEngine.start_workflow()` (engine.py:44), `complete_task()` (engine.py:102);
pauses at `assignment`/`approval`/`user_task`/`task_pool`/`escalation` and timer nodes,
setting status `waiting` and populating `current_node_ids`; logs via `ExecutionLogger` into
`node_execution_logs`.

## 5. Components (new, frontend)

All under `frontend/src/components/workflow/simulator/` unless noted.

1. **`useWorkflowSimulation.ts`** (hook / store) — the state machine:
   `idle → starting → running → (replaying logs) → awaitingInput → (submit) → running → … → completed | failed`.
   Responsibilities: call start; poll `instance`+`logs`+`tasks` every ~500ms while
   `running|waiting`; diff new logs and emit them to an animation queue (stagger ~250ms) so
   nodes grey out one-by-one; expose `nodeStatuses` map + current paused task(s); submit
   task completion; fast-forward timers (§6); cancel/reset. Pure logic, API injected for tests.

2. **`WorkflowSimulator.tsx`** — orchestrator: toolbar (workflow selector, Run, Reset,
   status badge) + reused canvas + right rail. Replaces `WorkflowTester.tsx` as the tab's
   test surface (old file removed or reduced to a thin re-export during transition).

3. **`TriggerInputForm.tsx`** — generates the trigger form from the workflow's declared
   inputs (`processVariables` and/or trigger node `config`), typed fields where known;
   **falls back to a JSON editor** when no schema is present. Produces the `variables` for
   `start`.

4. **`TaskInputPanel.tsx`** — form for a paused task: approve/reject (+ optional comment)
   for `approval` nodes; the task's expected output fields (from node `config`/`input_data`)
   for `assignment`/`user_task`/`task_pool`; generic key-value fallback. Produces
   `output_data` for `complete`.

5. **Canvas overlay extension** (small, in `WorkflowCanvas.tsx`/`WorkflowNode.tsx`):
   accept a `nodeStatuses: Record<nodeId, 'done'|'active'|'pending'|'failed'>` and an
   optional set of taken-branch edge ids. Map status → existing status-ring styles; dim
   not-reached nodes; strike-through/grey done nodes; highlight the active/paused node.
   The canvas already exposes `activeNodeId`.

6. **Variables inspector** (panel within the rail) — shows current instance `variables`
   (trigger inputs, task outputs, decision results) as it evolves.

## 6. Timer / wait / SLA nodes

**Fast-forward** (chosen default; easily changeable later). When the engine pauses on a
timer/wait/escalation-SLA node, the simulator immediately advances it and shows a
"timer skipped (Xd)" marker on the node.

**Implementation note (verify-then-decide):** prefer reusing
`POST /tasks/{task_id}/complete` on the timer task (the `TimerScheduler` already resumes via
the same `complete_task` flow). If `complete_task` rejects a `timer_event` task type, add a
thin `POST /api/projects/{pid}/tasks/{task_id}/fire-timer` endpoint that invokes the resume
path. **This is the only potential backend change in this spec.**

## 7. Realtime model

No server streaming. While the instance is `running`/`waiting`, the hook polls and, for each
newly-seen `node_execution_log`, pushes it onto an animation queue that reveals node-status
changes with a short stagger. Because auto-segments execute server-side in one synchronous
request, the staggered replay is what the user perceives as "watching it run"; human pauses
are real engine pauses. Polling stops on `completed`/`failed`/`cancelled`.

## 8. Error handling

- Node failure: `node_execution_log.status = failed` (+ `error_message`) → node painted red,
  error surfaced in the rail; run halts at the failed node.
- `start`/`complete` HTTP failure: inline error in the rail, run state goes to `failed`/idle;
  the tab never crashes.
- Timeout/stuck poll: bounded poll (e.g. stop after N idle polls with a "still running…"
  notice) so the UI can't spin forever.
- Missing trigger schema: JSON fallback (§5.3).

## 9. Persistence

Runs are **real `WorkflowInstance` rows** (the engine being real is the point). No new tables.
"Reset / New run" = cancel current instance (if any) + start a fresh one. Cleanup of old test
instances is out of scope (existing cancel suffices; a delete endpoint is not required).

## 10. Testing (TDD)

- **Hook** (`useWorkflowSimulation`) with injected/mocked API: state machine transitions
  (start → running → awaitingInput → completed); log-diff → animation queue; fast-forward
  timer path; complete→resume; cancel; failure → `failed`.
- **`TriggerInputForm`**: generates typed fields from a sample trigger schema; JSON fallback
  when none.
- **`TaskInputPanel`**: approval (approve/reject + comment) vs generic output fields → correct
  `output_data` shape.
- **Canvas overlay**: given logs+instance, computes the correct `nodeStatuses` map and
  taken-branch highlight.
- **Backend** (only if the `fire-timer` endpoint is added): unit test the fast-forward path.
- **Manual/integration**: a real seeded project workflow (e.g. an approval flow) run
  end-to-end through the engine, including a human pause and a fast-forwarded timer.

## 11. Risks

- **Trigger/task input schemas are inconsistent across workflows** → mitigated by JSON
  fallback and generic key-value forms; verify against real generated workflow definitions
  during implementation.
- **Timer fast-forward** may need the small backend endpoint (§6) — confirm
  `complete_task` behavior on `timer_event` tasks early.
- **Poll cadence vs animation**: ensure the animation queue is the single source of node
  reveal timing so fast polls don't make nodes flash; drain the queue independent of poll
  interval.
- **Replacing `WorkflowTester`**: confirm no other surface imports it before removal; keep a
  thin shim if needed.
