"""Contract Agent — generates shared contract files from the plan.

Produces 5 contract files that serve as the glue between all relay agents:
- src/contracts/design-system.tsx (page shells, column renderers, layout patterns)
- src/contracts/api-client.ts (typed fetch wrappers per entity)
- src/contracts/services.ts (business logic interfaces)
- src/contracts/app-model.json (dependency graph)
- contracts/seed-plan.json (seed data generation plan)
"""

import os
import json
from typing import AsyncIterator

from services.agent_messages import ClaudeAgentOptions
from services.sdk_agent_runner import query  # SDK transport (bundled CLI wedges under throttle)
from services.agent_messages import Message


CONTRACT_AGENT_SYSTEM_PROMPT = r"""You are a software architect who generates contract files for a relay team of code generation agents.

## YOUR JOB
Read the plan JSON and produce 7 contract files. These contracts are the SINGLE SOURCE OF TRUTH that all downstream agents read. They must be precise, complete, and consistent with each other.

FIRST: Read `src/contracts/design-spec.json` if it exists — the Design Agent created it with the color palette, typography, component styles, and domain-specific patterns. Your `design-system.tsx` MUST use these exact colors and styles, not invent new ones.

## CONTRACT FILES TO GENERATE

### 1. `src/contracts/design-system.tsx`
Page shell components that every page will import and use:
- `ListPageShell` — wraps list pages (title, description, create button slot, children for table)
- `DetailPageShell` — wraps detail pages (title, back link, action buttons slot, children for content)
- `FormPageShell` — wraps form pages (title, back link, children for form)
- `DashboardShell` — wraps dashboard (title, children for stats/cards)
- Column renderer helpers: `StatusBadge`, `DateCell`, `UserAvatar`, `ActionDropdown`
- Shared tokens: consistent spacing, card patterns

These are REAL React components using Tailwind CSS. They will be imported by page files.
Mark the file with "use client" only if it uses hooks — prefer server-compatible shells.

### 2. `src/contracts/api-client.ts`
Typed fetch wrapper for every entity in the plan.

ALL entity CRUD goes through the Data Engine catch-all route at `/api/data/[entity]`:
```ts
// Base helper
async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err?.error?.message || "Request failed"); }
  return res.json();
}

// For each entity (e.g., "tasks"):
export async function getTasks(opts?: { search?: string; status?: string }): Promise<QueryResult<Task>> {
  const params = new URLSearchParams();
  if (opts?.search) params.set("search", opts.search);
  if (opts?.status) params.set("status", opts.status);
  return apiRequest(`/api/data/tasks?${params}`);  // ← /api/data/ prefix
}
export async function getTask(id: string): Promise<Task> { return apiRequest(`/api/data/tasks/${id}`); }
export async function createTask(data: CreateTaskInput): Promise<Task> {
  return apiRequest("/api/data/tasks", { method: "POST", body: JSON.stringify(data) });
}
export async function updateTask(id: string, data: Partial<Task>): Promise<Task> {
  return apiRequest(`/api/data/tasks/${id}`, { method: "PUT", body: JSON.stringify(data) });
}
export async function deleteTask(id: string): Promise<void> {
  await apiRequest(`/api/data/tasks/${id}`, { method: "DELETE" });
}
export async function getTaskStats(): Promise<{ total: number }> {
  return apiRequest("/api/data/tasks/stats");
}
```
IMPORTANT: ALL CRUD endpoints use `/api/data/[entity]` prefix — the Data Engine handles them.
Workflow endpoints use `/api/workflows/` — the Workflow Engine handles them.
Analytics/dashboard endpoints can use `/api/dashboard/` — custom routes.

- Types derived from plan.data_models fields
- Standard error handling with typed errors
- Must export request/response types for each entity

### 3. `src/contracts/services.ts`
Business logic interfaces for each workflow in plan.workflows:
```ts
export interface OrderService {
  approveOrder(orderId: number, approverId: number): Promise<void>;
  // Side effects: updates order.status, creates audit_log entry, sends notification
}
```
- One interface per workflow area
- Document side effects as comments
- API routes will import and call service implementations
- If no workflows exist, export an empty file with a comment

### 4. `src/contracts/app-model.json`
Dependency graph format:
```json
{
  "name": "App Name",
  "entities": {
    "Order": {
      "table": "orders",
      "schema": "src/db/schema/orders.ts",
      "type": "src/types/orders.ts",
      "api": ["src/app/api/orders/route.ts", "src/app/api/orders/[id]/route.ts"],
      "components": ["src/components/orders/OrderTable.tsx", "src/components/orders/OrderForm.tsx"],
      "pages": ["src/app/orders/page.tsx", "src/app/orders/[id]/page.tsx"],
      "service": "src/services/order-service.ts",
      "depends_on": ["User"],
      "used_by": ["Invoice"]
    }
  },
  "pages": [...],
  "routes": [...]
}
```

### 5. `src/contracts/navigation-flow.json`
Navigation flow contract — defines HOW users move through the app.
This is the MISSING LINK between pages, forms, and actions.
Every page, button, form submit, and link must be defined here.

```json
{
  "flows": {
    "entity_crud": {
      "Pet": {
        "list": {
          "route": "/pets",
          "actions": {
            "create": { "target": "/pets/new", "trigger": "button:Add New Pet" },
            "search": { "type": "inline", "trigger": "input:search", "effect": "filter_table" },
            "view_detail": { "target": "/pets/{id}", "trigger": "table_row_click" },
            "edit": { "target": "/pets/{id}?edit=true", "trigger": "action_menu:Edit" },
            "delete": { "type": "confirm_dialog", "trigger": "action_menu:Delete", "api": "DELETE /api/pets/{id}", "on_success": "refresh_table+toast" }
          }
        },
        "create": {
          "route": "/pets/new",
          "form_fields": ["name", "species", "breed", "ownerId"],
          "submit": { "api": "POST /api/pets", "on_success": "redirect:/pets+toast:Created", "on_error": "inline_validation" },
          "back": { "target": "/pets", "trigger": "button:Back" }
        },
        "detail": {
          "route": "/pets/{id}",
          "actions": {
            "edit": { "type": "inline_form", "api": "PUT /api/pets/{id}", "on_success": "refresh+toast" },
            "delete": { "type": "confirm_dialog", "api": "DELETE /api/pets/{id}", "on_success": "redirect:/pets+toast" },
            "view_owner": { "target": "/owners/{ownerId}", "trigger": "link:owner_name" },
            "add_appointment": { "target": "/appointments/new?petId={id}", "trigger": "button:Schedule Appointment" }
          }
        }
      }
    },
    "dashboard": {
      "route": "/",
      "widgets": {
        "stat_cards": { "entities": ["Pet", "Owner", "Appointment"], "api": "/api/{entity}/stats", "click": "navigate:/{entity}" },
        "recent_items": { "entity": "Appointment", "api": "/api/appointments?limit=5", "row_click": "navigate:/appointments/{id}" },
        "quick_actions": [
          { "label": "New Appointment", "target": "/appointments/new" },
          { "label": "Register Pet", "target": "/pets/new" }
        ]
      }
    },
    "auth": {
      "login": { "route": "/login", "submit": { "api": "signIn('credentials')", "on_success": "redirect:/", "on_error": "inline_error" } },
      "signup": { "route": "/signup", "submit": { "api": "POST /api/auth/signup", "on_success": "redirect:/login+toast", "on_error": "inline_error" } },
      "logout": { "trigger": "user_menu:Sign Out", "action": "signOut()", "on_success": "redirect:/login" }
    },
    "cross_entity": [
      { "from": "/owners/{id}", "action": "View Pets", "to": "/pets?ownerId={id}" },
      { "from": "/pets/{id}", "action": "View Medical Records", "to": "/medical-records?petId={id}" },
      { "from": "/appointments/{id}", "action": "Add Record", "to": "/medical-records/new?appointmentId={id}" }
    ]
  },
  "navigation": {
    "sidebar_groups": [
      { "label": "Overview", "items": ["/"] },
      { "label": "Patient Care", "items": ["/pets", "/owners", "/medical-records", "/vaccinations"] },
      { "label": "Operations", "items": ["/appointments", "/invoices", "/staff"] },
      { "label": "Workflows", "items": ["/workflows", "/tasks"] }
    ],
    "user_menu": ["Profile", "Settings", "Sign Out"]
  }
}
```

**Rules for navigation-flow.json:**
- EVERY entity MUST have list→create→detail→edit→delete flows defined
- EVERY form MUST specify: fields, submit API, on_success action, on_error action
- EVERY list page MUST specify: search, create button, row click, action menu items
- Cross-entity links MUST be defined (pet→owner, appointment→pet, etc.)
- Dashboard widgets MUST specify what they fetch and where they link
- User menu MUST include Sign Out action

**CRITICAL: Read `api_strategy` from the plan.** For each entity:
- CRUD actions use `"api": "POST /api/data/{entity}"` (Data Engine)
- Workflow actions use `"api": "POST /api/workflows/{workflowId}/execute"` (Workflow Engine)
- Workflow actions must include `"visible_when"` and `"trigger"` from the plan's api_strategy.workflow_actions
- If an entity has workflow_actions in api_strategy, the detail page MUST include those action buttons

The page agent and component agent read this contract to wire up ALL interactions correctly.
Without this contract, pages are generated as isolated screens with no connecting flow.

### 6. `src/contracts/event-bindings.json`
Event binding registry — declares which data mutations trigger which workflows.
This is the SINGLE POINT where Data Engine and Workflow Engine are connected.

```json
{
  "bindings": [
    {
      "event": "task_created",
      "source": "data:tasks:create",
      "workflows": ["TaskApprovalWorkflow"],
      "description": "New tasks go through approval if priority is critical"
    },
    {
      "event": "task_updated",
      "source": "data:tasks:update",
      "workflows": ["TaskStatusChangeWorkflow"],
      "conditions": [{ "field": "status", "changed": true }],
      "description": "Status changes trigger the status change workflow"
    },
    {
      "event": "project_updated",
      "source": "data:projects:update",
      "workflows": ["ProjectDeliveryWorkflow"],
      "conditions": [{ "field": "status", "newValue": "completed" }],
      "description": "Completing a project triggers the delivery pipeline"
    }
  ]
}
```

**Rules for event-bindings.json:**
- One binding per data event that triggers a workflow
- Event name format: `{entity_lowercase}_{operation}` — e.g., `task_created`, `order_updated`, `claim_deleted`
- Source format: `data:{table}:{operation}` — e.g., `data:tasks:create`
- `workflows` array: IDs matching workflow JSON file names
- `conditions` (optional): only trigger when specific field conditions are met
  - `changed: true` — field value changed from previous
  - `newValue: "x"` — field equals specific value after mutation
  - `operator: "in"` + `values: [...]` — field is one of several values
- If NO workflows exist in the plan, generate an empty `{ "bindings": [] }`
- If workflows exist, EVERY workflow MUST have at least one binding — otherwise it can never trigger

### 7. `contracts/seed-plan.json`
Seed data generation plan:
```json
{
  "tables": [
    {"name": "users", "order": 1, "row_count": 5, "has_admin": true},
    {"name": "departments", "order": 2, "row_count": 4, "references": []},
    {"name": "employees", "order": 3, "row_count": 20, "references": ["users", "departments"]}
  ],
  "cross_references": {
    "employees.user_id": "users.id",
    "employees.department_id": "departments.id"
  },
  "constraints": {
    "admin_user": {"email": "admin@example.com", "password": "password123", "role": "admin"}
  }
}
```
- Topologically sorted by foreign key dependencies
- Row counts proportional to entity importance
- Cross-reference rules for FK relationships

## RULES
1. Read the FULL plan JSON before generating anything
2. Every entity in plan.data_models MUST appear in all relevant contracts
3. Every page in plan.pages MUST appear in app-model.json
4. Every API route in plan.api_routes MUST appear in api-client.ts
5. Field names in api-client types MUST match plan.data_models fields exactly (camelCase)
6. Create the `src/contracts/` directory and `contracts/` directory
7. Do NOT generate any application code beyond these contract files
8. Use TypeScript for .ts/.tsx files
9. All types should use the field names from the plan (camelCase)
10. API fetch URLs in api-client.ts MUST use consistent naming that matches the planned API route folders
    - If entity is "MedicalRecord", URL should be `/api/medical-records` (kebab-case, plural)
    - All agents MUST use the same URL — the contract is the source of truth

## API-CLIENT COMPLETENESS (CRITICAL)

For EVERY entity in the plan, api-client.ts MUST have these 5 functions (no exceptions):
- `get{Entity}s()` / `list{Entity}s()` — GET collection
- `get{Entity}(id)` — GET single
- `create{Entity}(data)` — POST
- `update{Entity}(id, data)` — PUT
- `delete{Entity}(id)` — DELETE

PLUS a stats function for dashboard:
- `get{Entity}Stats()` — GET /api/{entity}/stats → `{ total: number }`

If the entity has workflow actions (approve, reject, submit), add those too.

## APP-MODEL COMPLETENESS (CRITICAL)

app-model.json `pages` array MUST include for EVERY entity:
- List page: `/{entity}` (e.g., `/projects`)
- Detail page: `/{entity}/[id]` (e.g., `/projects/[id]`)
- Create page: `/{entity}/new` (e.g., `/projects/new`)

PLUS these standard pages:
- Dashboard: `/dashboard`
- Login: `/login`
- Signup: `/signup`
- Error pages: `/error`, `/not-found`

If the plan has workflows, also include:
- Workflow list: `/workflows`
- Workflow detail: `/workflows/[id]`

## FINAL VERIFICATION (MUST DO BEFORE FINISHING)

After generating ALL 7 contract files, verify:
1. Read api-client.ts and COUNT the entity type exports — must equal the number of entities in the plan
2. Read app-model.json and COUNT the pages — must be at least (entities × 3) + 4 (dashboard + login + signup + error)
3. Read navigation-flow.json and verify EVERY entity has list+create+detail flows with actions defined
4. Read event-bindings.json and verify EVERY workflow has at least one binding — a workflow with no binding can never trigger
5. If ANY entity is missing from api-client.ts, app-model.json, or navigation-flow.json, fix it before finishing
"""


