# Tentoro Forge — Implemented Features

**Status**: Ground-truth inventory of what's built (not planned)
**Last updated**: 2026-04-10
**Total implemented tasks**: 220+

This document tracks every feature/task that has been **shipped and works today**. Use it to understand current state before planning new work.

---

## 1. Authentication & User Management — ✅ 9 tasks

| # | Task | Key Files |
|---|------|-----------|
| 1.1 | JWT access + refresh tokens with blacklist | `backend/auth.py` |
| 1.2 | Password hashing (bcrypt) + strength validation (8+ chars, case, digits) | `backend/auth.py` |
| 1.3 | Account lockout after N failed attempts with lockout duration | `backend/auth.py` |
| 1.4 | User signup with email uniqueness and validation | `backend/routers/auth.py`, `backend/schemas/auth.py` |
| 1.5 | User login with JWT issuance | `backend/routers/auth.py` |
| 1.6 | Token refresh endpoint (rotation) | `backend/routers/auth.py` |
| 1.7 | Logout with token revocation | `backend/routers/auth.py` |
| 1.8 | `/me` endpoint returning authenticated user profile | `backend/routers/auth.py` |
| 1.9 | FastAPI JWT dependency (`get_current_user`) | `backend/auth.py` |

---

## 2. Organization Management — ✅ 10 tasks

| # | Task | Key Files |
|---|------|-----------|
| 2.1 | Organization CRUD with slug uniqueness | `backend/routers/orgs.py`, `backend/models/org.py` |
| 2.2 | Member role hierarchy (owner > admin > member) | `backend/routers/orgs.py` |
| 2.3 | Invite-by-email flow with status tracking | `backend/routers/orgs.py`, `backend/models/org.py` |
| 2.4 | People (OrgPerson) CRUD with department assignment | `backend/routers/orgs.py` |
| 2.5 | Department hierarchy (parent_id, head_person_id) | `backend/models/org.py` |
| 2.6 | Team management under departments | `backend/routers/orgs.py` |
| 2.7 | Custom role definitions with JSONB permissions per org | `backend/models/org.py` |
| 2.8 | Groups (standalone collections) with membership join | `backend/routers/orgs.py` |
| 2.9 | CSV bulk import of people with column mapping | `backend/routers/orgs.py` |
| 2.10 | Org chart endpoint (hierarchical dept → team → people) | `backend/routers/orgs.py` |

---

## 3. Project Management — ✅ 8 tasks

| # | Task | Key Files |
|---|------|-----------|
| 3.1 | Project CRUD (owner_id, org_id, output_dir) | `backend/routers/projects.py`, `backend/models/project.py` |
| 3.2 | Project copy/duplicate | `backend/routers/projects.py` |
| 3.3 | Project file browsing with metadata | `backend/routers/projects.py` |
| 3.4 | Project file download + ZIP export | `backend/routers/projects.py` |
| 3.5 | Conversation history per project | `backend/routers/projects.py`, `backend/models/project.py` |
| 3.6 | Version history with git commit hashes | `backend/routers/projects.py`, `backend/services/git_service.py` |
| 3.7 | Preview start/stop endpoints | `backend/routers/projects.py`, `backend/preview.py` |
| 3.8 | Project deletion with cleanup | `backend/routers/projects.py` |

---

## 4. Chat System — ✅ 8 tasks

| # | Task | Key Files |
|---|------|-----------|
| 4.1 | Chat message persistence (user/assistant/tool_use/error/status) | `backend/models/project.py` |
| 4.2 | Conversation grouping per generation session | `backend/models/project.py` |
| 4.3 | Chat UI panel with history display | `frontend/src/components/chat/ChatPanel.tsx` |
| 4.4 | Chat input with prompt injection guards | `frontend/src/components/chat/ChatInput.tsx`, `frontend/src/stores/chat.ts` |
| 4.5 | Real-time SSE streaming of agent responses | `frontend/src/hooks/useSSE.ts`, `backend/sse_helpers.py` |
| 4.6 | Chat history persistence in Zustand store | `frontend/src/stores/chat.ts` |
| 4.7 | Intent classification (APPROVE, PLAN, REFINE, EXPLAIN, etc.) | `backend/agents/orchestrator.py` |
| 4.8 | Message-to-agent routing via `/api/projects/{id}/chat` | `backend/routers/generate.py` |

---

