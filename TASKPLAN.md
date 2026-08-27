# Tentoro Forge — Implementation Task Plan

Generated from BLUEPRINT.md (24 sections, 7388 lines)

---

## Phase 0: Organization Foundation (Weeks 1-2)

### Sprint 0.1 — Platform Setup & Org Backend (Week 1)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 0.1.1 | Set up platform PostgreSQL, create initial Alembic migration with org/identity tables: `organizations`, `platform_users`, `org_members`, `departments`, `teams`, `org_people`, `org_roles`, `org_person_roles`, `org_groups`, `org_group_members` | Backend | 1d | — |
| 0.1.2 | SQLAlchemy models for all org/identity tables | Backend | 0.5d | 0.1.1 |
| 0.1.3 | Platform auth: signup, login, logout, JWT with `orgId` in token, `/api/auth/me` returning org memberships | Backend | 1d | 0.1.2 |
| 0.1.4 | Organization CRUD endpoints: `POST/GET /api/orgs`, `GET/PUT /api/orgs/:orgId` | Backend | 0.5d | 0.1.3 |
| 0.1.5 | Org membership & invitation: `POST /api/orgs/:orgId/invite`, accept/reject flow | Backend | 0.5d | 0.1.4 |
| 0.1.6 | Org people CRUD: `GET/POST/PUT/DELETE /api/orgs/:orgId/people` | Backend | 0.5d | 0.1.4 |
| 0.1.7 | Department & team CRUD: `GET/POST/PUT/DELETE /api/orgs/:orgId/departments`, same for teams | Backend | 0.5d | 0.1.4 |
| 0.1.8 | Org role management: default roles auto-created on org creation (Admin, Manager, Member), custom role CRUD | Backend | 0.5d | 0.1.6 |
| 0.1.9 | Group management: `GET/POST /api/orgs/:orgId/groups`, `PUT /api/orgs/:orgId/groups/:id/members` | Backend | 0.5d | 0.1.6 |
| 0.1.10 | CSV/JSON bulk import: `POST /api/orgs/:orgId/people/import` with column mapping, validation, error report | Backend | 1d | 0.1.6 |
| 0.1.11 | Org chart API: `GET /api/orgs/:orgId/org-chart` (full tree with departments → teams → people + reporting lines), `PUT /api/orgs/:orgId/org-chart` (update from drag) | Backend | 0.5d | 0.1.7 |

### Sprint 0.2 — Org Frontend (Week 2)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 0.2.1 | Frontend project scaffold: Next.js 15 + Tailwind 4 + Zustand + React Query + shadcn/ui setup | Frontend | 0.5d | — |
| 0.2.2 | Auth pages: signup, login, JWT token management in Zustand store | Frontend | 1d | 0.1.3 |
| 0.2.3 | Landing page: org selector cards, "Create Organization" button | Frontend | 0.5d | 0.2.2 |
| 0.2.4 | Org creation wizard: name, slug, logo upload, initial settings | Frontend | 0.5d | 0.1.4 |
| 0.2.5 | Org dashboard: app cards grid + sidebar (Apps, Templates, Org Structure, People, Roles & Groups, Access, Settings) | Frontend | 1d | 0.2.3 |
| 0.2.6 | Org chart visual editor: React Flow canvas with DepartmentNode, TeamNode, PersonNode; drag to reorganize; reporting lines as edges | Frontend | 2d | 0.1.11 |
| 0.2.7 | People directory: searchable/filterable table, add person form, edit modal | Frontend | 1d | 0.1.6 |
| 0.2.8 | Role & group management pages: role list with permissions editor, group list with member assignment | Frontend | 1d | 0.1.8, 0.1.9 |
| 0.2.9 | CSV import UI: file picker → preview table → column mapping dropdowns → import with progress | Frontend | 1d | 0.1.10 |

**Sprint 0 Deliverable**: Developer can create an org, upload people via CSV, visually arrange the org chart, define roles and groups.

---

## Phase 1: Foundation (Weeks 3-5)

