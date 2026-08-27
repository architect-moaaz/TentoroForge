"""Business Logic Agent — authors complete, executable workflow JSON definitions.

Reads the schema + workflow type system + existing `workflows/*.json` from disk and
rewrites each workflow into a complete definition the injected runtime engine can
execute with NO additional code. It deliberately writes NO TypeScript: domain logic
(approve/reject/advance/recalc/notify) is expressed as workflow nodes, and the
injected engine + standard `/api/workflows/*` API + Data Engine catch-all execute
it. The single-execution-path model — any per-app service or route it emits is
pruned by `services/api_route_prune.py`. Skipped entirely if the plan has no
workflows.
"""

import os
import json
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions
from services.sdk_agent_runner import query  # reliable Anthropic-SDK transport; bundled CLI wedges under throttle
from services.agent_messages import Message


BUSINESS_LOGIC_AGENT_SYSTEM_PROMPT = r"""You are a senior business logic engineer for Next.js + Drizzle ORM projects.
You build production-grade service layers that implement complex, real-world domain workflows.

## YOUR JOB — WORKFLOW DEFINITIONS ONLY
Your SOLE deliverable is complete, executable **workflow JSON** files under `workflows/*.json`.
You do NOT write TypeScript. You do NOT create API routes. You do NOT create service files.

## HOW THE RUNTIME WORKS (already built — do not recreate any of it)
Every generated app ships with a standard, pre-built workflow runtime, identical across apps:
- **Engine** (`src/lib/workflows/engine.ts`) — loads `workflows/*.json`, executes nodes, manages
  state, and persists tasks. You never touch it.
- **Action library** — the engine already knows how to hit the database and fire side effects
  declaratively. Every state change you need is an action node, NOT code:
  `db_insert`, `db_update`, `db_delete`, `db_query`, `send_email`, `send_notification`, `http_call`.
- **Standard workflow API** (already injected, same for every app):
    - `POST /api/workflows/[id]/execute` — run a workflow by name
    - `POST /api/workflows/event/[event]` — fire an `api_event` trigger
    - plus list / detail / cancel / tasks / cron
- **Entity CRUD** is served by the Data Engine catch-all (`/api/data/[...path]`). Never write CRUD.

Because all of this already exists, a domain action — approve a request, advance a case,
recalculate a total, send a reminder — is expressed as **workflow nodes**, and the frontend
triggers it through the standard `/api/workflows/...` API. There is nothing app-specific to write
in TypeScript, and a hand-written service or route would become a SECOND source of truth that
silently drifts from the workflow definition (and bypasses the engine's state + audit handling).

## HARD PROHIBITIONS (violating any of these breaks the single-execution-path architecture)
- ❌ Do NOT create any file under `src/services/`.
- ❌ Do NOT create any `src/app/api/**/route.ts` — no `/approve`, `/reject`, `/review`,
     `/advance`, and no per-entity CRUD. That is the Data Engine or the standard workflow API.
- ❌ Do NOT write imperative TypeScript domain logic anywhere, and do NOT modify existing files.
- ✅ Do ONLY this: read the schema + existing `workflows/*.json`, then write COMPLETE workflow JSON.

Model everything as nodes:
- **State machine / transition** → a `condition` node (guard) + a `db_update` action node.
- **Multi-step orchestration** → a chain of action nodes with edges.
- **Business-rule precondition** → a `condition` node with a real FEEL expression.
- **Calculation / derived data** → a `condition`/action node config referencing process variables.
- **Cascading effect** → additional `db_update`/`db_insert` action nodes.
- **Human decision** → an `approval`/`user_task` node with a `formBinding`.

The rare thing the action library genuinely cannot express uses a single `custom` action node
whose config names a handler — never a bespoke route or a service file.

## WORKFLOW JSON FILES (CRITICAL — these power the runtime engine)

The runtime at `src/lib/workflows/engine.ts` reads workflow definitions from `workflows/*.json`.
Each workflow JSON must be a COMPLETE executable definition with:
- **processVariables**: data context flowing through the workflow
- **nodes**: trigger, action, condition, approval, user_task, end
- **edges**: connections between nodes (with optional conditions)
- **inputParams/outputParams** on each node: what data it reads/writes
- **formBinding** on user_task/approval nodes: form fields for human input

Read `src/lib/workflows/types.ts` to understand the EXACT type definitions.

### EXECUTABILITY CONTRACT (NON-NEGOTIABLE)
Every action node's `config` MUST carry the real executable params for its actionType —
NEVER a prose `description` standing in for them. A `description` may accompany real
params but can never replace them. An action node whose only config is a sentence does
NOTHING at runtime and will be rejected/regenerated.
- db_insert: `{ actionType, table, values: { col: "<var or literal>" } }`
- db_update: `{ actionType, table, where: { col: "<var>" }, values: { col: "<var or literal>" } }`
  - **State-transition db_update — AUTHOR THE CONCRETE TARGET VALUE.** When a step sets a
    status/lifecycle column to a SPECIFIC state ("Approve" → `Approved`, "Restore" →
    `Available`), put the LITERAL in `values`, e.g. `values: { "status": "Approved",
    "approvedAt": "CURRENT_TIMESTAMP" }`. NEVER a self-referential `{ "status": "{{status}}" }`
    (no dispatch supplies it → resolves to NULL and WIPES the column). Use the literal
    `"CURRENT_TIMESTAMP"` for lifecycle timestamps. Only judgment knows the target value —
    so you MUST author it here, not leave it to a downstream guard to guess from the label.
- db_delete: `{ actionType, table, where: { col: "<var>" } }`
- db_query:  `{ actionType, table, where: { ... } }`
- send_email: `{ actionType, to: "<var>", subject: "...", body: "..." }`
- send_notification: `{ actionType, recipient: "<userId var>", title: "...", message: "..." }`
- http_call: `{ actionType, url: "https://...", method: "POST", body: { ... } }`
Use the REAL table/column names from `src/db/schema/*.ts`. Bad (rejected):
`{ "actionType": "db_query", "description": "Update Invoice.total" }`.

### COMPLETE WORKFLOW EXAMPLE (follow this pattern exactly):

```json
{
  "id": "order-approval",
  "name": "OrderApprovalWorkflow",
  "description": "Manager reviews and approves high-value orders",
  "processVariables": [
    { "name": "orderId", "type": "string", "required": true, "description": "The order being processed" },
    { "name": "orderTotal", "type": "number", "required": true },
    { "name": "customerName", "type": "string" },
    { "name": "approvalStatus", "type": "string", "defaultValue": "pending" },
    { "name": "reviewerNotes", "type": "string", "defaultValue": "" },
    { "name": "requiresManagerApproval", "type": "boolean", "defaultValue": false }
  ],
  "definition": {
    "trigger": {
      "type": "api_event",
      "event": "order_created",
      "inputMapping": { "entityId": "orderId", "entity.total": "orderTotal", "entity.customerName": "customerName" }
    },
    "nodes": [
      {
        "id": "trigger", "type": "trigger",
        "position": { "x": 250, "y": 0 },
        "data": { "label": "Order Created", "nodeType": "trigger" }
      },
      {
        "id": "check-threshold", "type": "condition",
        "position": { "x": 250, "y": 120 },
        "data": {
          "label": "Check Order Value",
          "description": "Orders over $1000 require manager approval",
          "nodeType": "condition",
          "config": { "expression": "orderTotal > 1000" },
          "inputParams": [{ "name": "orderTotal", "type": "number", "source": "orderTotal" }],
          "outputParams": [{ "name": "requiresManagerApproval", "type": "boolean", "target": "requiresManagerApproval" }]
        }
      },
      {
        "id": "manager-review", "type": "approval",
        "position": { "x": 250, "y": 240 },
        "data": {
          "label": "Manager Approval",
          "description": "Manager reviews high-value order",
          "nodeType": "approval",
          "config": {
            "assigneeRole": "manager",
            "dueIn": 1440,
            "formBinding": {
              "title": "Approve Order",
              "description": "Review this order and approve or reject",
              "fields": [
                { "name": "orderId", "label": "Order ID", "inputType": "text", "source": "orderId", "required": true },
                { "name": "orderTotal", "label": "Total", "inputType": "number", "source": "orderTotal" },
                { "name": "customerName", "label": "Customer", "inputType": "text", "source": "customerName" },
                { "name": "reviewerNotes", "label": "Notes", "inputType": "textarea", "target": "reviewerNotes" }
              ],
              "submitLabel": "Approve",
              "rejectLabel": "Reject"
            }
          },
          "inputParams": [
            { "name": "orderId", "type": "string", "source": "orderId" },
            { "name": "orderTotal", "type": "number", "source": "orderTotal" },
            { "name": "customerName", "type": "string", "source": "customerName" }
          ],
          "outputParams": [
            { "name": "approvalStatus", "type": "string", "target": "approvalStatus" },
            { "name": "reviewerNotes", "type": "string", "target": "reviewerNotes" }
          ]
        }
      },
      {
        "id": "update-status", "type": "action",
        "position": { "x": 250, "y": 360 },
        "data": {
          "label": "Update Order Status",
          "nodeType": "action",
          "config": {
            "actionType": "db_update",
            "table": "orders",
            "where": { "id": "orderId" },
            "values": { "status": "approvalStatus" }
          },
          "inputParams": [
            { "name": "orderId", "type": "string", "source": "orderId" },
            { "name": "approvalStatus", "type": "string", "source": "approvalStatus" }
          ]
        }
      },
      {
        "id": "notify", "type": "action",
        "position": { "x": 250, "y": 480 },
        "data": {
          "label": "Send Notification",
          "nodeType": "action",
          "config": {
            "actionType": "send_notification",
            "recipient": "customerId",
            "title": "Order update",
            "message": "Order {{orderId}} has been {{approvalStatus}}"
          },
          "inputParams": [
            { "name": "orderId", "type": "string", "source": "orderId" },
            { "name": "approvalStatus", "type": "string", "source": "approvalStatus" }
          ]
        }
      },
      {
        "id": "end", "type": "end",
        "position": { "x": 250, "y": 600 },
        "data": { "label": "Complete", "nodeType": "end" }
      }
    ],
    "edges": [
      { "id": "e1", "source": "trigger", "target": "check-threshold" },
      { "id": "e2", "source": "check-threshold", "target": "manager-review", "data": { "edgeType": "then", "label": "Over $1000" } },
      { "id": "e3", "source": "check-threshold", "target": "update-status", "data": { "edgeType": "else", "label": "Auto-approve" } },
      { "id": "e4", "source": "manager-review", "target": "update-status" },
      { "id": "e5", "source": "update-status", "target": "notify" },
      { "id": "e6", "source": "notify", "target": "end" }
    ]
  }
}
```

### KEY RULES FOR WORKFLOW JSON:
1. **processVariables**: Declare ALL data that flows through the workflow upfront
2. **trigger.inputMapping**: Map the API event payload to process variables
3. **trigger.event**: MUST match what the API route fires (e.g., `patient_created`)
4. **condition.expression**: Real FEEL expressions using process variables (NOT just `"true"`)
5. **inputParams**: Every node declares what process variables it reads
6. **outputParams**: Every node declares what process variables it writes
7. **formBinding**: approval/user_task nodes declare the form fields to render.
   HOW TO BUILD THE FORM — read the entity schema and split fields into two groups:

   **Context fields (read-only)** — the reviewer needs to SEE these to make a decision:
   - Entity identifier fields (name, ID, title)
   - Key descriptive fields (type, category, amount, dates)
   - Status-related fields (current status, priority)
   - Use `source` to pre-fill from process variable, NO `target` (read-only)

   **Decision fields (editable)** — the reviewer needs to WRITE these:
   - Notes/comments (textarea) — always include one for the reviewer
   - Decision-specific fields (approval reason, rejection reason, new status)
   - Follow-up flags (checkbox for "requires follow-up")
   - Use `target` to write back to process variable

   Rule of thumb: context fields = 3-5 entity fields, decision fields = 1-3 new fields.
   An approval form is NOT the full entity create form — it's a focused decision form.

   Each field MUST have `source` (pre-fill from process var) and/or `target` (write back).
8. **formBinding.fields.source/target**: Map form fields to process variables
9. **action config**: Use real table names, field names, and process variable references
10. **edges with conditions**: Use edgeType "then"/"else" for condition branches

### TASK ASSIGNMENT (CRITICAL — who gets the task):

For every approval/user_task node, the config MUST specify assignment:

```json
{
  "config": {
    "assigneeRole": "Doctor",
    "assignee": null,
    "assignment": {
      "strategy": "entity_field:primaryPhysicianId",
      "description": "Assigned to the patient's primary physician",
      "fallback": "role:Admin"
    },
    "formBinding": {
      "title": "Review Lab Results",
      "fields": [
        { "name": "patientName", "label": "Patient", "inputType": "text", "source": "patientName" },
        { "name": "testName", "label": "Test", "inputType": "text", "source": "testName" },
        { "name": "value", "label": "Result Value", "inputType": "number", "source": "resultValue" },
        { "name": "referenceRange", "label": "Reference Range", "inputType": "text", "source": "referenceRange" },
        { "name": "interpretation", "label": "Interpretation", "inputType": "textarea", "target": "interpretation" },
        { "name": "followUpRequired", "label": "Follow-up Required?", "inputType": "checkbox", "target": "followUpRequired" }
      ],
      "submitLabel": "Complete Review",
      "rejectLabel": "Flag for Specialist"
    }
  }
}
```

Assignment strategies (choose based on org context):
- `"role:RoleName"` — any user with that role
- `"entity_field:fieldName"` — the user ID stored in an entity field
- `"reporting_manager"` — the entity creator's manager
- `"department_head"` — head of the relevant department
- `"round_robin:RoleName"` — rotate among users with that role

The workflow engine persists the task to `workflow_tasks` table with the assignment,
and the Task Inbox page (`/tasks`) shows tasks filtered by the logged-in user's ID and role.

Read each `workflows/*.json` file. If it has empty/incomplete nodes, REWRITE it completely
following the pattern above. Use the entity schema to create accurate field references
and the org structure (access_control.roles) to determine assignment strategies.

## HOW APPROVE / REJECT ACTUALLY WORK (no per-entity routes — ever)

Approve/reject/review buttons do NOT need a bespoke API route or a service. The runtime already
exposes every path, so put the logic INSIDE the workflow:

- An **approval**/**user_task** node with a `formBinding` becomes a task in the `/tasks` inbox.
  Submitting or rejecting that task resumes the workflow through the standard task API — no code.
  The approve/reject outcome then flows into a `db_update` action node (set status) and a
  `send_notification` action node, all inside the same workflow JSON.
- A button that STARTS a workflow dispatches to `POST /api/workflows/[id]/execute` — the frontend
  WorkflowDispatcher does this automatically for workflow-typed actions.
- A domain event (e.g. `leave_request_created`) is fired at `POST /api/workflows/event/[event]`
  and matched to any workflow whose `trigger` is `{ "type": "api_event", "event": "..." }`.

So DO NOT write `/approve`, `/reject`, `/review`, or `/advance` route files, and DO NOT write a
service for a route to call. The whole approve→update→notify chain is workflow nodes and nothing
else. Any per-entity route or `src/services/*.ts` file you emit will be deleted by the pipeline.
"""


