# Tentoro Forge — Remaining Implementation Tasks
# Generated 2026-03-06 from Blueprint.md analysis

Status legend: `[ ]` = Not started, `[~]` = Partially done, `[x]` = Complete

---

## Priority 1: Generated App Code Templates (CRITICAL GAP)

The platform-side editors and configuration are largely complete, but the code
generation pipeline does not yet output runtime code for several advanced features
into the generated apps. This is the single biggest gap.

### 1A. FEEL-Lite & Decision Tables for Generated Apps
```
[ ] FEEL-lite parser template: src/shared/feel-lite/ in generated apps
[ ] Decision table evaluator template: src/shared/decisions/ in generated apps
[ ] Decision graph evaluator template for generated apps
[ ] Standalone decision files: src/domain/{module}/decisions/{name}.ts
[ ] Decision schema in Drizzle: decision_versions, decision_execution_logs tables
[ ] Planner/Code Generator: include decision tables in plan when rules warrant them
```

### 1B. RBAC Runtime for Generated Apps
```
[ ] useFieldPermissions React hook template for generated app components
[ ] /api/me/permissions endpoint template for generated apps
[ ] Org structure sync: platform org_people → generated app users table
[ ] Field-level access enforcement in generated API route handlers
[ ] Record-scope filtering in generated repository queries
```

### 1C. Workflow Runtime for Generated Apps
```
[ ] Workflow executor template: src/workflows/runtime.ts
[ ] Trigger registration template: src/workflows/triggers.ts
[ ] Workflow definition JSON loader: src/workflows/definitions/
[ ] Workflow action templates: src/workflows/actions/
[ ] Task inbox page template for generated apps
[ ] Workflow assignment/approval UI templates
[ ] Escalation handler: SLA breach → escalate up org chart
```

### 1D. AI Agent Runtime for Generated Apps
```
[ ] Agent runtime template: src/agents/runtime.ts
[ ] Tool registry template: src/agents/tools/registry.ts (auto-register API routes)
[ ] Memory manager template: src/agents/memory.ts
[ ] Guardrails template: src/agents/guardrails.ts
[ ] Chat API route template: src/app/api/agents/[agentId]/chat/route.ts
[ ] ChatWidget component template (floating + full-page modes)
[ ] Agent conversation tables in generated app schema
[ ] Knowledge base: pgvector setup, document upload, chunking, embedding, search tool
[ ] Agent analytics dashboard template
[ ] AppModel index: agents section
```

### 1E. AI-Powered Features for Generated Apps
```
[ ] Smart field runtime: src/infrastructure/ai/smart-fields.ts template
[ ] Smart field types: ai_classify, ai_summarize, ai_sentiment, ai_extract,
    ai_generate, ai_translate, ai_score
[ ] Smart field test console ("Test with sample data" button)
[ ] Smart field UI indicators (✦ icon, override, recompute)
[ ] Async smart field computation (non-blocking API response)
[ ] Semantic search: pgvector setup, embedding computation, hybrid search
[ ] Semantic search UI component with score display
[ ] AI-assisted components: SmartFormField, InlineAssistant
[ ] NaturalLanguageQuery component (text → SQL → results → summary)
[ ] SmartFilterBar component (natural language → structured filters)
[ ] DataInsightsPanel component (auto-generated insights)
[ ] Scheduled AI tasks via workflow engine
[ ] AI configuration file template (ai-config.ts, ai-usage.ts)
[ ] Code Generator prompt: include smart field configs + AI components
```

---

## Priority 2: Module System Pipeline

The navigation editor exists but the module lifecycle is not wired end-to-end.

```
[x] Module creation wizard that triggers Planner agent for new module
[x] Module-scoped file organization (output/{project_id}/src/{module}/)
[~] Module-scoped AppModel index sections
[x] Cross-module dependency tracking (UI exists in navigation store, pipeline missing)
[x] Connections map: visual overview of all module relationships
[ ] Planner agent: split large requests into multiple modules
[ ] Code Generator: generate into module-scoped directories
[ ] Indexer: update module-scoped AppModel sections
```

---

## Priority 3: Frontend Org Management Pages

Backend APIs are fully built (orgs.py — 952 lines). Frontend pages exist as route
shells but have minimal UI. Each needs a proper data table, forms, and interactions.

```
[x] /org/[orgId]/people — People directory table with search, filter, inline edit
[x] /org/[orgId]/departments — Department tree with drag-to-reorganize
[x] /org/[orgId]/teams — Team list with member management
[x] /org/[orgId]/roles — Role list with hierarchy visualization, create/edit forms
[x] /org/[orgId]/groups — Group list with member add/remove
[x] /org/[orgId]/import — CSV/JSON import with column mapping preview
[x] /org/[orgId]/org-chart — React Flow org chart editor (drag people between depts)
[x] /org/[orgId]/settings — Org name, logo, plan, invite members
[x] Suggested apps section on org dashboard (based on departments without apps)
```