## 5. Agent Orchestration — ✅ 24 agents

| # | Agent | Purpose | Key File |
|---|-------|---------|----------|
| 5.1 | Orchestrator | Classifies intent, routes to specialist agents | `backend/agents/orchestrator.py` |
| 5.2 | Planner | Multi-turn requirements → structured plan | `backend/agents/planner.py` |
| 5.3 | Design Agent | Figma/text → design spec (colors, layout, density) | `backend/agents/design_agent.py` |
| 5.4 | Code Generator | Full-stack code from plan + design spec | `backend/agents/code_generator.py` |
| 5.5 | IR Router | Routes IR operations to edit/QA/figma sub-agents | `backend/agents/ir_router.py` |
| 5.6 | IR Edit | Modifies IR based on user feedback | `backend/agents/ir_edit_agent.py` |
| 5.7 | IR QA | Validates IR completeness and consistency | `backend/agents/ir_qa_agent.py` |
| 5.8 | Figma IR | Converts Figma MCP JSX → IR page skeletons | `backend/agents/figma_ir_agent.py` |
| 5.9 | AHTML Conversion | Annotated HTML → TSX via LLM | `backend/agents/ahtml_conversion_agent.py` |
| 5.10 | Schema | Drizzle ORM schema from entities | `backend/agents/schema_agent.py` |
| 5.11 | API | Next.js API routes from schema | `backend/agents/api_agent.py` |
| 5.12 | Business Logic | Validations, computed fields, business rules | `backend/agents/business_logic_agent.py` |
| 5.13 | Component | Reusable React components | `backend/agents/component_agent.py` |
| 5.14 | Page | Full page layouts and compositions | `backend/agents/page_agent.py` |
| 5.15 | Page Layout | Page skeletons with PlaceholderSlot markers | `backend/agents/page_layout_agent.py` |
| 5.16 | Auth | Auth system (login, signup, middleware) | `backend/agents/auth_agent.py` |
| 5.17 | Contract | Initializes contract registry from plan | `backend/agents/contract_agent.py` |
| 5.18 | Validator | Validates generated code, catches build errors | `backend/agents/validator.py` |
| 5.19 | Completeness Checker | Ensures all plan requirements are covered | `backend/agents/completeness_checker.py` |
| 5.20 | Seed Generator | Domain-aware realistic seed data | `backend/agents/seed_generator.py` |
| 5.21 | Refiner | Code fixes and optimizations from feedback | `backend/agents/refiner.py` |
| 5.22 | Design Analyzer | Theme/palette/typography from Figma | `backend/agents/design_analyzer.py` |
| 5.23 | QA | Quality assurance checks on generated code | `backend/agents/qa_agent.py` |
| 5.24 | Code Editor | Targeted single-file edits for visual editor | `backend/agents/code_editor.py` |

---

## 6. Figma Integration — ✅ 7 tasks

| # | Task | Key Files |
|---|------|-----------|
| 6.1 | Figma URL parser (fileKey, nodeId, branchKey extraction) | `backend/figma_parser.py` |
| 6.2 | Figma REST API client (files, nodes, styles, images) | `backend/figma_tools.py` |
| 6.3 | Styles.json extraction (recursive node tree with colors/layout/borders) | `backend/figma_tools.py` |
| 6.4 | Frame screenshot capture via Figma API | `backend/screenshot.py` |
| 6.5 | Image/SVG download with local cache (`public/images/`) | `backend/figma_tools.py` |
| 6.6 | Figma MCP integration (`get_design_context` for React+Tailwind code) | `backend/services/figma_context.py`, `backend/routers/design.py` |
| 6.7 | figma-context.json generation (colors, fonts, spacings, radii) | `backend/services/figma_context.py` |

---

## 7. IR System (Intermediate Representation) — ✅ 10 tasks