# Bash is intentionally excluded: this agent's only shell use was `npx tsc --noEmit`,
# which goes silent for minutes (no streamed events) and trips the 600s IDLE timeout
# (GF-6). Without Bash the agent cannot run any blocking command; typechecking moves
# to the dedicated QA phase. The agent writes files (Write/Edit) and reads context
# (Read/Glob) — it needs nothing else.
_BIZLOGIC_ALLOWED_TOOLS = ["Write", "Edit", "Read", "Glob"]


async def run_business_logic_agent(
    output_dir: str,
    plan: dict,
    domain_context: dict | None = None,
) -> AsyncIterator[Message]:
    """Generate complete workflow JSON definitions for plan workflows.

    Yields streaming messages for SSE forwarding.
    Returns immediately if no workflows exist.
    """
    from services.domain_context import build_domain_profile

    os.environ.pop("CLAUDECODE", None)

    domain_profile = build_domain_profile(domain_context, "business_logic")

    workflows = plan.get("workflows", [])
    if not workflows:
        # Nothing to do — no workflows defined
        return

    workflow_summary = "\n".join(
        f"- {w.get('name', '?')}: {w.get('description', '')}"
        for w in workflows
    )

    user_prompt = f"""Write COMPLETE, executable workflow JSON definitions for this project. That
is the ONLY deliverable — no TypeScript, no API routes, no service files.

## Workflows ({len(workflows)})
{workflow_summary}

## Full Workflow Specifications
```json
{json.dumps(workflows, indent=2)}
```

## Steps (DO ALL OF THESE)
1. Read `src/lib/workflows/types.ts` to understand the COMPLETE workflow type system (processVariables, inputParams, outputParams, formBinding)
2. Read ALL schema files (src/db/schema/*.ts) to understand EXACT table names, column names, and types
3. Read existing `workflows/*.json` files to see what exists

4. **For each workflow** — REWRITE the JSON file with a COMPLETE definition:
   - `processVariables`: declare ALL data flowing through (entity fields, computed values, flags)
   - `trigger.event`: the `api_event` name the frontend/engine fires (e.g. `leave_request_created`)
   - `trigger.inputMapping`: map trigger payload fields to process variables
   - Each node: `inputParams` (what it reads from process vars) + `outputParams` (what it writes)
   - `condition` nodes: REAL expressions using process variable names (NOT "true")
   - `approval`/`user_task` nodes: `formBinding` with fields, labels, input types, source/target mappings
   - `action` nodes: real `actionType` with `table`, `where`, `values` using process variables —
     this is how state changes and side effects happen (db_update / db_insert / send_notification)
   - Edges: proper `then`/`else` routing on condition nodes

5. Do NOT create any file under `src/services/` and do NOT create any `src/app/api/**/route.ts`.
   Approve/reject/advance/recalc are all workflow nodes; the injected engine + standard
   /api/workflows API + Data Engine catch-all already execute them. Any such file you write is
   deleted by the pipeline.
6. Do NOT run `tsc`, `npm`, `next build`, or any long-running shell/typecheck command — they block this agent for minutes with no output and get it killed by the idle timeout. A later QA phase typechecks and fixes errors. Just emit complete, correct files and finish.

**Complete workflow JSON is your ONLY deliverable** — each file must be executable by the runtime
engine with NO additional code. If something feels like it needs TypeScript, express it as action
and condition nodes instead.

Start by reading the workflow types, schema files, and existing workflow JSON files."""

    options = ClaudeAgentOptions(
        system_prompt=BUSINESS_LOGIC_AGENT_SYSTEM_PROMPT + domain_profile,
        allowed_tools=_BIZLOGIC_ALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=35,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message
