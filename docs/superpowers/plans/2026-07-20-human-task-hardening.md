# Slice E — Human-Task Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Human tasks (`user_task` / `approval` nodes) in a generated workflow are assigned to the right person deterministically, that person is notified automatically, the task appears in a first-class inbox UI the pipeline emits (not LLM-guessed), completion resumes the workflow without re-running side effects, and the whole path is validated by the SUBMIT-AUTHORITY contract.

**Architecture:** Six-layer strengthening of the existing (partial) task lifecycle discovered in the audit: (1) template the `workflow_tasks` schema so it's guaranteed to exist; (2) template the `/tasks` inbox + detail pages so every app has them; (3) implement the assignment strategies the planner already advertises but runtime doesn't honor; (4) auto-emit `send_notification` for every `user_task` at gen time; (5) resume-idempotency (skip already-completed upstream nodes); (6) add `submit.kind=workflow_resume` to the SUBMIT-AUTHORITY contract so task-completion forms flow through the same validators/guards.

**Tech Stack:** Python 3.11, TypeScript (runtime templates), Drizzle schema, pytest, no runtime framework changes.

**Branch:** `forge-v3-smith-orchestrator-v2` (or new `forge-v3-human-tasks`)

**Depends on:** Slice A (SUBMIT-AUTHORITY contract) live and stable — E6 extends it.

**Blocks:** anything domain-specific that involves multi-actor flows (recruitment approvals, procurement, compliance sign-off, medical charting review) — those all need this to ship first.

---

## Motivation (from live audit on `output/4ct3h8z2`)

Audit found:

- **Node types exist**: `user_task` + `approval` at `engine.ts:292-361`. Both pause via `waitingForHumanAction=true`.
- **3 assignment strategies implemented** at runtime (`index.ts:151-184`): static, `round_robin`, `load_balanced`. **5+ advertised** in the planner prompt (`entity_field`, `creator`, `reporting_manager`, `department_head`, `group`) — none implemented, silently degrade.
- **Notification is manual**: nothing auto-fires on task creation. Author must place a `send_notification` node beside every `user_task` or the assignee only finds out by polling `/tasks`.
- **`workflow_tasks` table**: no Drizzle schema template. `persistPendingTask` uses raw SQL wrapped in a try/catch that never throws (`index.ts:144`). If the LLM planner didn't emit a `WorkflowTask` data model → every task silently vanishes.
- **Task inbox UI**: `/api/tasks/route.ts` is templated (`runtime_injector.py:1213-1266`), but `src/app/tasks/page.tsx` is NOT. The LLM page agent has to build it per app; some apps get nothing.
- **Resume works**: `/api/workflows/[id]/execute` accepts `taskId` OR `__decision + entityId`, injects `__step_<node>_completed/_decision`, re-runs from trigger.
- **Resume re-runs upstream steps**: any `db_insert`/`db_update` before the approval fires again on resume — no idempotency guard.
- **Email off by default**: `RESEND_API_KEY` required; without it, silent in-app fallback only.
- **Dead orphan engine**: `templates/workflow-engine/` + `workflow-api-routes/` define a whole parallel system nothing references.

The invariant we want: **a workflow with a `user_task` node is guaranteed to reach a real human, they know about it, they can act on it, and their action resumes the workflow correctly — with no LLM authoring judgment in the load-bearing path.**

## Non-goals

- Multi-assignee tasks (parallel approval by N reviewers) — v2
- Task delegation / reassignment — v2
- Task escalation (nudge if not completed in N days) — v2
- SLA / due-date enforcement — v2
- Mobile push notifications — v2 (in-app + email only in v1)
- Deleting the orphan engine trees — E7, but low priority once E1-E6 land

## Contract additions

### `plan.workflows[].nodes[].config` — assignment strategies

Extend the runtime `_resolveAssignee` to honor every strategy the planner already advertises. Contract already exists on the planner side; runtime must catch up:

```typescript
type AssignmentStrategy =
  | { strategy: "static"; value: string }              // user id, works today
  | { strategy: "role"; value: string }                // resolve to any user with role
  | { strategy: "round_robin"; pool: string }          // works today
  | { strategy: "load_balanced"; pool: string }        // works today
  | { strategy: "creator" }                            // NEW: workflow.startedBy
  | { strategy: "entity_field"; field: string }        // NEW: e.g. candidate.assignedRecruiterId
  | { strategy: "reporting_manager"; user: string }    // NEW: user.managerId
  | { strategy: "department_head"; department: string } // NEW
  | { strategy: "group"; group: string }                // NEW: users.groups[] contains
```

### `plan.workflows[].nodes[].notification`

Optional block that auto-attaches a notification when this node fires. If omitted, generation adds a default (see E4):

```json
"notification": {
  "channel": "in_app" | "email" | "both",
  "subject": "Feedback awaits — {{candidate.fullName}}",
  "body":    "Please review the interview feedback for {{candidate.fullName}}.",
  "cta":     { "label": "Open task", "route": "/tasks/{{taskId}}" }
}
```

### `plan.pages[].submit.kind = "workflow_resume"` (extends Slice A contract)

New submit-kind for task-completion forms. Dispatches through `/api/workflows/[id]/execute` with `taskId` sourced from the URL:

```json
{
  "name": "TaskCompletionForm",
  "type": "form",
  "route": "/tasks/[id]",
  "submit": {
    "kind":    "workflow_resume",
    "target":  "SubmitFeedbackWorkflow",
    "task_id": {"kind": "route", "param": "id"}
  }
}
```

Validators from Slice A T3 extend: `submit.task_id.kind` must be `route` (v1), and `submit.target` must name a workflow whose `user_task` nodes exist. Guards from T7/T8 extend to check every declared `workflow_resume` form actually resumes a real workflow.

## File structure

**New files (templates):**
- `backend/templates/runtime/db/workflow-tasks.schema.ts` — Drizzle schema for `workflow_tasks` (E1)
- `backend/templates/app-foundation/src/app/tasks/page.tsx` — task inbox (E2)
- `backend/templates/app-foundation/src/app/tasks/[id]/page.tsx` — task detail + action form (E2)

**New files (services):**
- `backend/services/task_assignment_strategies.py` — server-side helpers for the 5 new strategies (E3)
- `backend/services/task_notification_defaults.py` — deterministic auto-injection of notification blocks (E4)
- `backend/services/workflow_resume_idempotency.py` — mark/skip already-completed upstream nodes (E5)

**New tests:**
- `backend/tests/services/test_task_assignment_strategies.py`
- `backend/tests/services/test_task_notification_defaults.py`
- `backend/tests/services/test_workflow_resume_idempotency.py`
- `backend/tests/services/test_submit_authority_workflow_resume.py`

**Modified files:**
- `backend/templates/runtime/workflows/index.ts` — extend `_resolveAssignee` with 5 new strategies (E3)
- `backend/templates/runtime/workflows/engine.ts` — resume-idempotency: skip nodes whose completion flag is present (E5)
- `backend/services/runtime_injector.py` — copy the new task schema + inbox pages (E1, E2)
- `backend/services/submit_authority.py` — accept `workflow_resume` kind (E6)
- `backend/services/plan_validator.py` — extend rules for `workflow_resume` submit (E6)
- `backend/services/submit_authority_guards.py` — extend `form_target_guard` for the new kind (E6)
- `backend/services/post_generate_fixes.py` — call `task_notification_defaults.inject_missing()` (E4)
- `backend/agents/planner.py` — remove advertised strategies that runtime still doesn't implement (or list only the working ones) after E3

**Deleted (E7):**
- `backend/templates/workflow-engine/` (entire tree)
- `backend/templates/workflow-api-routes/` (entire tree)

---

## Tasks

### Task E1: Template the `workflow_tasks` Drizzle schema

**Files:**
- Create: `backend/templates/runtime/db/workflow-tasks.schema.ts`
- Modify: `backend/services/runtime_injector.py` — copy the file
- Test: `backend/tests/services/test_runtime_injector_task_schema.py` (new)