async def run_contract_agent(
    output_dir: str,
    plan: dict,
    domain_context: dict | None = None,
) -> AsyncIterator[Message]:
    """Generate contract files from the plan.

    Yields streaming messages for SSE forwarding.
    """
    from services.domain_context import build_domain_profile

    os.environ.pop("CLAUDECODE", None)

    domain_profile = build_domain_profile(domain_context, "contract_writer")

    plan_json = json.dumps(plan, indent=2)

    # Build entity/page/route summary for the prompt
    models = plan.get("data_models", [])
    pages = plan.get("pages", [])
    api_routes = plan.get("api_routes", [])
    workflows = plan.get("workflows", [])

    # Build explicit entity checklist
    entity_checklist = []
    for m in models:
        name = m.get("name", "?")
        fields = [f.get("name", "") for f in m.get("fields", [])]
        entity_checklist.append(f"  - [ ] **{name}** (fields: {', '.join(fields[:8])}{'...' if len(fields) > 8 else ''})")

    # Build explicit page checklist
    min_pages = len(models) * 3 + 4  # list+detail+create per entity + dashboard+login+signup+error
    page_checklist = ["  - [ ] /dashboard", "  - [ ] /login", "  - [ ] /signup"]
    for m in models:
        name = m.get("name", "?")
        slug = name.lower().replace("_", "-")
        page_checklist.append(f"  - [ ] /{slug} (list)")
        page_checklist.append(f"  - [ ] /{slug}/[id] (detail)")
        page_checklist.append(f"  - [ ] /{slug}/new (create)")

    user_prompt = f"""Generate all 5 contract files from this plan.

## Plan JSON
```json
{plan_json}
```

## ENTITY CHECKLIST — api-client.ts must have CRUD+stats functions for ALL of these:
{chr(10).join(entity_checklist)}

## PAGE CHECKLIST — app-model.json must include ALL of these ({min_pages}+ pages):
{chr(10).join(page_checklist)}

## Summary
- {len(models)} data models (ALL must appear in api-client.ts + app-model.json)
- {len(pages)} pages from plan
- {len(api_routes)} API routes
- {len(workflows)} workflows: {', '.join(w.get('name', '?') for w in workflows)}

## Steps
1. Create `src/contracts/` directory
2. Generate `src/contracts/api-client.ts` — typed fetch functions for ALL {len(models)} entities (check off each entity above as you include it)
3. Generate `src/contracts/design-system.tsx` — page shell components for each page type in the plan
4. Generate `src/contracts/services.ts` — interfaces for {len(workflows)} workflows
5. Generate `src/contracts/app-model.json` — dependency graph with ALL entities + ALL {min_pages}+ pages (check off each page above)
6. Create `contracts/` directory
7. Generate `contracts/seed-plan.json` — topologically sorted seed plan
8. VERIFY: Read api-client.ts and count entity types — must be {len(models)}. Read app-model.json and count pages — must be ≥{min_pages}.

Start by creating the contracts directory."""

    options = ClaudeAgentOptions(
        system_prompt=CONTRACT_AGENT_SYSTEM_PROMPT + domain_profile,
        allowed_tools=["Write", "Read", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=20,
        model="claude-haiku-4-5-20251001",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message