| # | Task | Key Files |
|---|------|-----------|
| 7.1 | IR type definitions (AppIR, PageIR, ~35 IRNode types) | `packages/ir/src/types.ts` |
| 7.2 | IR compiler (AppIR → TSX files) | `packages/compiler/src/index.ts` |
| 7.3 | Pattern library (9 fragment types: browse, forms, detail, kanban, timeline, etc.) | `packages/patterns/src/fragments/` |
| 7.4 | Slot filler (PlaceholderSlot → concrete subtree) | `packages/patterns/src/slot-filler.ts` |
| 7.5 | `generateApp()` — AppSpec → AppIR main entry | `packages/patterns/src/generate-app.ts` |
| 7.6 | `generateAppFromSkeletons()` — skeleton-based generation | `packages/patterns/src/generate-app-from-skeleton.ts` |
| 7.7 | Roundtrip system (boundary markers, parse, merge, reverse-map) | `packages/roundtrip/src/` |
| 7.8 | Plan → AppSpec adapter | `backend/services/ir_adapter.py` |
| 7.9 | IR compiler service (Node.js subprocess bridge) | `backend/services/ir_compiler.py` |
| 7.10 | IR pipeline orchestration (full plan → TSX flow) | `backend/services/ir_pipeline.py` |

---

## 8. AHTML System (Annotated HTML) — ✅ 10 tasks

| # | Task | Key Files |
|---|------|-----------|
| 8.1 | AHTML schema (31 `data-*` attribute constants) | `packages/ahtml/src/schema.ts` |
| 8.2 | AHTML types (AnnotatedPage, DataBinding, ActionBinding, etc.) | `packages/ahtml/src/types.ts` |
| 8.3 | Cheerio-based validation (11 checks for valid annotations) | `packages/ahtml/src/validate.ts` |
| 8.4 | HTML parser (extracts semantic model from annotated HTML) | `packages/ahtml/src/html-parser.ts` |
| 8.5 | HTML → TSX prompt builder | `packages/ahtml/src/html-to-tsx.ts` |
| 8.6 | IR → AHTML converter with all node emitters | `packages/ahtml/src/ir-to-html.ts`, `packages/ahtml/src/emitters/` |
| 8.7 | AHTML compiler service (orchestrates parser + LLM agent) | `backend/services/ahtml_compiler.py` |
| 8.8 | AHTML storage (`.design/*.design.html` files) | `backend/services/ahtml_storage.py` |
| 8.9 | Image fixer (replaces gray placeholders with local assets) | `backend/services/ahtml_image_fixer.py` |
| 8.10 | MCP semanticizer (converts div-soup to semantic HTML) | `backend/services/mcp_semanticizer.py` |

---

## 9. Code Generation Pipeline — ✅ 12 tasks

| # | Task | Key Files |
|---|------|-----------|
| 9.1 | Unified relay pipeline (`_run_relay_pipeline`) | `backend/routers/generate.py` |
| 9.2 | Figma-specific relay pipeline (`_run_figma_relay_pipeline`) | `backend/routers/generate.py` |
| 9.3 | SSE event streaming with buffering | `backend/sse_helpers.py`, `backend/routers/generate.py` |
| 9.4 | Parallel agent runner with timeout enforcement | `backend/services/parallel_runner.py` |
| 9.5 | Post-generation fixes (lint, imports, formatting) | `backend/services/post_generate_fixes.py` |
| 9.6 | Figma prefetch (styles.json, screenshots, images) | `backend/agent.py` (`_prefetch_figma_data`) |
| 9.7 | Domain detection from description | `backend/services/domain_context.py` |
| 9.8 | Industry design injection (theme per domain) | `backend/services/industry_design.py` |
| 9.9 | Smart Figma color mapping (HSL-based hue categorization) | `backend/services/industry_design.py` (`_map_figma_colors_to_tokens`) |
| 9.10 | Agent timeout handling (`AGENT_TIMEOUT_SECONDS`) | `backend/services/parallel_runner.py` |
| 9.11 | Error surfacing in IR pipeline (try/except with SSE log) | `backend/routers/generate.py` |
| 9.12 | Pipeline commit with Figma URL in message | `backend/routers/generate.py`, `backend/services/git_service.py` |

---

## 10. Data Model — ✅ 14 tasks