- [ ] **Step 1: write failing test — after `runtime_injector.copy_runtime(...)` runs, `src/db/schema/workflow-tasks.ts` exists with expected columns (`id`, `workflow_id`, `workflow_run_id`, `node_id`, `assignee_id`, `assignee_role`, `status`, `process_variables`, `created_at`, `completed_at`, `completed_by`, `decision`).**

- [ ] **Step 2: implement the template — Drizzle schema matching the columns `persistPendingTask` writes to today (audit the raw SQL in `index.ts:186-231` for the exact column list).**

- [ ] **Step 3: extend `runtime_injector.py` to copy the file into every generated app's `src/db/schema/`.**

- [ ] **Step 4: verify against a generated app — copy runtime, run migrations, verify the table exists.**

- [ ] **Step 5: commit — `feat(runtime): template workflow_tasks Drizzle schema`**

### Task E2: Template the `/tasks` inbox + `/tasks/[id]` detail pages

**Files:**
- Create: `backend/templates/app-foundation/src/app/tasks/page.tsx`
- Create: `backend/templates/app-foundation/src/app/tasks/[id]/page.tsx`
- Modify: `backend/services/runtime_injector.py` — copy the two files
- Test: `backend/tests/services/test_task_inbox_template.py` (new)

- [ ] **Step 1: write failing test — after runtime injection, `src/app/tasks/page.tsx` exists and includes a call to `/api/tasks` + renders task rows with Approve/Reject/Open links.**

- [ ] **Step 2: implement the inbox — server-side fetch of `/api/tasks?assigneeId=current`, render as a table with columns (task, workflow, created, actions).**

- [ ] **Step 3: write failing test — `/tasks/[id]/page.tsx` exists and includes the task's `process_variables` context + a form to submit the decision.**

- [ ] **Step 4: implement the detail page — read task by id, render form derived from the workflow's declared inputs (via Slice A T4 form scaffolder), submit dispatches to `/api/workflows/[wfId]/execute` with `taskId`.**

- [ ] **Step 5: register both in `runtime_injector.py`.**

- [ ] **Step 6: commit — `feat(app-foundation): task inbox + detail page templates`**

### Task E3: Implement the 5 advertised assignment strategies

**Files:**
- Create: `backend/services/task_assignment_strategies.py` (server-side helper — computes assignee id from strategy + context)
- Modify: `backend/templates/runtime/workflows/index.ts` — extend `_resolveAssignee`
- Test: `backend/tests/services/test_task_assignment_strategies.py`

- [ ] **Step 1: write failing test — `resolve_assignee({strategy: "creator"}, ctx)` returns `ctx.workflow.startedBy`.**

- [ ] **Step 2: implement `creator` strategy in the Python helper.**

- [ ] **Step 3: write failing test — `resolve_assignee({strategy: "entity_field", field: "assignedRecruiterId"}, ctx)` returns the value of that field on `ctx.entity`.**

- [ ] **Step 4: implement `entity_field` strategy.**

- [ ] **Step 5: repeat pattern for `reporting_manager`, `department_head`, `group`.**

- [ ] **Step 6: port the helper logic into `index.ts::_resolveAssignee` — each strategy runs its DB query.**

- [ ] **Step 7: write integration test — a workflow with `assignment: {strategy: "entity_field", field: "assignedRecruiterId"}` on a candidate resolves to that candidate's recruiter.**

- [ ] **Step 8: commit — `feat(workflows): implement 5 advertised assignment strategies`**

### Task E4: Auto-emit `send_notification` on every `user_task`

**Files:**
- Create: `backend/services/task_notification_defaults.py`
- Modify: `backend/services/post_generate_fixes.py` — call the new pass
- Test: `backend/tests/services/test_task_notification_defaults.py`

- [ ] **Step 1: write failing test — `inject_missing_notifications(plan)` on a workflow with a `user_task` but no adjacent `send_notification` inserts one (with a sensible default subject/body derived from the node label).**