### Sprint 1.1 — Backend Core (Week 3)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 1.1.1 | Monorepo structure: `backend/` (FastAPI) + `frontend/` (Next.js) with shared env/config | Backend | 0.5d | Phase 0 |
| 1.1.2 | Platform DB tables: `projects` (with `org_id` FK), `modules`, `module_dependencies`, `conversations`, `agent_jobs`, `versions` | Backend | 0.5d | 0.1.1 |
| 1.1.3 | Project CRUD endpoints scoped to org: `POST/GET /api/orgs/:orgId/projects`, `GET/PUT/DELETE /api/projects/:id` | Backend | 0.5d | 1.1.2 |
| 1.1.4 | SSE streaming infrastructure: `sse_event()` helper, `StreamingResponse` wrapper, event types enum | Backend | 0.5d | 1.1.1 |
| 1.1.5 | Code Generator agent (Agent #4): system prompt for Next.js 15 + PostgreSQL + Drizzle ORM + Tailwind + shadcn/ui generation, Claude Agent SDK integration | Backend | 2d | 1.1.4 |
| 1.1.6 | Validator agent (Agent #8): run `npm run build`, parse errors, return pass/fail + error details | Backend | 0.5d | 1.1.5 |
| 1.1.7 | Indexer agent (Agent #7): read generated source files, produce AppModel JSON index (entities, pages, API routes, components) | Backend | 1d | 1.1.5 |
| 1.1.8 | Preview manager: spawn `npx next dev --port {port}` per project, poll until ready, kill on stop; port range 3200-3299 | Backend | 1d | 1.1.5 |
| 1.1.9 | Docker Compose support: spin up PostgreSQL per generated project (port range 5500-5599), health checks | Backend | 1d | 1.1.8 |
| 1.1.10 | Version history: auto `git init` on project creation, auto-commit after each agent run, `GET /api/projects/:id/versions` | Backend | 0.5d | 1.1.5 |

### Sprint 1.2 — Frontend Core (Week 4)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 1.2.1 | Project workspace layout: sidebar + header + content area; sidebar links (Chat, Preview, Code, etc.) | Frontend | 1d | 0.2.5 |
| 1.2.2 | Chat panel (full width): message list, input bar, streaming message display, agent thinking indicators | Frontend | 1.5d | 1.1.4 |
| 1.2.3 | Progress stream display: SSE event renderer (status, log, tool_call, file_created, complete, error) | Frontend | 1d | 1.1.4 |
| 1.2.4 | Live preview iframe: responsive device frames (desktop/tablet/mobile toggle), refresh button, loading state | Frontend | 1d | 1.1.8 |
| 1.2.5 | File tree sidebar + Monaco code editor: read-only file browsing, syntax highlighting, file tabs | Frontend | 1.5d | 1.1.3 |
| 1.2.6 | "New App" creation options: "Describe what you need" → Chat, "Start from template" → Gallery, "I'm not sure yet" → Discovery, "Import Figma design" → URL input | Frontend | 0.5d | 1.2.1 |

### Sprint 1.3 — Templates & Integration (Week 5)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 1.3.1 | Template DB tables: `app_templates`, `discovery_sessions` — Alembic migration | Backend | 0.5d | 1.1.2 |
| 1.3.2 | Seed template data: curate 15-20 initial templates across 8 categories (Operations, Sales, HR, Finance, Support, IT, Marketing, Legal), each with full Planner-format plan JSON | Backend | 2d | 1.3.1 |
| 1.3.3 | Template API endpoints: `GET /api/templates` (list/filter by category/department), `GET /api/templates/:slug`, `GET /api/orgs/:orgId/suggested-templates`, `POST /api/orgs/:orgId/projects/from-template` | Backend | 1d | 1.3.1 |
| 1.3.4 | Template-to-project flow: skip Planner, run Code Generator directly with template plan, validate, index | Backend | 0.5d | 1.3.3, 1.1.5 |
| 1.3.5 | Template gallery page: filterable grid by category/department, search, template detail expansion with customization options | Frontend | 1.5d | 1.3.3 |
| 1.3.6 | Template customization modal: app name, toggle modules, add custom fields, org role → app role mapping, "Use As-Is" / "Customize & Create" | Frontend | 1d | 1.3.5 |
| 1.3.7 | End-to-end test: describe app → generate → preview → browse code | Fullstack | 0.5d | 1.2.4, 1.1.9 |
| 1.3.8 | End-to-end test: pick template → customize → generate → preview | Fullstack | 0.5d | 1.3.6 |

**Sprint 1 Deliverable**: User can describe an app in chat, get it generated with PostgreSQL, preview it live, browse source code, or start from a template.

---

## Phase 2: Refinement & Chat (Weeks 6-7)

### Sprint 2.1 — Agent System (Week 6)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 2.1.1 | Orchestrator agent (Agent #0): intent classification prompt (PLAN / REFINE / EXPLAIN / SCAFFOLD / AGENT / DISCOVER / NAVIGATE / UNDO / AMBIGUOUS), Haiku 4.5, 1-2 turns | Backend | 1d | 1.1.5 |
| 2.1.2 | Refiner agent (Agent #2): reads AppModel index for context, makes targeted code edits, Sonnet 4, 3-8 turns | Backend | 1d | 2.1.1 |
| 2.1.3 | Planner agent (Agent #1): multi-turn requirement gathering, structured plan output (entities, pages, workflows, modules, access_control, ai_features), org-aware RBAC inference | Backend | 1.5d | 2.1.1 |
| 2.1.4 | Explainer agent (Agent #3): answers questions about app structure/code, Haiku 4.5, 2-5 turns | Backend | 0.5d | 2.1.1 |
| 2.1.5 | Scaffolder agent (Agent #6): adds focused features to existing modules (not full module planning), Sonnet 4 | Backend | 1d | 2.1.1 |
| 2.1.6 | Code Editor agent (Agent #5): focused single-file edits for precise changes, Sonnet 4 | Backend | 0.5d | 2.1.1 |
| 2.1.7 | Main orchestration flow: `handle_user_input()` — classify → route → validate → index → hot reload; handles all intents | Backend | 1d | 2.1.1 through 2.1.6 |
| 2.1.8 | Conversation persistence: save all messages to `conversations` table, load history on page refresh | Backend | 0.5d | 1.1.2 |

### Sprint 2.2 — Discovery & Chat Frontend (Week 7)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 2.2.1 | Discovery Agent (Agent #12): system prompt with 4 discovery types (problem_first, reference_based, department_need, vague_idea), multi-turn conversation, structured brief output | Backend | 1.5d | 2.1.1 |
| 2.2.2 | DISCOVER intent handling in orchestration flow: run Discovery Agent → produce brief → hand off to Planner | Backend | 0.5d | 2.2.1, 2.1.7 |
| 2.2.3 | Discovery API endpoints: `POST /api/orgs/:orgId/discovery/start`, `POST /.../discovery/:sid/message`, `GET /.../discovery/:sid`, `POST /.../discovery/:sid/convert`, `GET /.../discovery` | Backend | 1d | 2.2.1 |
| 2.2.4 | Org-aware template suggestion engine: match org departments to template `relevantDepartments`, score relevance, exclude areas already covered by existing apps | Backend | 1d | 1.3.2 |
| 2.2.5 | Plan approval UI: review plan in chat, approve/reject buttons, edit-and-resubmit | Frontend | 1d | 2.1.3 |
| 2.2.6 | Undo/revert UI: version history sidebar, revert to version button, diff preview | Frontend | 0.5d | 1.1.10 |
| 2.2.7 | Refine bar below preview: text input for quick refinements, send → stream → hot reload | Frontend | 0.5d | 2.1.2 |
| 2.2.8 | Chat history persistence: load previous messages on page load, scroll to latest | Frontend | 0.5d | 2.1.8 |
| 2.2.9 | Discovery conversation UI: `/orgs/[orgId]/discover` page, multi-turn chat, brief presentation card, "Build This App" / "Adjust Requirements" buttons | Frontend | 1.5d | 2.2.3 |
| 2.2.10 | Suggested apps section on org dashboard: cards with template suggestions based on org departments, dismiss/use/customize actions | Frontend | 1d | 2.2.4 |

**Sprint 2 Deliverable**: Full conversational loop — plan, refine, explain, undo. Discovery Agent guides unclear requirements. Org-aware template suggestions on dashboard.

---

## Phase 3: Data Model Editor (Weeks 8-9)

### Sprint 3.1 — ERD Canvas (Week 8)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 3.1.1 | ERD canvas component: React Flow with custom EntityCard nodes, RelationLine edges | Frontend | 1.5d | Phase 2 |
| 3.1.2 | EntityCard node: model name, collapsible field list (name, type, constraints icons), click to expand | Frontend | 1d | 3.1.1 |
| 3.1.3 | Add/edit/delete models: "Add Model" button → new card, right-click → delete with impact analysis confirmation | Frontend | 1d | 3.1.1 |
| 3.1.4 | Field editor: add/edit/delete fields, type picker dropdown (string, number, boolean, date, enum, relation, json), constraint checkboxes (required, unique, indexed), default value | Frontend | 1.5d | 3.1.2 |
| 3.1.5 | Relationship drawing: drag from entity → entity → relationship modal (type: one-to-one, one-to-many, many-to-many; foreign key config) | Frontend | 1d | 3.1.1 |
| 3.1.6 | Enum editor: inline enum value list editor in field properties | Frontend | 0.5d | 3.1.4 |
| 3.1.7 | Index editor: add composite indexes, unique constraints | Frontend | 0.5d | 3.1.4 |
| 3.1.8 | Instruction builder for data editor: translate each action (add model, add field, add relation, etc.) into natural language instruction for Refiner agent | Backend | 1d | 3.1.3, 2.1.2 |

### Sprint 3.2 — Database Integration (Week 9)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 3.2.1 | Seed data table editor: spreadsheet-like grid for each model, edit cell → save, "Generate realistic data" button (LLM call to produce 10-20 sample rows) | Frontend | 1.5d | 3.1.4 |
| 3.2.2 | Impact analysis: when changing a model/field, show downstream effects (pages using this field, rules referencing it, workflows depending on it) via AppModel cross-reference | Backend | 1d | 1.1.7 |
| 3.2.3 | Schema push integration: on data model change → run `drizzle-kit push` in generated app, report success/failure | Backend | 1d | 1.1.9 |
| 3.2.4 | Database browser: `GET /api/projects/:id/db/tables`, `GET /api/projects/:id/db/tables/:name`, `GET/POST /api/projects/:id/db/query` | Backend | 1d | 1.1.9 |
| 3.2.5 | Database browser UI: table list sidebar, table grid with inline editing, SQL console with Monaco editor | Frontend | 1.5d | 3.2.4 |
| 3.2.6 | Seed data actions: `POST /api/projects/:id/db/seed` (re-run), `POST /api/projects/:id/db/reset` (drop & recreate) | Backend | 0.5d | 3.2.4 |

**Sprint 3 Deliverable**: Visual ERD editor, seed data management, live database browser with SQL console.

---

## Phase 4: Rules & Access Control (Weeks 10-12)

### Sprint 4.1 — Rules Engine UI (Week 10)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 4.1.1 | Rules table page: filterable/sortable table (Name, Type, Attached To, Condition, Enforce At), filter by type/model/enforcement | Frontend | 1d | Phase 3 |
| 4.1.2 | Condition builder component: visual expression builder (field dropdown → operator dropdown → value input), AND/OR/NOT grouping, nested conditions, fallback to raw expression | Frontend | 2d | — |
| 4.1.3 | Validation rule form: select model, select field, condition builder, error message, enforcement checkboxes (API, UI, DB) | Frontend | 1d | 4.1.2 |
| 4.1.4 | Access control rule form: model + action matrix (role → allow/deny + optional condition) | Frontend | 1d | 4.1.2 |
| 4.1.5 | Business rule form: model, trigger action (create/update/delete), condition, consequence description | Frontend | 0.5d | 4.1.2 |
| 4.1.6 | Computed field rule form: model, target field, expression builder (reference other fields) | Frontend | 0.5d | 4.1.2 |
| 4.1.7 | State machine editor: React Flow mini-diagram for state transitions, states list, transition rules | Frontend | 1d | — |
| 4.1.8 | Trigger rule form: model, field watch, condition, action description (send email, call webhook, update field) | Frontend | 0.5d | 4.1.2 |
| 4.1.9 | Instruction builder for rule actions: translate each rule form submission into instruction for Refiner | Backend | 1d | 4.1.3-4.1.8 |

### Sprint 4.2 — RBAC System (Week 11)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 4.2.1 | Field Access Matrix editor: model × role grid (view 👁 / edit ✎ / hidden ── per cell), model selector dropdown | Frontend | 2d | 3.1.4 |
| 4.2.2 | Record Scope editor: scope rules per model (department, department+sub, team, owner, manager chain, unrestricted), scope column selector | Frontend | 1d | 4.2.1 |
| 4.2.3 | App-role mapping page: org roles → app roles configuration table, auto-suggest from org structure | Frontend | 1d | 0.2.8 |
| 4.2.4 | App access policies: which org roles/groups/departments can access this app, access level (user/admin/none) | Frontend | 0.5d | 4.2.3 |
| 4.2.5 | RBAC policy API endpoints: `GET/POST/DELETE /api/projects/:id/access-policies`, `GET/POST/PUT /api/projects/:id/field-access`, `GET /api/projects/:id/field-access/matrix`, `GET/POST/PUT /api/projects/:id/workflow-assignments` | Backend | 1.5d | 1.1.2 |

### Sprint 4.3 — RBAC in Generated Apps (Week 12)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 4.3.1 | RBAC middleware template for generated apps: field-level filter (strip hidden fields from API responses), record-level scope filter (add WHERE clause based on user's dept/role) | Backend | 2d | 4.2.5 |
| 4.3.2 | Org-to-app identity sync: when generated app starts, sync org people → app's users table with role mappings | Backend | 1d | 0.1.6 |
| 4.3.3 | `useFieldPermissions` React hook template: generated apps call `/api/me/permissions` → hook returns `{canView, canEdit}` per field, components use it to hide/disable fields | Backend | 1d | 4.3.1 |
| 4.3.4 | `/api/me/permissions` endpoint template: returns current user's field permissions and record scope for all models | Backend | 0.5d | 4.3.1 |
| 4.3.5 | Planner agent update: auto-infer `access_control` section from org structure (sensitive fields → restrict to dept, record scope → department ownership) | Backend | 1d | 2.1.3 |
| 4.3.6 | Cross-reference integration: show rules in data model editor field properties, show access rules in properties panel | Frontend | 0.5d | 4.1.9, 4.2.1 |

**Sprint 4 Deliverable**: Visual rules engine, field/record-level RBAC matrix, org-to-app identity sync. Generated apps enforce access control at API, UI, and DB layers.

---

## Phase 5: Workflow Editor (Weeks 13-15)

### Sprint 5.1 — Workflow Canvas (Week 13)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 5.1.1 | Workflow canvas: React Flow with custom node types, edge types, minimap, controls | Frontend | 1d | Phase 4 |
| 5.1.2 | Node types: TriggerNode (green), ActionNode (blue), ConditionNode (yellow), WaitNode (gray), EndNode (red) — each with icon, label, status indicator | Frontend | 1.5d | 5.1.1 |
| 5.1.3 | Assignment/approval node types: AssignmentNode (teal), ApprovalNode (green), TaskPoolNode (blue), EscalationNode (red) | Frontend | 1d | 5.1.1 |
| 5.1.4 | Edge types: Default (solid), Then (green dashed), Else (red dashed), Error (orange dotted) | Frontend | 0.5d | 5.1.1 |
| 5.1.5 | Node palette: draggable node types grouped by category (Triggers, Actions, Flow Control, Human-in-Loop) | Frontend | 0.5d | 5.1.2, 5.1.3 |
| 5.1.6 | Node properties panel: context-sensitive form based on selected node type (trigger config, action config, condition expression, assignment rules) | Frontend | 2d | 5.1.2, 5.1.3 |
| 5.1.7 | Variable picker with autocomplete: `{{trigger.fieldName}}`, `{{stepId.output}}`, populated from AppModel data models and upstream step outputs | Frontend | 1d | 5.1.6 |
| 5.1.8 | Workflow definition JSON format: nodes array + edges array + metadata, save/load to project files | Backend | 0.5d | 5.1.1 |

### Sprint 5.2 — Workflow Runtime (Week 14)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 5.2.1 | Workflow runtime template for generated apps: thin executor that walks the node graph, evaluates conditions, runs action functions | Backend | 2d | 5.1.8 |
| 5.2.2 | Trigger registration system: API event triggers, schedule triggers (cron), DB change triggers, webhook triggers, manual triggers | Backend | 1d | 5.2.1 |
| 5.2.3 | Built-in action types: DB query (Drizzle), HTTP call (fetch), send email, send notification | Backend | 1d | 5.2.1 |
| 5.2.4 | Workflow action generator agent (Agent #10): given a node description + context, generate the action function TypeScript file | Backend | 1.5d | 5.2.1 |
| 5.2.5 | Assignment resolution: resolve "requester's manager" / "department head" / "role: Approver" dynamically from org structure at runtime | Backend | 1d | 4.3.2 |
| 5.2.6 | Approval patterns: single approver, sequential chain, parallel-all, parallel-any, threshold-based | Backend | 1d | 5.2.5 |
| 5.2.7 | Task pool: claim model (round-robin / skills-based / first-claim), task inbox query | Backend | 0.5d | 5.2.5 |

### Sprint 5.3 — Workflow Testing & UI (Week 15)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 5.3.1 | Escalation node: SLA breach detection, escalate to manager/role, configurable hours + escalation target | Backend | 0.5d | 5.2.5 |
| 5.3.2 | Notification system template: email + in-app notifications for task assignments, approval requests, escalations | Backend | 1d | 5.2.5 |
| 5.3.3 | Task inbox page template for generated apps: pending tasks list, claim/approve/reject actions, filter by workflow | Backend | 1d | 5.2.7 |
| 5.3.4 | Workflow tester UI: run with sample data, highlight active node in canvas, step-through mode, execution timeline | Frontend | 1.5d | 5.2.1 |
| 5.3.5 | Execution log viewer: timeline of step executions, input/output data per step, error details | Frontend | 1d | 5.2.1 |
| 5.3.6 | Instruction builder for workflow actions: translate canvas operations into instructions for agents | Backend | 1d | 5.1.8 |
| 5.3.7 | End-to-end test: create workflow → add trigger + actions + approval → run → verify execution + approval + escalation | Fullstack | 0.5d | 5.3.4 |

**Sprint 5 Deliverable**: Visual workflow builder with human-in-the-loop assignments, approvals, escalation. Task inbox in generated apps.

---

## Phase 6: UI Editor (Weeks 16-19)

### Sprint 6.1 — GrapesJS Integration (Week 16)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 6.1.1 | GrapesJS + @grapesjs/react setup: `EditorShell.tsx` with `<Canvas/>` that disables all default UI, dynamic import for Next.js SSR avoidance | Frontend | 1d | Phase 5 |
| 6.1.2 | White-label chrome: custom `EditorToolbar.tsx` (undo/redo/preview/save powered by GrapesJS commands API) | Frontend | 0.5d | 6.1.1 |
| 6.1.3 | Tailwind integration plugin: inject Tailwind CSS into canvas iframe, configure design tokens | Frontend | 1d | 6.1.1 |
| 6.1.4 | Custom `LayerPanel.tsx`: shadcn/ui tree component powered by GrapesJS Layer Manager API (`layer:custom` event), component nesting, visibility toggle, reorder | Frontend | 1d | 6.1.1 |
| 6.1.5 | Custom `StylePanel.tsx`: shadcn/ui controls powered by GrapesJS Style Manager API (`style:custom` event), sectors for Typography, Layout, Spacing, Background, Borders, Effects | Frontend | 2d | 6.1.1 |
| 6.1.6 | Custom `DeviceToolbar.tsx`: desktop/tablet/mobile switcher using GrapesJS Device Manager API, canvas resizes accordingly | Frontend | 0.5d | 6.1.1 |

### Sprint 6.2 — Component Types (Week 17)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 6.2.1 | `tentoroforge-components.ts` plugin — Layout components: Container, Grid (2/3/4 col), Stack, Flex Row, Card, Section, Tabs, Accordion, Sidebar Layout, Header/Footer | Frontend | 2d | 6.1.1 |
| 6.2.2 | `tentoroforge-components.ts` plugin — Display components: Heading (h1-h6), Text, Image, Avatar, Badge, Tag, Alert, Table, DataTable (with rich canvas preview), List, Chart (bar/line/pie), Stat Card, Progress | Frontend | 2d | 6.2.1 |
| 6.2.3 | `tentoroforge-components.ts` plugin — Navigation components: Button, LinkButton, IconButton, Breadcrumb, Pagination, Navbar, Dropdown Menu | Frontend | 1d | 6.2.1 |
| 6.2.4 | Canvas component views: rich editor previews for DataTable (sample rows), Chart (placeholder SVG), KanbanBoard (sample columns), Calendar (month grid) — look different in editor vs. production | Frontend | 2d | 6.2.2 |

### Sprint 6.3 — Form Components (Week 18)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 6.3.1 | `form-components.ts` plugin — Text inputs: TextInput, TextArea, RichTextEditor, EmailInput, URLInput, PasswordInput, PhoneInput | Frontend | 1.5d | 6.1.1 |
| 6.3.2 | `form-components.ts` plugin — Selection inputs: Select, MultiSelect, Combobox, AsyncSelect, Checkbox, CheckboxGroup, RadioGroup, Switch, Toggle | Frontend | 1.5d | 6.1.1 |
| 6.3.3 | `form-components.ts` plugin — Date/number inputs: DatePicker, TimePicker, DateRangePicker, NumberInput, Slider, Rating | Frontend | 1d | 6.1.1 |
| 6.3.4 | `form-components.ts` plugin — Specialized inputs: FileUpload, ImageUpload, Dropzone, ColorPicker, TagInput, Signature, CodeEditor | Frontend | 1d | 6.1.1 |
| 6.3.5 | FormGroup component: wraps any input with label + description + error message + required indicator | Frontend | 0.5d | 6.3.1 |
| 6.3.6 | FormStepper component: multi-step wizard wrapper, step navigation, validation per step | Frontend | 1d | 6.3.5 |
| 6.3.7 | SubmitButton component: configurable action (create record, update record, trigger workflow), model binding | Frontend | 0.5d | 6.3.5 |
| 6.3.8 | Form component traits: all form components get validation traits (required, min, max, regex, custom), conditional visibility traits, data binding traits (model + field) | Frontend | 1d | 6.3.1-6.3.7 |

### Sprint 6.4 — Properties, Binding & Instructions (Week 19)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 6.4.1 | Custom `PropertiesPanel.tsx`: shadcn/ui form powered by GrapesJS Trait Manager API (`trait:custom` event), dynamic rendering based on selected component's traits | Frontend | 1.5d | 6.1.1 |
| 6.4.2 | `ComponentPalette.tsx`: shadcn/ui sidebar with collapsible categories (Layout, Display, Form, Navigation, Data, AI), drag block to canvas | Frontend | 1d | 6.2.1-6.3.7 |
| 6.4.3 | `FieldMapper.tsx`: bind data model fields to component traits, dropdown shows available models + fields from AppModel, auto-populate column configs for DataTable | Frontend | 1.5d | 3.1.4, 6.2.2 |
| 6.4.4 | Instruction builder for UI editor: translate GrapesJS changes (add component, move, resize, style change, prop change) into natural language instructions for Refiner agent | Backend | 1.5d | 2.1.2 |
| 6.4.5 | Page-level layout editing: sidebar/header/content area structure, layout template selection | Frontend | 1d | 6.2.1 |
| 6.4.6 | End-to-end test: open UI editor → drag DataTable → bind to model → add form fields → style → save → verify code changes in preview | Fullstack | 0.5d | 6.4.4 |

**Sprint 6 Deliverable**: White-labeled GrapesJS editor with 60+ component types (including 25+ form fields), style manager, device preview, data binding.

---

## Phase 7: Navigation & Modules (Weeks 20-21)

### Sprint 7.1 — Navigation Editor (Week 20)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 7.1.1 | Navigation editor canvas: React Flow with ScreenNode cards (route + page thumbnail), navigation edge links | Frontend | 1.5d | Phase 6 |
| 7.1.2 | Screen node interactions: drag to organize, draw edges to define navigation, click → edit route/layout/access rules | Frontend | 1d | 7.1.1 |
| 7.1.3 | Sidebar/navbar menu configuration: menu items list, ordering, icons, show/hide per role, nested menu groups | Frontend | 1d | 7.1.1 |
| 7.1.4 | Default/home screen config, 404 page config, error page config | Frontend | 0.5d | 7.1.1 |
| 7.1.5 | Instruction builder for navigation actions: add page, link pages, configure menu → instructions for Refiner | Backend | 0.5d | 7.1.1 |

### Sprint 7.2 — Module System (Week 21)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 7.2.1 | Module management UI: list modules, create module (triggers Planner agent for module-scoped planning), delete module | Frontend | 1d | 2.1.3 |
| 7.2.2 | Module dependency graph: React Flow visualization of cross-module dependencies, click module → see its entities/pages | Frontend | 1d | 7.2.1 |
| 7.2.3 | Cross-module dependency tracking: when Planner creates module plan, detect references to entities in other modules, create dependency links | Backend | 1d | 7.2.1 |
| 7.2.4 | Connections map: visual overview of all module relationships (which modules share entities, API routes, workflows) | Frontend | 0.5d | 7.2.2 |
| 7.2.5 | Module-scoped file organization: generated app files organized by module directories | Backend | 0.5d | 7.2.1 |
| 7.2.6 | Module-scoped AppModel index sections: indexer produces per-module sections in app-model.json | Backend | 0.5d | 1.1.7, 7.2.5 |

**Sprint 7 Deliverable**: Visual navigation editor, multi-module apps with dependency management.

---

## Phase 8: AI Agent Builder (Weeks 22-24)

### Sprint 8.1 — Agent Builder UI (Week 22)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 8.1.1 | Agent Builder canvas: React Flow with node types — SystemPromptNode, ToolNode, GuardrailNode, MemoryNode, HumanHandoffNode, RouterNode | Frontend | 2d | Phase 7 |
| 8.1.2 | Node palette: draggable agent building blocks grouped by category | Frontend | 0.5d | 8.1.1 |
| 8.1.3 | System prompt editor: multi-line editor with variable interpolation (`{{user.name}}`, `{{context.orderCount}}`), live preview | Frontend | 1d | 8.1.1 |
| 8.1.4 | Tool picker: auto-discover available tools from AppModel API routes, toggle on/off, show endpoint + description | Frontend | 1d | 8.1.1 |
| 8.1.5 | Custom tool editor: name, description, input JSON schema editor, handler file path | Frontend | 0.5d | 8.1.4 |
| 8.1.6 | Properties panels: guardrail config (input/output validation, rate limits, blocked topics), memory config (conversation window, summarization, knowledge base toggle), multi-agent router config | Frontend | 1.5d | 8.1.1 |
| 8.1.7 | Instruction builder for agent editor actions | Backend | 0.5d | 8.1.1 |

### Sprint 8.2 — Agent Runtime & Platform Agent (Week 23)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 8.2.1 | Agent Builder agent (Agent #11): system prompt, reads AppModel for API routes, generates agent definition + runtime code | Backend | 2d | 2.1.1 |
| 8.2.2 | AGENT intent in Orchestrator: route to Agent Builder agent, validate + index after changes | Backend | 0.5d | 8.2.1 |
| 8.2.3 | Agent runtime template (`src/agents/runtime.ts`): agentic loop calling Anthropic API, tool execution, conversation management | Backend | 2d | — |
| 8.2.4 | Tool registry template (`src/agents/tools/registry.ts`): auto-map API routes to tools, input/output schema, auth forwarding | Backend | 1d | 8.2.3 |
| 8.2.5 | Memory manager template (`src/agents/memory.ts`): conversation history, sliding window, optional summarization | Backend | 0.5d | 8.2.3 |
| 8.2.6 | Guardrails template (`src/agents/guardrails.ts`): input validation, output filtering, rate limiting, cost caps | Backend | 0.5d | 8.2.3 |
| 8.2.7 | Chat API route template (`src/app/api/agents/[agentId]/chat/route.ts`): SSE streaming, auth, conversation persistence | Backend | 0.5d | 8.2.3 |

### Sprint 8.3 — Agent Features (Week 24)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 8.3.1 | ChatWidget component template: floating mode (bottom-right bubble) + full-page mode, message list, input bar, typing indicator, tool call display | Backend | 1d | 8.2.7 |
| 8.3.2 | Agent conversation tables in generated app schema: `agent_conversations`, `agent_messages` | Backend | 0.5d | 8.2.3 |
| 8.3.3 | Agent templates: 5 pre-built configs (Customer Support Bot, Data Assistant, Workflow Agent, Admin Copilot, Onboarding Guide) | Backend | 1d | 8.2.3 |
| 8.3.4 | Test console: send messages to agent in builder, inspect tool calls/responses, latency, cost per message | Frontend | 1.5d | 8.2.1 |
| 8.3.5 | Knowledge base: pgvector setup in generated app, document upload (PDF, DOCX, TXT, MD), chunking, embedding (text-embedding-3-small), vector search tool | Backend | 2d | 8.2.4 |
| 8.3.6 | Agent analytics dashboard template: conversations count, tool usage breakdown, average cost, error rate | Backend | 0.5d | 8.3.2 |
| 8.3.7 | AppModel index: agents section (agent list, tools, memory config, guardrails) | Backend | 0.5d | 1.1.7 |

**Sprint 8 Deliverable**: Visual agent builder, agent runtime in generated apps, knowledge base (RAG), 5 templates, test console.

---

## Phase 9: AI-Powered App Features (Weeks 25-27)

### Sprint 9.1 — Smart Fields (Week 25)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 9.1.1 | Smart field runtime template (`src/lib/smart-fields.ts`): compute field value using LLM on record create/update, Haiku for classification/extraction, Sonnet for generation | Backend | 2d | Phase 8 |
| 9.1.2 | Smart field types: `ai_classify`, `ai_summarize`, `ai_sentiment`, `ai_extract`, `ai_generate`, `ai_translate`, `ai_score` — each with prompt template + output format | Backend | 2d | 9.1.1 |
| 9.1.3 | Async smart field computation: API returns immediately, field computes in background, UI shows loading indicator, WebSocket/polling for completion | Backend | 1d | 9.1.1 |
| 9.1.4 | Smart field configuration in Data Model Editor: field properties panel gets "AI Type" selector, prompt template, source fields, model selector (Haiku/Sonnet) | Frontend | 1d | 3.1.4, 9.1.2 |
| 9.1.5 | Smart field test console: "Test with sample data" button → show LLM input/output/cost/latency | Frontend | 0.5d | 9.1.4 |
| 9.1.6 | Smart field UI indicators: ✦ icon on AI-computed fields, override button (manually set value), recompute button | Frontend | 0.5d | 9.1.4 |

### Sprint 9.2 — Semantic Search & AI Workflow Nodes (Week 26)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 9.2.1 | Semantic search setup: pgvector extension, embedding computation on record create/update (text-embedding-3-small via OpenAI SDK), embedding column in schema | Backend | 1.5d | — |
| 9.2.2 | Hybrid search implementation: combine semantic (cosine similarity) + keyword (tsvector) + structured filters, configurable weights | Backend | 1d | 9.2.1 |
| 9.2.3 | Semantic search UI component: search input with score display, result ranking, highlight relevant text | Frontend | 1d | 9.2.2 |
| 9.2.4 | Workflow AI nodes: `ai_classify` (route workflow based on LLM classification), `ai_extract` (extract structured data from text), `ai_decide` (LLM makes yes/no decision with reasoning), `ai_generate` (generate content/email/summary) | Backend | 2d | 5.2.1 |
| 9.2.5 | Workflow AI node palette entries and properties panels: prompt template editor, input/output variable mapping, model selector | Frontend | 1d | 9.2.4, 5.1.6 |

### Sprint 9.3 — AI Components & Integration (Week 27)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 9.3.1 | AI rules: `content_moderation` (flag inappropriate content), `similarity_check` (detect near-duplicates), `ai_validation` (LLM validates complex business rules), `ai_enrichment` (auto-fill fields from external context) | Backend | 1.5d | 4.1.9 |
| 9.3.2 | AI rule forms in Rules Editor: prompt template, threshold config, action on trigger | Frontend | 1d | 9.3.1 |
| 9.3.3 | AI-assisted UI components: `SmartFormField` (auto-suggest, auto-complete), `InlineAssistant` (contextual help) | Backend | 1d | — |
| 9.3.4 | `NaturalLanguageQuery` component: text input → LLM generates SQL → execute → display results → LLM summarizes | Backend | 1.5d | — |
| 9.3.5 | `SmartFilterBar` component: natural language → structured filters (parse "sales over $10k last month" → SQL WHERE) | Backend | 1d | — |
| 9.3.6 | `DataInsightsPanel` component: auto-analyze data, generate top-N insights, trend detection | Backend | 1d | — |
| 9.3.7 | Scheduled AI tasks: workflow cron trigger → AI node (e.g., weekly summary email, daily content moderation scan) | Backend | 0.5d | 5.2.2, 9.2.4 |
| 9.3.8 | AI configuration template (`ai-config.ts`): API key management, model selection, cost caps; usage tracking template (`ai-usage.ts`): per-feature cost logging | Backend | 0.5d | — |
| 9.3.9 | AI features overview panel in project settings: list of active AI features, total cost, enable/disable toggles | Frontend | 0.5d | 9.3.8 |
| 9.3.10 | Planner agent update: auto-detect AI requirements from natural language ("auto-categorize tickets" → `ai_classify` smart field) | Backend | 0.5d | 2.1.3 |

**Sprint 9 Deliverable**: Smart fields, semantic search, AI workflow nodes, NL query, AI rules — all configured visually, running on the app's own API key.

---

## Phase 10: Portal & Polish (Weeks 28-30)

### Sprint 10.1 — Multi-App Portal (Week 28)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 10.1.1 | Multi-app portal generation: auto-generated landing page per org, app grid with icons/descriptions | Backend | 1.5d | Phase 9 |
| 10.1.2 | Role-based app visibility: portal shows only apps the user has access to (based on `app_access_policies`) | Backend | 0.5d | 4.2.5 |
| 10.1.3 | Unified task inbox: aggregate pending approvals/tasks across all org apps, `GET /api/portal/tasks` endpoint in each generated app | Backend | 1.5d | 5.3.3 |
| 10.1.4 | Cross-app notifications and activity feed: `GET /api/portal/activity` in each app, aggregated in portal | Backend | 1d | 10.1.3 |
| 10.1.5 | SSO token sharing across apps in same org: shared JWT validation, single sign-on flow | Backend | 1d | 0.1.3 |
| 10.1.6 | Portal UI: app grid, task inbox page, activity feed, quick search across all apps | Frontend | 1.5d | 10.1.1-10.1.4 |

### Sprint 10.2 — Export & Deployment (Week 29)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 10.2.1 | ZIP export: download project with README (setup instructions, env vars, commands), proper .gitignore | Backend | 1d | — |
| 10.2.2 | Git push export: push to user's GitHub/GitLab repo (OAuth integration for repo access) | Backend | 1d | — |
| 10.2.3 | Dockerfile generation: production-ready Dockerfile + docker-compose.yml for deployment | Backend | 1d | — |
| 10.2.4 | Error handling: graceful agent failures with retry (max 2 retries), user-friendly error messages in chat | Backend | 1d | 2.1.7 |
| 10.2.5 | Preview server crash recovery: detect crashed preview, auto-restart, notify user | Backend | 0.5d | 1.1.8 |

### Sprint 10.3 — UX Polish & Testing (Week 30)

| # | Task | Owner | Est | Dependencies |
|---|------|-------|-----|-------------|
| 10.3.1 | Performance: agent response caching for common patterns (same instruction → skip LLM call) | Backend | 1d | — |
| 10.3.2 | Performance: incremental AppModel updates (only re-index changed files, not full scan) | Backend | 1d | 1.1.7 |
| 10.3.3 | Keyboard shortcuts: Cmd+K command palette, Cmd+Z undo, Cmd+S save, Cmd+P preview toggle | Frontend | 1d | — |
| 10.3.4 | Command palette (Cmd+K): fuzzy search across actions, pages, models, components | Frontend | 1d | 10.3.3 |
| 10.3.5 | Onboarding tutorial: first-time user walkthrough (create org → upload people → create first app → preview) | Frontend | 1d | — |
| 10.3.6 | Monitoring: agent cost tracking per project (total cost, per-agent breakdown, daily chart) | Backend | 0.5d | — |
| 10.3.7 | Monitoring: error logging and alerting (failed agent runs, build failures, preview crashes) | Backend | 0.5d | — |
| 10.3.8 | Integration tests: agent pipeline tests (classify → route → refine → validate → index) | Fullstack | 1d | — |
| 10.3.9 | E2E tests: visual editor workflows (open editor → drag component → style → save → verify) | Fullstack | 1d | — |
| 10.3.10 | User guide documentation | Fullstack | 1d | — |

**Sprint 10 Deliverable**: Production-ready platform with multi-app portal, SSO, export/deployment, command palette, onboarding.

---

## Summary

```
Phase    Weeks    Tasks    Focus
─────────────────────────────────────────────────────────────
  0      1-2       20     Org foundation (identity, chart, roles)
  1      3-5       24     Core generation + preview + templates
  2      6-7       18     Agents + discovery + chat refinement
  3      8-9       14     Data model editor + DB browser
  4     10-12      21     Rules engine + 3-layer RBAC
  5     13-15      21     Workflow editor + runtime + assignments
  6     16-19      24     GrapesJS UI editor (white-labeled, 60+ components)
  7     20-21      11     Navigation editor + module system
  8     22-24      21     AI Agent Builder + runtime + knowledge base
  9     25-27      22     Smart fields + semantic search + AI features
 10     28-30      19     Portal + export + polish + testing
─────────────────────────────────────────────────────────────
Total   30 weeks  215 tasks   2-3 developers
```

## Critical Path

```
Phase 0 (org) → Phase 1 (generation) → Phase 2 (agents + chat)
    ↓
Phase 3 (data models) → Phase 4 (rules + RBAC) → Phase 5 (workflows)
    ↓
Phase 6 (UI editor) → Phase 7 (navigation + modules)
    ↓
Phase 8 (AI agents) → Phase 9 (AI features) → Phase 10 (portal + polish)
```

Phases 8-9 (AI) can partially overlap with Phase 7 (navigation) since they are independent feature areas. Similarly, Phases 3-5 are sequential but frontend and backend work within each phase can run in parallel.

## Team Allocation

```
Developer 1 (Backend/AI):
  Primary: Agent prompts (all 13 agents), orchestration, template curation,
           workflow runtime, RBAC middleware, identity sync, AI feature templates
  Phases:  Heavy in 1, 2, 4, 5, 8, 9

Developer 2 (Frontend/Visual):
  Primary: All visual editors (React Flow ×5, GrapesJS ×1), org chart,
           template gallery, discovery UI, all shadcn/ui panels
  Phases:  Heavy in 0, 3, 6, 7, 8

Developer 3 (Fullstack/Integration):
  Primary: AppModel indexing, binding system, module dependencies,
           multi-tenancy middleware, SSO, portal, export, testing
  Phases:  Heavy in 1, 4, 7, 10
```