| # | Task | Key Files |
|---|------|-----------|
| 10.1 | Entity CRUD (create/read/update/delete) | `backend/routers/data_model.py` |
| 10.2 | Field type system (string, number, date, boolean, enum, relation, computed) | `backend/routers/data_model.py`, `frontend/src/components/data-model/EditFieldDialog.tsx` |
| 10.3 | Field constraints (required, unique, default, maxLength, enum values) | `backend/routers/data_model.py` |
| 10.4 | Relationships (1-to-1, 1-to-many, many-to-many) | `frontend/src/components/data-model/RelationshipEditor.tsx` |
| 10.5 | Visual ERD canvas with React Flow | `frontend/src/components/data-model/ERDCanvas.tsx` |
| 10.6 | Index management | `frontend/src/components/data-model/IndexEditor.tsx` |
| 10.7 | Enum editor | `frontend/src/components/data-model/EnumEditor.tsx` |
| 10.8 | Drizzle schema generation (per-entity split) | `backend/agents/schema_agent.py` |
| 10.9 | Schema apply via `drizzle-kit push` | `backend/routers/data_model.py` |
| 10.10 | SQL console (raw queries) | `frontend/src/components/data-model/SqlConsole.tsx`, `backend/routers/data_model.py` |
| 10.11 | Database browser (read-only asyncpg) | `frontend/src/components/data-model/DatabaseBrowser.tsx` |
| 10.12 | Seed data editor UI | `frontend/src/components/data-model/SeedDataEditor.tsx` |
| 10.13 | Smart fields (AI-computed field editor) | `frontend/src/components/data-model/SmartFieldEditor.tsx` |
| 10.14 | Schema impact analysis | `frontend/src/components/data-model/ImpactAnalysis.tsx` |

---

## 11. Preview & Runtime — ✅ 7 tasks

| # | Task | Key Files |
|---|------|-----------|
| 11.1 | Dev server launcher (`npx next dev`) | `backend/preview.py` |
| 11.2 | Port allocation from pool (3200-3299) | `backend/preview.py`, `backend/services/preview_manager.py` |
| 11.3 | Health check polling (HTTP GET with 30s interval) | `backend/services/preview_manager.py` |
| 11.4 | Auto-restart with exponential backoff (max 3 attempts) | `backend/services/preview_manager.py` |
| 11.5 | Process tree kill (SIGTERM on setsid group) | `backend/services/preview_manager.py` |
| 11.6 | Docker PostgreSQL per project | `backend/services/preview_manager.py` |
| 11.7 | Next.js HMR-aware reload detection | `frontend/src/components/preview/PreviewFrame.tsx` |

---

## 12. Visual Editor (Blueprint-Aligned) — ✅ 14 tasks

| # | Task | Key Files |
|---|------|-----------|
| 12.1 | 3-panel layout (Sections / Canvas / Properties) | `frontend/src/components/visual-editor/VisualEditor.tsx` |
| 12.2 | Bridge.js injection for DOM extraction | `backend/static/bridge.js`, `backend/routers/visual_editor.py` |
| 12.3 | Element click selection with overlays | `backend/static/bridge.js`, `frontend/src/hooks/useBridge.ts` |
| 12.4 | Direct Tailwind class editing (add/remove/replace) | `backend/services/visual_edit_service.py` |
| 12.5 | Direct text content editing | `backend/services/visual_edit_service.py` |
| 12.6 | Direct JSX prop editing | `backend/services/visual_edit_service.py` |
| 12.7 | Git-backed undo/redo | `backend/routers/visual_editor.py` |
| 12.8 | Section outline panel (hierarchical tree) | `frontend/src/components/visual-editor/SectionOutlinePanel.tsx` |
| 12.9 | Context panel (Tailwind class chips + props display) | `frontend/src/components/visual-editor/ContextPanel.tsx` |
| 12.10 | Element action popover (edit text, delete, ask AI) | `frontend/src/components/visual-editor/ElementActionPopover.tsx` |
| 12.11 | AI-mediated edits via code_editor agent with SSE | `backend/routers/visual_editor.py`, `backend/agents/code_editor.py` |
| 12.12 | Add section wizard with template library | `frontend/src/hooks/useAddSection.ts`, `backend/services/section_instruction_builder.py` |
| 12.13 | Section reordering (Babel AST-based drag-and-drop) | `backend/services/section_reorder_service.py` |
| 12.14 | Source annotation (file/line/component data attrs) | `backend/services/source_annotator.py` |

---

## 13. AHTML Editor (GrapeJS-Based) — ✅ 11 tasks