- [ ] **Step 2: implement — walk each workflow's nodes, detect `user_task`/`approval` without a following `send_notification` edge, insert the default node.**

- [ ] **Step 3: write failing test — an existing `send_notification` node isn't duplicated.**

- [ ] **Step 4: register in `apply_post_generate_fixes` — runs before workflow generation writes the runtime JSON.**

- [ ] **Step 5: verify on a generated app — every `user_task` has at least one downstream `send_notification` unless explicitly opted out (`notification: {kind: "none"}` on the node).**

- [ ] **Step 6: commit — `feat(post-gen): auto-emit notifications for human tasks`**

### Task E5: Resume-idempotency guard

**Files:**
- Modify: `backend/templates/runtime/workflows/engine.ts` — extend node executor to check completed-flag before re-running
- Create: `backend/services/workflow_resume_idempotency.py` — server-side helper that marks completed nodes in the workflow's persisted state
- Test: `backend/tests/services/test_workflow_resume_idempotency.py`

- [ ] **Step 1: write failing test — a workflow that db-inserted a row before a `user_task`, then resumes, does NOT insert the row again.**

- [ ] **Step 2: extend engine to persist per-node completion flags after each action node executes.**

- [ ] **Step 3: implement resume: on re-run from trigger, skip any node whose completion flag is set.**

- [ ] **Step 4: write failing test — a `condition` node's already-taken branch is preserved on resume (doesn't re-evaluate).**

- [ ] **Step 5: implement branch-decision persistence.**

- [ ] **Step 6: commit — `feat(runtime): resume-idempotency for human-task workflows`**

### Task E6: `submit.kind = workflow_resume` in SUBMIT-AUTHORITY

**Files:**
- Modify: `backend/services/submit_authority.py` — accept new kind
- Modify: `backend/services/plan_validator.py` — new rule set for workflow_resume
- Modify: `backend/services/submit_authority_guards.py` — form_target_guard tolerates the new kind
- Modify: `backend/agents/planner.py` — SUBMIT-AUTHORITY prompt block adds workflow_resume shape
- Test: `backend/tests/services/test_submit_authority_workflow_resume.py`

- [ ] **Step 1: write failing test — `resolve_page_submit(plan, "TaskForm")` returns `{kind: "workflow_resume", target: "W", task_id: {kind: "route", param: "id"}}`.**

- [ ] **Step 2: extend the helper to accept the new kind + preserve `task_id` verbatim.**

- [ ] **Step 3: write failing test — plan validator flags a `workflow_resume` submit whose `task_id.kind` isn't `route`.**

- [ ] **Step 4: extend validator rules.**

- [ ] **Step 5: write failing test — `form_target_guard` accepts the new kind (was only tolerating `workflow`/`data_api`).**

- [ ] **Step 6: extend guard.**

- [ ] **Step 7: update the planner prompt block to document the new shape + when to use it (task-completion forms, /tasks/[id] pages).**

- [ ] **Step 8: commit — `feat(submit-authority): workflow_resume kind for task forms`**

### Task E7: Mine orphan engine trees, then STOP — they are not orphan

**Second-pass finding (2026-07-21):** an audit revealed that
`backend/templates/workflow-engine/` and
`backend/templates/workflow-api-routes/` are **not strictly orphan**
— they are actively copied into a generated app by
`backend/routers/workflows.py::apply_workflow` (POST
`/api/projects/{id}/workflows/{wfId}/apply`), the endpoint the
editor's `frontend/src/components/workflow/WorkflowPanel.tsx` calls
when the user clicks "Apply Workflow". The trees carry the
`WorkflowEngine` class + `wfInstances` / `wfTaskInstances` /
`wfExecutionLogs` Drizzle schema + a `/api/workflows/{wfId}/complete`
task-completion route that the copy path materializes into
`src/lib/workflow-engine/` and `src/app/api/workflows/`.

The **runtime** engine (`backend/templates/runtime/workflows/`) is a
different tree used by the automatic gen-time injector. Two engines
coexist for two distinct code paths:

- `runtime/workflows/` → materialized on every generation via
  `runtime_injector._generate_workflow_api_route`.
- `workflow-engine/` + `workflow-api-routes/` → materialized on
  demand when the user applies a workflow from the editor.

Neither is dead. Deleting either breaks the corresponding surface.

**Rationale for the revision:** the orphan trees carry runtime
features (`WorkflowEngine.completeTask`, the `wfInstances` schema)
the live-runtime engine doesn't. Some are worth mining; the trees
themselves must stay until either (a) the editor's "Apply Workflow"
flow is switched to also use the runtime engine, or (b) the two are
unified into one. Neither is Slice E scope.

**What's already mined (Slice E early):**

- `evaluateExpression` from `workflow-engine/domain/feel-lite/` was
  wired into `runtime/workflows/input-assembly.ts` for the `computed`
  source kind (Slice E EARLY, commit `c8c0c98`). `computed_unsupported`
  is replaced with `computed_failed`; a `computed` source now
  evaluates FEEL-lite over `{form, route, auth, inputs}`.
- The shipped FEEL-lite already lives at
  `backend/templates/runtime/feel-lite/` (`runtime_injector.py:214`
  copies it into every generated app). No new module was added — the
  input-assembly import path is `../feel-lite` (sibling).

**What can NOT be deleted (verified by audit):**
- `backend/templates/workflow-engine/` — used by
  `backend/routers/workflows.py::apply_workflow` (line 279:
  `shutil.copytree(engine_src, engine_dst)`) to install the
  WorkflowEngine class + wf* Drizzle schema into a generated app
  when the user clicks "Apply Workflow" in `WorkflowPanel.tsx`.
- `backend/templates/workflow-api-routes/` — same code path (line
  285), materializes `/api/workflows/{wfId}/complete` etc.
- Additional references: `backend/services/schema_barrel.py:14`
  (docstring), `backend/tests/services/test_schema_barrel.py:19`
  (test), `runtime_injector` NOT among them — the two engines are
  in truly separate code paths.

**Future work (NOT in Slice E):**
- Decide whether to (a) migrate `apply_workflow` onto the runtime
  engine so the two trees can merge, or (b) accept the split
  permanently. This is an architectural call bigger than
  human-task hardening and needs its own spec.
- If (a): once the editor's Apply path stops copying the orphan
  trees, revisit the delete steps below.

**Follow-up (this session, part of T7 closeout):**
- [x] Update this plan doc to record the finding (this edit).
- [x] Leave the orphan trees in place. Do NOT delete.

**Delete steps (DEFERRED — do not run until `apply_workflow` is
switched away from the orphan trees):**
- [ ] `git grep 'templates/workflow-engine' backend/` — expect zero hits.
- [ ] `git grep 'templates/workflow-api-routes' backend/` — expect zero hits.
- [ ] `rm -rf backend/templates/workflow-engine backend/templates/workflow-api-routes`.
- [ ] Run full test suite — nothing regresses.
- [ ] Commit — `chore: delete orphan workflow-engine + workflow-api-routes trees`.

### Task E8: Live E2E — a full human-task loop on a fresh recruitment app

- [ ] **Step 1: kick off a fresh generation of the recruitment ATS via chat.**

- [ ] **Step 2: verify plan.json has:**
  - `workflow_tasks` in `data_models[]` (or the template shim covers it)
  - Every `user_task` node has a `notification` block (from E4)
  - Every task-completion form has `submit.kind=workflow_resume`

- [ ] **Step 3: verify generated app has:**
  - `src/db/schema/workflow-tasks.ts` (from E1)
  - `src/app/tasks/page.tsx` and `src/app/tasks/[id]/page.tsx` (from E2)

- [ ] **Step 4: boot the app, seed it with candidates + a workflow that has a `user_task`.**

- [ ] **Step 5: trigger the workflow — verify a `workflow_tasks` row is created + assignee is resolved by the declared strategy + a notification row lands in `forge_notifications`.**