---

## Priority 4: DRD Visual Editor

The decision graph evaluator exists on both backend and frontend, but there is
no visual canvas for building Decision Requirement Diagrams.

```
[x] Mini React Flow canvas for chaining decisions
[x] DRD node types: InputData (oval), Decision (rectangle), KnowledgeSource (wavy)
[x] DRD edge drawing (input data → decision, decision → decision)
[x] Inline decision table editor per DRD Decision node
[~] Topological evaluation visualization (show execution path)
```

---

## Priority 5: Multi-App Portal

Portal router and store exist but the cross-app features are not built.

```
[x] Multi-app portal page generation (auto-generated per org)
[x] App grid with role-based visibility
[x] Unified task inbox (pending approvals/tasks across all apps)
[x] Cross-app notifications and activity feed
[x] Portal API endpoints in generated apps (/api/portal/tasks, badges, activity)
[ ] SSO token sharing across apps in same org (sso.py router exists, logic incomplete)
[x] Quick search across all apps
```

---

## Priority 6: Export & Deployment

```
[x] Export: git push to user's repository (GitHub/GitLab integration)
[x] Export: Dockerfile generation for production deployment
[x] Export: docker-compose.yml for production (Postgres + app)
[x] Export: README.md generation with setup instructions
[x] Export: Environment variable documentation (.env.example)
```

---

## Priority 7: Testing & Quality

```
[ ] E2E tests for visual editors (Playwright or Cypress)
[ ] Integration tests for full agent pipeline (generate → validate → index)
[ ] Integration tests for relay pipeline (contract → schema → parallel → QA)
[x] Unit tests for FEEL-lite expression engine (both backend and frontend)
[x] Unit tests for decision table evaluator
[x] Unit tests for workflow runtime engine
[ ] Load testing for SSE streaming under concurrent users
[ ] User documentation / user guide
```

---

## Priority 8: Polish & UX

```
[x] Onboarding tutorial for new users (portal store has state, UI not built)
[x] Command palette full implementation (store exists, not all commands wired)
[x] Preview server crash recovery (auto-restart on failure)
[ ] Agent response caching for common patterns
[ ] Incremental AppModel updates (not full re-index after every change)
```

---

## Priority 9: Smaller Gaps & Cross-Cutting

### Agent System Gaps
```
[~] Agent #10 (Workflow Generator) — agent file exists, integration partial
[~] Agent #11 (Agent Builder) — agent file exists, integration partial
[~] Full relay pipeline orchestration — individual agents exist, parallel
    pipeline coordination in generate.py may need wiring for all paths
[ ] AppModel index automatic refresh after every code change (indexer pipeline)
```

### Rules Editor Gaps
```
[x] Cross-reference: show rules in data model editor field properties
[x] Cross-reference: show access rules in UI editor component properties
[ ] Decision table copy/paste rows from spreadsheet apps
[x] Expression autocomplete provider from AppModel schema — PARTIAL
[~] Type checking: verify expressions match bound variable types — PARTIAL
```

### Decision Versioning Gaps
```
[x] Version diff view (side-by-side comparison of decision table versions)
[ ] Effective dating (schedule version activation for a future date)
```

### Visual Editor Gaps
```
[ ] Field mapper — bind data model fields to component traits in visual editor
```

### Navigation Editor Gaps
```
[ ] Screen node thumbnail preview (screenshot of each page)
```

---

## Implementation Order Recommendation

For maximum impact, work in this order:

1. **Generated App Code Templates (Priority 1)** — This is the keystone feature.
   Without it, the platform can generate basic CRUD apps but can't output the
   advanced features users configure via the visual editors. Start with 1B (RBAC)
   and 1C (Workflows) as they affect the most apps.

2. **Frontend Org Pages (Priority 3)** — Quick wins. Backend is done. Just needs
   proper React tables/forms. High visibility improvement.

3. **Module System (Priority 2)** — Enables building complex, multi-module apps.
   Currently all generation is single-module.

4. **DRD Visual Editor (Priority 4)** — The evaluator works. Just needs the
   React Flow canvas for visual editing.

5. **Export & Deployment (Priority 6)** — Users can download ZIP today but can't
   deploy to production easily.

6. **Portal (Priority 5)** + **Testing (Priority 7)** + **Polish (Priority 8)**
   — Final stretch for production readiness.