| # | Task | Key Files |
|---|------|-----------|
| 13.1 | GrapeJS editor integration with canvas | `frontend/src/components/design-editor/DesignEditor.tsx`, `grapesjs-config.ts` |
| 13.2 | Component palette with 5 categories (Layout/Content/Inputs/Data/Slots) | `frontend/src/components/design-editor/ComponentPalette.tsx` |
| 13.3 | Draggable blocks with gradient icons (workflow-palette style) | `frontend/src/components/design-editor/blocks/` |
| 13.4 | Custom GrapeJS component types with traits | `frontend/src/components/design-editor/grapesjs-config.ts` (`registerCustomComponents`) |
| 13.5 | Droppable containers (Stack, Row, Grid, Card, Form, Tabs) | `grapesjs-config.ts` |
| 13.6 | Tailwind CSS in canvas via CDN script | `grapesjs-config.ts` (`setupCanvasTailwind`) |
| 13.7 | Annotation panel (data-* attribute editor) | `frontend/src/components/design-editor/panels/AnnotationPanel.tsx` |
| 13.8 | Data binding panel (entity picker, field binding, form/table insertion) | `frontend/src/components/design-editor/panels/DataBindingPanel.tsx` |
| 13.9 | Workflow binding panel (connect form → workflow) | `frontend/src/components/design-editor/panels/WorkflowBindingPanel.tsx` |
| 13.10 | Page flow panel (React Flow mini-canvas of page graph) | `frontend/src/components/design-editor/panels/PageFlowPanel.tsx` |
| 13.11 | Fast compile path (MCP code → TSX without LLM) | `backend/routers/design.py`, `backend/services/mcp_semanticizer.py` |

---

## 14. Workflow System — ✅ 14 tasks

| # | Task | Key Files |
|---|------|-----------|
| 14.1 | Workflow definition CRUD (JSON storage) | `backend/routers/workflows.py`, `backend/models/workflow.py` |
| 14.2 | React Flow-based visual canvas | `frontend/src/components/workflow/WorkflowCanvas.tsx` |
| 14.3 | 15+ node types (triggers, actions, flow control, human-in-loop, AI) | `frontend/src/components/workflow/nodes/` |
| 14.4 | Sequence and conditional edges | `frontend/src/components/workflow/edges/` |
| 14.5 | Node properties panel | `frontend/src/components/workflow/NodePropertiesPanel.tsx` |
| 14.6 | Workflow instance execution engine | `backend/runtime/engine.py`, `backend/routers/workflows.py` |
| 14.7 | Task instance tracking (pending/running/completed/failed) | `backend/models/workflow_instance.py`, `backend/runtime/task_executor.py` |
| 14.8 | Assignment policies (role/group/person/process-variable) | `backend/runtime/assignment.py`, `backend/models/workflow.py` |
| 14.9 | Variable resolver for node inputs | `backend/runtime/variable_resolver.py` |
| 14.10 | Decision node evaluation (FEEL-lite conditions) | `backend/runtime/decision_evaluator.py` |
| 14.11 | Timer scheduling (wait/delay nodes) | `backend/runtime/timer_scheduler.py` |
| 14.12 | Execution logger with audit trail | `backend/runtime/execution_logger.py`, `frontend/src/components/workflow/ExecutionLogViewer.tsx` |
| 14.13 | Workflow tester (sample input → simulation) | `frontend/src/components/workflow/WorkflowTester.tsx` |
| 14.14 | Workflow apply (compile to generated code) | `backend/routers/workflows.py` |

---

## 15. Rules System — ✅ 10 tasks

| # | Task | Key Files |
|---|------|-----------|
| 15.1 | Project rules CRUD (10 rule types supported) | `backend/routers/rules.py`, `backend/models/rules.py` |
| 15.2 | FEEL-lite parser + evaluator (frontend + backend) | `frontend/src/lib/feel-lite/`, `backend/runtime/feel_lite/` |
| 15.3 | Visual condition builder (AND/OR logic) | `frontend/src/components/rules/ConditionBuilder.tsx`, `ConditionRow.tsx` |
| 15.4 | Rule validation (syntax, types, data dependencies) | `backend/services/validate_rules.py` |
| 15.5 | Access policies (app-level + field-level) | `backend/routers/rules.py`, `frontend/src/components/rules/AccessControlRuleForm.tsx` |
| 15.6 | Field access matrix (role × field visualization) | `frontend/src/components/rules/FieldAccessMatrix.tsx` |
| 15.7 | Record scope filtering | `frontend/src/components/rules/RecordScopeEditor.tsx` |
| 15.8 | State machine editor | `frontend/src/components/rules/StateMachineEditor.tsx` |
| 15.9 | Rule cross-references (which pages/workflows use it) | `frontend/src/components/rules/RuleCrossReferences.tsx` |
| 15.10 | 18 FEEL-lite built-in functions (sum, count, min, max, contains, matches, date, etc.) | `frontend/src/lib/feel-lite/evaluator.ts` |