- [ ] **Step 6: log in as the assignee, navigate to `/tasks`, complete the task via `/tasks/[id]`.**

- [ ] **Step 7: verify workflow resumes, downstream nodes execute, upstream nodes do NOT re-run (E5).**

- [ ] **Step 8: report the acceptance notes + declare Slice E complete.**

---

## Success criteria

1. Every generated app has a `workflow_tasks` table without depending on the LLM planner emitting it.
2. Every generated app has a `/tasks` inbox + `/tasks/[id]` detail page — pipeline-emitted, not LLM-authored.
3. All 5 advertised assignment strategies work at runtime (audit them by inspecting `_resolveAssignee` after E3).
4. Every `user_task` in a generated workflow has at least one downstream `send_notification` — unless the plan explicitly opts out.
5. Workflow resume after human action does not re-run any `db_insert` / `db_update` that already fired.
6. Task-completion forms flow through SUBMIT-AUTHORITY: `submit.kind=workflow_resume` is a first-class kind with its own validator rules + guard checks.
7. Live E2E: candidate feedback flow (recruitment ATS) round-trips from workflow trigger → task assignment → notification → assignee action → workflow resume without any manual intervention.

## Rollout

- Ship behind no env flag — every new generation gets the hardening.
- Existing generated apps unaffected until re-planned (they retain the current LLM-authored inbox / manual notification wiring).
- E7 (orphan deletion) can be a separate PR — no runtime impact, purely a cleanup.

## Risk

- **`workflow_tasks` template schema drifts from `persistPendingTask` SQL**: audit both against each other at test-time; add an integration test that inserts via the raw SQL and reads via Drizzle to catch schema/SQL drift.
- **Templated inbox pages ignored by LLM page agent**: the page agent might re-author `/tasks/page.tsx` and clobber our template. Mitigation: pre-existing file check in page agent (already exists for other foundation files); confirm it applies here.
- **Assignment strategy DB queries slow at scale**: `load_balanced` already queries `count(open_tasks)` per assignee; the new `entity_field` / `reporting_manager` / `department_head` add one query per resolution. Cache within a workflow run.
- **Resume-idempotency false negatives**: a node marked "completed" that was actually rolled back would be skipped incorrectly. Mitigation: only mark completed AFTER the node's transaction commits.
- **Auto-notification spam**: if E4 emits notifications for every `user_task` without opt-out, some flows will over-notify. Mitigation: opt-out is `notification: {kind: "none"}` at plan time.

## Open decisions

1. **In-app notification renders where?** — Task inbox badge count is obvious. Do we also want a bell icon in the app shell with a dropdown of recent unread notifications? *Recommend: yes, bell + dropdown; small addition to the app-foundation shell template.*

2. **Assignee's task view UI — approve/reject buttons vs full form?** — Some tasks are pure approve/reject (up/down decision); others require the assignee to fill in structured data (interview feedback scores). *Recommend: both — if the `user_task` node has `inputs[]` declared, render a form; otherwise just approve/reject buttons.*

3. **Notification default channel?** — `in_app` is always safe. `email` requires `RESEND_API_KEY`. *Recommend: default to `in_app`; email opts in per node.*

4. **`entity_field` — what if the field is null?** — Fall back to a default assignee (like `role: admin`) or fail the workflow? *Recommend: fall back to `role: admin` and log a warning. Failing the workflow on a null recruiter would break every candidate the CRM ingested before recruiters existed.*

5. **Resume behavior on re-fired trigger** — if the same trigger fires twice for the same entity (e.g., a candidate submits feedback twice), does it start two independent workflow runs or resume the first? *Recommend: default to independent runs; add `dedupe_key` config for workflows that need idempotency at the trigger level (future slice).*

6. **Should E5 (idempotency) also protect against replay from an external trigger source (webhook, queue redelivery)?** — Different problem (trigger-side vs resume-side). *Recommend: no, keep E5 scoped to human-task resume. Trigger-side idempotency is its own slice.*