---

## 16. Navigation — ✅ 9 tasks

| # | Task | Key Files |
|---|------|-----------|
| 16.1 | Screen CRUD | `backend/routers/navigation.py`, `frontend/src/components/navigation/NavigationPanel.tsx` |
| 16.2 | Flow editor (React Flow canvas with screens + edges) | `frontend/src/components/navigation/FlowEditor.tsx` |
| 16.3 | Screen properties panel | `frontend/src/components/navigation/ScreenProperties.tsx` |
| 16.4 | Flow edge properties (transition conditions) | `frontend/src/components/navigation/FlowEdgeProperties.tsx` |
| 16.5 | Module manager (group screens into modules) | `frontend/src/components/navigation/ModuleManager.tsx` |
| 16.6 | Module creation wizard | `frontend/src/components/navigation/ModuleWizard.tsx` |
| 16.7 | Layout assignment per screen (sidebar/topbar/blank) | `backend/routers/navigation.py` |
| 16.8 | navigation.json persistence | `backend/routers/navigation.py` |
| 16.9 | Apply navigation → compile to Next.js routes | `backend/routers/navigation.py` |

---

## 17. Templates — ✅ 7 tasks

| # | Task | Key Files |
|---|------|-----------|
| 17.1 | Template CRUD | `backend/routers/templates.py`, `backend/models/template.py` |
| 17.2 | Template gallery UI with filtering | `frontend/src/app/org/[orgId]/templates/` |
| 17.3 | Template categories (Operations, Sales, HR, Finance, etc.) | `backend/seeds/templates.py` |
| 17.4 | Complexity levels (Simple/Moderate/Advanced) | `backend/seeds/templates.py` |
| 17.5 | Template → project conversion | `backend/routers/templates.py` |
| 17.6 | Context-aware template suggestions | `backend/routers/portal.py` |
| 17.7 | 15+ seeded templates (Inventory, CRM Lite, Quote Builder, Asset Tracker, etc.) | `backend/seeds/templates.py` |

---

## 18. Seed Data — ✅ 4 tasks

| # | Task | Key Files |
|---|------|-----------|
| 18.1 | seed-plan.json contract generation | `backend/agents/seed_generator.py` |
| 18.2 | AI-generated realistic data (names, emails, dates, descriptions) | `backend/agents/seed_generator.py` |
| 18.3 | Domain-aware seeding (theme parameter per industry) | `backend/agents/seed_generator.py` |
| 18.4 | Drizzle seed.ts file generation + auto-execution | `backend/agents/seed_generator.py` |

---

## 19. Discovery — ✅ 4 tasks

| # | Task | Key Files |
|---|------|-----------|
| 19.1 | Multi-turn discovery session (Q&A based requirements gathering) | `backend/routers/discovery.py` |
| 19.2 | Session persistence with conversation history | `backend/models/discovery.py` |
| 19.3 | Org context integration (departments, people, existing projects) | `backend/routers/discovery.py` |
| 19.4 | Discovery → project conversion | `backend/routers/discovery.py` |

---

## 20. Registry (Contract Registry) — ✅ 9 tasks

| # | Task | Key Files |
|---|------|-----------|
| 20.1 | Registry CRUD (in-memory + file-based) | `backend/services/registry.py` |
| 20.2 | Entity registry (fields, constraints) | `backend/services/registry.py` |
| 20.3 | Route registry (API endpoint tracking) | `backend/services/registry.py` |
| 20.4 | Component registry (with prop signatures) | `backend/services/registry.py` |
| 20.5 | Page registry (route → components mapping) | `backend/services/registry.py` |
| 20.6 | Registry extractor (parse schema/routes/components from files) | `backend/services/registry_extractor.py` |
| 20.7 | Registry validator (11 consistency checks) | `backend/services/registry_validator.py` |
| 20.8 | Registry auto-repair (fix deterministic mismatches) | `backend/services/registry_repair.py` |
| 20.9 | Registry persistence (`registry.json`) | `backend/services/registry.py` |

---

## 21. Monitoring & Observability — ✅ 8 tasks

| # | Task | Key Files |
|---|------|-----------|
| 21.1 | Cost tracking panel (token usage by agent/phase) | `frontend/src/components/monitoring/CostTrackingPanel.tsx`, `backend/routers/portal.py` |
| 21.2 | Error log tracking per project | `backend/routers/portal.py` |
| 21.3 | Sentry integration (optional via DSN) | `backend/main.py`, `backend/config.py` |
| 21.4 | Metrics middleware (request latency, status codes) | `backend/middleware/metrics.py` |
| 21.5 | Structured JSON logging middleware | `backend/middleware/logging.py` |
| 21.6 | Rate limiting middleware (default 60 req/min) | `backend/middleware/rate_limit.py` |
| 21.7 | Project cost summary | `backend/routers/portal.py` |
| 21.8 | Prometheus metrics endpoint (`/metrics`) | `backend/main.py` |

---

## 22. Virtual Office (Agent Visualization) — ✅ 8 tasks

| # | Task | Key Files |
|---|------|-----------|
| 22.1 | Sprite-based agent characters with animations | `frontend/src/components/virtual-office/AgentCharacter.ts`, `SpriteLoader.ts` |
| 22.2 | 2D canvas office renderer | `frontend/src/components/virtual-office/OfficeRenderer.ts` |
| 22.3 | Agent pathfinding (grid-based movement) | `frontend/src/components/virtual-office/Pathfinder.ts` |
| 22.4 | Office state manager (positions, activities) | `frontend/src/components/virtual-office/OfficeStateManager.ts` |
| 22.5 | SSE-triggered activity events (meeting, working, presenting) | `backend/services/office_events.py` |
| 22.6 | HUD overlays (status labels, phase info) | `frontend/src/components/virtual-office/hud/` |
| 22.7 | Office layout system (desks, meeting rooms, whiteboard) | `frontend/src/components/virtual-office/layout.ts` |
| 22.8 | Sprite sheet slicing tool | `tools/slice_sprites.py` |

---

## 23. Pages & Routing — ✅ 4 tasks

| # | Task | Key Files |
|---|------|-----------|
| 23.1 | Page entity CRUD (PageDefinition model) | `backend/routers/pages.py`, `backend/models/page.py` |
| 23.2 | Route mapping (page → `/route` path) | `backend/routers/pages.py` |
| 23.3 | Page → TSX compilation | `backend/routers/pages.py` |
| 23.4 | Section templates library (hero, form, table, gallery, etc.) | `backend/services/section_templates.py` |

---

## 24. Decisions (DRD Editor) — ✅ 7 tasks

| # | Task | Key Files |
|---|------|-----------|
| 24.1 | Decision table editor (Excel-like UI) | `frontend/src/components/decision/DecisionTableEditor.tsx` |
| 24.2 | DRD canvas (visual diagram) | `frontend/src/components/decision/DRDCanvas.tsx` |
| 24.3 | Decision node properties (hit policy: first/any/unique/collect) | `frontend/src/components/decision/DRDNodePanel.tsx` |
| 24.4 | Expression autocomplete | `frontend/src/components/decision/ExpressionAutocomplete.tsx` |
| 24.5 | Decision testing with sample inputs | `frontend/src/components/decision/DecisionTestPanel.tsx` |
| 24.6 | Decision versioning with diff/rollback | `frontend/src/components/decision/DecisionVersionPanel.tsx` |
| 24.7 | Decision tracing (which rules fired for input) | `frontend/src/components/decision/DecisionAnalysisOverlay.tsx` |

---

## 25. Agent Builder — ✅ 6 tasks

| # | Task | Key Files |
|---|------|-----------|
| 25.1 | Custom agent definition CRUD | `backend/routers/agent_builder.py`, `frontend/src/components/agent-builder/AgentBuilderPanel.tsx` |
| 25.2 | Visual agent canvas (React Flow) | `frontend/src/components/agent-builder/AgentCanvas.tsx` |
| 25.3 | Agent node types (Input, Process, Decision, Output, API, LLM) | `frontend/src/components/agent-builder/nodes/` |
| 25.4 | Pre-built agent templates | `frontend/src/components/agent-builder/AgentTemplateSelector.tsx` |
| 25.5 | Agent test console (run with sample inputs) | `frontend/src/components/agent-builder/AgentTestConsole.tsx` |
| 25.6 | Agent apply → register in pipeline | `backend/routers/agent_builder.py` |

---

## 26. AI Features — ✅ 6 tasks

| # | Task | Key Files |
|---|------|-----------|
| 26.1 | Semantic search configuration per entity | `backend/routers/ai_features.py` |
| 26.2 | AI component config (smart forms, smart tables) | `backend/routers/ai_features.py`, `frontend/src/components/ai-features/AIFeaturesPanel.tsx` |
| 26.3 | Scheduled AI tasks (daily reports, cron-like) | `backend/routers/ai_features.py` |
| 26.4 | Smart field testing UI | `backend/routers/ai_features.py` |
| 26.5 | AI model configuration (primary/embedding/budget) | `backend/routers/ai_features.py` |
| 26.6 | MCP semanticizer service | `backend/services/mcp_semanticizer.py` |

---

## Summary by Category

| Category | Tasks | Status |
|----------|-------|--------|
| Auth & Users | 9 | ✅ Complete |
| Org Management | 10 | ✅ Complete (enterprise features pending) |
| Projects | 8 | ✅ Complete |
| Chat | 8 | ✅ Complete |
| Agent Orchestration | 24 | ✅ Complete (24 agents) |
| Figma Integration | 7 | ✅ Complete |
| IR System | 10 | ✅ Complete |
| AHTML System | 10 | ✅ Complete |
| Code Generation | 12 | ✅ Complete |
| Data Model | 14 | ✅ Complete |
| Preview & Runtime | 7 | ✅ Complete (dev mode only) |
| Visual Editor | 14 | ✅ Complete |
| AHTML Editor | 11 | ✅ Complete |
| Workflow System | 14 | ✅ Complete |
| Rules System | 10 | ✅ Complete |
| Navigation | 9 | ✅ Complete |
| Templates | 7 | ✅ Complete |
| Seed Data | 4 | ⚠️ Partial (no UI editor) |
| Discovery | 4 | ✅ Complete |
| Registry | 9 | ✅ Complete |
| Monitoring | 8 | ⚠️ Partial (no dashboards) |
| Virtual Office | 8 | ✅ Complete |
| Pages & Routing | 4 | ✅ Complete |
| Decisions (DRD) | 7 | ✅ Complete |
| Agent Builder | 6 | ✅ Complete |
| AI Features | 6 | ✅ Complete |

**Total implemented tasks**: ~230 (24 agents + ~206 feature tasks)
**Categories fully built**: 23 of 26
**Categories partial**: 2 (Seed Data, Monitoring)
**Categories missing**: 0 (everything has at least a starting point)

---

## What's NOT Implemented (For Reference)

These are in the development plan but not yet built:

### Core Platform
- ❌ One-click deployment (Vercel, Railway, Cloudflare)
- ❌ Production runtime mode (only dev mode)
- ❌ Log capture from generated apps
- ❌ Process supervision (auto-restart works, but no PM2-level features)
- ❌ Resource limits per project

### Data & DB
- ❌ Managed DB providers (Neon, Supabase, PlanetScale)
- ❌ Migration versioning / rollback
- ❌ CSV/JSON bulk seed import
- ❌ Database backup/restore
- ❌ Multi-DB support (SQLite, MySQL)

### Org Enterprise
- ❌ Billing / subscription tiers / usage metering
- ❌ Resource quotas
- ❌ Audit log middleware (table exists, not wired)
- ❌ Email sending (SendGrid/Postmark)
- ❌ SAML SSO, OAuth providers
- ❌ MFA/2FA, password reset

### Rules
- ❌ Runtime rule engine (rules still code-injected)
- ❌ Rule testing playground
- ❌ Conflict detection
- ❌ Impact analysis
- ❌ AI rule suggester

### Collaboration
- ❌ Multi-user concurrent editing
- ❌ Comment threads on elements
- ❌ Presence indicators
- ❌ Real-time notifications

### Mobile
- ❌ React Native / Expo generation
- ❌ Capacitor wrapping
- ❌ Mobile IR compiler
- ❌ EAS Build integration
- ❌ TestFlight / Play Store deploy

### Messaging
- ❌ Platform team chat
- ❌ Generated app messaging library (`@tentoro/messaging`)

### AI Collaboration
- ❌ Vision-enabled code_editor agent (screenshots)
- ❌ Diff preview / approval gate for AI edits
- ❌ Intent annotations (`data-intent="locked"`)
- ❌ Real-time AI suggestions

See `DEVELOPMENT_PLAN.md` for the plan to close these gaps.
