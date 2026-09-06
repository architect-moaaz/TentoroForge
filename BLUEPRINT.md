# Tentoro Forge — Conversational + Visual App Creator
# Complete Implementation Blueprint

---

## Table of Contents

1. [Platform Overview](#1-platform-overview)
2. [Tech Stack](#2-tech-stack)
3. [Project Structure](#3-project-structure)
4. [Platform Database Schema](#4-platform-database-schema)
5. [Agent System](#5-agent-system)
6. [Backend API](#6-backend-api)
7. [Frontend Pages & Components](#7-frontend-pages--components)
8. [Visual Editors](#8-visual-editors)
9. [Generated App Structure](#9-generated-app-structure)
9A. [Schema / Renderer Contract](#9a-schema--renderer-contract)
10. [Preview System](#10-preview-system)
11. [Module System](#11-module-system)
12. [AppModel Index](#12-appmodel-index)
13. [Binding System](#13-binding-system)
14. [Rules Engine & Decision Builder](#14-rules-engine--decision-builder)
15. [Workflow Engine](#15-workflow-engine)
16. [Database Management](#16-database-management)
17. [Authentication & Authorization](#17-authentication--authorization)
18. [Real-time & Collaboration](#18-real-time--collaboration)
19. [Deployment & Export](#19-deployment--export)
20. [AI Agent Builder](#20-ai-agent-builder)
21. [AI-Powered Application Features](#21-ai-powered-application-features)
22. [Organization & Multi-Tenancy](#22-organization--multi-tenancy)
23. [Discovery & Templates](#23-discovery--templates)
24. [Implementation Phases](#24-implementation-phases)
25. [Virtual Office](#25-virtual-office)
26. [Domain Context System](#26-domain-context-system)
27. [Current State Audit (2026-07-21)](#27-current-state-audit-2026-07-21) — authoritative overlay of every material capability shipped since §1–§26 were last touched
28–31. Dated addenda (2026-06-19 → 2026-07-26): Business Rules editor, re-plan gate, visual-editor hardening, per-app Design DNA
32. [**Current State Audit (2026-08-26) — the smithv2 / a2ui rebuild**](#32-current-state-audit-2026-08-26--the-smithv2--a2ui-rebuild) — the current architecture; supersedes §27

---

> **Reading this document?** It is layered by date, newest wins.
> §1–§26 are the original design (May 2026). §27 is a full re-audit (2026-07-21).
> §28–§31 are dated addenda. **§32 [Current State Audit (2026-08-26)](#32-current-state-audit-2026-08-26--the-smithv2--a2ui-rebuild)
> is the current truth for the `smithv2` rebuild** — the LangGraph pipeline spine,
> the Living Application Blueprint, the A2UI (`agent2ui` MCP) composer, Smith, and
> the ship→heal verify loop. **When sections disagree, the higher-numbered
> (newer) section wins: §32 > §31…§28 > §27 > §1–§26.** Start at §32 for what the
> code actually does today, then read the earlier sections for the parts §32 says
> still hold.

---

## 1. Platform Overview

### 1.1 What It Is

A platform where users describe applications in natural language, get a fully working app with live preview, then visually edit every aspect — UI, data models, workflows, rules, and navigation — through specialized visual editors. Every visual edit produces a natural language instruction that the same LLM agent processes, keeping the system simple.

### 1.2 Core Loop

```
User Input (chat or visual editor)
    → Orchestrator classifies intent
    → Routes to appropriate agent
    → Agent reads AppModel index for context
    → Agent reads/edits source code
    → Validator confirms build passes
    → Indexer updates AppModel
    → Preview hot-reloads
    → All editors refresh
```

### 1.3 Key Principles

- Code is the source of truth. The AppModel index is a navigation aid, not a code generator.
- Every visual editor action produces a text instruction. One LLM pipeline for everything.
- Generated apps use PostgreSQL from day one. Docker Compose handles local setup.
- Apps are built module by module, not all at once. Each module is a manageable generation task.
- The LLM is a very fast developer, not a magic generator. Humans guide, validate, and refine.
- Generated apps can be intelligent. LLM capabilities are embedded into data processing, workflows, and UI — not just chatbots.
- Organizations are the root entity. Users, roles, departments exist at the org level and are shared across all apps.
- RBAC is three layers deep: org-level roles, app-level roles, and field/record-level access — enforced everywhere.
- Generated apps follow Clean Architecture: domain logic has zero framework dependencies, services orchestrate use cases, repositories abstract the database, API routes are thin HTTP handlers.

---

## 2. Tech Stack

### 2.1 Platform (the builder tool itself)

```
Backend:
  Runtime:        Python 3.12+
  Framework:      FastAPI
  LLM SDK:        Claude Agent SDK (claude-agent-sdk)
  LLM Models:     Claude Sonnet 4 (primary), Claude Haiku 4.5 (utility)
  Database:       PostgreSQL 16 (platform state — projects, conversations, etc.)
  ORM:            SQLAlchemy 2.0 + asyncpg
  Migrations:     Alembic
  Task Queue:     None initially (async endpoints suffice), later: Celery + Redis
  WebSocket:      FastAPI WebSocket for real-time preview updates
  SSE:            sse-starlette for streaming agent progress
  File Storage:   Local filesystem (output/{project_id}/)
  Container Mgmt: Docker SDK for Python (docker-py)

Frontend:
  Framework:      Next.js 15 (App Router)
  Language:       TypeScript 5.7+
  Styling:        Tailwind CSS 4
  State:          Zustand (global state) + React Query (server state)
  Visual Editors:
    Flow/Graph:   @xyflow/react 12 (workflows, navigation, ERD, agent builder, org chart)
    UI Canvas:    Agentic React Builder (bridge.js + AST — TSX source-of-truth, not GrapesJS)
    Code Editor:  Monaco Editor (@monaco-editor/react)
    Icons:        Lucide React
    Layout:       dagre (graph auto-layout for ERD, workflows)
  Drag & Drop:    HTML5 native drag events (section reordering in visual editor)
  HTTP:           fetch (typed API client in lib/api.ts with token refresh)
  WebSocket:      native WebSocket API
  Forms:          Zod validation (inline, no React Hook Form dependency)
  Data Fetching:  @tanstack/react-query 5 (server state)
  Animations:     canvas-confetti (achievement celebrations)
```

### 2.2 Generated Apps (what the platform produces)

```
Framework:      Next.js 15 (App Router)
Language:       TypeScript 5.7+
Styling:        Tailwind CSS 4
Database:       PostgreSQL 16 via Docker Compose
ORM:            Drizzle ORM + pg driver
Auth:           NextAuth.js v5 (when auth is needed)
Email:          Resend (when email is needed)
File Upload:    UploadThing or local (when file upload is needed)
Containerized:  docker-compose.yml with Postgres service
```

---

## 3. Project Structure

### 3.1 Platform Monorepo

```
tentoroforge/
├── backend/
│   ├── main.py                      # FastAPI app, middleware stack, 24 routers, startup/shutdown
│   ├── agent.py                     # Core agent runner (run_agent, run_reviewer, run_fixer, run_refinement)
│   ├── config.py                    # Environment config (DB, JWT, rate limits, Sentry, S3, email)
│   ├── database.py                  # Platform DB connection (async SQLAlchemy + asyncpg)
│   ├── auth.py                      # JWT auth (access/refresh tokens, lockout, password strength)
│   ├── cache.py                     # Caching layer (Redis optional)
│   ├── sse_helpers.py               # SSE event formatting utilities
│   ├── figma_parser.py              # Figma URL parsing (file_key, node_id extraction)
│   ├── figma_tools.py               # Figma API client (styles, image export)
│   ├── screenshot.py                # App screenshot capture for visual review
│   ├── preview.py                   # Next.js dev server lifecycle management
│   │
│   ├── models/                      # SQLAlchemy models (16 model files)
│   │   ├── auth.py                  # PlatformUser (auth_provider, password_hash, external_id)
│   │   ├── project.py               # Project, Conversation, AgentJob, Version + enums
│   │   ├── org.py                   # Organization, OrgMember, Department, Team, OrgPerson, OrgRole, OrgGroup
│   │   ├── template.py              # AppTemplate (gallery, category, plan JSON)
│   │   ├── discovery.py             # DiscoverySession (multi-turn state)
│   │   ├── rules.py                 # ProjectRule, AppAccessPolicy, FieldAccessPolicy
│   │   ├── page.py                  # PageDefinition (HTML/CSS/data bindings)
│   │   ├── workflow_instance.py     # WorkflowInstance, TaskInstance
│   │   ├── notification.py          # Notification events
│   │   ├── webhook.py               # WebhookEndpoint, WebhookEvent
│   │   ├── audit.py                 # AuditLog
│   │   ├── environment.py           # Environment (dev, staging, prod)
│   │   └── node_execution_log.py    # Workflow node execution tracking
│   │
│   ├── routers/                     # FastAPI routers (24 routers)
│   │   ├── generate.py              # App generation pipeline + SSE (1975 lines)
│   │   ├── projects.py              # Project CRUD, files, conversations, versions (327 lines)
│   │   ├── orgs.py                  # Org management, people, teams, depts, RBAC, CSV import (952 lines)
│   │   ├── rules.py                 # Access policies, field-level access, rule definitions (884 lines)
│   │   ├── workflows.py             # Workflow definitions, instances, task assignment (882 lines)
│   │   ├── visual_editor.py         # Visual editing, bridge, direct/AI edits, sections (522 lines)
│   │   ├── portal.py                # Dashboard, cost tracking, exports (521 lines)
│   │   ├── data_model.py            # App-model, schema changes, SQL queries, seeding (442 lines)
│   │   ├── agent_builder.py         # Agent definition CRUD, testing (423 lines)
│   │   ├── decisions.py             # Decision table CRUD, evaluation, testing (386 lines)
│   │   ├── pages.py                 # Page definition CRUD, data bindings (337 lines)
│   │   ├── discovery.py             # Multi-turn discovery sessions (284 lines)
│   │   ├── ai_features.py           # AI config, semantic search, AI components (283 lines)
│   │   ├── navigation.py            # Navigation config, module management (281 lines)
│   │   ├── templates.py             # Template gallery, create-from-template
│   │   ├── auth.py                  # Signup, login, token refresh, logout
│   │   ├── health.py                # Liveness + readiness probes
│   │   ├── notifications.py         # Notification endpoints
│   │   ├── sso.py                   # SSO provider integration
│   │   ├── audit.py                 # Audit logging
│   │   ├── files.py                 # File upload/download
│   │   ├── environments.py          # Environment configuration
│   │   └── webhooks.py              # Webhook management
│   │
│   ├── agents/                      # LLM agent definitions (24 modules)
│   │   ├── __init__.py
│   │   ├── orchestrator.py          # Agent #0: Intent router (Haiku)
│   │   ├── planner.py               # Agent #1: Multi-turn planning (Sonnet)
│   │   ├── refiner.py               # Agent #2: Change request handler, Figma-aware (Sonnet)
│   │   ├── explainer.py             # Agent #3: Q&A about the app (Haiku)
│   │   ├── code_generator.py        # Agent #4: Full-stack generation from text (Sonnet, 307 lines)
│   │   ├── code_editor.py           # Agent #5: Single-file precision edits (Sonnet)
│   │   ├── scaffolder.py            # Agent #6: Add features to existing app, Figma-aware (Sonnet)
│   │   ├── indexer.py               # Agent #7: Generates app-model.json (Haiku)
│   │   ├── validator.py             # Agent #8: Build checking + iterative fixes (Haiku)
│   │   ├── reviewer.py              # Agent #9: Visual QA (Sonnet)
│   │   ├── discovery.py             # Agent #12: Requirement discovery multi-turn (Sonnet)
│   │   ├── design_analyzer.py       # Agent #13: Figma design → structured plan (Sonnet)
│   │   ├── figma_ui_agent.py        # Agent #14: Figma UI-only generation (Sonnet)
│   │   ├── contract_agent.py        # Relay: API contracts from plan
│   │   ├── schema_agent.py          # Relay: DB schema + config + types
│   │   ├── auth_agent.py            # Relay: Authentication scaffolding
│   │   ├── api_agent.py             # Relay: API route handlers
│   │   ├── business_logic_agent.py  # Relay: Workflow/business logic services
│   │   ├── component_agent.py       # Relay: UI components (text pipeline)
│   │   ├── page_agent.py            # Relay: Page files + layouts (text pipeline)
│   │   ├── qa_agent.py              # Relay: Cross-agent QA verification
│   │   ├── completeness_checker.py  # Relay: Completeness validation
│   │   ├── seed_generator.py        # Relay: Seed data generation
│   │   └── fallback.py              # Fallback agent for unclassified intents
│   │
│   ├── services/                    # Business logic (20 service modules)
│   │   ├── preview_manager.py       # Docker + dev server management
│   │   ├── project_service.py       # Project creation, copying, authorization
│   │   ├── git_service.py           # Git initialization, commits, reverts, history
│   │   ├── generation_buffer.py     # SSE event buffering for reconnect recovery
│   │   ├── figma_context.py         # Figma design token extraction + persistence
│   │   ├── parallel_runner.py       # Concurrent agent execution for relay pipeline
│   │   ├── suggestion_service.py    # Template suggestion engine
│   │   ├── bridge_injector.py       # Visual editing bridge.js injection
│   │   ├── source_annotator.py      # AST-based source code annotation
│   │   ├── component_extractor.py   # React component extraction from code
│   │   ├── element_props_extractor.py # DOM element property extraction
│   │   ├── page_section_parser.py   # Route → page file → AST section tree
│   │   ├── section_templates.py     # 15 section templates across 12 categories
│   │   ├── section_instruction_builder.py # Prompt builder for code_editor agent
│   │   ├── section_reorder_service.py # AST-first + line-based section reorder
│   │   ├── webhook_service.py       # Webhook delivery and retry
│   │   ├── notification_service.py  # Notification dispatch
│   │   ├── email_service.py         # SendGrid/SMTP email
│   │   ├── audit_service.py         # Audit log recording
│   │   └── storage_service.py       # S3/local file storage
│   │
│   ├── runtime/                     # Workflow execution engine
│   │   ├── engine.py                # WorkflowRuntimeEngine (465 lines)
│   │   ├── state_manager.py         # Workflow instance lifecycle + state persistence
│   │   ├── gateway_controller.py    # Decision logic, branching (323 lines)
│   │   ├── task_executor.py         # Task execution, action invocation
│   │   ├── assignment.py            # Task assignment (role/group/person/manager)
│   │   ├── execution_logger.py      # Execution history tracking
│   │   ├── variable_resolver.py     # Process variable substitution
│   │   ├── decision_evaluator.py    # Decision table evaluation (462 lines)
│   │   ├── timer_scheduler.py       # Timer/deadline management
│   │   ├── timer_queue.py           # Timer event queuing
│   │   ├── feel_lite/               # FEEL-Lite expression language
│   │   │   ├── tokenizer.py         # Tokenization (281 lines)
│   │   │   ├── parser.py            # Expression parsing (335 lines)
│   │   │   └── evaluator.py         # AST walker evaluation (609 lines)
│   │   ├── ai/                      # AI workflow actions
│   │   │   ├── base.py, generate.py, extract.py, classify.py, decide.py
│   │   └── actions/                 # Built-in workflow actions
│   │       ├── base.py, db_query.py, http_call.py, send_email.py
│   │       ├── send_notification.py, custom.py
│   │
│   ├── middleware/                   # Custom middleware stack (5 modules)
│   │   ├── error_handler.py         # Global exception handling
│   │   ├── security_headers.py      # CSP, X-Frame-Options, etc.
│   │   ├── logging.py               # Structured JSON logging with request_id
│   │   ├── rate_limit.py            # Token bucket rate limiting by IP
│   │   └── metrics.py               # Prometheus metrics + /metrics endpoint
│   │
│   ├── schemas/                     # Pydantic v2 schemas (17 schema files)
│   │   ├── project.py               # ProjectCreate/Update/Response, ChatRequest, GenerateRequest
│   │   ├── auth.py                  # Signup/Login/TokenResponse, RefreshRequest
│   │   ├── org.py                   # OrgCreate, PersonCreate, RoleCreate, ImportResult
│   │   ├── workflow.py              # WorkflowSave, TaskCompleteRequest, InstanceResponse
│   │   ├── data_model.py            # SchemaChangeRequest, SqlQueryRequest, SeedRequest
│   │   ├── rules.py                 # AccessPolicyCreate, FieldAccessMatrixResponse, RuleCreate
│   │   ├── decision.py              # DecisionTableCreate, EvaluateRequest, TestRequest
│   │   ├── page.py                  # PageCreate/Update/Response
│   │   ├── visual_edit.py           # VisualEditRequest, AIEditRequest, AddSectionRequest
│   │   ├── ai_features.py           # AIConfigSave, SemanticSearchConfig, AIComponentConfig
│   │   ├── template.py              # TemplateResponse, CreateFromTemplateRequest
│   │   ├── discovery.py             # DiscoveryStartRequest, DiscoverySessionResponse
│   │   ├── navigation.py            # NavigationSave with screens/edges/links
│   │   ├── agent_builder.py         # AgentDefinitionSave, AgentTestRequest
│   │   ├── portal.py                # PortalDashboard, ProjectCostSummary, ExportRequest
│   │   ├── audit.py                 # AuditLogResponse
│   │   └── notification.py          # NotificationResponse
│   │
│   ├── static/                      # Static assets for visual editor
│   │   ├── bridge.js                # In-iframe bridge: overlays, events, DOM tree
│   │   ├── annotate-source.mjs      # Babel: add/strip data-source-* attributes
│   │   ├── parse-sections.mjs       # Babel: extract top-level JSX sections
│   │   └── reorder-section.mjs      # Babel: AST-level section reorder
│   │
│   ├── jobs/                        # Background job processing
│   │   ├── worker.py                # Job worker
│   │   └── generation_job.py        # Async generation job
│   │
│   ├── tests/                       # Test suite
│   │   ├── conftest.py              # Test fixtures
│   │   ├── test_api_integration.py  # API integration tests
│   │   ├── test_figma_parser.py     # Figma parser tests
│   │   ├── test_auth.py             # Auth tests
│   │   └── test_workflows.py        # Workflow tests
│   │
│   ├── seeds/                       # Seed data
│   │   └── templates.py             # Initial template library
│   │
│   ├── alembic/                     # Platform DB migrations (8+ versions)
│   │   ├── versions/
│   │   └── env.py
│   │
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
│
├── frontend/
│   ├── src/
│   │   ├── app/                     # Next.js 15 App Router pages
│   │   │   ├── layout.tsx           # Root layout with providers
│   │   │   ├── page.tsx             # Landing / org selector
│   │   │   ├── (auth)/              # Auth group layout
│   │   │   │   ├── layout.tsx       # Auth layout
│   │   │   │   ├── login/page.tsx   # Login page
│   │   │   │   └── signup/page.tsx  # Signup page
│   │   │   ├── org/[orgId]/         # Org-scoped pages
│   │   │   │   ├── people/page.tsx  # People directory
│   │   │   │   ├── departments/page.tsx
│   │   │   │   ├── teams/page.tsx
│   │   │   │   ├── roles/page.tsx
│   │   │   │   ├── groups/page.tsx
│   │   │   │   ├── import/page.tsx  # CSV/JSON import
│   │   │   │   ├── org-chart/page.tsx
│   │   │   │   ├── settings/page.tsx
│   │   │   │   ├── templates/page.tsx
│   │   │   │   └── projects/[projectId]/  # Project workspace
│   │   │   │       └── layout.tsx   # 12-tab workspace shell
│   │   │   └── globals.css
│   │   │
│   │   ├── components/
│   │   │   ├── auth-guard.tsx       # Auth route protection
│   │   │   ├── providers.tsx        # React Query + providers wrapper
│   │   │   ├── ui/                  # shadcn/ui component library (20+ components)
│   │   │   │   ├── button.tsx, input.tsx, label.tsx, card.tsx
│   │   │   │   ├── dialog.tsx, dropdown-menu.tsx, table.tsx, tabs.tsx
│   │   │   │   ├── avatar.tsx, badge.tsx, separator.tsx, sheet.tsx
│   │   │   │   ├── select.tsx, sonner.tsx
│   │   │   │   └── ...
│   │   │   │
│   │   │   ├── chat/                # Chat panel components
│   │   │   │   ├── ChatInput.tsx    # Message input with send
│   │   │   │   ├── ChatPanel.tsx    # Main chat container with streaming
│   │   │   │   ├── ChatHistory.tsx  # Message list with quest tracker
│   │   │   │   ├── ChatMessage.tsx  # Individual message rendering
│   │   │   │   ├── PlanCard.tsx     # Structured plan display + approve/reject
│   │   │   │   ├── QuestTracker.tsx # XP/phase progress visualization
│   │   │   │   ├── AchievementBanner.tsx # Completion celebration with stats
│   │   │   │   └── ActionButtons.tsx # Quick action toolbar
│   │   │   │
│   │   │   ├── preview/             # Live preview components
│   │   │   │   └── PreviewFrame.tsx # Device frame + iframe + refine bar
│   │   │   │
│   │   │   ├── code/                # Code editor components
│   │   │   │   ├── CodeEditor.tsx   # Monaco editor wrapper
│   │   │   │   └── CodePanel.tsx    # Multi-tab code viewer
│   │   │   │
│   │   │   ├── visual-editor/       # Agentic React Builder (bridge.js + AST)
│   │   │   │   ├── VisualEditor.tsx          # 3-panel layout, panel toggle
│   │   │   │   ├── CanvasFrame.tsx           # iframe with scrollTo/highlight
│   │   │   │   ├── SectionOutlinePanel.tsx   # Left: tree view, drag reorder, + Add
│   │   │   │   ├── ContextPanel.tsx          # Right: element info, class chips, actions
│   │   │   │   ├── ComponentPalette.tsx      # Sheet: section template browser
│   │   │   │   ├── AIEditInput.tsx           # AI input with suggestion chips
│   │   │   │   ├── ElementActionPopover.tsx  # Floating popover on selected element
│   │   │   │   └── QuickStylePopover.tsx     # Quick Tailwind style editor
│   │   │   │
│   │   │   ├── data-model/          # Data model editor
│   │   │   │   ├── DataModelPanel.tsx   # Main database schema UI
│   │   │   │   ├── DataModelSidebar.tsx # Model list sidebar
│   │   │   │   ├── ERDCanvas.tsx        # Entity-relationship diagram (React Flow)
│   │   │   │   ├── EntityCardNode.tsx   # Visual entity node
│   │   │   │   ├── AddModelDialog.tsx   # New entity creation
│   │   │   │   ├── DeleteConfirmDialog.tsx
│   │   │   │   ├── RelationshipEditor.tsx
│   │   │   │   ├── EnumEditor.tsx
│   │   │   │   ├── IndexEditor.tsx
│   │   │   │   ├── SeedDataEditor.tsx   # Test data generation
│   │   │   │   ├── DatabaseBrowser.tsx  # Schema exploration
│   │   │   │   ├── SqlConsole.tsx       # Direct SQL execution
│   │   │   │   ├── ImpactAnalysis.tsx   # Shows affected bindings
│   │   │   │   └── SchemaChangeProgress.tsx
│   │   │   │
│   │   │   ├── workflow/            # Workflow editor (19 node types)
│   │   │   │   ├── WorkflowPanel.tsx    # Workflow orchestration panel
│   │   │   │   ├── WorkflowCanvas.tsx   # React Flow canvas
│   │   │   │   ├── NodePropertiesPanel.tsx
│   │   │   │   ├── VariablePicker.tsx   # {{variable}} autocomplete
│   │   │   │   ├── WorkflowTester.tsx   # Test run with sample data
│   │   │   │   └── ExecutionLogViewer.tsx
│   │   │   │
│   │   │   ├── rules/               # Rules editor (10+ rule types)
│   │   │   │   ├── ConditionRow.tsx
│   │   │   │   ├── ConditionBuilder.tsx      # No-code + expression mode
│   │   │   │   ├── ValidationRuleForm.tsx
│   │   │   │   ├── ValidationRuleForm.tsx
│   │   │   │   ├── AccessRuleForm.tsx
│   │   │   │   ├── BusinessRuleForm.tsx
│   │   │   │   ├── ComputedRuleForm.tsx
│   │   │   │   ├── StateMachineEditor.tsx # Visual state diagram
│   │   │   │   ├── TriggerRuleForm.tsx
│   │   │   │   └── ConditionBuilder.tsx  # Visual condition builder
│   │   │   │
│   │   │   ├── navigation-editor/   # Navigation editor
│   │   │   │   ├── NavCanvas.tsx         # Screen flow diagram
│   │   │   │   ├── ScreenNode.tsx        # Page/screen node
│   │   │   │   ├── NavProperties.tsx     # Navigation config
│   │   │   │   └── MenuEditor.tsx        # Sidebar/navbar config
│   │   │   │
│   │   │   ├── database/             # Data browser
│   │   │   │   ├── DataBrowser.tsx       # Table data grid
│   │   │   │   ├── SQLConsole.tsx        # Raw SQL editor
│   │   │   │   ├── TableSelector.tsx     # Pick table to browse
│   │   │   │   └── CellEditor.tsx       # Inline cell editing
│   │   │   │
│   │   │   ├── modules/              # Module management
│   │   │   │   ├── ModuleList.tsx        # Module cards/list
│   │   │   │   ├── ModuleCard.tsx        # Individual module
│   │   │   │   ├── ConnectionsMap.tsx    # Cross-module dep graph
│   │   │   │   └── ModuleWizard.tsx      # New module creation
│   │   │   │
│   │   │   ├── progress/             # Progress/streaming
│   │   │   │   ├── ProgressStream.tsx    # SSE event display
│   │   │   │   ├── AgentSpinner.tsx      # Loading states
│   │   │   │   └── EventItem.tsx         # Individual event render
│   │   │   │
│   │   │   └── shared/               # Reusable components
│   │   │       ├── Button.tsx
│   │   │       ├── Input.tsx
│   │   │       ├── Select.tsx
│   │   │       ├── Modal.tsx
│   │   │       ├── Toast.tsx
│   │   │       ├── Tabs.tsx
│   │   │       ├── Badge.tsx
│   │   │       ├── Table.tsx
│   │   │       ├── ConfirmDialog.tsx
│   │   │       └── EmptyState.tsx
│   │   │
│   │   ├── stores/                   # Zustand 5 stores (11 stores, ~130KB)
│   │   │   ├── auth.ts               # Token, user, login/signup/logout, refresh
│   │   │   ├── chat.ts               # Messages, streaming, quest progress, plan state
│   │   │   ├── visual-editor.ts      # Selected element, device preview, section tree
│   │   │   ├── navigation.ts         # Screens, edges, sidebar/topbar links, modules
│   │   │   ├── decision.ts           # Decision tables, test cases, analysis
│   │   │   ├── workflow.ts           # Workflow list, current workflow, execution logs
│   │   │   ├── rules.ts              # Rules list, filtering, CRUD
│   │   │   ├── agent-builder.ts      # Agents, node selection, test console, templates
│   │   │   ├── data-model.ts         # AppModel, selected table
│   │   │   ├── portal.ts             # Apps, tasks, activity, command palette, onboarding
│   │   │   └── ai-features.ts        # Smart field configuration
│   │   │
│   │   ├── hooks/                    # Custom React hooks (8 hooks)
│   │   │   ├── useSSE.ts             # SSE streaming with reconnect, dedup, session tracking
│   │   │   ├── useVisualEdit.ts      # Direct/AI edits, undo, reorder, progress streaming
│   │   │   ├── useAddSection.ts      # AI-driven section generation with templates
│   │   │   ├── useBridge.ts          # Cross-iframe bridge messaging protocol
│   │   │   ├── useSchemaChange.ts    # DB schema mutations with impact analysis
│   │   │   ├── useOrgEntities.ts     # Query people, teams, departments
│   │   │   ├── usePreview.ts         # Start/stop preview server
│   │   │   └── useKeyboardShortcuts.ts # Command palette, tab switching
│   │   │
│   │   ├── lib/                      # Utilities (15+ modules)
│   │   │   ├── api.ts                # Typed API client with token refresh + error handling
│   │   │   ├── utils.ts              # General utilities (cn, etc.)
│   │   │   ├── quest-phases.ts       # Quest progression (9 phases + Figma phase)
│   │   │   ├── instruction-builder.ts      # Base instruction builder
│   │   │   ├── ui-instruction-builder.ts   # UI generation instructions
│   │   │   ├── rule-instruction-builder.ts # Rule → NL instruction
│   │   │   ├── workflow-instruction-builder.ts
│   │   │   ├── rbac-instruction-builder.ts
│   │   │   ├── agent-instruction-builder.ts
│   │   │   ├── section-tree-utils.ts # DOM tree manipulation
│   │   │   ├── ai-suggestion-utils.ts # AI suggestion generation
│   │   │   ├── erd-layout.ts         # dagre-based ERD auto-layout
│   │   │   ├── feel-lite/            # FEEL-Lite expression language (frontend)
│   │   │   │   ├── tokenizer.ts, parser.ts, evaluator.ts, validator.ts
│   │   │   └── decision/            # Decision engine (frontend)
│   │   │       ├── table-evaluator.ts, graph-evaluator.ts
│   │   │       ├── analysis.ts, templates.ts
│   │   │
│   │   └── types/                    # TypeScript types (11 type files)
│   │       ├── project.ts            # Project, ChatMessage, AgentJob, Version, SSEEvent
│   │       ├── app-model.ts          # DB schema, API routes, smart fields
│   │       ├── visual-editor.ts      # ElementInfo, DeviceSize, SectionNode
│   │       ├── navigation.ts         # Screen nodes, edges, NavLink, AppModule
│   │       ├── decision.ts           # Decision tables, hit policies, test cases
│   │       ├── workflow.ts           # 19 node types, execution logs, assignments
│   │       ├── rules.ts              # 10 rule types, condition builder, RBAC matrix
│   │       ├── agent-builder.ts      # 6 agent node types, tools, guardrails
│   │       ├── ai-features.ts        # Smart field configuration
│   │       ├── portal.ts             # Portal apps, tasks, activity, onboarding
│   │       └── ui-editor.ts          # UI generation config
│   │
│   ├── package.json
│   ├── next.config.ts
│   ├── tsconfig.json
│   ├── postcss.config.mjs
│   └── Dockerfile
│
├── output/                           # Generated projects live here
│   ├── {project_id}/
│   │   ├── src/
│   │   ├── docker-compose.yml
│   │   ├── app-model.json            # AppModel index for this project
│   │   └── ...
│   └── ...
│
├── docker-compose.yml                # Platform services (platform DB, Redis)
├── Makefile                          # Dev commands
└── README.md
```

---

## 4. Platform Database Schema

The platform itself needs a database to track organizations, users, projects, conversations, and state.

### 4.1 Tables

```sql
-- ═══════════════════════════════════
-- ORGANIZATION & IDENTITY TABLES
-- ═══════════════════════════════════

-- Organizations (tenants)
CREATE TABLE organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    slug            VARCHAR(100) NOT NULL UNIQUE,         -- acme-corp → used in URLs
    logo_url        TEXT,
    plan            VARCHAR(50) NOT NULL DEFAULT 'free',  -- free, pro, enterprise
    settings        JSONB DEFAULT '{}',                   -- org-wide settings
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Platform users (who's using the builder)
CREATE TABLE platform_users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    name            VARCHAR(255) NOT NULL,
    password_hash   VARCHAR(255),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Org membership (many-to-many: users belong to orgs)
CREATE TABLE org_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES platform_users(id) ON DELETE CASCADE,
    platform_role   VARCHAR(50) NOT NULL DEFAULT 'member',-- owner, admin, builder, member
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(org_id, user_id)
);

-- Departments
CREATE TABLE departments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    parent_id       UUID REFERENCES departments(id) ON DELETE SET NULL,  -- hierarchy
    head_user_id    UUID REFERENCES org_people(id),      -- department head
    display_order   INTEGER NOT NULL DEFAULT 0,
    metadata        JSONB DEFAULT '{}',                   -- cost center, location, etc.
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(org_id, name)
);

-- Teams (sub-groups within departments)
CREATE TABLE teams (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    department_id   UUID REFERENCES departments(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    lead_user_id    UUID REFERENCES org_people(id),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(org_id, name)
);

-- Org people (end-users of the generated apps — NOT platform_users)
CREATE TABLE org_people (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email           VARCHAR(255) NOT NULL,
    name            VARCHAR(255) NOT NULL,
    title           VARCHAR(255),                         -- job title
    department_id   UUID REFERENCES departments(id) ON DELETE SET NULL,
    team_id         UUID REFERENCES teams(id) ON DELETE SET NULL,
    manager_id      UUID REFERENCES org_people(id) ON DELETE SET NULL,  -- reporting line
    status          VARCHAR(50) NOT NULL DEFAULT 'active',-- active, inactive, invited
    avatar_url      TEXT,
    metadata        JSONB DEFAULT '{}',                   -- phone, location, hire_date, etc.
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(org_id, email)
);

-- Org roles (custom roles defined per org)
CREATE TABLE org_roles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(100) NOT NULL,                -- admin, manager, staff, viewer
    description     TEXT,
    level           INTEGER NOT NULL DEFAULT 0,           -- 0=lowest, higher=more authority
    is_system       BOOLEAN NOT NULL DEFAULT FALSE,       -- system roles can't be deleted
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(org_id, name)
);

-- Person-role assignments
CREATE TABLE org_person_roles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    person_id       UUID NOT NULL REFERENCES org_people(id) ON DELETE CASCADE,
    role_id         UUID NOT NULL REFERENCES org_roles(id) ON DELETE CASCADE,
    UNIQUE(person_id, role_id)
);

-- Groups (cross-cutting: audit committee, safety team, etc.)
CREATE TABLE org_groups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(org_id, name)
);

-- Group membership
CREATE TABLE org_group_members (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id        UUID NOT NULL REFERENCES org_groups(id) ON DELETE CASCADE,
    person_id       UUID NOT NULL REFERENCES org_people(id) ON DELETE CASCADE,
    UNIQUE(group_id, person_id)
);

-- ═══════════════════════════════════
-- RBAC POLICY TABLES
-- ═══════════════════════════════════

-- App access policies (which roles/groups/people can access which apps)
CREATE TABLE app_access_policies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    target_type     VARCHAR(20) NOT NULL,                 -- role, group, department, person
    target_id       UUID NOT NULL,                        -- references role/group/dept/person
    access_level    VARCHAR(50) NOT NULL DEFAULT 'user',  -- user, admin, none
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, target_type, target_id)
);

-- Field-level access policies
CREATE TABLE field_access_policies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    model_name      VARCHAR(255) NOT NULL,                -- "Product", "SupportTicket"
    field_name      VARCHAR(255) NOT NULL,                -- "unitCost", "salary"
    target_type     VARCHAR(20) NOT NULL,                 -- role, group, department, person
    target_id       UUID NOT NULL,
    can_view        BOOLEAN NOT NULL DEFAULT TRUE,
    can_edit        BOOLEAN NOT NULL DEFAULT TRUE,
    condition       TEXT,                                  -- optional condition expression
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_field_access ON field_access_policies(project_id, model_name, field_name);

-- Workflow assignment policies (who handles which workflow tasks)
CREATE TABLE workflow_assignment_policies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    workflow_id     VARCHAR(255) NOT NULL,                -- "expense-approval"
    node_id         VARCHAR(255) NOT NULL,                -- specific step in the workflow
    assign_type     VARCHAR(50) NOT NULL,                 -- role, group, department, person,
                                                          -- manager_of_requester, department_head
    assign_target   UUID,                                 -- NULL for dynamic types like manager_of
    sla_hours       INTEGER,                              -- auto-escalate after N hours
    escalate_to     VARCHAR(50),                          -- role name to escalate to
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ═══════════════════════════════════
-- PROJECT & APP TABLES (updated)
-- ═══════════════════════════════════

-- Projects (now belong to an org)
CREATE TABLE projects (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    short_id        VARCHAR(8) NOT NULL UNIQUE,          -- human-readable ID
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    owner_id        UUID NOT NULL REFERENCES platform_users(id),
    status          VARCHAR(50) NOT NULL DEFAULT 'active', -- active, archived, deleted
    output_dir      TEXT NOT NULL,                        -- filesystem path
    preview_port    INTEGER,                              -- current preview port (null if stopped)
    db_port         INTEGER,                              -- Postgres port for this project
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Modules within a project
CREATE TABLE modules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    status          VARCHAR(50) NOT NULL DEFAULT 'active', -- active, generating, error
    display_order   INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, name)
);

-- Module dependencies
CREATE TABLE module_dependencies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    module_id       UUID NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    depends_on_id   UUID NOT NULL REFERENCES modules(id) ON DELETE CASCADE,
    UNIQUE(module_id, depends_on_id)
);

-- Conversation messages
CREATE TABLE conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    role            VARCHAR(20) NOT NULL,                 -- user, assistant, system
    content         TEXT NOT NULL,
    message_type    VARCHAR(50) NOT NULL DEFAULT 'chat',  -- chat, plan, approval, refinement, error
    metadata        JSONB DEFAULT '{}',                   -- agent name, tool calls, costs, etc.
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_conversations_project ON conversations(project_id, created_at);

-- Generation/refinement jobs (tracks async agent runs)
CREATE TABLE agent_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_type      VARCHAR(50) NOT NULL,                 -- planner, code_generator, refiner, etc.
    status          VARCHAR(50) NOT NULL DEFAULT 'running', -- running, completed, failed, cancelled
    instruction     TEXT,
    result          JSONB,                                -- {num_turns, cost_usd, duration_ms, files_changed}
    started_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMP,
    error_message   TEXT
);

-- Version history (git commits in the project)
CREATE TABLE versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    commit_hash     VARCHAR(40) NOT NULL,
    message         TEXT NOT NULL,
    agent_job_id    UUID REFERENCES agent_jobs(id),       -- which agent run created this version
    files_changed   JSONB DEFAULT '[]',                   -- list of changed file paths
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ═══════════════════════════════════
-- TEMPLATE & DISCOVERY TABLES
-- ═══════════════════════════════════

-- App templates (pre-built plans for common app types)
CREATE TABLE app_templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            VARCHAR(100) NOT NULL UNIQUE,          -- "crm-basic", "hr-onboarding"
    name            VARCHAR(255) NOT NULL,
    description     TEXT NOT NULL,
    category        VARCHAR(100) NOT NULL,                 -- Operations, Sales, HR, Finance, Support
    subcategory     VARCHAR(100),                          -- optional finer grouping
    icon            VARCHAR(50),                           -- lucide icon name
    tags            JSONB DEFAULT '[]',                    -- ["crm", "sales", "pipeline"]
    plan            JSONB NOT NULL,                        -- full Planner-format plan (entities, pages, workflows, etc.)
    preview_image   TEXT,                                  -- URL or path to screenshot
    complexity      VARCHAR(20) NOT NULL DEFAULT 'medium', -- simple, medium, complex
    estimated_modules INTEGER NOT NULL DEFAULT 1,
    org_departments JSONB DEFAULT '[]',                    -- departments this template is relevant to
    is_published    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_templates_category ON app_templates(category);

-- Discovery sessions (tracks multi-turn discovery conversations)
CREATE TABLE discovery_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES platform_users(id),
    status          VARCHAR(50) NOT NULL DEFAULT 'active', -- active, brief_ready, converted, abandoned
    initial_input   TEXT NOT NULL,                          -- user's first message
    discovery_type  VARCHAR(50) NOT NULL,                   -- problem_first, reference_based, department_need, vague_idea
    brief           JSONB,                                  -- structured brief when ready
    converted_to    UUID REFERENCES projects(id),           -- project created from this session
    messages        JSONB DEFAULT '[]',                     -- conversation history
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_discovery_org ON discovery_sessions(org_id, status);
```

### 4.2 SQLAlchemy Models

```python
# backend/models/project.py

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from database import Base


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    short_id = Column(String(8), unique=True, nullable=False)
    org_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("platform_users.id"), nullable=False)
    status = Column(String(50), nullable=False, default="active")
    output_dir = Column(Text, nullable=False)
    preview_port = Column(Integer)
    db_port = Column(Integer)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    organization = relationship("Organization", back_populates="projects")
    modules = relationship("Module", back_populates="project", cascade="all, delete-orphan")
    conversations = relationship("Conversation", back_populates="project", cascade="all, delete-orphan")
    versions = relationship("Version", back_populates="project", cascade="all, delete-orphan")
```

---

## 5. Agent System

### 5.1 Agent Overview

The pipeline has **two coexisting frontend backends**, both fed by the same shared back-end relay (contracts → schema → auth/api/biz):

- **Schema mode** (default, `SCHEMA_MODE_ENABLED=true` — Phase 4 flipped this on) — the frontend is emitted as **JSON Page schemas** under `output/<short_id>/src/schemas/<entity>/<page_type>.json`, rendered at preview time by `@tentoroforge/renderer` + `@tentoroforge/library`. The `feature_slice_schema_agent` replaces the legacy `component_agent` + `page_agent` for the frontend half. See Section 5.14 for the schema-mode flow and Section 9A for the renderer contract.
- **Legacy TSX mode** (`SCHEMA_MODE_ENABLED=false`, plus per-entity opt-out via `legacy_tsx_mode: true`) — the original text pipeline that emits TSX page files. `component_agent` → `page_agent` → QA → validator → indexer. This path is still on disk and used as a fallback.
- **IR mode** (legacy, `IR_FRONTEND_ENABLED=true`) — pre-schema-mode experiment that compiled an Intermediate Representation to TSX via `services.ir_pipeline`. Retained for back-compat; not the default.
- **AHTML mode** (legacy GrapesJS editor path) — generates `.design.html` files via the AHTML compiler. Retained for the GrapesJS-based design editor only; not part of the chat-driven generation pipeline.

```
Agent ID                              Model       Used in mode        Purpose
──────────────────────────────────────────────────────────────────────────────────────────
Routing / conversation
  orchestrator                        Haiku 4.5   all                 Intent classification on chat input
  planner                             Sonnet 4    all                 Multi-turn brief → structured plan
  planner.run_planner_oneshot         Sonnet 4    all                 Headless plan path (~12s vs ~4m)
  refiner                             Sonnet 4    all                 Change requests, Figma-aware
  explainer                           Haiku 4.5   all                 Q&A about the app
  discovery                           Sonnet 4    all                 Vague-idea → brief
  fallback                            —           all                 Catch-all for unclassified intent

Design + register
  design_agent                        Sonnet 4    schema + tsx        Researches register, palette, typography, density, UX patterns, navigation → src/contracts/design-spec.json
  design_analyzer                     Sonnet 4    figma               Figma file → structured plan
  register_selector.classify_register —           all                 Rule-based register pick (default | workday | linear | stripe | notion | figma)
  register_selector.classify_register_llm  Sonnet 4 all               LLM register pick (falls back to rules on any failure)

Shared backend relay
  contract_agent                      Sonnet 4    all                 Reads plan → src/contracts/{api-contracts,db-schema-plan,types}.json; seeds registry.entities
  schema_agent                        Sonnet 4    all                 Drizzle schema, config, types, npm install
  auth_agent                          Sonnet 4    all                 NextAuth.js scaffolding + middleware
  api_agent                           Sonnet 4    all                 Next.js API route handlers (registry-aware)
  business_logic_agent                Sonnet 4    all                 Validations, computed fields, workflow scaffolds
  rules_agent                         Sonnet 4    all (optional)      Generates rule definitions from planner intent
  seed_generator                      Sonnet 4    all                 seed-plan.json + seed.ts; domain-aware faker

Schema-mode frontend
  feature_slice_schema_agent          Sonnet 4    schema (default)    Per-entity: emits list/detail/form (or custom) JSON schemas under src/schemas/<entity_slug>/

Legacy TSX-mode frontend
  component_agent                     Sonnet 4    tsx                 Reusable React components
  page_agent                          Sonnet 4    tsx                 Page files + layouts (registry-aware)
  page_layout_agent                   Sonnet 4    tsx                 Page skeletons with PlaceholderSlot markers
  qa_agent                            Sonnet 4    tsx                 Registry-aware cross-agent QA on emitted TSX
  completeness_checker                —           tsx                 Deterministic completeness check
  validator                           Sonnet 4    tsx                 Build check + runtime scan (2-phase, max 3 cycles)
  indexer                             Haiku 4.5   tsx                 Rebuilds app-model.json after every change
  fix_agent / patch_agent             Sonnet 4    tsx                 Targeted post-fix work
  code_editor                         Sonnet 4    all                 Single-file edits driven by the visual editor

IR (legacy)
  ir_router / ir_edit_agent / ir_qa_agent  Sonnet 4   ir              Plan → IR → TSX path
  figma_ir_agent                      Sonnet 4    figma               Figma MCP → IR page skeletons
  figma_ui_agent                      Sonnet 4    figma               UI-only TSX emit when foundation already exists

AHTML (legacy GrapesJS editor)
  ahtml_conversion_agent              Sonnet 4    ahtml editor only   Annotated HTML → TSX
  scaffolder                          Sonnet 4    legacy              Adds features to existing app, Figma-aware
```

All `run_*_agent()` functions share the contract `run_*_agent(output_dir, plan, domain_context=None, ...)` and return `AsyncIterator[Message]` so the relay pipeline in `routers/generate.py` can stream their output through `_stream_phase()` as SSE events. Every agent prompt is augmented with `## YOUR DOMAIN EXPERTISE` from `services/domain_context.py` (17 domains, persona per role).

### 5.2 Agent #0: Orchestrator

```python
# backend/agents/orchestrator.py

ORCHESTRATOR_SYSTEM_PROMPT = """You are a routing agent for an application builder platform.
Your job is to classify the user's intent and route to the correct specialist agent.

You have access to the current project's AppModel index which tells you what exists.

## Classification Rules

Respond with EXACTLY ONE of these categories:

PLAN — User wants to create a new app or add a major new module/feature
  Examples: "Build me a task app", "Add an inventory module",
  "I need user authentication", "Create a reporting dashboard"

REFINE — User wants to change something that already exists
  Examples: "Make the button red", "Add a search bar to the task list",
  "Change the card layout to a table", "Add validation to the email field"

EXPLAIN — User is asking a question, not requesting a change
  Examples: "How does the auth work?", "What tables exist?",
  "Why is the sidebar component structured this way?", "Show me the task flow"

SCAFFOLD — User wants to add a specific new feature to an existing module
  Examples: "Add a notifications system", "Add CSV export to the task list",
  "Add a dark mode toggle", "Add pagination to the API"
  (Distinguish from PLAN: scaffold is a focused feature, plan is a whole module)

AGENT — User wants to create, modify, or manage an AI agent within the app
  Examples: "Add a customer support chatbot", "Create an AI assistant that can query orders",
  "Add a tool to the support agent", "Change the agent's personality",
  "Add a second agent for inventory questions"

DISCOVER — User has a vague idea, problem, or reference but no clear requirements
  Examples: "I need something for my HR team", "We have a problem with tracking expenses",
  "Build something like Trello", "I'm not sure what I need but our onboarding is broken",
  "What apps would help my sales department?"

NAVIGATE — User wants to switch views or see something specific
  Examples: "Show me the data model", "Open the workflow editor",
  "Go to the preview", "Open the agent builder"

UNDO — User wants to revert a change
  Examples: "Undo that", "Revert the last change", "Go back to before"

AMBIGUOUS — You can't determine intent. Ask a clarifying question.

## Response Format

{
  "intent": "PLAN|REFINE|EXPLAIN|SCAFFOLD|AGENT|DISCOVER|NAVIGATE|UNDO|AMBIGUOUS",
  "reasoning": "brief explanation",
  "clarification": "question to ask if AMBIGUOUS, null otherwise",
  "context_needed": ["list of AppModel sections the downstream agent will need"]
}
"""

ORCHESTRATOR_OPTIONS = ClaudeAgentOptions(
    system_prompt=ORCHESTRATOR_SYSTEM_PROMPT,
    allowed_tools=["Read"],  # Can read app-model.json
    permission_mode="bypassPermissions",
    max_turns=2,
    model="claude-haiku-4-5-20251001",
)
```

### 5.3 Agent #1: Planner

```python
# backend/agents/planner.py

PLANNER_SYSTEM_PROMPT = """You are an application architect planning the structure of a new
application or module. You have a multi-turn conversation with the user to clarify requirements,
then produce a detailed structured plan.

IMPORTANT: You have access to the organization's structure (departments, teams, roles, people,
reporting lines). Use this to automatically infer access control, workflow assignments, and
role-based permissions. Do NOT ask the user "what roles do you need?" — infer them from the org.

## Your Process

1. UNDERSTAND: Read the user's request. If building onto an existing app, read the AppModel
   index to understand what already exists.

2. CLARIFY: Ask 2-4 focused questions about:
   - Core entities and their relationships
   - Key user workflows (what does the user DO in this app?)
   - Authentication/authorization needs
   - Any integrations (email, payments, file upload, external APIs)
   - Mobile vs web vs both
   - AI/intelligence requirements (auto-categorization, search, content generation)
   Do NOT ask more than 4 questions. Make reasonable assumptions for anything else.

   IMPORTANT: If the user's description implies AI capabilities (e.g., "auto-categorize",
   "smart search", "generate descriptions", "detect sentiment", "find similar"),
   automatically include the appropriate smart fields, semantic search, or AI workflow
   nodes in the plan. You don't need to ask — just include them.

3. PLAN: Once requirements are clear, produce a structured plan:

## Plan Output Format (JSON)

{
  "module_name": "Inventory Management",
  "description": "Track products, warehouses, stock levels, and purchase orders",

  "data_models": [
    {
      "name": "Product",
      "fields": [
        {"name": "id", "type": "uuid", "constraints": ["pk", "auto"]},
        {"name": "sku", "type": "varchar(100)", "constraints": ["unique", "not_null"]},
        {"name": "name", "type": "varchar(255)", "constraints": ["not_null"]},
        {"name": "description", "type": "text", "constraints": []},
        {"name": "category", "type": "varchar(100)", "constraints": []},
        {"name": "unitCost", "type": "decimal(10,2)", "constraints": ["not_null"]},
        {"name": "unitPrice", "type": "decimal(10,2)", "constraints": ["not_null"]},
        {"name": "reorderPoint", "type": "integer", "constraints": ["default:10"]},
        {"name": "isActive", "type": "boolean", "constraints": ["default:true"]},
        {"name": "createdAt", "type": "timestamp", "constraints": ["not_null", "auto"]},
        {"name": "updatedAt", "type": "timestamp", "constraints": ["not_null", "auto"]}
      ],
      "indexes": ["idx_product_sku (sku)", "idx_product_category (category)"]
    }
    // ... more models
  ],

  "relations": [
    {"from": "StockLevel", "to": "Product", "type": "many-to-one", "field": "productId"},
    {"from": "StockLevel", "to": "Warehouse", "type": "many-to-one", "field": "warehouseId"},
    {"from": "PurchaseOrderLine", "to": "PurchaseOrder", "type": "many-to-one", "field": "orderId"},
    {"from": "PurchaseOrderLine", "to": "Product", "type": "many-to-one", "field": "productId"}
  ],

  "pages": [
    {
      "route": "/inventory/products",
      "name": "Product List",
      "description": "Searchable, filterable table of all products with stock indicators",
      "components": ["ProductTable", "ProductFilters", "AddProductButton"]
    },
    {
      "route": "/inventory/products/[id]",
      "name": "Product Detail",
      "description": "Product info, stock levels across warehouses, order history",
      "components": ["ProductInfo", "StockLevelTable", "OrderHistory"]
    }
    // ... more pages
  ],

  "api_routes": [
    {"method": "GET",    "path": "/api/products",      "description": "List products with search/filter/pagination"},
    {"method": "POST",   "path": "/api/products",      "description": "Create product"},
    {"method": "GET",    "path": "/api/products/:id",   "description": "Get product detail with stock levels"},
    {"method": "PUT",    "path": "/api/products/:id",   "description": "Update product"},
    {"method": "DELETE", "path": "/api/products/:id",   "description": "Soft delete product (set isActive=false)"}
    // ... more routes
  ],

  "workflows": [
    {
      "name": "on-low-stock",
      "trigger": "StockLevel.available drops below Product.reorderPoint",
      "steps": ["Create draft PurchaseOrder", "Notify purchasing team"]
    },
    {
      "name": "on-goods-received",
      "trigger": "GoodsReceipt is completed",
      "steps": ["Update StockLevel quantities", "Update PO status to received"]
    }
  ],

  "rules": [
    {"type": "validation", "model": "Product", "field": "unitPrice", "condition": "value > 0", "message": "Price must be positive"},
    {"type": "validation", "model": "Product", "field": "sku", "condition": "unique", "message": "SKU must be unique"},
    {"type": "computed", "model": "StockLevel", "field": "available", "expression": "quantity - reserved"},
    {"type": "state_machine", "model": "PurchaseOrder", "field": "status", "states": ["draft", "submitted", "approved", "received", "cancelled"]}
  ],

  "seed_data": {
    "description": "Generate 10 sample products, 3 warehouses, stock levels, and 2 sample POs",
    "notes": "Use realistic product names and SKUs for a general supplies company"
  },

  "access_control": {
    "app_roles": [
      {"name": "inventory_admin", "maps_from_org_role": "manager", "description": "Full CRUD on all inventory data"},
      {"name": "warehouse_staff", "maps_from_org_role": "staff", "maps_from_dept": "warehouse", "description": "Can update stock levels"},
      {"name": "inventory_viewer", "maps_from_org_role": "staff", "description": "Read-only access"}
    ],
    "field_access": [
      {"model": "Product", "field": "unitCost", "view": ["finance_dept", "manager+"], "edit": ["inventory_admin"]},
      {"model": "Product", "field": "margin", "view": ["finance_dept", "director+"], "edit": []},
      {"model": "Product", "field": "supplierNotes", "view": ["procurement_team", "admin"], "edit": ["procurement_team"]}
    ],
    "record_scope": [
      {"model": "Product", "scope": "department", "column": "department_id",
       "rules": "staff sees own dept, manager sees own + sub-depts, finance/admin sees all"}
    ],
    "workflow_assignments": [
      {"workflow": "on-low-stock", "node": "approve-po", "assign_to": "requester's manager",
       "sla_hours": 24, "escalate_to": "director"},
      {"workflow": "on-goods-received", "node": "verify-receipt", "assign_to": "warehouse_staff",
       "assign_mode": "round_robin"}
    ]
  },

  "ai_features": {
    "smart_fields": [
      // Auto-populated when user requirements imply AI
      {"model": "Product", "field": "description", "type": "ai_generate",
       "source": ["name", "specs", "features"], "trigger": "manual",
       "prompt": "Generate marketing product description from specs"}
    ],
    "semantic_search": [
      {"model": "Product", "fields": ["name", "description"], "trigger": "on_create_update"}
    ],
    "ai_workflow_nodes": [],
    "ai_rules": [],
    "scheduled_ai": [],
    "ai_components": [
      {"type": "SmartFilterBar", "page": "/inventory/products"},
      {"type": "DataInsightsPanel", "page": "/dashboard"}
    ]
  },

  "cross_module_dependencies": [
    // Only if this module depends on existing modules
    {"module": "finance", "reason": "Goods receipt creates AP journal entry"}
  ]
}

4. CONFIRM: Present the plan to the user for approval. If they want changes, adjust and re-present.

## Important Rules
- Keep plans scoped. A single module should have 3-8 data models, 4-12 pages, and 2-6 workflows.
- If the user's request is too large for one module, split it into multiple modules and explain why.
- Always include seed data so the app works immediately on preview.
- Consider the existing app's data models when planning relations and cross-module integrations.
- Use PostgreSQL-native types (uuid, varchar, timestamp, jsonb, etc.).
"""

PLANNER_OPTIONS = ClaudeAgentOptions(
    system_prompt=PLANNER_SYSTEM_PROMPT,
    allowed_tools=["Read", "Glob"],
    permission_mode="bypassPermissions",
    max_turns=15,
    model="claude-sonnet-4-20250514",
)
```

### 5.4 Agent #2: Refiner

```python
# backend/agents/refiner.py

REFINER_SYSTEM_PROMPT = """You are a developer applying changes to an existing Next.js +
Tailwind CSS + PostgreSQL (Drizzle ORM) application based on user instructions.

## Your Process

1. Read the AppModel index (app-model.json) to understand what exists and where files are.
2. Identify which files need to change based on the instruction.
3. Read only the affected files.
4. Make targeted edits using the Edit tool (NOT Write — preserve existing code).
5. If adding new files, use Write.
6. If the change affects the database schema, also update src/infrastructure/db/schema.ts and run migrations.
7. After all edits, verify the build: npm run build
8. If the build fails, fix the error.

## Rules
- Make ONLY the changes described in the instruction.
- Use Edit for modifications, Write only for new files.
- Preserve existing code structure and patterns.
- Preserve the Clean Architecture layer separation. When adding new logic, place it in the correct layer:
  - Domain types/rules → `src/domain/{module}/`
  - Service logic → `src/application/{module}/`
  - DB queries → `src/infrastructure/db/repositories/`
  - Auth/RBAC → `src/infrastructure/auth/`
  - AI features → `src/infrastructure/ai/`
  - Route handlers → `src/app/api/` (keep thin — delegate to services)
  - Components → `src/components/` (presentation only)
- Never move business logic into route handlers or components.
- Never add direct DB queries to route handlers — always go through services and repositories.
- If the instruction came from a visual editor, it will be very specific — follow it exactly.
- If the instruction came from chat, it may be vague — use your judgment for the best implementation.
- When changing data models, update: schema.ts, repository, service, API routes, components, and seed data.
- Use Tailwind CSS classes matching the project's existing style.
- Do NOT add new dependencies without explicit instruction.
- Do NOT refactor or reorganize code beyond what's requested.

## Database Changes
When modifying src/infrastructure/db/schema.ts:
- Use Drizzle ORM pgTable, pgEnum syntax
- Add proper constraints (notNull, unique, default, references)
- Add indexes for frequently queried columns
- After schema changes, the preview system will run drizzle-kit push automatically

## Figma Design Context
If src/contracts/figma-context.json exists, this project was generated from a Figma design.
Read it to understand the design tokens (colors, typography, spacing, border radii).
When making visual changes, prefer using values from the original design system.
Also read reference.png to see the original design if helpful.
"""

REFINER_OPTIONS = ClaudeAgentOptions(
    system_prompt=REFINER_SYSTEM_PROMPT,
    allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
    permission_mode="bypassPermissions",
    max_turns=30,
    model="claude-sonnet-4-20250514",
)
```

The refiner's user prompt also conditionally includes design tokens via `get_figma_context_for_prompt()` when `src/contracts/figma-context.json` exists.

### 5.5 Agent #4: Code Generator

```python
# backend/agents/code_generator.py

CODE_GENERATOR_SYSTEM_PROMPT = """You are a senior full-stack developer generating a complete
Next.js + Tailwind CSS + PostgreSQL application from a structured plan.

## Tech Stack (ALWAYS use these exactly)
- Next.js 15 (App Router)
- TypeScript 5.7+
- Tailwind CSS 4 (with @import "tailwindcss" in globals.css)
- PostgreSQL 16 via Docker Compose
- Drizzle ORM with pg driver
- @tailwindcss/postcss for PostCSS config

## Clean Architecture — EVERY generated app follows this structure

The app is organized into strict layers. Each layer has a clear responsibility.
Import direction: domain ← application ← infrastructure, api → application, components → types.

### Directory Placement Rules

| Code type | Goes in | Example |
|-----------|---------|---------|
| TypeScript types, domain constants | `src/domain/{module}/entities.ts` | `Product`, `OrderStatus` |
| Pure business rule functions | `src/domain/{module}/rules.ts` | `canApproveExpense(user, expense)` |
| Domain error classes | `src/domain/{module}/errors.ts` | `InsufficientStockError` |
| Zod input/output schemas | `src/application/{module}/{resource}.schema.ts` | `createProductSchema` |
| Use case / service methods | `src/application/{module}/{resource}.service.ts` | `ProductService.create()` |
| Drizzle table definitions | `src/infrastructure/db/schema.ts` | `pgTable('products', ...)` |
| DB connection pool | `src/infrastructure/db/connection.ts` | `export const db = drizzle(pool)` |
| DB queries (repository) | `src/infrastructure/db/repositories/{resource}.repository.ts` | `ProductRepository.findById()` |
| Auth middleware | `src/infrastructure/auth/middleware.ts` | `requireAuth()` |
| RBAC enforcement | `src/infrastructure/auth/rbac.ts` | `applyScopeFilter()` |
| Org context resolver | `src/infrastructure/auth/org-context.ts` | `resolveOrgContext()` |
| AI config, smart fields, search | `src/infrastructure/ai/` | `config.ts`, `smart-fields.ts`, `semantic-search.ts`, `usage.ts` |
| Real-time socket server | `src/infrastructure/realtime/socket-server.ts` | `initSocketServer()` |
| Real-time React hook | `src/infrastructure/realtime/use-realtime.ts` | `useRealtime(channel, event, cb)` |
| Email sending | `src/infrastructure/email/email.service.ts` | `sendEmail()` |
| External API clients | `src/infrastructure/external/{api}.client.ts` | `StripeClient` |
| Seed data | `src/infrastructure/db/seed.ts` | Idempotent seed script |
| API route handlers | `src/app/api/{resource}/route.ts` | Thin — max 15-20 lines |
| Page components | `src/app/{module}/{resource}/page.tsx` | Server Components |
| React UI components | `src/components/{module}/{Resource}Form.tsx` | Presentation only |
| Shared types | `src/types/index.ts` | Re-exports from domain entities |

### Import Direction Rules (NEVER violate)
- `domain/` imports NOTHING (pure TypeScript, no npm packages except type-only)
- `application/` imports from `domain/` and `infrastructure/`
- `infrastructure/` imports from `domain/` only
- `app/` (routes) imports from `application/` only (never touch DB directly)
- `components/` imports from `types/` only (no business logic)

### Anti-Patterns to AVOID
- NO DB queries in route handlers (use services)
- NO business logic in components (just render props)
- NO framework imports in domain layer (no Drizzle, no Next.js, no Zod)
- NO direct DB calls from app/ routes (always go through service → repository)
- NO `src/lib/` grab-bag folder (everything has a proper layer)

## Required Files (generate ALL of these)

### Project Config
1. package.json — dependencies: next, react, react-dom, drizzle-orm, pg, zod, tailwindcss, @tailwindcss/postcss
   optional deps (when real-time needed): socket.io, socket.io-client
   devDeps: drizzle-kit, tsx, @types/pg, typescript, @types/react, @types/react-dom
   scripts: dev, build, start, db:up, db:push, db:seed, db:reset, db:studio
2. docker-compose.yml — PostgreSQL 16 service with health check, using DB_PORT env var
3. .env — DATABASE_URL=postgresql://app:app@localhost:${DB_PORT:-5432}/app
4. .env.example — same without real values
5. .gitignore — node_modules, .next, .env, data/
6. tsconfig.json — standard Next.js config with path aliases (@/ → src/)
7. next.config.ts — standard Next.js config
8. postcss.config.mjs — {"plugins": {"@tailwindcss/postcss": {}}}
9. drizzle.config.ts — PostgreSQL dialect, schema path, DATABASE_URL

### Domain Layer
10. src/domain/{module}/entities.ts — TypeScript types + domain constants per module
11. src/domain/{module}/rules.ts — Pure business rule functions (no imports from infra)
12. src/domain/{module}/errors.ts — Domain-specific error classes

### Application Layer
13. src/application/{module}/{resource}.service.ts — Service with CRUD + business operations
14. src/application/{module}/{resource}.schema.ts — Zod schemas for input validation

### Infrastructure Layer
15. src/infrastructure/db/schema.ts — ALL tables using pgTable, pgEnum, with proper types:
    - uuid for IDs (defaultRandom)
    - varchar for short strings (with length)
    - text for long strings
    - timestamp for dates (defaultNow where appropriate)
    - pgEnum for enums
    - Foreign keys with references() and onDelete behavior
    - Indexes for searchable/filterable columns
16. src/infrastructure/db/connection.ts — Pool connection, drizzle instance, export db
17. src/infrastructure/db/seed.ts — Realistic sample data, check before inserting (idempotent)
    Run with: npx tsx src/infrastructure/db/seed.ts
18. src/infrastructure/db/repositories/{resource}.repository.ts — DB queries per resource
    - Repositories return domain types, not Drizzle row types
    - One repository per entity
19. src/infrastructure/auth/middleware.ts — Auth middleware
20. src/infrastructure/auth/rbac.ts — Field/record access enforcement
21. src/infrastructure/auth/org-context.ts — Org structure resolver

### API Layer (thin handlers)
22. src/app/globals.css — @import "tailwindcss"; + any custom styles
23. src/app/layout.tsx — Root layout with Google Fonts, metadata
24. src/app/page.tsx — Dashboard/home page
25. src/app/{module}/{resource}/page.tsx — List pages (Server Components)
26. src/app/api/{resource}/route.ts — CRUD API routes per resource
    Each handler: parse request → validate with Zod → call service → return response

### Components (presentation only)
27. src/components/layout/ — Sidebar, Header, PageWrapper
28. src/components/shared/ — DataTable, FormField, Badge, etc.
29. src/components/{module}/ — Module-specific components ({Resource}Form, {Resource}Table, etc.)

### Shared Types
30. src/types/index.ts — Re-exports domain entity types for use by components and routes

## Server-Side Rendering Strategy
- Server Components by default for ALL pages — data fetched at the server, zero client JS
- List pages, detail pages, dashboards, layouts, navigation: ALWAYS Server Components
- Server Components can call services directly (no API roundtrip needed for reads)
- Use Client Components ("use client") ONLY for: forms with state, real-time UI, DataTable
  with client-side sorting/filtering, components using useState/useEffect/event handlers
- API routes for ALL mutations (create, update, delete) — not Server Actions
- Server Actions may wrap service calls as thin pass-throughs when convenient, but API
  routes remain the primary mutation pattern for portability and testability

## Real-Time (when needed)
- Only add Socket.IO when the app has features that need it (agents, workflows with
  assignments, smart fields, collaborative editing, live notifications)
- Socket server: `src/infrastructure/realtime/socket-server.ts` — attaches to Next.js
  custom server, handles room-based broadcasting
- Event types: `src/infrastructure/realtime/events.ts` — typed event definitions
- React hook: `src/infrastructure/realtime/use-realtime.ts` — `useRealtime(channel, event, cb)`
- Room scoping: `org:{orgId}`, `user:{userId}`, `record:{model}:{id}`
- Keep SSE for agent chat streaming (simpler, one-directional)
- Use Socket.IO for: smart field completion push, workflow task assignments,
  live notifications, data refresh after mutations by other users

## Code Quality Rules
- Every API route must validate input with Zod schemas before calling services
- Every API route must handle errors with try/catch and return proper HTTP status codes
- Every API route must be thin: max 15-20 lines (parse → validate → call service → respond)
- Every list endpoint must support basic pagination (page, limit query params)
- Every component must have TypeScript props interface
- Use "use client" directive only on components with interactivity (state, effects, handlers)
- Server Components by default, Client Components only when needed
- Use exact Tailwind arbitrary values for pixel-perfect styling
- Format all files consistently (2-space indent, single quotes, trailing commas)
- Services are the ONLY place that coordinates DB calls + business rules
- Each service method = one use case (e.g., createProduct, approveExpense)

## CRITICAL: After generating all files, run:
1. npm install
2. npm run db:up (starts Docker Postgres)
3. npx drizzle-kit push (applies schema)
4. npx tsx src/infrastructure/db/seed.ts (seeds data)
5. npm run build (verifies compilation)

If any step fails, fix the error and retry.

## Navigation & Layout
- Generate a sidebar or navbar with links to all pages
- Use a consistent layout with header, sidebar, and content area
- Active page should be highlighted in navigation
- Use Next.js Link component for client-side navigation
"""

CODE_GENERATOR_OPTIONS = ClaudeAgentOptions(
    system_prompt=CODE_GENERATOR_SYSTEM_PROMPT,
    allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
    permission_mode="bypassPermissions",
    max_turns=80,
    model="claude-sonnet-4-20250514",
)
```

### 5.6 Agent #5: Code Editor

```python
# backend/agents/code_editor.py

CODE_EDITOR_SYSTEM_PROMPT = """You are a focused code editor. You receive a specific file
and a specific instruction. Make the minimum change needed.

Rules:
- Use Edit tool, not Write (preserve existing code)
- Change ONLY what the instruction says
- Do not refactor, reorganize, or "improve" surrounding code
- Do not add comments unless the instruction says to
- Preserve existing formatting and style
- After editing, verify the change makes sense in context

If the file doesn't exist yet, use Write to create it.
If the change requires imports, add them.
If the change would break TypeScript types, fix the type errors too.
"""

CODE_EDITOR_OPTIONS = ClaudeAgentOptions(
    system_prompt=CODE_EDITOR_SYSTEM_PROMPT,
    allowed_tools=["Write", "Edit", "Read", "Bash"],
    permission_mode="bypassPermissions",
    max_turns=15,
    model="claude-sonnet-4-20250514",
)
```

### 5.7 Agent #7: Indexer

```python
# backend/agents/indexer.py

INDEXER_SYSTEM_PROMPT = """You maintain the AppModel index (app-model.json) for a generated
application. After code changes, you scan the affected files and update the index.

## What You Do
1. Read the current app-model.json
2. Read the list of changed files provided in the instruction
3. Scan each changed file to extract:
   - Components: name, file path, props, description
   - Pages: route, file path, description, components used
   - Data models: name, fields with types, file path
   - API routes: method, path, file path, description
   - Workflows: name, trigger, file path
   - Rules: type, attached model/field, condition
   - Bindings: which components are bound to which models
4. Update app-model.json with the new information
5. Remove entries for deleted files

## Output
Write the updated app-model.json using the Write tool.
The format must match the AppModel schema exactly (see below).

## Important
- Do NOT hallucinate entries. Only index what you can verify by reading the files.
- If a file was deleted, remove its entries from the index.
- If a file was modified, re-read it and update its entries.
- Preserve entries for files that weren't changed.
"""

INDEXER_OPTIONS = ClaudeAgentOptions(
    system_prompt=INDEXER_SYSTEM_PROMPT,
    allowed_tools=["Read", "Write", "Glob"],
    permission_mode="bypassPermissions",
    max_turns=10,
    model="claude-haiku-4-5-20251001",
)
```

### 5.8 Agent #8: Validator (2-Phase)

The Validator runs in two phases after QA verification and deterministic pre-fixes.

**Phase 7.5: Deterministic Pre-Fixes (no LLM, runs before Validator)**

These run instantly via `services/post_generate_fixes.py`:

| Fix | What it does |
|-----|-------------|
| `_fix_tailwind_v3_syntax` | `@tailwind base` → `@import "tailwindcss"` |
| `_fix_apply_directives` | Replaces `@apply ring-blue-500` with CSS variables |
| `_fix_postcss_config` | `tailwindcss` → `@tailwindcss/postcss` plugin |
| `_fix_missing_use_client` | Adds `"use client"` to files using hooks/event handlers |
| `_fix_missing_page_default_export` | Adds `export default` to page.tsx files missing it |

**Phase 1: Build Validation**
- Runs `npm run build`, reads errors, fixes all in one batch
- Re-runs build (up to 5 fix attempts)
- Handles: TypeScript errors, imports, missing deps, Tailwind v4, Drizzle ORM, async params (Next.js 15)

**Phase 2: Runtime Safety Scan**

After build passes, runs shell commands to detect patterns that `npm build` misses but crash at runtime:

| Check | Why it crashes |
|-------|---------------|
| Missing `"use client"` | Hooks/events in server components → "useState is not a function" |
| Async client components | `async function` + `"use client"` → React error |
| Missing default exports | page.tsx without `export default` → Next.js 404 |
| Hydration mismatches | `typeof window` / `localStorage` in render → hydration error |
| API route issues | Missing `NextResponse` returns → 500 errors |
| Undefined variables | `tsc --noEmit --strict` catches remaining type errors |

```python
# backend/agents/validator.py
VALIDATOR_OPTIONS = ClaudeAgentOptions(
    system_prompt=VALIDATOR_SYSTEM_PROMPT,
    allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
    permission_mode="bypassPermissions",
    max_turns=30,        # Increased from 10 to accommodate runtime scan
    model="claude-sonnet-4-20250514",  # Upgraded from Haiku for better fixes
)
```

### 5.9 Relay Pipeline

The relay pipeline replaces the monolithic Code Generator (Agent #4) with a sequence of specialized agents, each focused on one concern. The orchestration lives in `backend/routers/generate.py::_run_relay_pipeline()` and emits a continuous SSE stream of `status`, `log`, `office`, `registry_validation`, and `agent_result` events.

**Domain Context Injection:** At the start of every pipeline run, `services/domain_context.py` detects the application domain from keywords (17 industries supported) and generates role-specific personas. Each agent receives a `## YOUR DOMAIN EXPERTISE` section in its system prompt. Example: for a Hospital Management System, the Schema Designer gets "You are a database architect with deep experience in Healthcare data modeling..."

**Contract Registry (per-project):** `output/<short_id>/src/contracts/registry.json` is created at pipeline start and incrementally **merged** after every agent phase by `services/registry.py`. After each phase, `services/registry_extractor.py` parses the just-emitted artefacts (schemas, route files, components, pages) into structured entries and `merge_section()` writes them back. `services/registry_validator.py` runs 11 cross-reference checks at two checkpoints — `post_api` and `pre_qa` — emitting `registry_validation` SSE events with `{section, name, error, suggestion, severity}` per issue. `services/registry_repair.py` deterministically fixes mismatches (import names, field refs) before QA runs.

**Phase Gates:** Between phases, deterministic gates in `services/phase_gates.py` re-run the corresponding agent with a focused `fix_prompt` rather than continuing on incomplete state. The gates that fire today: Contract Gate (gaps in contracts), Auth Gate, API Gate (entities missing routes), Component Gate, Page Gate, X-Ref Gate (page→API references unresolved), UX Gate (domain UX patterns), Workflow Gate (workflow integration), Build Gate (validator output drives the fix loop, up to `MAX_REVIEW_CYCLES`).

**Current pipeline (`_run_relay_pipeline`, default schema-mode):**
```
discovery_domain
  → design_agent           (writes src/contracts/design-spec.json — palette/typography/density/register)
  → design_compiler        (tokens.custom.json from design-spec, gated by FIDELITY_MODE_ENABLED)
  → contract_agent         → contract_gate (re-run if gaps)
  → schema_agent           → registry merge (entities)
  → parallel [auth, api, business_logic]
                           → registry merge (routes)
                           → registry_validate (post_api)  [emits registry_validation SSE]
  → rules_agent            (optional, non-fatal)
  → auth_gate              (re-run auth on issues)
  → runtime injection      (services/runtime_injection — non-fatal)
  → api_gate               (re-run api if entities missing routes)
  ───── frontend split (SCHEMA_MODE_ENABLED / IR_FRONTEND_ENABLED) ─────
  ┃ schema mode (default):
  ┃   run_schema_frontend_pipeline    → per entity: feature_slice_schema_agent
  ┃   build_success → agent_result    (skips QA/validator/indexer; expected artefacts are JSON)
  ┃ IR mode (legacy flag):
  ┃   run_ir_frontend_pipeline        → IR compiler → TSX
  ┃ TSX mode (legacy fallback):
  ┃   component_agent      → registry merge (components) → component_gate
  ┃   page_agent           → registry merge (pages) → registry_validate (pre_qa) → registry_repair
  ┃   page_gate, xref_gate, ux_gate, workflow_gate
  ────────────────────────────────────────────────────────────────────
  → seed_generator                (seed-plan.json + seed.ts; auto-executes seed)
  → fidelity_loop                 (optional, FIDELITY_MODE_ENABLED — vision_evaluator)
  → qa_agent                      (TSX path only — registry-aware)
  → post_generate_fixes           (deterministic lint/imports/format — no LLM)
  → validator                     (build + runtime; fix loop via page_agent or fix_agent)
  → design_reviewer / fixer       (optional, MAX_VISUAL_CYCLES)
  → flow_validator                (validates navigation graph)
  → browser_validator             (boots dev server, headless visit per page)
  → indexer                       (rebuilds app-model.json)
  → verify_pipeline               (CSS + page sanity)
  → build_success event           (triggers Virtual Office celebration + confetti)
```

**Figma variant (`_run_figma_relay_pipeline`):** identical until the frontend split, where `figma_ui_agent` runs in place of the component/page pair, generating pixel-perfect UI from the prefetched Figma reference.

**Parallel execution** uses `services/parallel_runner.py` which runs agents concurrently via `asyncio.gather()`, interleaving SSE events with agent-name prefixes. Each parallel agent has its own timeout enforced via `AGENT_TIMEOUT_SECONDS`.

**Office Events:** `agent_start`, `agent_complete`, `agent_handoff`, `parallel_start`, `phase_start`, `phase_complete`, `build_success`, and `credits_exhausted` events flow to the Virtual Office visualization (see Section 25). `PHASE_TO_ROOM` maps each phase key (`contract`, `schema`, `api`, `auth`, `bizlogic`, `components`, `pages`, `seed`, `indexing`) to a room id; `agent_handoff_event` carries an `artifact` label.

**Reconnect:** `services/generation_buffer.py` buffers events per `session_id` so a frontend reconnect via `/api/projects/{id}/generation/reconnect` resumes the SSE stream from the last seen index without losing events.

**Billing Error Handling:** All `query()` calls are wrapped with `billing_safe_query()` from `sse_helpers.py`, which intercepts `AssistantMessage(error='billing_error')` from the Claude SDK and raises a clear `BillingError`. This propagates to the frontend as a credit error, triggering the office protest animation.

### 5.9.1 Per-Agent Registry Contract

Each agent that participates in the relay both **reads** earlier registry sections (injected into its prompt by `services/registry.py::summary_for_agent()`) and **writes** new entries through post-phase extraction:

| Agent | Reads from registry | Writes (via extractor) |
|---|---|---|
| `contract_agent` | (none — seeds initial state) | `entities` from `db-schema-plan.json` |
| `schema_agent` | `entities` | refines `entities` (Drizzle column types) |
| `auth_agent` | `entities`, `relations` | — |
| `api_agent` | `entities`, `relations` | `api_routes` |
| `business_logic_agent` | `entities`, `api_routes` | workflow scaffolds |
| `component_agent` (TSX) | `entities`, `api_routes` | `components` (with prop signatures) |
| `page_agent` (TSX) | `entities`, `routes`, `components` | `pages` (route → components mapping) |
| `feature_slice_schema_agent` | `entities` | (schemas live under `src/schemas/`, not in registry) |
| `qa_agent` | full map + cross-ref errors | — |

The validator's 11 checks include: every `api_routes[*].entity` exists in `entities`; every `components[*].imports` resolves; every `pages[*].uses` matches a known component; every entity has list/detail/form coverage; field references in routes match entity fields; etc.

### 5.9.2 SSE Event Reference

Events emitted by the pipeline (consumed by `frontend/src/hooks/useSSE.ts` and `frontend/src/stores/chat.ts`):

| Event | Payload | Triggered by |
|---|---|---|
| `session` | `{session_id}` | First event on a new generation |
| `status` | `{message}` | Phase boundaries — drives the top-line UI label |
| `log` | `{text}` | Tagged log lines (`[Schema]`, `[QA]`, `[Registry]`, gate names) — `chat.ts` parses tags to drive office activity |
| `office` | `agent_start | agent_complete | agent_handoff | parallel_start | phase_start | phase_complete | build_success | credits_exhausted` | Virtual Office |
| `registry_validation` | `{phase, errors: [{section, name, error, suggestion, severity}]}` | After post_api / pre_qa validation runs |
| `phase_start` / `phase_complete` | phase-specific data | Fidelity loop, top-level phases |
| `agent_result` | `{status, schema_count?, ...}` | End of pipeline (final summary) |
| `error` | `{message}` | Unrecoverable failure |

### 5.10 Agent #13: Design Analyzer

Analyzes a Figma design (reference.png + styles.json) and produces a structured plan with pages, data models, workflows, and features — same format as the Planner output. Supports multi-turn conversation for user to adjust requirements before approval.

```python
# backend/agents/design_analyzer.py
# Reads: reference.png, styles.json (pre-fetched from Figma API)
# Outputs: structured plan in ```plan-json``` format
# Supports conversation_history for multi-turn adjustments
```

### 5.11 Agent #14: Figma UI Agent

Wrapper around `run_agent()` from `agent.py` that constrains output to UI-only files. Used in the Figma relay pipeline where foundation files already exist from prior relay phases.

```python
# backend/agents/figma_ui_agent.py

async def run_figma_ui_agent(output_dir, plan, figma_url, figma_token):
    """Calls run_agent(ui_only=True) — generates ONLY:
    - src/app/globals.css
    - src/app/layout.tsx, src/app/**/layout.tsx
    - src/components/**/*.tsx
    - src/app/**/page.tsx
    - src/app/error.tsx, not-found.tsx, loading.tsx

    Does NOT create: package.json, tsconfig, schema, auth, API routes, services
    (these already exist on disk from relay phases 1-3).
    """
    from agent import run_agent
    async for message in run_agent(
        figma_url=figma_url,
        figma_token=figma_token,
        output_dir=output_dir,
        requirements=plan,
        ui_only=True,  # Prepends foundation-exclusion rules to user prompt
    ):
        yield message
```

### 5.12 Figma Design Context Persistence

Design tokens extracted from `styles.json` are persisted as `src/contracts/figma-context.json` so that future agents (refiner, scaffolder) maintain design consistency.

```python
# backend/services/figma_context.py

def extract_figma_context(output_dir: str, figma_url: str) -> dict:
    """Parse styles.json, extract unique design tokens, write figma-context.json."""
    # Walks the style tree recursively
    # Collects: colors, fonts, font_sizes, border_radii, spacings
    # Writes to src/contracts/figma-context.json

def should_refetch_figma(output_dir: str, new_figma_url: str | None) -> bool:
    """Check if Figma data needs re-fetching (URL changed or artifacts missing)."""

def get_figma_context_for_prompt(output_dir: str) -> str:
    """Return a prompt section with design tokens for agents to include."""
```

**figma-context.json schema:**
```json
{
  "figma_url": "https://www.figma.com/file/...",
  "fetched_at": "2026-03-05T10:00:00Z",
  "styles_json_hash": "sha256:abc123...",
  "design_tokens": {
    "colors": ["#6e2574", "#f8f9fa", "#ffffff"],
    "fonts": ["Inter"],
    "font_sizes": [12, 14, 16, 24, 32],
    "border_radii": [4, 8, 12],
    "spacings": [8, 12, 16, 24, 40, 48]
  }
}
```

**Integration points:**
- Created after `_prefetch_figma_data()` in `/generate` endpoint
- Refiner reads it via `get_figma_context_for_prompt()` to maintain design consistency
- Scaffolder reads it when adding new features to use the same design system
- Figma URL change detection in `/chat` triggers re-fetch + re-extract

### 5.13 Agent Orchestration Flow

```python
# backend/agents/__init__.py — main orchestration logic

async def handle_user_input(
    project_id: str,
    user_message: str,
    output_dir: str,
    source: str = "chat",  # "chat" | "visual_editor"
) -> AsyncIterator[dict]:
    """Main entry point for all user inputs — chat messages and visual editor actions."""

    # Step 1: Classify intent (skip for visual editor — always REFINE)
    if source == "visual_editor":
        intent = "REFINE"
    else:
        intent = await classify_intent(user_message, output_dir)

    # Step 2: Route to appropriate agent
    if intent == "PLAN":
        async for event in run_planner(output_dir, user_message):
            yield event
        # After plan approval, run code generator
        # ... (see generation flow below)

    elif intent == "REFINE":
        yield sse_event("refine_start", {"message": f"Applying: {user_message}"})

        # Run refiner
        files_changed = []
        async for event in run_refiner(output_dir, user_message):
            yield event
            if event.get("event") == "file_created":
                files_changed.append(event["data"]["path"])

        # Validate build
        yield sse_event("status", {"message": "Verifying build..."})
        build_ok = await run_validator(output_dir)
        if not build_ok:
            yield sse_event("error", {"message": "Build failed after changes"})
            return

        # Update index
        yield sse_event("status", {"message": "Updating project index..."})
        await run_indexer(output_dir, files_changed)

        # Push schema changes if any db files changed
        if any("schema" in f or "db/" in f for f in files_changed):
            yield sse_event("status", {"message": "Applying database changes..."})
            await push_schema(output_dir)

        yield sse_event("refine_complete", {"message": "Done"})

    elif intent == "EXPLAIN":
        async for event in run_explainer(output_dir, user_message):
            yield event

    elif intent == "SCAFFOLD":
        async for event in run_scaffolder(output_dir, user_message):
            yield event

    elif intent == "AGENT":
        yield sse_event("agent_build_start", {"message": f"Building agent: {user_message}"})
        files_changed = []
        async for event in run_agent_builder(output_dir, user_message):
            yield event
            if event.get("event") == "file_created":
                files_changed.append(event["data"]["path"])
        # Validate + Index
        build_ok = await run_validator(output_dir)
        await run_indexer(output_dir, files_changed)
        yield sse_event("agent_build_complete", {"message": "Agent ready"})

    elif intent == "DISCOVER":
        yield sse_event("discover_start", {"message": "Let me help you figure out what you need..."})
        async for event in run_discovery_agent(output_dir, user_message, org_id):
            yield event
            # When discovery produces a brief, hand off to Planner
            if event.get("event") == "discover_brief_ready":
                brief = event["data"]["brief"]
                async for plan_event in run_planner(output_dir, brief):
                    yield plan_event

    elif intent == "UNDO":
        await git_revert_last(output_dir)
        yield sse_event("status", {"message": "Reverted last change"})
```

### 5.14 Schema-Mode Frontend Pipeline

`backend/services/schema_pipeline.py::run_schema_frontend_pipeline()` is the frontend half of the relay when `SCHEMA_MODE_ENABLED=true` (the default since Phase 4). It iterates the plan's entities and, for each one, calls `feature_slice_schema_agent` to emit JSON Page schemas instead of TSX.

```python
# backend/services/schema_pipeline.py

SCHEMA_MODE_ENABLED = os.getenv("SCHEMA_MODE_ENABLED", "true").lower() in ("true", "1", "yes")

async def run_schema_frontend_pipeline(output_dir, plan, description, domain_context=None):
    # The new planner emits entities under `data_models`; legacy plans use `entities`.
    raw_entities = plan.get("data_models") or plan.get("entities") or []
    for entity in raw_entities:
        # Per-entity opt-out — if `legacy_tsx_mode: true`, fall through to TSX path.
        if entity.get("legacy_tsx_mode") is True:
            continue
        entity_plan = {**plan, "entity": entity}
        await run_feature_slice_schema_agent(output_dir, entity_plan, domain_context)
```

**`feature_slice_schema_agent` contract** (`backend/agents/feature_slice_schema_agent.py`):

- One LLM call **per (entity, page_type)** triple — page types default to `["list", "detail", "form"]`, but `entity.pages` may supply a custom list of short identifiers (e.g. `["dashboard", "settings"]`). Path-like or file-extension-containing `pages` values are ignored (those come from the legacy planner) and the defaults are used.
- Output goes to `output/<short_id>/src/schemas/<entity_slug>/<page_type>.json` — one file per page type.
- Prompt construction lives in `services/schema_prompt.py::build_schema_prompt()` and pulls in:
  - Entity name + fields + relations from the plan
  - Domain persona from `services/domain_context.py`
  - The current register (from `design-spec.json`) so the prompt mentions which library variants to favor
  - The canonical token namespace (loaded from `packages/library` defaults via `load_default_tokens`)
  - A list of legal library component names (the same set registered in `SchemaRendererWrapper`)
- Output is validated against the `Page` schema by `services/schema_validator.py`. Token references are checked via `validate_token_refs()` / `invalid_ref_pct()` — but **only soft-fails are warned** because the runtime resolver is wider than the strict regex (see Section 9A on the schema/renderer contract).
- The agent is **synchronous from the pipeline's perspective** — it doesn't yield SSE messages directly; the caller in `schema_pipeline.py` emits `status` and `log` events around each entity.
- Schema mode **skips QA, validator, and indexer** — those are TSX-specific. The pipeline emits `build_success` and an `agent_result` event with `schema_count` after the last entity completes.

**Register selection** (`backend/services/register_selector.py`): every project picks one of six stylistic registers — `default | workday | linear | stripe | notion | figma`. Selection runs in two layers:

1. `classify_register_llm(brief, domain, plan)` — Sonnet reads the brief, inferred domain, and (when available) the entity/page plan. Returns one of the six valid names. Timeouts at 10s, falls through to the rule-based classifier on any failure (no API key, parse error, timeout).
2. `classify_register(brief, domain)` — sync, rule-based. `DOMAIN_REGISTER_MAP` (hr/healthcare → `workday`, fintech/payments → `stripe`, saas/devtools → `linear`, docs/wiki → `notion`, etc.) plus keyword hints. Always available, never fails.

The chosen register is persisted to `src/contracts/design-spec.json` under the `register` key. The schema prompt biases component-variant choices toward that register's preferred shapes, and the renderer applies the register's token overrides at render time (see Section 9A).

---

## 6. Backend API

### 6.1 All Endpoints

```
Organizations
  POST   /api/orgs                          Create organization
  GET    /api/orgs                          List user's organizations
  GET    /api/orgs/:orgId                   Get org details
  PUT    /api/orgs/:orgId                   Update org settings
  POST   /api/orgs/:orgId/invite            Invite platform user to org

Org Structure
  GET    /api/orgs/:orgId/people             List all people in org
  POST   /api/orgs/:orgId/people             Add person manually
  PUT    /api/orgs/:orgId/people/:id         Update person details
  DELETE /api/orgs/:orgId/people/:id         Deactivate person
  POST   /api/orgs/:orgId/people/import      Bulk import (CSV/JSON upload)
  GET    /api/orgs/:orgId/departments         List departments
  POST   /api/orgs/:orgId/departments         Create department
  PUT    /api/orgs/:orgId/departments/:id     Update department (rename, move)
  DELETE /api/orgs/:orgId/departments/:id     Delete department (reassign people)
  GET    /api/orgs/:orgId/teams               List teams
  POST   /api/orgs/:orgId/teams               Create team
  GET    /api/orgs/:orgId/org-chart           Get full org tree (for visual editor)
  PUT    /api/orgs/:orgId/org-chart           Update org tree (from visual editor drag)
  GET    /api/orgs/:orgId/roles               List org roles
  POST   /api/orgs/:orgId/roles               Create custom role
  PUT    /api/orgs/:orgId/roles/:id           Update role
  DELETE /api/orgs/:orgId/roles/:id           Delete role (reassign people)
  GET    /api/orgs/:orgId/groups              List groups
  POST   /api/orgs/:orgId/groups              Create group
  PUT    /api/orgs/:orgId/groups/:id/members  Add/remove group members

RBAC Policies
  GET    /api/projects/:id/access-policies          List app access policies
  POST   /api/projects/:id/access-policies          Add app access policy
  DELETE /api/projects/:id/access-policies/:pid     Remove app access policy
  GET    /api/projects/:id/field-access              List field-level access rules
  POST   /api/projects/:id/field-access              Add field access rule
  PUT    /api/projects/:id/field-access/:pid         Update field access rule
  DELETE /api/projects/:id/field-access/:pid         Remove field access rule
  GET    /api/projects/:id/field-access/matrix       Get access matrix (model × role grid)
  GET    /api/projects/:id/workflow-assignments       List workflow assignments
  POST   /api/projects/:id/workflow-assignments       Add workflow assignment
  PUT    /api/projects/:id/workflow-assignments/:pid  Update workflow assignment

Projects (scoped to org)
  POST   /api/orgs/:orgId/projects              Create new project in org
  GET    /api/orgs/:orgId/projects              List org's projects
  GET    /api/projects/:id                  Get project details
  PUT    /api/projects/:id                  Update project name/description
  DELETE /api/projects/:id                  Archive project

Generation & Chat
  POST   /api/projects/:id/chat             Send message (SSE stream response)
  GET    /api/projects/:id/conversations    Get conversation history
  POST   /api/projects/:id/generate         Generate from plan (SSE stream)

Preview
  POST   /api/projects/:id/preview/start    Start dev server + Postgres
  POST   /api/projects/:id/preview/stop     Stop dev server + Postgres
  GET    /api/projects/:id/preview/status   Get preview port/status

Files
  GET    /api/projects/:id/files            List project files
  GET    /api/projects/:id/file?path=       Read file content
  PUT    /api/projects/:id/file?path=       Write file content (from code editor)
  GET    /api/projects/:id/download         Download project as ZIP

AppModel
  GET    /api/projects/:id/app-model        Get full AppModel index
  GET    /api/projects/:id/app-model/models Get just data models
  GET    /api/projects/:id/app-model/pages  Get just pages
  GET    /api/projects/:id/app-model/rules  Get just rules
  // etc. for each section

Modules
  GET    /api/projects/:id/modules          List modules
  POST   /api/projects/:id/modules          Create module (triggers planning)
  GET    /api/projects/:id/modules/:mid     Get module details
  DELETE /api/projects/:id/modules/:mid     Remove module

Visual Editor Actions
  POST   /api/projects/:id/visual/action    Execute visual editor action (SSE stream)
    body: {
      "editor": "ui|data|workflow|rules|navigation|agent",
      "action": "add_field|change_style|add_node|create_agent|add_tool|...",
      "params": { ... },
      "instruction": "Generated text instruction"
    }

Agents (within generated apps — managed via visual editor)
  GET    /api/projects/:id/app-model/agents     List agents in the app
  POST   /api/projects/:id/agents/test          Test agent with sample message
    body: { "agentId": "support-agent", "message": "Where is my order?", "userId": "test-user" }

Database Browser
  GET    /api/projects/:id/db/tables        List tables in generated app's DB
  GET    /api/projects/:id/db/tables/:name  Get table schema
  GET    /api/projects/:id/db/query         Execute SELECT query
  POST   /api/projects/:id/db/query         Execute INSERT/UPDATE/DELETE
  POST   /api/projects/:id/db/seed          Re-run seed data
  POST   /api/projects/:id/db/reset         Drop and recreate database

Version History
  GET    /api/projects/:id/versions         List versions (git log)
  POST   /api/projects/:id/versions/:hash/revert   Revert to version

Templates
  GET    /api/templates                     List all published templates
  GET    /api/templates?category=Sales      Filter by category
  GET    /api/templates?department=HR       Filter by relevant department
  GET    /api/templates/:slug               Get template details + plan
  GET    /api/orgs/:orgId/suggested-templates  Templates relevant to org's departments
  POST   /api/orgs/:orgId/projects/from-template  Create project from template
    body: { "templateSlug": "crm-basic", "customizations": { "name": "Our CRM" } }

Discovery
  POST   /api/orgs/:orgId/discovery/start   Start discovery session (SSE stream)
    body: { "input": "I need something for my HR team" }
  POST   /api/orgs/:orgId/discovery/:sid/message  Continue discovery conversation (SSE stream)
    body: { "message": "Yes we need to track PTO and approvals" }
  GET    /api/orgs/:orgId/discovery/:sid     Get discovery session details + brief
  POST   /api/orgs/:orgId/discovery/:sid/convert  Convert brief to project (triggers Planner)
  GET    /api/orgs/:orgId/discovery          List active/recent discovery sessions

Auth (Platform)
  POST   /api/auth/signup                   Create account
  POST   /api/auth/login                    Login (returns JWT with orgId)
  POST   /api/auth/logout                   Logout
  GET    /api/auth/me                       Current user + org memberships
  POST   /api/auth/switch-org               Switch active org context
```

### 6.2 SSE Event Types

```
All streaming endpoints use Server-Sent Events with these event types:

Generation events:
  status          — General progress message: {message: string}
  log             — Agent thinking/reasoning: {text: string}
  tool_call       — Tool invocation: {tool: string, args: string}
  file_created    — File written: {path: string}
  plan_ready      — Plan for user review: {plan: object}
  plan_approved   — User approved plan
  complete        — Generation finished: {num_turns, cost_usd, duration_ms}

Refinement events:
  refine_start    — Refinement starting: {message: string}
  refine_complete — Refinement done: {message, num_turns, cost_usd, duration_ms}

Agent builder events:
  agent_build_start    — Agent creation/edit starting: {message: string}
  agent_build_complete — Agent creation/edit done: {message, agentId, num_turns, cost_usd}

Discovery events:
  discover_start       — Discovery conversation starting: {message: string}
  discover_question    — Agent asking clarifying question: {question: string, options?: string[]}
  discover_suggestion  — Agent suggesting a template or approach: {suggestion: object}
  discover_brief_ready — Structured brief ready for conversion: {brief: object}

Review events:
  review_start    — Visual review starting: {message, iteration}
  review_issues   — Issues found: {message, issues, iteration}
  fix_start       — Fixes being applied: {message, iteration}
  review_approved — Design matches: {message, iteration}

Index events:
  index_updated   — AppModel index refreshed: {sections_changed: string[]}

Error:
  error           — Error occurred: {message: string}
```

---

## 7. Frontend Pages & Components

### 7.1 Page Structure

```
/ (landing — org selector)
  ├── Org list cards (orgs the user belongs to)
  ├── "Create Organization" button → org creation wizard
  └── Each card links to /orgs/[orgId]

/orgs/[orgId] (org dashboard)
  ├── App cards grid (all apps in this org)
  ├── "New App" button → creation options:
  │   ├── "Describe what you need" → Chat (Planner)
  │   ├── "I'm not sure yet" → Discovery conversation
  │   ├── "Start from a template" → Template gallery
  │   └── "Import Figma design" → Figma URL input
  ├── Suggested apps section (based on org departments without apps)
  ├── Sidebar:
  │   ├── Apps (grid view)
  │   ├── Templates (template gallery)
  │   ├── Org Structure (org chart editor)
  │   ├── People (user directory)
  │   ├── Roles & Groups
  │   ├── Access Policies
  │   └── Org Settings
  │
  ├── /orgs/[orgId]/templates       → Template gallery (filterable by category/department)
  ├── /orgs/[orgId]/discover        → Discovery conversation UI
  ├── /orgs/[orgId]/org-chart       → Visual org chart editor (React Flow)
  ├── /orgs/[orgId]/people          → People directory table + import
  ├── /orgs/[orgId]/roles           → Role management + role hierarchy
  ├── /orgs/[orgId]/groups          → Group management
  ├── /orgs/[orgId]/access          → Cross-app access policy overview
  └── /orgs/[orgId]/settings        → Org name, logo, plan, invite members

/org/[orgId]/projects/[projectId] (workspace — org-scoped routing)
  ├── Layout: 12-tab IDE workspace shell
  │
  ├── Sidebar (always visible):
  │   ├── ← Back to Org
  │   ├── Project name
  │   ├── Navigation links:
  │   │   ├── Chat (default view)
  │   │   ├── Preview
  │   │   ├── Code
  │   │   ├── Design (Agentic React Builder)
  │   │   ├── Data Models
  │   │   ├── Workflows
  │   │   ├── Rules
  │   │   ├── Navigation
  │   │   ├── Access Control (field/record RBAC for this app)
  │   │   ├── Agents
  │   │   ├── Database
  │   │   └── Settings
  │   └── Module list (collapsible)
  │
  ├── Content area (changes based on active tab):
  │   ├── /projects/[id]             → Chat panel (full width)
  │   ├── /projects/[id]/preview     → PreviewFrame + RefineBar
  │   ├── /projects/[id]/code        → FileTree + Monaco Editor
  │   ├── /projects/[id]/ui-editor   → Canvas + ComponentTree + Properties
  │   ├── /projects/[id]/data        → ERD canvas + field editor
  │   ├── /projects/[id]/workflows   → Workflow canvas + node properties
  │   ├── /projects/[id]/rules       → Rules table + rule forms
  │   ├── /projects/[id]/navigation  → Screen flow canvas + nav config
  │   ├── /projects/[id]/access      → Field access matrix + record scope rules
  │   ├── /projects/[id]/agents      → Agent Builder canvas + test console
  │   ├── /projects/[id]/database    → DataBrowser + SQL console
  │   └── /projects/[id]/settings    → Project settings
  │
  └── Bottom bar (always visible):
      └── Quick refine input (type to change, applies in current context)
```

### 7.2 Chat Page Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ┌─ Sidebar ─┐  ┌─ Chat ──────────────────────────────────────────────┐ │
│ │            │  │                                                     │ │
│ │ 💬 Chat    │  │  ┌─────────────────────────────────────────────┐   │ │
│ │ 👁 Preview │  │  │ User: Build me a task management app with  │   │ │
│ │ 📝 Code    │  │  │       teams and deadline tracking           │   │ │
│ │ 🎨 UI      │  │  └─────────────────────────────────────────────┘   │ │
│ │ 📊 Data    │  │                                                     │ │
│ │ ⚡ Flows   │  │  ┌─────────────────────────────────────────────┐   │ │
│ │ 📏 Rules   │  │  │ Assistant: I'll create a Task Management    │   │ │
│ │ 🗺 Nav     │  │  │ module. A few questions:                     │   │ │
│ │ 💾 DB      │  │  │                                              │   │ │
│ │ ⚙ Settings│  │  │ 1. Do you need user auth with roles?        │   │ │
│ │            │  │  │ 2. Should tasks have subtasks?               │   │ │
│ │ ── Modules │  │  │ 3. Do you need file attachments on tasks?   │   │ │
│ │ ▸ Core     │  │  └─────────────────────────────────────────────┘   │ │
│ │ ▸ Tasks    │  │                                                     │ │
│ │ + Add      │  │  ┌─────────────────────────────────────────────┐   │ │
│ │            │  │  │ User: Yes to auth, no subtasks, yes to      │   │ │
│ │            │  │  │       file attachments                       │   │ │
│ │            │  │  └─────────────────────────────────────────────┘   │ │
│ │            │  │                                                     │ │
│ │            │  │  ┌─ Plan Approval Card ────────────────────────┐   │ │
│ │            │  │  │ 📋 Task Management Module                    │   │ │
│ │            │  │  │                                              │   │ │
│ │            │  │  │ Data Models: User, Team, Task, Attachment   │   │ │
│ │            │  │  │ Pages: 6 (dashboard, list, detail, ...)     │   │ │
│ │            │  │  │ API Routes: 12 endpoints                     │   │ │
│ │            │  │  │ Workflows: 3 (overdue, assignment, digest)  │   │ │
│ │            │  │  │                                              │   │ │
│ │            │  │  │ [View Full Plan]  [Approve ✓]  [Edit ✏]    │   │ │
│ │            │  │  └──────────────────────────────────────────────┘   │ │
│ │            │  │                                                     │ │
│ │            │  │  ┌──────────────────────────────────────────────┐  │ │
│ │            │  │  │ 💬 Type a message...                  [Send] │  │ │
│ │            │  │  └──────────────────────────────────────────────┘  │ │
│ └────────────┘  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.3 Preview Page Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ┌─ Sidebar ─┐  ┌─ Preview ───────────────────────────────────────────┐ │
│ │            │  │  ┌─ Toolbar ─────────────────────────────────────┐  │ │
│ │            │  │  │ [Desktop] [Tablet] [Mobile]    [↻ Refresh]   │  │ │
│ │            │  │  └───────────────────────────────────────────────┘  │ │
│ │            │  │                                                     │ │
│ │            │  │  ┌──────────────────────────────────────────────┐  │ │
│ │            │  │  │                                              │  │ │
│ │            │  │  │              iframe                          │  │ │
│ │            │  │  │              (generated app)                 │  │ │
│ │            │  │  │                                              │  │ │
│ │            │  │  │                                              │  │ │
│ │            │  │  │                                              │  │ │
│ │            │  │  │                                              │  │ │
│ │            │  │  └──────────────────────────────────────────────┘  │ │
│ │            │  │                                                     │ │
│ │            │  │  ┌─ Refinement Log (collapsible) ───────────────┐  │ │
│ │            │  │  │ ▸ 3 events                          [▾ Hide] │  │ │
│ │            │  │  └──────────────────────────────────────────────┘  │ │
│ │            │  │                                                     │ │
│ │            │  │  ┌──────────────────────────────────────────────┐  │ │
│ │            │  │  │ "make the sidebar darker"       [Send] [↻]  │  │ │
│ │            │  │  └──────────────────────────────────────────────┘  │ │
│ └────────────┘  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 8. Visual Editors

### 8.1 Instruction Builder

Every visual editor action is converted to a text instruction. This is the core abstraction.

```typescript
// frontend/src/lib/instruction.ts

export type EditorAction =
  | UIEditorAction
  | DataEditorAction
  | WorkflowEditorAction
  | RulesEditorAction
  | NavigationEditorAction
  | AgentEditorAction;

// --- UI Editor Actions ---

interface UIChangeStyle {
  editor: "ui";
  action: "change_style";
  component: string;        // "TaskCard"
  file: string;             // "src/components/TaskCard.tsx"
  element: string;          // "container" | "title" | "badge"
  property: string;         // "backgroundColor" | "padding" | "borderRadius"
  oldValue: string;
  newValue: string;
}

interface UIAddComponent {
  editor: "ui";
  action: "add_component";
  targetPage: string;       // "src/app/tasks/page.tsx"
  componentType: string;    // "Button" | "Table" | "Chart" | "Form"
  position: string;         // "after:TaskList" | "inside:Header" | "end"
  props?: Record<string, unknown>;
}

interface UIRemoveComponent {
  editor: "ui";
  action: "remove_component";
  component: string;
  file: string;
}

interface UIBindModel {
  editor: "ui";
  action: "bind_model";
  component: string;
  model: string;
  fieldMappings: Array<{
    field: string;
    displayAs: string;       // "text" | "badge" | "avatar" | "date" | "input"
    config?: Record<string, unknown>;
  }>;
}

// --- Data Editor Actions ---

interface DataAddModel {
  editor: "data";
  action: "add_model";
  name: string;
  fields: Array<{
    name: string;
    type: string;
    constraints: string[];
  }>;
}

interface DataAddField {
  editor: "data";
  action: "add_field";
  model: string;
  field: {
    name: string;
    type: string;
    constraints: string[];
  };
  updateUI: boolean;        // whether to also update bound components
}

interface DataRemoveField {
  editor: "data";
  action: "remove_field";
  model: string;
  fieldName: string;
}

interface DataAddRelation {
  editor: "data";
  action: "add_relation";
  from: string;             // "SalesOrder"
  to: string;               // "Customer"
  type: string;             // "many-to-one" | "one-to-many" | "many-to-many"
  fieldName: string;        // "customerId"
  onDelete: string;         // "cascade" | "set_null" | "restrict"
}

// --- Workflow Editor Actions ---

interface WorkflowAddNode {
  editor: "workflow";
  action: "add_node";
  workflowId: string;
  nodeType: "trigger" | "action" | "condition" | "wait";
  config: Record<string, unknown>;
  connectAfter?: string;    // node ID to connect after
}

interface WorkflowRemoveNode {
  editor: "workflow";
  action: "remove_node";
  workflowId: string;
  nodeId: string;
}

interface WorkflowUpdateNode {
  editor: "workflow";
  action: "update_node";
  workflowId: string;
  nodeId: string;
  changes: Record<string, unknown>;
}

interface WorkflowConnect {
  editor: "workflow";
  action: "connect";
  workflowId: string;
  fromNodeId: string;
  toNodeId: string;
  edgeType?: "then" | "else" | "error";
}

// --- Build instruction from action ---

export function buildInstruction(action: EditorAction): string {
  switch (action.editor) {
    case "ui":
      return buildUIInstruction(action);
    case "data":
      return buildDataInstruction(action);
    case "workflow":
      return buildWorkflowInstruction(action);
    case "rules":
      return buildRulesInstruction(action);
    case "navigation":
      return buildNavInstruction(action);
    case "agent":
      return buildAgentInstruction(action);
  }
}

function buildDataInstruction(action: DataEditorAction): string {
  switch (action.action) {
    case "add_field": {
      const constraints = action.field.constraints.join(", ");
      let instruction = `Add a '${action.field.name}' field of type ${action.field.type} to the ${action.model} model.`;
      if (constraints) instruction += ` Constraints: ${constraints}.`;
      instruction += ` Update the database schema in src/infrastructure/db/schema.ts.`;
      instruction += ` Update the API routes to accept and return this field.`;
      if (action.updateUI) {
        instruction += ` Update any components bound to ${action.model} to display/input this field.`;
      }
      instruction += ` Update the seed data to include values for this field.`;
      return instruction;
    }
    case "remove_field": {
      return `Remove the '${action.fieldName}' field from the ${action.model} model. ` +
        `Remove it from the database schema, API routes, and all components that reference it. ` +
        `Do NOT drop the column from the database — just stop using it in code.`;
    }
    // ... more cases
  }
}
```

### 8.2 UI Editor

**Library: GrapesJS (open-source, BSD 3-Clause) + @grapesjs/react**

GrapesJS provides a battle-tested drag-and-drop editor with built-in Style Manager, Layer Manager,
Device Manager, Undo/Redo, and Block Manager. We use `@grapesjs/react` with `<Canvas/>` to
**disable all default UI** and render our own panels with shadcn/ui — fully white-labeled.

```
The UI editor does NOT directly edit source code.
It renders a representation of the generated page components.
When the user makes a change, it produces an instruction → LLM edits the real code.

Workflow:
1. Read AppModel index → know what pages and components exist
2. Read the actual source files → parse props, className, children
3. Register custom GrapesJS component types matching our component library
4. Render an editable representation in GrapesJS canvas (iframe-isolated)
5. User makes changes (drag, resize, edit properties, style)
6. On change commit → build instruction → send to Refiner
7. LLM edits source code → hot reload → UI editor re-reads and refreshes
```

#### White-Label Architecture

```tsx
// EditorShell.tsx — all default GrapesJS UI disabled
import GjsEditor, { Canvas } from '@grapesjs/react';
import grapesjs from 'grapesjs';

export function EditorShell({ page, onInstruction }) {
  return (
    <GjsEditor
      grapesjs={grapesjs}
      options={{
        storageManager: false,
        canvas: {
          styles: ['/generated-app-styles.css'],  // Tailwind in canvas
        },
        plugins: [tentoroForgeBlocks, tentoroForgeComponents, formComponents, tailwindIntegration],
      }}
      onEditor={(editor) => initEditor(editor, page)}
    >
      {/* ALL default GrapesJS UI is hidden — we render our own */}
      <div className="flex h-full">
        <ComponentPalette />           {/* Our shadcn/ui blocks sidebar */}
        <div className="flex-1 flex flex-col">
          <EditorToolbar />            {/* Our undo/redo/device/preview bar */}
          <Canvas className="flex-1" /> {/* Only GrapesJS-rendered element */}
        </div>
        <div className="w-[320px] border-l flex flex-col">
          <LayerPanel />               {/* Our component tree */}
          <PropertiesPanel />          {/* Our trait/props editor */}
          <StylePanel />               {/* Our style manager */}
        </div>
      </div>
    </GjsEditor>
  );
}
```

#### Component Palette (blocks)

All panels are our own React components using shadcn/ui, communicating with GrapesJS via `useEditor()`.

```
Component Palette (left sidebar, our shadcn/ui, not GrapesJS default)
├── Layout
│   ├── Container, Grid (2/3/4 col), Stack, Flex Row
│   ├── Card, Section, Divider, Spacer
│   ├── Tabs, Accordion, Collapsible
│   └── Sidebar Layout, Header/Footer
├── Display
│   ├── Heading (h1-h6), Text, Paragraph, Prose
│   ├── Image, Avatar, Icon, Badge, Tag
│   ├── Alert, Callout, Toast placeholder
│   ├── Table, DataTable (with sorting/filtering/pagination)
│   ├── List, DescriptionList, Timeline
│   └── Chart (bar, line, pie, area), Stat Card, Progress
├── Form
│   ├── TextInput, TextArea, RichTextEditor
│   ├── Select, MultiSelect, Combobox, AsyncSelect
│   ├── DatePicker, TimePicker, DateRangePicker
│   ├── Checkbox, CheckboxGroup, RadioGroup
│   ├── Switch, Toggle, ToggleGroup
│   ├── NumberInput, Slider, Rating
│   ├── FileUpload, ImageUpload, Dropzone
│   ├── ColorPicker, TagInput, PhoneInput
│   ├── EmailInput, URLInput, PasswordInput
│   ├── Signature, CodeEditor
│   ├── FormGroup (label + input + error + description)
│   ├── FormStepper (multi-step wizard wrapper)
│   └── SubmitButton (bind to API route or workflow)
├── Navigation
│   ├── Button, LinkButton, IconButton
│   ├── Breadcrumb, Pagination, Stepper
│   ├── Navbar, Sidebar Menu, Dropdown Menu
│   └── Tabs Navigation, Command Palette
├── Data
│   ├── KanbanBoard, Calendar, Gantt (read-only)
│   ├── DataGrid (inline editable), TreeView
│   └── EmptyState, LoadingSkeleton, ErrorBoundary
└── AI (when AI features are enabled)
    ├── SmartFormField (AI-assisted input)
    ├── NaturalLanguageQuery (text → SQL)
    ├── SmartFilterBar (natural language filters)
    ├── DataInsightsPanel (auto-generated insights)
    └── ChatWidget (embedded agent chat)
```

Each block is registered as a GrapesJS custom component type with:
- Editor-specific view (how it looks on canvas — may differ from production)
- Traits (editable properties shown in Properties Panel)
- Drag rules (where it can be dropped, what can be dropped inside)

#### Custom Component Types

```javascript
// grapes-plugins/tentoroforge-components.ts

export default function tentoroForgeComponents(editor) {
  // Example: DataTable component type
  editor.Components.addType('tentoroforge-datatable', {
    isComponent: (el) => el.dataset?.component === 'DataTable',
    model: {
      defaults: {
        tagName: 'div',
        attributes: { 'data-component': 'DataTable' },
        droppable: false,
        traits: [
          { type: 'select', name: 'model', label: 'Data Model',
            options: [] },  // populated dynamically from AppModel
          { type: 'text', name: 'columns', label: 'Visible Columns' },
          { type: 'checkbox', name: 'sortable', label: 'Sortable' },
          { type: 'checkbox', name: 'filterable', label: 'Filterable' },
          { type: 'checkbox', name: 'pagination', label: 'Pagination' },
          { type: 'number', name: 'pageSize', label: 'Page Size' },
          { type: 'checkbox', name: 'inlineEdit', label: 'Inline Editing' },
        ],
      },
    },
    view: {
      onRender({ el, model }) {
        // Render a rich preview on canvas (placeholder with column headers)
        const modelName = model.get('attributes')['data-model'] || 'Items';
        el.innerHTML = `
          <div class="border rounded-lg overflow-hidden">
            <div class="bg-gray-50 px-4 py-2 font-semibold text-sm">${modelName}</div>
            <table class="w-full text-sm">
              <thead><tr class="bg-gray-100">
                <th class="px-3 py-2 text-left">Name</th>
                <th class="px-3 py-2 text-left">Status</th>
                <th class="px-3 py-2 text-left">Date</th>
              </tr></thead>
              <tbody>
                <tr class="border-t"><td class="px-3 py-2">Sample row 1</td>
                  <td class="px-3 py-2">Active</td><td class="px-3 py-2">2024-01-01</td></tr>
                <tr class="border-t"><td class="px-3 py-2">Sample row 2</td>
                  <td class="px-3 py-2">Draft</td><td class="px-3 py-2">2024-01-02</td></tr>
              </tbody>
            </table>
            <div class="bg-gray-50 px-4 py-2 text-xs text-gray-500">Showing 2 of 2</div>
          </div>`;
      },
    },
  });
}
```

#### Built-in Features We Get Free

```
From GrapesJS (no custom code needed):
├── Style Manager         — visual CSS editor with 50+ properties, per-breakpoint
├── Layer Manager          — component tree with nesting, visibility toggle, reorder
├── Device Manager         — desktop / tablet / mobile preview with media queries
├── Undo/Redo Manager      — full action history, Ctrl+Z / Ctrl+Shift+Z
├── Block Manager          — drag blocks from palette to canvas
├── Selector Manager       — CSS class management
├── Asset Manager           — image upload/selection
├── Canvas selection       — click to select, hover highlights, resize handles
├── Copy/paste/duplicate   — keyboard shortcuts
├── Canvas iframe           — style isolation (generated app CSS doesn't leak)
└── Storage Manager         — save/load project state (we override with our own)

We only build the UI chrome (panels, toolbars) using shadcn/ui + useEditor() hook.
```

### 8.2.1 Agentic React Builder (Design Tab — Visual Page Builder)

The Design tab has been transformed from a single-column point-and-edit tool into a **3-panel visual page builder** where AI agents are the core building engine. Unlike GrapesJS-based JSON-data builders, TSX source code remains the source of truth. The builder uses AST parsing for structure, direct edits for speed, and AI agents for generative work.

#### Architecture

- **Source-code-first**: TSX files are the source of truth, versioned with git
- **Bridge-driven outline**: `bridge.js` sends full DOM trees via `sendTree()` — the parent listens for `tree` messages and transforms them into a section outline
- **AST for structure**: Babel-based parsing (same tools as source annotation) extracts page sections and element props
- **Agents for generation**: The existing `code_editor` (15 turns) and `refiner` (30 turns) agents handle all generative tasks
- **Native drag**: HTML5 drag events for section reordering — no DnD library needed

#### 3-Panel Layout

```
┌──────────────────────────────────────────────────────────────────┐
│ Toolbar: [←] [◧] [↩] [Route ▾]              [💻 📱 📲] [◨] │
├──────────┬───────────────────────────────────┬───────────────────┤
│ Page     │                                   │ Properties        │
│ Outline  │         Canvas (iframe)           │                   │
│          │                                   │ Element Info      │
│ <header> │                                   │ Tailwind Classes  │
│ <main>   │                                   │ Props             │
│   <Hero> │                                   │ Actions           │
│   <Feat> │                                   │                   │
│          │                                   │                   │
│ [+ Add]  ├───────────────────────────────────┤                   │
│          │ [suggestions] AI Input [Send]     │                   │
├──────────┴───────────────────────────────────┴───────────────────┘
```

- Left panel (260px, collapsible): Section Outline — tree view of page sections parsed from bridge DOM tree
- Center: Canvas iframe + AI input bar with suggestion chips
- Right panel (280px, collapsible): Context panel showing selected element properties, Tailwind class chips, actions

#### Frontend Files

```
frontend/src/
├── components/visual-editor/
│   ├── VisualEditor.tsx              # 3-panel layout, panel toggle buttons
│   ├── CanvasFrame.tsx               # iframe with scrollTo/highlight methods
│   ├── SectionOutlinePanel.tsx       # Left sidebar: tree view, drag reorder, + Add Section
│   ├── ContextPanel.tsx              # Right sidebar: element info, class chips, props, actions
│   ├── ComponentPalette.tsx          # Sheet drawer: section template browser + custom prompt
│   ├── AIEditInput.tsx               # AI input with context-aware suggestion chips
│   ├── ElementActionPopover.tsx      # Floating popover on selected element
│   └── QuickStylePopover.tsx         # Quick Tailwind style editor
├── hooks/
│   ├── useBridge.ts                  # Bridge messaging + tree handler + requestTree
│   ├── useVisualEdit.ts             # Direct/AI edits + reorderSection
│   └── useAddSection.ts             # SSE hook for AI section generation
├── stores/
│   └── visual-editor.ts             # Zustand: panel state, sectionTree, selectedSectionId
├── types/
│   └── visual-editor.ts             # ElementInfo, SectionNode, DeviceSize
└── lib/
    ├── section-tree-utils.ts         # transformBridgeTree(), findSectionByXPath()
    └── ai-suggestion-utils.ts        # getSuggestions() — tag-based chip mapping
```

#### Backend Files

```
backend/
├── routers/
│   └── visual_editor.py              # All visual editor endpoints (12 total)
├── schemas/
│   └── visual_edit.py                # TailwindEdit, TextEdit, PropEdit, AddSectionRequest, ReorderSectionRequest
├── services/
│   ├── visual_edit_service.py        # apply_tailwind_edit, apply_text_edit, apply_prop_edit
│   ├── component_extractor.py        # Extract enclosing React component for scoped AI edits
│   ├── page_section_parser.py        # Route → page file → AST section tree
│   ├── element_props_extractor.py    # JSX attribute extraction for props panel
│   ├── section_templates.py          # 15 section templates across 12 categories
│   ├── section_instruction_builder.py # Build prompts for code_editor agent
│   ├── section_reorder_service.py    # AST-first + line-based fallback section reorder
│   ├── bridge_injector.py            # Inject/remove bridge.js into Next.js app
│   └── source_annotator.py           # AST annotation of data-source-* attributes
└── static/
    ├── bridge.js                      # In-iframe bridge: overlays, events, DOM tree
    ├── annotate-source.mjs           # Babel: add/strip data-source-* attributes
    ├── parse-sections.mjs            # Babel: extract top-level JSX sections
    └── reorder-section.mjs           # Babel: AST-level section reorder
```

#### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/projects/:id/bridge/inject` | Inject bridge.js + annotate source |
| POST | `/api/projects/:id/bridge/remove` | Remove bridge.js + strip annotations |
| POST | `/api/projects/:id/visual-edit` | Direct Tailwind/text/prop edits |
| POST | `/api/projects/:id/visual-edit/undo` | Revert last visual commit |
| GET | `/api/projects/:id/visual-edit/history` | Recent git log entries |
| POST | `/api/projects/:id/visual-edit/ai` | AI-mediated edit (SSE stream) |
| GET | `/api/projects/:id/visual-edit/page-sections` | AST-parsed section data for route |
| GET | `/api/projects/:id/visual-edit/element-props` | JSX element props at file:line |
| GET | `/api/projects/:id/visual-edit/section-templates` | Section template catalog |
| POST | `/api/projects/:id/visual-edit/add-section` | Generate + insert section (SSE stream) |
| POST | `/api/projects/:id/visual-edit/reorder-section` | Move section before/after another |

#### Section Templates (15)

Categories: `hero`, `features`, `pricing`, `testimonials`, `cta`, `footer`, `stats`, `faq`, `team`, `contact`, `content`, `gallery`

Each template provides a `prompt_template` used by the `section_instruction_builder` to construct a detailed instruction for the `code_editor` agent.

#### Key Interactions

1. **Section Outline**: Bridge sends `tree` messages → `transformBridgeTree()` → `SectionNode[]` in store → rendered as collapsible tree with expand/collapse, icons per tag type
2. **Element Selection**: Click in canvas → bridge sends `select` → element info in store → right panel shows props/classes/actions
3. **Tailwind Class Editing**: Class chips in right panel — click X to remove, type to add → `directEdit({ tailwind_edits })` → git commit → HMR reload
4. **AI Suggestions**: Tag-based suggestion chips above AI input — clicking submits immediately (e.g., "Change color" for buttons, "Add more content" for sections)
5. **Add Section**: "+ Add Section" button → ComponentPalette sheet → pick template or write custom prompt → SSE streaming via `code_editor` agent → git commit → reload
6. **Section Reorder**: HTML5 drag-and-drop on root-level outline items → `reorder-section.mjs` (Babel AST) or line-based fallback → git commit → reload

### 8.3 Data Model Editor

**Library: React Flow**

```
Nodes: Entity cards showing model name + fields
Edges: Relationship lines (one-to-many, many-to-many)
Interactions:
  - Click entity → expand field list → edit fields
  - Click "+ Add Model" → new entity card appears
  - Drag from entity to entity → create relationship
  - Click field → edit type, constraints, default
  - Right-click entity → delete (with impact analysis)
  - Click "Seed" tab → edit seed data in table format
```

### 8.4 Workflow Editor

**Library: React Flow**

```
Node types:
  - TriggerNode (green, lightning icon): API event, schedule, DB change, webhook, manual
  - ActionNode (blue, play icon): DB query, HTTP call, email, notification, custom function
  - ConditionNode (yellow, branch icon): if/else based on expression
  - DecisionNode (purple, table icon): decision table with multi-row rules and hit policies
  - WaitNode (gray, clock icon): delay, wait for event
  - EndNode (red, stop icon): terminate workflow
  - AssignmentNode (teal, user-plus icon): assign task to user/role/manager/dept/group
  - ApprovalNode (green, check-circle icon): single/sequential/parallel approval
  - TaskPoolNode (blue, users icon): assign to pool, claim or round-robin
  - EscalationNode (red, arrow-up icon): escalate on SLA breach or condition

Edge types:
  - Default (solid line): normal flow
  - Then (green dashed): condition true path
  - Else (red dashed): condition false path
  - Error (orange dotted): error handler path

Variable system:
  - Trigger outputs are available as {{trigger.fieldName}}
  - Each action's output is available as {{stepId.fieldName}}
  - Decision node outputs are available as {{stepId.outputColumnName}}
  - Properties panel shows autocomplete for available variables
  - Variables are resolved from the AppModel data models

DecisionNode behavior:
  - Collapsed view on canvas shows: rule count, hit policy badge, input/output column names
  - Click to expand inline decision table editor in properties panel
  - Decision output variables are written to workflow context
  - Downstream gateways/conditions can route on decision outputs
  - Can replace simple condition nodes when logic requires multiple rules
```

### 8.5 Rules & Decision Editor

```
Main view: Filterable table of all rules and decisions
  Columns: Name | Type | Attached To | Condition/Rules | Enforce At
  Filters: by type, by model, by enforcement layer
  Tabs: Rules | Decision Tables | All

Rule forms (one per type):
  - Validation: model, field, condition builder, error message, enforce checkboxes
  - Access Control: model, action, role table (role → allow/deny + condition)
  - Business: model, action, condition, consequence
  - Computed: model, field, expression
  - State Machine: model, field, states list, transition diagram (React Flow)
  - Trigger: model, field, condition, action description

Condition Builder (enhanced):
  Two modes — visual form builder and raw expression editor, togglable.

  No-code mode (default):
    - Field picker: dropdown of available workflow/model variables with type info
    - Operator picker: context-aware based on field type
      (string → contains/starts with, number → range/comparison, date → before/after)
    - Value input: type-appropriate (number slider, date picker, enum dropdown, text)
    - AND/OR group nesting with drag-and-drop
    - Generated expression preview shown below the builder

  Expression mode:
    FEEL-lite expression language with autocomplete:
      Comparisons:    > 100, >= 50, < 10, <= 0, = "active"
      Ranges:         [18..65] (inclusive), (0..100) (exclusive), [1000..5000)
      Lists:          "gold", "platinum" (match any)
      Negation:       not("cancelled", "rejected"), not([0..18])
      Null checks:    null, not(null)
      String ops:     starts with "PRE-", ends with "@co.com", contains "urgent"
      Regex:          matches "^[A-Z]{2}\\d{4}$"
      Arithmetic:     order.total * 0.15, base + tax
      Conditional:    if score > 80 then "fast" else "standard"
      Date/duration:  < date("2026-06-01"), > now() - duration("P30D")
      Empty cell:     matches everything (wildcard)

  Mockup (no-code mode):
    ┌─ Rule Builder ──────────────────────────────────────────────┐
    │  IF  ┌─ ALL of ──────────────────────────────────────────┐  │
    │      │ [customer.tier ▼] [is one of ▼] [gold, platinum]  │  │
    │      │ AND                                                │  │
    │      │ ┌─ ANY of ────────────────────────────────────┐   │  │
    │      │ │ [order.total ▼] [greater than ▼] [500]      │   │  │
    │      │ │ OR                                           │   │  │
    │      │ │ [order.items ▼] [greater than ▼] [10]       │   │  │
    │      │ └──────────────────────────────────────────────┘   │  │
    │      └────────────────────────────────────────────────────┘  │
    │                                                              │
    │  THEN  discount = [15] %                                     │
    │                                                              │
    │  Expression: customer.tier in ("gold","platinum")            │
    │              and (order.total > 500 or order.items > 10)     │
    │                                                              │
    │  [+ Add Condition]  [+ Add Group]  [Toggle Expression Mode]  │
    └──────────────────────────────────────────────────────────────┘

Decision Table Editor:
  Spreadsheet-like grid for multi-rule decisions. Used in standalone rules
  and embedded in workflow decision nodes.

  Structure:
    - Input columns: each bound to a workflow variable or model field
    - Output columns: one or more result columns (category, score, team, etc.)
    - Rows: each row is a rule — if all input cells match → produce output
    - Hit policy selector: dropdown at top-left corner

  Hit Policies:
    U (Unique)     — exactly one row matches, error if ambiguous
    F (First)      — first matching row wins (order matters)
    A (Any)        — multiple matches OK if all give same output
    P (Priority)   — highest-priority matching output wins
    C (Collect)    — return all matching outputs as list (sum/min/max/count)
    R (Rule Order) — return all matches in table order

  Interactions:
    - Drag to reorder rows (for First/Priority hit policies)
    - Add/remove rows and columns via toolbar buttons
    - Click cell to edit with expression autocomplete
    - Right-click column header → set type, rename, delete
    - Column header dropdown → bind to workflow variable or model field
    - Copy/paste rows (including from spreadsheet apps)
    - Empty cell = wildcard (matches any value)

  Mockup:
    ┌─ Hit Policy: [First ▼] ──────────────────────────────────────┐
    │                                                                │
    │  #  │ customer.tier │ order.total │ → discount │ → note       │
    │ ────┼───────────────┼─────────────┼────────────┼──────────────│
    │  1  │ "platinum"    │     -       │    20%     │ VIP          │
    │  2  │ "gold"        │  > 500      │    15%     │              │
    │  3  │ "gold"        │  <= 500     │    10%     │              │
    │  4  │     -         │  > 1000     │    10%     │ bulk         │
    │  5  │     -         │     -       │     0%     │ default      │
    │                                                                │
    │  [+ Add Row]  [+ Add Input Column]  [+ Add Output Column]     │
    └────────────────────────────────────────────────────────────────┘

Decision Graph (DRD — Decision Requirements Diagram):
  Mini React Flow canvas for chaining multiple decisions together.
  Used when a single decision table is not sufficient.

    Node types:
      - InputDataNode (oval): maps to workflow variable or external data
      - DecisionNode (rectangle): contains a decision table or expression
      - KnowledgeSourceNode (wavy): links to policy docs (metadata only)

    Edges: dependency arrows (input data → decision, decision → decision)

    Mockup:
      ┌──────────┐     ┌──────────────┐     ┌──────────────┐
      │ customer │────▶│ Credit Score  │────▶│  Loan        │
      │ data     │     │ Assessment    │     │  Decision    │──▶ outputs
      └──────────┘     └──────────────┘     └──────────────┘
                              ▲                     ▲
      ┌──────────┐           │              ┌──────────────┐
      │ loan     │───────────┘              │ Risk Tier    │
      │ request  │─────────────────────────▶│ Calculation  │
      └──────────┘                          └──────────────┘

    Each DecisionNode in the DRD opens its own decision table editor.
    Outputs of upstream decisions are available as inputs to downstream ones.

Decision Test Panel:
  Inline testing for decision tables, accessible from the editor toolbar.

    ┌─ Decision Tester ────────────────────────────────────────────┐
    │  Inputs:                                                      │
    │    customer.tier:  [gold     ▼]                               │
    │    order.total:    [750       ]                               │
    │                                                               │
    │  [▶ Evaluate]                                                 │
    │                                                               │
    │  Result:  ✓ Row 2 matched                                     │
    │    discount: 15%                                              │
    │    note: (empty)                                              │
    │                                                               │
    │  ─────────────────────────────────────────                    │
    │  Saved Test Cases:                  [+ Add Current as Test]   │
    │    ✓ Test 1: platinum VIP             → 20%                   │
    │    ✓ Test 2: gold large order         → 15%                   │
    │    ✗ Test 3: silver small order       → expected 0%, got 5%   │
    │                                                               │
    │  Coverage: 4/5 rows hit  (Row 4 untested)                     │
    └───────────────────────────────────────────────────────────────┘

  Features:
    - Enter input values, see which row matches and output produced
    - Save test cases with expected outputs for regression testing
    - Batch run all saved tests, show pass/fail summary
    - Coverage indicator: highlight rows never hit by any test case
    - Boundary testing: auto-suggest edge-case inputs from range expressions
    - Trace view: for DRDs, show evaluation path through chained decisions

Decision Validation & Analysis:
  Static analysis overlays shown inline in the decision table editor.

    - Completeness check: detect input combinations not covered by any row
    - Overlap detection: find rows where same inputs match multiple rules
      (error for Unique hit policy, warning for others)
    - Subsumption check: find rows completely shadowed by earlier rows (dead rules)
    - Type checking: verify expressions are type-compatible with bound variable
    - Gap highlighting: yellow cells indicating missing coverage
    - Conflict highlighting: red cells indicating overlapping conditions

Rule Templates:
  Pre-built decision table patterns users can drop in and configure.

    - Score Card: weighted inputs → sum → threshold → outcome
    - Eligibility Check: all conditions must pass (AND-table)
    - Tier / Classification: input ranges → category label
    - Routing Matrix: input combinations → team/queue assignment
    - Discount Ladder: ordered rules → discount percentage
    - Validation Rule Set: each row = one validation, collect all failures
    - Priority Matrix: impact × urgency → priority level
```

### 8.6 Navigation Editor

**Library: React Flow**

```
Nodes: Screen/page cards showing route + thumbnail
Edges: Navigation links (click → navigate, button → navigate)
Interactions:
  - Drag screens to organize visual layout
  - Draw edges between screens to define navigation
  - Click screen → edit route, layout, access rules
  - Configure sidebar/navbar menu items and ordering
  - Set which screen is the default/home
  - Configure 404 and error pages
```

### 8.7 Org Chart Editor

**Library: React Flow** (at the org level, not project level)

```
Nodes:
  - DepartmentNode (blue rectangle): name, head, employee count
  - TeamNode (blue rounded): name, lead, member count
  - PersonNode (avatar card): name, title, email, role badges

Edges:
  - Reporting lines (solid): manager → report hierarchy
  - Department membership (dashed): team belongs to department

Interactions:
  - Drag person between departments/teams → updates org structure
  - Click person → edit title, role, manager, department
  - Right-click department → add sub-department, add team, delete
  - Click "+ Add Person" → manual entry form
  - Import button → CSV/JSON upload with column mapping
  - Filter: by department, by role, search by name
  - View toggle: tree view | flat list | matrix view
  - Collapse/expand departments
```

### 8.8 Field Access Editor

```
Located in project workspace under "Access Control" tab.
Shows a matrix of models × roles with field-level permissions.

┌─ Access Matrix: Product ──────────────────────────────────┐
│                                                            │
│ Field          │ staff    │ manager  │ finance  │ admin    │
│ ───────────────┼──────────┼──────────┼──────────┼──────── │
│ name           │ 👁 ✎    │ 👁 ✎    │ 👁 ✎    │ 👁 ✎   │
│ sku            │ 👁       │ 👁 ✎    │ 👁       │ 👁 ✎   │
│ description    │ 👁       │ 👁 ✎    │ 👁       │ 👁 ✎   │
│ unitPrice      │ 👁       │ 👁 ✎    │ 👁 ✎    │ 👁 ✎   │
│ unitCost       │ ──       │ ──       │ 👁 ✎    │ 👁 ✎   │
│ margin         │ ──       │ 👁       │ 👁       │ 👁      │
│ supplierNotes  │ ──       │ ──       │ 👁       │ 👁 ✎   │
│                                                            │
│ 👁 = can view   ✎ = can edit   ── = hidden                │
│                                                            │
│ Model: [Product ▾]   [Save Changes]                       │
└────────────────────────────────────────────────────────────┘

Record Scope Rules (below the matrix):
┌─ Record Scoping ──────────────────────────────────────────┐
│ Rule: staff sees only records from their own department    │
│       manager sees records from their dept + sub-depts    │
│       finance sees all records                             │
│       admin sees all records                               │
│                                                            │
│ Scope column: [department_id ▾]                           │
│ Scope source: [user's department from org structure]      │
│                                                            │
│ [+ Add scope rule]                                        │
└────────────────────────────────────────────────────────────┘

Instruction generated on save:
  "Update the Product model's API routes to enforce field-level access:
   hide unitCost and margin from staff role, hide supplierNotes from
   non-admin roles. Add department-based record scoping: staff sees
   only their department's products, managers see their department
   and sub-departments."
```

---

## 9. Generated App Structure

### 9.1 Standard Structure (every generated app follows this)

Generated apps follow **Clean Architecture** with strict layer separation:
- **Domain** — pure business logic, zero framework dependencies
- **Application** — use cases / services that orchestrate domain + infrastructure
- **Infrastructure** — external concerns (DB, email, AI, auth)
- **API** — thin HTTP handlers that delegate to services
- **Components** — presentation only, no business logic

Import direction: `domain ← application ← infrastructure`, `api → application`, `components → types`

```
{project_id}/
├── docker-compose.yml
├── .env
├── .env.example
├── .gitignore
├── package.json
├── tsconfig.json
├── next.config.ts
├── postcss.config.mjs
├── drizzle.config.ts
├── app-model.json              ← AppModel index (maintained by Indexer agent)
│
├── src/
│   ├── domain/                 ← Pure business logic (no frameworks, no DB, no HTTP)
│   │   └── {module}/
│   │       ├── entities.ts     ← TypeScript types + domain constants
│   │       ├── rules.ts        ← Business rules (validation, computation, state machines)
│   │       └── errors.ts       ← Domain-specific error classes
│   │
│   ├── application/            ← Use cases / services (orchestrates domain + infra)
│   │   └── {module}/
│   │       ├── {resource}.service.ts  ← CRUD + business operations
│   │       ├── {resource}.schema.ts   ← Zod schemas for input validation
│   │       └── {workflow}.handler.ts  ← Workflow action handlers
│   │
│   ├── infrastructure/         ← External concerns (DB, email, AI, external APIs)
│   │   ├── db/
│   │   │   ├── schema.ts       ← All table definitions (Drizzle pgTable)
│   │   │   ├── connection.ts   ← Pool + drizzle instance
│   │   │   ├── seed.ts         ← Seed data script
│   │   │   └── repositories/
│   │   │       └── {resource}.repository.ts ← DB queries (Drizzle)
│   │   ├── auth/
│   │   │   ├── middleware.ts   ← Auth middleware (org-aware, role resolver)
│   │   │   ├── rbac.ts        ← Field-level access + record scope enforcement
│   │   │   └── org-context.ts ← Org structure context (roles, dept, manager chain)
│   │   ├── ai/                 ← (when AI features present)
│   │   │   ├── config.ts       ← AI model and rate limit configuration
│   │   │   ├── smart-fields.ts ← Smart field computation engine
│   │   │   ├── semantic-search.ts ← Embedding + pgvector hybrid search
│   │   │   └── usage.ts        ← Token usage tracking and cost logging
│   │   ├── realtime/           ← (when real-time features needed)
│   │   │   ├── socket-server.ts ← Socket.IO server setup
│   │   │   ├── events.ts       ← Event type definitions
│   │   │   └── use-realtime.ts  ← React hook: useRealtime(channel, event, cb)
│   │   ├── email/
│   │   │   └── email.service.ts ← Email sending
│   │   └── external/
│   │       └── {api}.client.ts ← External API clients
│   │
│   ├── app/                    ← HTTP layer (thin — delegates to application layer)
│   │   ├── globals.css
│   │   ├── layout.tsx          ← Root layout (sidebar, header, fonts)
│   │   ├── page.tsx            ← Dashboard/home
│   │   ├── {module}/
│   │   │   ├── {resource}/
│   │   │   │   ├── page.tsx    ← List page (Server Component)
│   │   │   │   └── [id]/
│   │   │   │       └── page.tsx ← Detail page
│   │   │   └── ...
│   │   └── api/
│   │       ├── {resource}/
│   │       │   ├── route.ts    ← GET (list), POST (create) → calls service
│   │       │   └── [id]/
│   │       │       └── route.ts ← GET (detail), PUT (update), DELETE → calls service
│   │       └── ...
│   │
│   ├── components/             ← React components (presentation only)
│   │   ├── layout/
│   │   │   ├── Sidebar.tsx     ← Navigation sidebar
│   │   │   ├── Header.tsx      ← Top bar
│   │   │   └── PageWrapper.tsx ← Content area wrapper
│   │   ├── shared/
│   │   │   ├── DataTable.tsx   ← Reusable table component
│   │   │   ├── FormField.tsx   ← Form field wrapper
│   │   │   ├── Badge.tsx       ← Status/priority badge
│   │   │   └── ...
│   │   └── {module}/
│   │       ├── {Resource}Form.tsx
│   │       ├── {Resource}Card.tsx
│   │       ├── {Resource}Table.tsx
│   │       └── ...
│   │
│   ├── workflows/              ← Workflow runtime + definitions
│   │   ├── runtime.ts          ← Workflow executor
│   │   ├── triggers.ts         ← Trigger registration
│   │   ├── definitions/
│   │   │   └── {name}.json     ← Workflow definitions
│   │   └── actions/
│   │       ├── send-email.ts
│   │       ├── update-stock.ts
│   │       └── ...
│   │
│   ├── agents/                 ← AI agents (if app has agents)
│   │   ├── runtime.ts          ← Agent executor + tool registry
│   │   ├── definitions/
│   │   │   └── {name}.json     ← Agent definitions (prompts, tools, config)
│   │   ├── memory.ts           ← Conversation history + knowledge base
│   │   ├── guardrails.ts       ← Input/output validation, content filters
│   │   └── tools/
│   │       ├── registry.ts     ← Auto-registers app API routes as tools
│   │       ├── db-query.ts     ← Natural language → SQL tool
│   │       ├── http-call.ts    ← External API call tool
│   │       └── ...
│   │
│   └── types/                  ← Shared TypeScript types
│       └── index.ts
│
├── drizzle/                    ← Generated migration files
│   └── ...
│
└── public/
    └── images/                 ← Static assets
```

#### 9.1.1 Layer Rules

| Layer | May import from | Never imports from |
|-------|----------------|-------------------|
| `domain/` | Nothing (pure TypeScript) | `application/`, `infrastructure/`, `app/`, any npm package |
| `application/` | `domain/`, `infrastructure/` | `app/`, `components/` |
| `infrastructure/` | `domain/` | `application/`, `app/`, `components/` |
| `app/` (routes) | `application/` | `infrastructure/`, `domain/` (only types via `types/`) |
| `components/` | `types/` | `application/`, `infrastructure/`, `domain/` |

#### 9.1.2 What Goes Where

| Code Type | Location | Example |
|-----------|----------|---------|
| TypeScript type / interface | `domain/{module}/entities.ts` | `Product`, `OrderStatus` |
| Validation function (pure) | `domain/{module}/rules.ts` | `canApproveExpense(user, expense)` |
| Domain error class | `domain/{module}/errors.ts` | `InsufficientStockError` |
| Zod input schema | `application/{module}/{resource}.schema.ts` | `createProductSchema` |
| CRUD + business operation | `application/{module}/{resource}.service.ts` | `ProductService.create()` |
| Drizzle table definition | `infrastructure/db/schema.ts` | `pgTable('products', {...})` |
| DB query (Drizzle) | `infrastructure/db/repositories/{resource}.repository.ts` | `ProductRepository.findById()` |
| Auth middleware | `infrastructure/auth/middleware.ts` | `requireAuth()` |
| RBAC enforcement | `infrastructure/auth/rbac.ts` | `applyScopeFilter()` |
| Smart field computation | `infrastructure/ai/smart-fields.ts` | `computeSmartFields()` |
| Real-time socket server | `infrastructure/realtime/socket-server.ts` | `initSocketServer()` |
| Real-time React hook | `infrastructure/realtime/use-realtime.ts` | `useRealtime()` |
| API route handler | `app/api/{resource}/route.ts` | `GET`, `POST` — max 15-20 lines |
| React component | `components/{module}/{Resource}Form.tsx` | Presentation only |

---

## 9A. Schema / Renderer Contract

The schema-mode pipeline (Section 5.14) emits per-page JSON files; everything that turns those files into a rendered UI lives in three workspace packages plus one preview app:

| Package / app | Role |
|---|---|
| `packages/schema` | The JSON contract — Zod `PageV1` / `PageV2` schemas, node taxonomy, token-ref types, expressions, style-slots, layout templates. Source of truth for what is a valid page. |
| `packages/renderer` | Runtime: validates a `Page`, resolves data sources, walks the node tree, dispatches each node to either an internal primitive/layout/data node or to the library via `LibraryDispatcher`. Provides Mustache interpolation, expression evaluation, token compilation, style-slot application. |
| `packages/library` | The ~55 production-grade React components (Hero, MetricTile, DataGrid, Chart, ApprovalStepper, …) registered into the renderer. Owns the token namespace (`defaultTokens`), the register bundles, and the `TokensProvider` context. |
| `apps/render-scaffold` | Next.js preview surface at port `6503`. Route `/p/[projectId]/[...slug]` loads a schema from `output/<short_id>/src/schemas/<entity>/<slug>.json`, mounts tokens, fetches fixture data, and renders. This is the surface users see while iterating. |

### 9A.1 Per-Project Output Layout

A schema-mode generation writes the following under `output/<short_id>/`:

```
output/<short_id>/
├── src/
│   ├── schemas/
│   │   ├── <entity_slug_1>/
│   │   │   ├── list.json
│   │   │   ├── detail.json
│   │   │   └── form.json
│   │   └── <entity_slug_2>/…
│   ├── contracts/
│   │   ├── design-spec.json     # palette, typography, density, register
│   │   ├── tokens.custom.json   # compiled token overrides (FIDELITY_MODE_ENABLED)
│   │   ├── registry.json        # contract registry: entities, routes, components, pages
│   │   ├── api-contracts.json
│   │   ├── db-schema-plan.json
│   │   ├── types.json
│   │   └── app-model.json       # rebuilt by indexer (TSX path only)
│   ├── db/schema/<entity>.ts    # Drizzle (still emitted by schema_agent)
│   └── app/api/.../route.ts     # API routes (still emitted by api_agent)
├── .fixtures-cache/
│   └── <entity_slug>.json       # per-entity LLM-generated preview records (Layer 2-cache)
└── package.json, docker-compose.yml, …
```

The schema-mode pipeline emits **only the schemas and the backend half** — there is no TSX page tree. The render-scaffold app at `:6503` reads schemas from disk; in production, the deploy story is that the same scaffold (or any consumer of the renderer + library) serves the live app.

### 9A.2 The `Page` Schema

`packages/schema/src/page.ts` defines a discriminated union on `schemaVersion`:

```ts
export const Page = z.discriminatedUnion("schemaVersion", [PageV1, PageV2]);
```

**Shared envelope** for every page (`PageV1` + `PageV2`):

| Field | Type | Notes |
|---|---|---|
| `schemaVersion` | `"1"` \| `"2"` | Discriminator. |
| `id` | non-empty string | Stable id; surfaces as `data-page-id` in DOM. |
| `route` | non-empty string | The URL the page lives at in the generated app (e.g. `/tasks`). |
| `meta` | `{title?, description?}` (V1) / `Record<string, any>` (V2) | Optional. |
| `layout` | string | Layout template name; resolved against `layouts` registry at render time. |
| `dataSources` | `DataSource[]` | Declarative `{name, entity, op, filter?, select?, orderBy?, limit?}` triples. Resolved before render. |
| `tokens` | `Record<scope, Record<key, TokenRef>>` (V1 only) | Per-page token overrides. |
| `slots` | `Record<string, Node>` (V1 only) | Named slots filled by layout templates. |
| `root` | `Node` (V1) / `NodeV2` (V2) | The root of the node tree. |

**`NodeV2`** is a `z.discriminatedUnion("type", …)` over ~50 branches. The discriminated-union form is **load-bearing** — the previous `z.union` form caused multi-GB OOMs on trees with ~30+ nodes because every child position retried every branch and built a deep `ZodError` per failure. The union splits into four families:

1. **Strict v2 typed nodes** — `Hero`, `Section`, `MetricTile`, `FeatureCard`, `Card`, `Heading`, `Split`, `Sidebar`, `Cluster`, `Tabs`, `Accordion`, `AccordionPanel`, `Avatar`, `KeyValueList`, `Skeleton`, `Input`, `Select`, `Textarea`, `Checkbox`, `DatePicker`, `FadeIn`, `Stagger`. Each declares its own `props` Zod shape in `packages/schema/src/nodes/{foundation,layout-v2,inputs,display,motion}.ts`.
2. **Tier-2 data + enterprise nodes** — `Chart`, `Sparkline`, `DataGrid`, `Timeline`, `ApprovalStepper`, `PersonCard`, `FilterBar`, `CommandPalette`, `ActivityFeed`, `EmptyStateRich`, `DateRangePicker`, `MultiSelect`, `AppShell`, `InspectorPanel`, `TabPanelWithDeepLink`.
3. **Structural v1-compat nodes** — `Stack`, `Row`, `Grid`, `Container`, `Spacer`, `Box`, `Text`, `Image`, `Repeat`, `Conditional`, `DataBoundary`, `Slot`, `Custom` — all re-declared inline so their children validate against `NodeV2`.
4. **Library bridge nodes** — `Button`, `Link`, `NavLink`, `IconButton`, `TabPanel`, `Badge`, `Divider`, `Breadcrumb`, `Alert`, `EmptyState`, `LoadingState`, `Table`, `Form`. Each accepts `z.record(z.unknown())` props at this layer; the **library** owns the authoritative prop schema, applied at render time by `LibraryDispatcher.validateProps()`.

**Cross-field invariants** (`Tabs.children.length === Tabs.props.tabs.length`; `Skeleton.lines` only valid when `variant === "text"`) are applied as a single `superRefine` on the union so each member stays a plain `ZodObject` (the precondition for O(1) discriminated-union dispatch).

**Envelope fields** every node accepts: `id?` (optional — most nested nodes ship without one; renderer falls back to array index), `style?` (`StyleProps | StyleSlot`), `bind?` (`DataBinding` or bare source string), `visibleIf?` (Expression), `on?` (Record of event handlers).

**`TokenRef` is a wide string** (`z.string().min(1)`). The LLM emits three valid forms — canonical dotted (`tokens.spacing.1`), short scope (`primary.500`), semantic alias (`lg`, `tight`) — plus Mustache indirection (`{{theme.gap}}`). The runtime resolver in `packages/library` accepts all four; validating shape here would only produce false positives.

**Tolerant parsing in the scaffold** — `apps/render-scaffold/.../page.tsx` calls `PageUnion.safeParse(raw)` and **falls through to the raw tree** on Zod failure (logging the first 3 issues), because the renderer is already tolerant of unknown shapes (unknown types render as labelled placeholders; mustache interpolates at render time). This keeps the preview alive while schemas are still being iterated.

### 9A.3 Renderer Pipeline

`packages/renderer/src/SchemaRenderer.tsx` is an **async server component**:

```ts
export async function SchemaRenderer({ page, dataEngine, layouts, user, request, registry }) {
  const valid = validatePage(page);                                       // Zod
  const data  = await resolveDataSources(valid, dataEngine, {request, user}); // src/server/DataResolver
  const root  = valid.layout ? applyLayout(valid, layouts[valid.layout]) : valid.root;
  return <>{renderNode(root, { data, user, registry })}</>;
}
```

The render-scaffold wraps it in a client boundary (`SchemaRendererWrapper`) because the library components call React hooks (`useTokens`, `useDensity`); only plain-serialisable props (`page`, `tokens`, `register`, `previewData`) cross the server→client line. The registry itself — which holds React component references — is constructed on the client.

**`renderNode(node, ctx)`** (`packages/renderer/src/runtime/dispatch.tsx`) is the heart of the render loop. For every node, in order:

1. **`visibleIf`** — if present, evaluate via `evalExpression` against `{...ctx.data, user: ctx.user}`. Expression errors are treated as `false`. Skip the node entirely on false.
2. **Mustache interpolation** — `interpolateDeep(node.props, {...ctx.data, user})` walks the props recursively and replaces every `{{path.to.value}}` with the resolved value. This is what turns LLM-emitted literals like `"Welcome, {{user.name}}!"` and `{{leaveRequest.id}}` into real strings before dispatch. Done **once per node** at the props level; child nodes run their own pass when recursed into.
3. **Data nodes** (`Repeat`, `Conditional`, `DataBoundary`) get dispatched **before** child computation, because each manages its own child scoping:
   - `Repeat` builds a per-item scope (`{[as]: item}`) and re-renders children once per item; key derived from `keyPath`.
   - `Conditional` evaluates `when`, picks `children` or `else`.
   - `DataBoundary` wraps render in try/catch and shows `fallback` on error.
4. **Structural / primitive nodes** — children are pre-computed with stable React keys (`c.id ?? i`), then the node dispatches to its component: `Stack`, `Row`, `Grid`, `Container`, `Spacer`, `Box`, `Text`, `Image`, `Slot`. `Custom` renders sanitised HTML via `DOMPurify.sanitize()` and supports an optional `customRenderer` hook used by the editor.
5. **Registry fallthrough** — for any other `node.type`, if `ctx.registry.has(node.type)`, the dispatcher calls `ctx.registry.validateProps(node.type, node.props)` (which runs the library's authoritative Zod schema **plus prop remaps** — see 9A.5), passes `node.style` through to `LibraryDispatcher`, and renders. If `validateProps` throws, a labelled placeholder is rendered in place — the canvas stays usable while the user fixes the schema. Unknown types fall through to a labelled placeholder too.

**`Text` node specifics** (`packages/renderer/src/nodes/primitive/Text.tsx`): runs additional formatting on the interpolated content — date detection (ISO strings rendered with `Intl.DateTimeFormat`), snake_case humanizer, prefix-icon detection (e.g. `"✓ Approved"` → icon + label). These exist because LLM-emitted text is human-readable but not pre-formatted.

**Layout templates** (`packages/schema/src/layout-template.ts`): a layout is a node tree with `Slot` placeholders. `applyLayout(page, template)` replaces each `Slot.props.name` with the matching entry from `page.slots`. Layouts let multiple pages share a shell (e.g. AppShell + sidebar) without duplicating it per page.

**Expression language** (`packages/schema/src/expressions.ts`): small embedded language for `visibleIf`, `Conditional.when`, and bindings. Supports dotted paths, comparison operators, boolean ops, function calls (`isEmpty`, `length`, `formatDate`, …). Implemented in `packages/renderer/src/runtime/bindings.ts`.

### 9A.4 Tokens + Registers

The library owns the token namespace. `packages/library/src/theme/default-tokens.ts` exports `defaultTokens` — a typed object whose **keys are the canonical token paths** referenced by `TokenRef` (`color.primary.500`, `spacing.4`, `radius.md`, `typography.scale.h1`, `shadow.sm`, `motion.duration.fast`, …). The schema prompt loads this object at generation time to constrain what tokens the LLM can reference.

**Six registers** live in `packages/library/src/theme/registers/{workday,linear,stripe,notion,figma}.ts`. Each `RegisterBundle` is a partial token tree (with optional density / radius scale / typography mode overrides). `resolveTokens(name)` deep-merges the bundle on top of `defaultTokens` to produce the active set. `default` is the un-overridden baseline.

`apps/render-scaffold/src/lib/loadTokens.ts` reads the project's `src/contracts/tokens.custom.json` (if present, written by `services/design_compiler.py` from `design-spec.json`) and merges it on top of `defaultTokens` **after** the register merge.

`compileTokens(tokenGroups)` (exported from the renderer) flattens the token tree into a `React.CSSProperties` object of CSS custom properties (`--color-primary-500`, `--spacing-4`, …). The scaffold's root `<main>` carries this style object, so every library component reads from CSS vars and re-renders cleanly when tokens change.

`TokensProvider` wraps the render tree on the client, exposing the typed token map via `useTokens()`, plus convenience hooks `useDensity()`, `useElevation()`, `useMotionLevel()`, `useRadiusScale()`. Library components use these to pick variant shapes (e.g. `Button` reads density to choose padding scale).

### 9A.5 Library Component Registry

`createRegistry()` (`packages/library/src/registry.ts`) builds a name-keyed map of `{name, component, propsSchema, category, acceptsChildren}` entries. The scaffold's `SchemaRendererWrapper` registers every library component at mount time:

```ts
const registry = createRegistry();
registry.register({ name: "Button", component: Button, propsSchema: ButtonProps, category: "interactive" });
registry.register({ name: "DataGrid", component: DataGrid, propsSchema: DataGridPropsSchema, category: "data", acceptsChildren: false });
// … ~55 entries
```

**Prop remaps at the registry boundary** — LLM-generated schemas use v1/legacy prop names that don't match the strict v2 contracts:

- `Button.content` / `.children` → `label`; `.href` → `navigate`; `variant: "outline"` → `"secondary"`
- `Input.validators.minLength` / `.maxLength` → `.min` / `.max` (same for `Textarea`, `Select`, `DatePicker`)
- `Table.columns[].title` → `.label`; empty/missing label falls back to the column `key`
- `Tabs.{defaultValue, variant}` → synthesised `{tabs: [{id, label}], value}` placeholder so the canvas renders rather than erroring

`registry.validateProps(name, props)` runs the remap **then** the v2 Zod schema. This is the choke point that lets the canvas stay usable on partially-correct LLM output without rewriting the on-disk JSON.

### 9A.6 Fixture Data Pipeline

`{{mustache}}` bindings in schemas resolve against the data context built by `loadPreviewData()` in the render-scaffold's page route. The data comes from a backend endpoint:

```
GET /api/_debug/preview-data/{short_id}
  → backend/routers/_debug_schema.py
```

The endpoint walks `registry.json` (or `app-model.json` as fallback) for the entity list, then for each entity calls `services/fixtures/dispatcher.py::provide_records_async()`. The dispatcher resolves through **four layers**, best-first:

| Layer | Source | When it fires |
|---|---|---|
| 1 | Hand-curated bank in `backend/fixtures/<domain>/<entity>.json` | Few (domain, entity) pairs are seeded by `scripts/seed_reference_bank.py`. Highest quality. |
| 2-cache | `output/<short_id>/.fixtures-cache/<entity>.json` | Set after the first LLM call. Fast, no cost. |
| 2-llm | Fresh Sonnet call via `services/fixtures/llm_gen.py` | Cold project — written to the cache. Per-entity calls run **concurrently** via `asyncio.gather` on the route's own event loop (the Claude SDK's subprocess pipes don't bridge through `asyncio.to_thread` cleanly). |
| 3 | Faker via `services/fixtures/faker_gen.py` | Realistic for ~20 known field names (`name`, `email`, `phone`, `department`, `created_at`, …); Lorem-style fallback otherwise. |
| 4 | `[{}, {}, …]` empty dicts | No fields known. |

Field hints for the LLM and Faker layers come from the Drizzle schema TS file (`src/db/schema/<entity-kebab>.ts`) — `_infer_hints_from_schema_file()` parses `pgTable` column lines like `userId: uuid("user_id")` into `FieldHint(name="userId", type="string")`.

**Post-processing in the route** — `_enrich_record()` adds three classes of synthetic fields on top of the raw record:

- **FK joins** — for any `*Id` field whose value matches another entity's `id`, attach a snake_case alias for the joined entity (`assigneeId` → `assignee`) with name/email/initials. The same record gets short, lowercased "person aliases" (`assignedTo`, `requestedBy`, `submittedBy`) so common LLM bind variants resolve.
- **Semantic aliases** — `name` ↔ `fullName` ↔ `title`, `createdAt` ↔ `created`, `updatedAt` ↔ `updated`, `status` ↔ `state`. Mustache strings hit these without forcing the schema to use the exact column name.
- **Stat aliases** — for list pages, the response root includes derived counts (`stats.totalCount`, `stats.pendingCount`) and last-N collections (`recentItems`) so MetricTile / Hero bindings have stable surface area.

The register-to-domain map (`workday → hr`, `stripe → fintech`, `linear/notion/figma/default → general`) decides which fixture bank to draw from when no explicit domain is set on the project.

### 9A.7 Render-Scaffold Routing

`apps/render-scaffold/src/app/p/[projectId]/[...slug]/page.tsx` resolves a request like `/p/genmetrics-1778439719/tasks/list` into:

1. **Validate `projectId`** — `resolveProject()` rejects path traversal; bad ids 404 cleanly.
2. **Resolve schema path** with **production-style URL fallback**:
   - The pipeline emits `{entity}/{list|detail|form}.json` schemas.
   - Live Next.js apps from this platform use dynamic routes (`/tasks/[id]`, `/tasks/new`). Schemas emit `navigate: "/tasks/{{item.id}}"` and `"/tasks/new"`.
   - The scaffold's own routing is flat, so without a fallback every "View" / "Create" button would 404. Rule: if the literal `/<entity>/<id>` doesn't load, try `<entity>/form` for `new`/`create` segments and `<entity>/detail` for anything else.
3. **Parse Zod-permissively** — `PageUnion.safeParse(raw)` is tolerant of validation errors as described in 9A.2.
4. **Load tokens + register** — `loadTokens()` (defaults + project overrides), `loadRegister()` (from `design-spec.json`, defaults to `"default"`).
5. **Build a11y tree** — `buildA11yTree(page)` (`src/lib/a11yTree.ts`) extracts a semantic outline embedded as JSON in the rendered HTML (`A11yTreeEmbed`) for downstream evaluators.
6. **Fetch fixture data** — `loadPreviewData(projectId)` calls the backend `preview-data` endpoint described in 9A.6.
7. **Render** — `<SchemaRendererWrapper page tokens register previewData />` mounts the registry + `TokensProvider` and invokes `renderNode` on the client.

The root `<main>` carries the compiled token CSS vars as inline style plus `data-project-id`, `data-page-path`, `data-register` for debugging and the embedded evaluator.

### 9A.8 Validation Lifecycle Summary

```
Pipeline writes:                       Renderer reads:
  src/schemas/<e>/<type>.json    ──►   loadSchema() → safeParse(PageUnion) → permissive fallback
  src/contracts/design-spec.json ──►   loadRegister() → resolveTokens(register) ──►
  src/contracts/tokens.custom.json ──►                                         deep-merge ──►  compileTokens
  src/contracts/registry.json    ──►   backend /preview-data ──►  dispatcher (4-layer)  ──►
  src/db/schema/<e>.ts           ──►   _infer_hints_from_schema_file ──►  FieldHint[]   ──►   previewData
                                                                                              │
                                                                                              ▼
                                       SchemaRenderer (server) → renderNode (dispatch)
                                         ├─ visibleIf → evalExpression
                                         ├─ interpolateDeep (Mustache)
                                         ├─ Repeat / Conditional / DataBoundary
                                         ├─ structural primitives + Text formatting
                                         └─ registry.validateProps → LibraryDispatcher
```

The contract is **deliberately loose at the edges and strict in the middle**. The page schema only requires what the renderer cannot recover from. The library schema is strict because it's the last line before the actual component call. The renderer fills in everything in between — Mustache, token resolution, register merge, prop remap, fallback rendering — so LLM-emitted schemas can be partially wrong and still produce a usable preview.

### 9A.9 Editor Inspector (Props / Style / Bindings / Tokens)

The schema-mode visual editor (`frontend/src/components/canvas/Canvas.tsx` at `/editor/<short_id>` and the project workspace "Editor" tab, both via `VisualEditorWorkspace`) renders the same page schema through the client `@tentoroforge/engine` `<Engine>` and exposes a right-panel inspector (`components/properties/RightPanel.tsx`) with four tabs. Every tab reads/writes the in-memory `Artifacts` in the Zustand editor store (`lib/editor-store.ts`); each mutation flows through `@forge/patches` `applyAction` (typed inverse pushed onto the undo stack) and a debounced persister (`lib/persistence.ts`) writes the changed page schema back to `src/schemas/<path>.json`. Selection: the renderer tags every node with `data-node-id`; a canvas click walks to the nearest one and selects it; the panels resolve that id in the store.

| Tab | Reads | Writes | Mechanism |
|---|---|---|---|
| **Props** | `node.props` | `node.props[name]` | Registry-descriptor-driven controls (`@forge/registry`), grouped content/style/state/behavior/data; `updateProp` action. Bind toggle wraps a prop as `{ $binding }`. |
| **Style** | `node.style` (StyleSlot) | `node.style[key]` | `updateStyle` action → the top-level StyleSlot the renderer resolves (`applyStyleSlot` for structural nodes, the `style` prop for library ones). Values are token-refs (`spacing.4`, `radius.md`, `shadow.md`, `color.*`; `Motion` enum) → `var(--token-*)`. The editor canvas injects those vars via `compileTokens` on the canvas root so StyleSlot styling resolves in-editor, matching the production `<html>` injection. |
| **Bindings** | `node.props` | (display) | Lists every `{{…}}` string and `{ $binding }` on the selected node, including freshly-toggled empty ones. Authoring happens via the Props-tab bind toggle. |
| **Tokens** | `artifacts.tokens` | `tokens.*` | `TokenEditor` edits the project's real color/typography tree (seeded from `src/theme/tokens.custom.json`); `updateToken`/`removeToken`. The store's live tokens feed `EngineProvider` so edits recolor the canvas, and persist back to `src/theme/tokens.custom.json`. |

**Invariants worth preserving:**
- `node.style` (StyleSlot) is the styling channel, **not** `node.props.style`. `updateStyle` also clears any colliding legacy `node.props.style` key (structural nodes spread `node.props.style` last as `callerStyle` for the Figma/MCP pipeline, so a stale value there would otherwise override the StyleSlot).
- `compileTokens` **drops the outermost key** — `compileTokens(defaultTokens)` yields `--token-4`, not `--token-spacing-4`. Wrap the merged tree as `compileTokens({ t: merged })` so the group name (`spacing`/`radius`/`shadow`/`color`) survives to match `applyStyleSlot`'s `var(--token-<group>-…)` lookup.
- Tokens persist to `src/theme/tokens.custom.json` (the file the generated app + editor actually read), never `src/contracts/tokens.json`.

*History:* the four tabs were repaired on 2026-07-02 (branch `component-fixes`) — Style wrote token-names into `node.props.style` (ignored by the renderer) and the canvas never injected `--token-*`; Tokens were seeded empty and saved to a dead file; Bindings hid empty bindings via a falsy check. All four are verified applying to the canvas and persisting to disk.

---

## 10. Preview System

### 10.1 Preview Manager

```python
# backend/services/preview_manager.py

import asyncio
import os
import signal
import subprocess
from pathlib import Path
from typing import Optional
import httpx

# Port ranges
PREVIEW_PORT_MIN = 3200
PREVIEW_PORT_MAX = 3299
DB_PORT_MIN = 5500
DB_PORT_MAX = 5599

# Active previews: {project_id: {proc, preview_port, db_port, output_dir}}
_previews: dict[str, dict] = {}


async def start_preview(project_id: str, output_dir: str) -> dict:
    """Start Docker Postgres + Next.js dev server for a project.

    Returns: {"preview_port": int, "db_port": int}
    """
    # Already running?
    if project_id in _previews:
        existing = _previews[project_id]
        if existing["proc"].returncode is None:
            return {
                "preview_port": existing["preview_port"],
                "db_port": existing["db_port"],
            }
        del _previews[project_id]

    # Pick ports
    preview_port = _pick_port(PREVIEW_PORT_MIN, PREVIEW_PORT_MAX)
    db_port = _pick_port(DB_PORT_MIN, DB_PORT_MAX)

    # Write .env with project-specific DB port
    env_path = Path(output_dir) / ".env"
    env_path.write_text(
        f"DATABASE_URL=postgresql://app:app@localhost:{db_port}/app\n"
        f"DB_PORT={db_port}\n"
    )

    # Step 1: Start Postgres
    env = {**os.environ, "DB_PORT": str(db_port)}
    docker_up = await asyncio.create_subprocess_exec(
        "docker", "compose", "up", "-d", "--wait",
        cwd=output_dir, env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await docker_up.wait()

    # Step 2: Install dependencies if needed
    if not (Path(output_dir) / "node_modules").exists():
        install = await asyncio.create_subprocess_exec(
            "npm", "install", cwd=output_dir,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await install.wait()

    # Step 3: Push schema
    push = await asyncio.create_subprocess_exec(
        "npx", "drizzle-kit", "push",
        cwd=output_dir, env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await push.wait()

    # Step 4: Seed data
    seed = await asyncio.create_subprocess_exec(
        "npx", "tsx", "src/infrastructure/db/seed.ts",
        cwd=output_dir, env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await seed.wait()

    # Step 5: Start Next.js dev server
    proc = await asyncio.create_subprocess_exec(
        "npx", "next", "dev", "--port", str(preview_port),
        cwd=output_dir, env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        preexec_fn=os.setsid,
    )

    _previews[project_id] = {
        "proc": proc,
        "preview_port": preview_port,
        "db_port": db_port,
        "output_dir": output_dir,
    }

    # Poll until ready
    url = f"http://localhost:{preview_port}"
    async with httpx.AsyncClient(timeout=5) as client:
        for _ in range(60):
            await asyncio.sleep(0.5)
            try:
                resp = await client.get(url)
                if resp.status_code < 500:
                    return {"preview_port": preview_port, "db_port": db_port}
            except (httpx.ConnectError, httpx.ReadError, httpx.TimeoutException):
                continue

    stop_preview(project_id)
    raise RuntimeError(f"Preview server failed to start")


def stop_preview(project_id: str) -> bool:
    """Stop dev server and Docker Postgres for a project."""
    entry = _previews.pop(project_id, None)
    if not entry:
        return False

    # Kill Next.js
    proc = entry["proc"]
    if proc.returncode is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

    # Stop Docker
    subprocess.run(
        ["docker", "compose", "down"],
        cwd=entry["output_dir"],
        capture_output=True,
        env={**os.environ, "DB_PORT": str(entry["db_port"])},
    )
    return True


def stop_all_previews():
    for pid in list(_previews.keys()):
        stop_preview(pid)
```

### 10.2 Database Proxy

The platform backend proxies SQL queries to the generated app's Postgres instance:

```python
# backend/services/db_proxy.py

import asyncpg
from typing import Any


async def execute_query(
    db_port: int,
    query: str,
    params: list | None = None,
    readonly: bool = True,
) -> dict:
    """Execute a SQL query against a generated app's database."""
    conn = await asyncpg.connect(
        f"postgresql://app:app@localhost:{db_port}/app"
    )
    try:
        if readonly:
            rows = await conn.fetch(query, *(params or []))
            columns = [col for col in rows[0].keys()] if rows else []
            return {
                "columns": columns,
                "rows": [dict(row) for row in rows],
                "count": len(rows),
            }
        else:
            result = await conn.execute(query, *(params or []))
            return {"result": result}
    finally:
        await conn.close()


async def list_tables(db_port: int) -> list[dict]:
    """List all tables in the generated app's database."""
    result = await execute_query(
        db_port,
        """
        SELECT table_name,
               (SELECT count(*) FROM information_schema.columns c
                WHERE c.table_name = t.table_name
                AND c.table_schema = 'public') as column_count
        FROM information_schema.tables t
        WHERE table_schema = 'public'
        AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
    )
    return result["rows"]


async def get_table_schema(db_port: int, table_name: str) -> list[dict]:
    """Get column definitions for a table."""
    result = await execute_query(
        db_port,
        """
        SELECT column_name, data_type, is_nullable, column_default,
               character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = $1
        ORDER BY ordinal_position
        """,
        [table_name],
    )
    return result["rows"]
```

---

## 11. Module System

### 11.1 Module Lifecycle

```
1. CREATE
   User: "Add an inventory module"
   → Planner Agent generates structured plan
   → User reviews and approves
   → Module record created in platform DB (status: generating)

2. GENERATE
   → Code Generator runs with the plan
   → Generates all files for the module
   → If module depends on existing modules, reads their schemas and APIs
   → Validator verifies build
   → Indexer updates AppModel
   → Module status → active

3. CONNECT
   → If cross-module dependencies exist:
     Code Generator adds foreign keys, API calls, and shared types
     Example: Sales.SalesOrderLine references Inventory.Product
   → Indexer records the cross-module bindings

4. REFINE
   → User makes changes to module via chat or visual editors
   → Refiner Agent scoped to module context
   → Impact analysis checks cross-module effects

5. DELETE
   → Impact analysis shows what depends on this module
   → If other modules depend on it, warn/block
   → Remove module files
   → Update AppModel index
   → Module status → deleted
```

### 11.2 Cross-Module Dependencies

```json
// app-model.json — crossModuleBindings section

{
  "crossModuleBindings": [
    {
      "id": "xb1",
      "from": {"module": "sales", "model": "SalesOrderLine", "field": "productId"},
      "to": {"module": "inventory", "model": "Product", "field": "id"},
      "type": "foreign_key",
      "onDelete": "restrict"
    },
    {
      "id": "xb2",
      "from": {"module": "sales", "workflow": "on-order-confirmed"},
      "to": {"module": "inventory", "api": "POST /api/stock/reserve"},
      "type": "api_call",
      "description": "Reserve inventory when sales order is confirmed"
    },
    {
      "id": "xb3",
      "from": {"module": "sales", "workflow": "on-invoice-posted"},
      "to": {"module": "finance", "api": "POST /api/journal-entries"},
      "type": "api_call",
      "description": "Create AR journal entry when invoice is posted"
    }
  ]
}
```

---

## 12. AppModel Index

### 12.1 Full Schema

```json
// app-model.json — complete structure

{
  "version": 1,
  "projectId": "abc123",
  "updatedAt": "2026-02-28T12:00:00Z",

  "modules": [
    {
      "id": "inventory",
      "name": "Inventory Management",
      "description": "Track products, warehouses, and stock levels",
      "status": "active"
    }
  ],

  "dataModels": [
    {
      "name": "Product",
      "module": "inventory",
      "file": "src/infrastructure/db/schema.ts",
      "tableName": "products",
      "fields": [
        {"name": "id", "type": "uuid", "constraints": ["pk", "auto"]},
        {"name": "sku", "type": "varchar(100)", "constraints": ["unique", "not_null"]},
        {"name": "name", "type": "varchar(255)", "constraints": ["not_null"]},
        {"name": "unitPrice", "type": "decimal(10,2)", "constraints": ["not_null"]}
      ],
      "relations": [
        {"field": "categoryId", "target": "Category", "type": "many-to-one"}
      ],
      "indexes": ["idx_product_sku", "idx_product_category"]
    }
  ],

  "pages": [
    {
      "route": "/inventory/products",
      "name": "Product List",
      "module": "inventory",
      "file": "src/app/inventory/products/page.tsx",
      "description": "Searchable product table with filters",
      "components": ["ProductTable", "ProductFilters"]
    }
  ],

  "components": [
    {
      "name": "ProductTable",
      "module": "inventory",
      "file": "src/components/inventory/ProductTable.tsx",
      "props": ["products: Product[]", "onEdit: (id) => void", "onDelete: (id) => void"],
      "boundTo": {"model": "Product", "fields": ["sku", "name", "unitPrice", "isActive"]},
      "usedIn": ["/inventory/products"]
    }
  ],

  "apiRoutes": [
    {
      "method": "GET",
      "path": "/api/products",
      "module": "inventory",
      "file": "src/app/api/products/route.ts",
      "description": "List products with pagination and search",
      "model": "Product",
      "params": ["page", "limit", "search", "category"]
    },
    {
      "method": "POST",
      "path": "/api/products",
      "module": "inventory",
      "file": "src/app/api/products/route.ts",
      "description": "Create product",
      "model": "Product",
      "accepts": ["sku", "name", "description", "categoryId", "unitCost", "unitPrice"]
    }
  ],

  "workflows": [
    {
      "id": "wf-on-low-stock",
      "name": "Low Stock Alert",
      "module": "inventory",
      "definitionFile": "src/workflows/definitions/low-stock-alert.json",
      "trigger": {"type": "db_change", "model": "StockLevel", "condition": "available < reorderPoint"},
      "steps": 3,
      "actionFiles": [
        "src/workflows/actions/check-reorder-point.ts",
        "src/workflows/actions/create-draft-po.ts",
        "src/workflows/actions/notify-purchasing.ts"
      ]
    }
  ],

  "rules": [
    {
      "id": "r1",
      "name": "Price must be positive",
      "type": "validation",
      "module": "inventory",
      "attachedTo": {"model": "Product", "field": "unitPrice"},
      "condition": "value > 0",
      "message": "Price must be greater than zero",
      "enforce": ["ui", "api"]
    },
    {
      "id": "r2",
      "name": "PO status transitions",
      "type": "state_machine",
      "module": "inventory",
      "attachedTo": {"model": "PurchaseOrder", "field": "status"},
      "states": ["draft", "submitted", "approved", "received", "cancelled"],
      "transitions": [
        {"from": "draft", "to": ["submitted", "cancelled"]},
        {"from": "submitted", "to": ["approved", "cancelled"]},
        {"from": "approved", "to": ["received", "cancelled"]},
        {"from": "received", "to": []},
        {"from": "cancelled", "to": ["draft"]}
      ],
      "enforce": ["ui", "api"]
    }
  ],

  "bindings": [
    {
      "id": "b1",
      "model": "Product",
      "target": {"type": "component", "component": "ProductTable"},
      "fields": {
        "sku": {"display": "text", "sortable": true},
        "name": {"display": "text", "sortable": true},
        "unitPrice": {"display": "currency", "format": "USD"},
        "isActive": {"display": "badge", "colorMap": {"true": "green", "false": "gray"}}
      }
    },
    {
      "id": "b2",
      "model": "Product",
      "target": {"type": "api", "route": "/api/products"},
      "operations": ["list", "get", "create", "update", "delete"]
    }
  ],

  "agents": [
    {
      "id": "agent-support",
      "name": "Customer Support",
      "module": "support",
      "description": "Answers customer questions, creates support tickets, checks order status",
      "definitionFile": "src/agents/definitions/customer-support.json",
      "runtimeFile": "src/agents/runtime.ts",
      "systemPrompt": "You are a helpful customer support agent for...",
      "model": "claude-haiku-4-5-20251001",
      "tools": [
        {"name": "get_order", "source": "api", "route": "/api/orders/:id"},
        {"name": "create_ticket", "source": "api", "route": "/api/tickets"},
        {"name": "search_faq", "source": "custom", "file": "src/agents/tools/search-faq.ts"}
      ],
      "memory": {"type": "conversation", "maxMessages": 50, "tableName": "agent_conversations"},
      "guardrails": ["no_pii_in_response", "max_tokens_2000"],
      "chatRoute": "/support/chat",
      "chatComponent": "src/components/support/ChatWidget.tsx"
    }
  ],

  "crossModuleBindings": [],

  "theme": {
    "primaryColor": "#3b82f6",
    "font": "Inter",
    "borderRadius": "8px"
  },

  "navigation": {
    "type": "sidebar",
    "items": [
      {"label": "Dashboard", "route": "/", "icon": "LayoutDashboard"},
      {
        "label": "Inventory",
        "icon": "Package",
        "children": [
          {"label": "Products", "route": "/inventory/products"},
          {"label": "Warehouses", "route": "/inventory/warehouses"},
          {"label": "Purchase Orders", "route": "/inventory/purchase-orders"}
        ]
      }
    ]
  }
}
```

---

## 13. Binding System

### 13.1 How Bindings Work

```
When a component is "bound" to a data model, the binding record tracks:
  - Which model (Product)
  - Which component (ProductTable)
  - Which fields are mapped and how they're displayed
  - What data source feeds the component (API route)

When the model changes:
  1. Indexer detects the binding
  2. Shows impact analysis: "Product model changed, these components use it"
  3. If user opts to propagate:
     → Instruction generated for each affected component
     → Refiner updates each one

When a component is created:
  1. UI Editor shows "Bind to model" dropdown
  2. User selects model → fields auto-populate
  3. User configures how each field is displayed
  4. Instruction generated → LLM creates the component with proper data flow
```

### 13.2 Data Flow Through Bindings

```
Database (Postgres)
    ↓ Drizzle ORM query
API Route (route.ts)
    ↓ HTTP response (JSON)
Page Component (page.tsx)
    ↓ fetch() or server component
    ↓ passes data as props
Bound Component (ProductTable.tsx)
    ↓ renders each field according to binding config
UI (table rows, cards, forms)

The binding tracks this entire chain so that when the model changes,
we know exactly which files need updating.
```

---

## 14. Rules Engine & Decision Builder

### 14.1 Rule Types and Code Generation

Each rule type generates specific code patterns:

```
VALIDATION → src/domain/{module}/rules.ts + src/application/{module}/{resource}.schema.ts + API-level checks
ACCESS     → middleware or route-level role checks + UI conditional rendering
BUSINESS   → API route logic (if/else in handlers)
COMPUTED   → getter function or derived column
STATE      → transition validation function + UI dropdown filtering
TRIGGER    → workflow trigger registration
DECISION   → src/domain/{module}/decisions.ts + decision table evaluator
```

### 14.2 Enforcement Layers

```
                    Rule: "Price must be > 0"
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                  │
         UI Layer          API Layer          DB Layer
            │                 │                  │
   ProductForm.tsx       route.ts           schema.ts
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │ if (price<=0)│  │ if (price<=0)│  │ .check(      │
   │  showError() │  │  return 400  │  │  gt(price,0))│
   └──────────────┘  └──────────────┘  └──────────────┘

All three are generated from a single rule definition.
The instruction builder includes all enforcement points.
```

### 14.3 FEEL-lite Expression Language

A safe, sandboxed expression language used across condition builders, decision table
cells, computed fields, and workflow conditions. Subset of DMN's FEEL standard.

```typescript
// Generated in app: src/shared/feel-lite/parser.ts

// The parser compiles FEEL-lite expressions to an AST, then evaluates safely
// against a variable context. No eval(), no code injection.

// Supported expression types:

type FEELExpression =
  | { type: "comparison"; op: "=" | "!=" | ">" | ">=" | "<" | "<="; value: any }
  | { type: "range"; start: number; end: number; startInclusive: boolean; endInclusive: boolean }
  | { type: "list"; values: any[]; negated: boolean }               // "gold","platinum" or not("rejected")
  | { type: "null_check"; negated: boolean }                         // null, not(null)
  | { type: "string_op"; op: "starts_with" | "ends_with" | "contains" | "matches"; value: string }
  | { type: "arithmetic"; left: Expr; op: "+" | "-" | "*" | "/"; right: Expr }
  | { type: "conditional"; condition: Expr; then: Expr; else: Expr }
  | { type: "date"; op: string; value: string }                      // < date("2026-06-01")
  | { type: "duration"; value: string }                              // duration("P30D")
  | { type: "variable_ref"; path: string[] }                         // customer.tier
  | { type: "function_call"; name: string; args: Expr[] }            // sum(), count(), min(), max()
  | { type: "logical"; op: "and" | "or" | "not"; operands: Expr[] }
  | { type: "wildcard" };                                             // empty cell / dash

// Evaluation
function evaluateExpression(expr: FEELExpression, context: Record<string, any>): any;

// Cell matching — used by decision table evaluator
// Returns true if the cell expression matches the input value
function matchCell(cellExpr: FEELExpression, inputValue: any): boolean;

// Safety: expressions are parsed to AST at save time and validated.
// Runtime evaluation walks the AST — no string interpolation or eval.
```

### 14.4 Decision Table Evaluator

The core engine that evaluates decision tables at runtime, used by both the rules
engine (standalone decisions) and the workflow engine (decision nodes).

```typescript
// Generated in app: src/shared/decisions/evaluator.ts

interface DecisionTableDefinition {
  id: string;
  name: string;
  hitPolicy: "U" | "F" | "A" | "P" | "C" | "R";
  collectOperator?: "sum" | "min" | "max" | "count" | "avg";  // only for C hit policy
  inputs: InputColumn[];
  outputs: OutputColumn[];
  rules: DecisionRule[];
}

interface InputColumn {
  id: string;
  label: string;                   // display name
  variablePath: string;            // e.g. "customer.tier"
  type: "string" | "number" | "boolean" | "date";
}

interface OutputColumn {
  id: string;
  label: string;                   // e.g. "discount"
  type: "string" | "number" | "boolean" | "date";
  priority?: number;               // for P hit policy: lower = higher priority
}

interface DecisionRule {
  id: string;
  inputEntries: (FEELExpression | null)[];   // null = wildcard (match any)
  outputEntries: (FEELExpression | null)[];  // null = empty output
  annotation?: string;                        // optional row comment
}

// Main evaluation function
function evaluateDecisionTable(
  table: DecisionTableDefinition,
  inputContext: Record<string, any>,
): DecisionResult {
  const matchingRules = table.rules.filter(rule =>
    rule.inputEntries.every((entry, i) => {
      if (entry === null) return true;  // wildcard
      const inputValue = resolveVariable(table.inputs[i].variablePath, inputContext);
      return matchCell(entry, inputValue);
    })
  );

  switch (table.hitPolicy) {
    case "U":
      if (matchingRules.length !== 1) throw new DecisionError(
        matchingRules.length === 0 ? "no_match" : "ambiguous_match",
        table, matchingRules
      );
      return { matched: [matchingRules[0]], outputs: extractOutputs(matchingRules[0], table) };

    case "F":
      if (matchingRules.length === 0) throw new DecisionError("no_match", table, []);
      return { matched: [matchingRules[0]], outputs: extractOutputs(matchingRules[0], table) };

    case "A":
      // All matches must produce the same output
      const outputs = matchingRules.map(r => extractOutputs(r, table));
      if (!allEqual(outputs)) throw new DecisionError("conflicting_outputs", table, matchingRules);
      return { matched: matchingRules, outputs: outputs[0] };

    case "P":
      // Sort by priority (output column priority), take highest
      const sorted = matchingRules.sort((a, b) => outputPriority(a, table) - outputPriority(b, table));
      return { matched: [sorted[0]], outputs: extractOutputs(sorted[0], table) };

    case "C":
      // Collect all matching outputs, optionally aggregate
      const collected = matchingRules.map(r => extractOutputs(r, table));
      const aggregated = table.collectOperator
        ? aggregate(collected, table.collectOperator)
        : collected;
      return { matched: matchingRules, outputs: aggregated };

    case "R":
      // Return all matches in rule order
      return { matched: matchingRules, outputs: matchingRules.map(r => extractOutputs(r, table)) };
  }
}

interface DecisionResult {
  matched: DecisionRule[];           // which rules matched
  outputs: Record<string, any> | Record<string, any>[];  // single or collected
}
```

### 14.5 Decision Graph (DRD) Evaluator

For chained decisions where one decision's output feeds into another.

```typescript
// Generated in app: src/shared/decisions/graph-evaluator.ts

interface DecisionGraph {
  id: string;
  name: string;
  nodes: DRDNode[];
  edges: DRDEdge[];
}

type DRDNode =
  | { type: "input_data"; id: string; variablePath: string }
  | { type: "decision"; id: string; table: DecisionTableDefinition }
  | { type: "knowledge_source"; id: string; description: string };

interface DRDEdge {
  source: string;  // node id
  target: string;  // node id
}

// Evaluates the DRD by topologically sorting decisions and evaluating
// in dependency order. Each decision's output is added to the context
// for downstream decisions.
function evaluateDecisionGraph(
  graph: DecisionGraph,
  inputContext: Record<string, any>,
): Record<string, DecisionResult> {
  const results: Record<string, DecisionResult> = {};
  const context = { ...inputContext };

  for (const nodeId of topologicalSort(graph)) {
    const node = graph.nodes.find(n => n.id === nodeId);
    if (node?.type !== "decision") continue;

    const result = evaluateDecisionTable(node.table, context);
    results[nodeId] = result;

    // Merge decision outputs into context for downstream decisions
    if (!Array.isArray(result.outputs)) {
      Object.assign(context, { [nodeId]: result.outputs });
    }
  }

  return results;
}
```

### 14.6 Decision Versioning and Audit

```typescript
// Generated in app: src/infrastructure/decisions/

// Decision tables are versioned. Each save creates a new version.
// Active version is tracked per decision. Effective dating allows
// scheduling version activation.

interface DecisionVersion {
  id: string;
  decisionId: string;
  version: number;
  table: DecisionTableDefinition;       // full snapshot
  createdBy: string;
  createdAt: Date;
  effectiveFrom?: Date;                  // null = immediately active
  effectiveUntil?: Date;                 // null = no expiration
  changeNote?: string;
}

// Execution audit — logged every time a decision is evaluated
interface DecisionExecutionLog {
  id: string;
  decisionId: string;
  versionId: string;
  workflowInstanceId?: string;           // if invoked from workflow
  inputSnapshot: Record<string, any>;    // what inputs were provided
  matchedRules: string[];                // which rule IDs matched
  outputSnapshot: Record<string, any>;   // what output was produced
  evaluatedAt: Date;
  durationMs: number;
}
```

### 14.7 Schema-Aware Variable Binding

Decision tables and condition builders are schema-aware — they know the types
and structure of available variables and provide autocomplete accordingly.

```
Variable sources (resolved in order):
  1. Workflow trigger payload     → {{trigger.fieldName}}
  2. Previous node outputs        → {{stepId.fieldName}}
  3. Data model fields            → {{modelName.fieldName}} (from AppModel)
  4. Upstream decision outputs    → {{decisionNodeId.outputColumn}}
  5. System variables             → {{system.currentUser}}, {{system.now}}, {{system.orgId}}

Schema registry (platform-side):
  - Extracts field names + types from AppModel data models
  - Extracts output schemas from workflow nodes and decision tables
  - Provides autocomplete suggestions with type info to the expression editor
  - Validates expression type compatibility at save time
```

### 14.8 Integration Points

```
Decision tables are usable from three contexts:

1. Standalone Rules
   Rules Editor → Decision Tables tab → create/edit decision table
   Generated as: src/domain/{module}/decisions/{decisionName}.ts
   Called from: API routes, business logic, computed fields

2. Workflow Decision Nodes
   Workflow Editor → drag DecisionNode → configure inline decision table
   Evaluated by: workflow engine during execution (see Section 15)
   Outputs: written to workflow variables, available to downstream nodes

3. Enhanced Condition Nodes
   Workflow Editor → ConditionNode → toggle to expression mode
   Uses FEEL-lite expressions instead of structured field/operator/value
   Backwards compatible: existing structured conditions still work

All three contexts share the same FEEL-lite parser and decision table evaluator.
```

---

## 15. Workflow Engine

### 15.1 Runtime Structure

```typescript
// Generated in app: src/workflows/runtime.ts

interface WorkflowDefinition {
  id: string;
  name: string;
  trigger: TriggerConfig;
  steps: StepDefinition[];
}

interface StepDefinition {
  id: string;
  type: "action" | "condition" | "decision" | "wait" | "assignment" | "approval" | "task_pool"
      | "escalation" | "ai_classify" | "ai_extract" | "ai_decide" | "ai_generate";
  actionFile?: string;          // path to action function
  condition?: string;           // FEEL-lite expression for condition nodes
  decisionTableId?: string;     // reference to decision table definition
  decisionTable?: DecisionTableDefinition;  // inline decision table (for embedded tables)
  thenStep?: string;            // step ID for true branch
  elseStep?: string;            // step ID for false branch
  nextStep?: string;            // step ID for normal flow
  onErrorStep?: string;         // step ID for error handling
  outputMapping?: Record<string, string>;   // map decision outputs to workflow variables
  config: Record<string, any>;  // action-specific configuration
}

type TriggerConfig =
  | { type: "api_event"; event: string }
  | { type: "schedule"; cron: string }
  | { type: "db_change"; model: string; field?: string; condition?: string }
  | { type: "webhook"; path: string }
  | { type: "manual"; name: string };

// Executor
async function executeWorkflow(
  workflow: WorkflowDefinition,
  triggerData: Record<string, any>,
): Promise<ExecutionLog> {
  const context = { trigger: triggerData };
  const log: ExecutionLog = { workflowId: workflow.id, steps: [], startedAt: new Date() };

  let currentStepId = workflow.steps[0]?.id;

  while (currentStepId) {
    const step = workflow.steps.find(s => s.id === currentStepId);
    if (!step) break;

    const stepLog: StepLog = { stepId: step.id, startedAt: new Date(), status: "running" };

    try {
      if (step.type === "condition") {
        // FEEL-lite expression evaluation (supports arbitrary expressions)
        const result = evaluateFEELExpression(step.condition!, context);
        stepLog.result = { conditionResult: result };
        currentStepId = result ? step.thenStep : step.elseStep;
      } else if (step.type === "decision") {
        // Decision table evaluation — multi-row rule matching with hit policies
        const table = step.decisionTable ?? await loadDecisionTable(step.decisionTableId!);
        const result = evaluateDecisionTable(table, context);
        // Write decision outputs to workflow context
        if (step.outputMapping && !Array.isArray(result.outputs)) {
          for (const [outputCol, varName] of Object.entries(step.outputMapping)) {
            context[varName] = result.outputs[outputCol];
          }
        }
        context[step.id] = result.outputs;
        stepLog.result = { matchedRules: result.matched.map(r => r.id), outputs: result.outputs };
        currentStepId = step.nextStep;
      } else if (step.type === "action") {
        const actionFn = await import(step.actionFile!);
        const result = await actionFn.default(context, step.config);
        context[step.id] = result;
        stepLog.result = result;
        currentStepId = step.nextStep;
      } else if (step.type === "wait") {
        // For MVP: just delay. Later: persist and resume.
        await delay(step.config.durationMs);
        currentStepId = step.nextStep;
      }

      stepLog.status = "completed";
    } catch (error) {
      stepLog.status = "failed";
      stepLog.error = error.message;
      currentStepId = step.onErrorStep || undefined;
    }

    stepLog.completedAt = new Date();
    log.steps.push(stepLog);
  }

  log.completedAt = new Date();
  return log;
}
```

### 15.2 Trigger Registration

```typescript
// Generated in app: src/workflows/triggers.ts
// This file is auto-generated based on workflow definitions

import { executeWorkflow } from "./runtime";
import { loadWorkflowDefinitions } from "./definitions";
const workflows = loadWorkflowDefinitions();

// API event triggers — called from API routes
export async function onEvent(eventName: string, data: Record<string, any>) {
  const matching = workflows.filter(
    w => w.trigger.type === "api_event" && w.trigger.event === eventName
  );
  for (const wf of matching) {
    // Run asynchronously (don't block the API response)
    executeWorkflow(wf, data).catch(err =>
      console.error(`Workflow ${wf.name} failed:`, err)
    );
  }
}

// Schedule triggers — registered via cron
// In production, use a proper scheduler. For dev, use node-cron.
import cron from "node-cron";

for (const wf of workflows.filter(w => w.trigger.type === "schedule")) {
  cron.schedule(wf.trigger.cron, () => {
    executeWorkflow(wf, { scheduledAt: new Date() });
  });
}
```

---

## 16. Database Management

### 16.1 Schema Changes (via Data Model Editor)

```
User adds field → Instruction → LLM edits schema.ts → drizzle-kit push → column added
User changes type → Instruction → LLM edits schema.ts + writes migration SQL → applied
User deletes field → Instruction → LLM removes from code (keeps column in DB)
User adds relation → Instruction → LLM adds foreign key + references()
User adds index → Instruction → LLM adds .index() in schema
```

### 16.2 Seed Data Management

```
Seed data lives in src/infrastructure/db/seed.ts.
It's idempotent — checks before inserting.
Visual editor: table UI where users can add/edit/delete seed rows.
"Generate realistic data" button → LLM generates 10-20 rows of realistic data.
"Reset database" → drops all data, re-runs seed.
```

### 16.3 Data Browser Endpoints

```
GET  /api/projects/:id/db/tables          → list tables (via information_schema)
GET  /api/projects/:id/db/tables/:name    → get table schema
GET  /api/projects/:id/db/query?sql=...   → execute SELECT (read-only)
POST /api/projects/:id/db/query           → execute INSERT/UPDATE/DELETE
POST /api/projects/:id/db/seed            → re-run seed script
POST /api/projects/:id/db/reset           → docker compose down -v, up, push, seed
```

---

## 17. Authentication & Authorization

### 17.1 Platform Auth (who uses the builder)

```
Simple email/password auth via JWT.
Stored in platform PostgreSQL (platform_users table).
JWT in HttpOnly cookie, contains: {userId, orgId, platformRole}
Middleware on all /api/ routes except /api/auth/*.
Org-scoped: all API routes resolve the current org from JWT or URL.
```

### 17.2 Generated App Auth (org-aware)

```
Generated apps authenticate against the org's people directory.
Users don't create accounts per-app — they exist at the org level.

How it works:
  1. Platform maintains org_people with all end-users
  2. When an app is generated, the Code Generator creates:
     - NextAuth.js v5 configuration
     - Auth syncs from platform org_people (via API or embedded JWT)
     - Login page (email/password or SSO depending on org settings)
     - Auth middleware for protected routes
     - Role resolver: maps org roles → app-level permissions
     - Field access middleware: filters response fields per role
     - Record scope middleware: filters query by department/team ownership
     - Session includes: {userId, orgRoles, appRoles, departmentId, teamId, managerId}

  3. On each request the middleware:
     a. Validates JWT → gets userId
     b. Loads user's org roles and app roles from context
     c. For read requests: filters out fields the user can't view
     d. For write requests: validates field-level edit permissions
     e. For list requests: applies record-scope filter (e.g., department-only)

  4. Auth data flow:
     Platform (org_people, org_roles, field_access_policies)
       → synced to generated app on preview start / deploy
       → stored in generated app's own PostgreSQL (users, roles, policies tables)
       → runtime enforcement via middleware + Drizzle query filters

The org structure is the source of truth.
Generated apps consume it, they don't define it.
```

### 17.3 Multi-App SSO

```
Within an organization, all generated apps share identity:
  - User logs into the org portal once
  - Session token is valid across all apps in the org
  - Apps resolve user identity from the shared token
  - No separate registration per app

Implementation:
  - Org portal issues JWT with orgId + userId
  - Each app validates JWT against shared secret (set in org settings)
  - Apps that need extra app-specific claims can enrich the session
    from their own roles/permissions table
```

---

## 18. Real-time & Collaboration

### 18.1 Preview Hot-Reload Communication

```
When an agent makes code changes:
  1. Agent edits files → Next.js HMR detects file changes → iframe auto-refreshes
  2. Platform sends WebSocket message to frontend: {type: "files_changed", paths: [...]}
  3. Frontend refreshes:
     - File tree (re-fetches file list)
     - Code editor (re-reads current file)
     - AppModel store (re-fetches app-model.json)
     - Visual editors (re-read their relevant data)
```

### 18.2 Future: Multi-User Collaboration

```
Not in MVP. Future addition:
  - WebSocket room per project
  - Operational transform or CRDT for concurrent edits
  - Cursor presence (see who's editing what)
  - Lock visual editor sections to prevent conflicts
  - Chat is naturally multi-user
```

---

## 19. Deployment & Export

### 19.1 Export Options

```
ZIP Download:
  - Everything needed to run the app
  - docker-compose.yml for Postgres
  - README with setup instructions
  - npm install && npm run dev works out of the box

Git Repository:
  - Initialize git repo in output dir
  - Every agent change is a commit
  - User can push to their own remote

Docker Image:
  - Generate production Dockerfile
  - Multi-stage build (build + runtime)
  - docker-compose.production.yml with proper configs
```

### 19.2 Production Dockerfile (generated)

```dockerfile
# Generated in the app: Dockerfile

FROM node:22-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
```

---

## 20. AI Agent Builder

### 20.1 Overview

The AI Agent Builder lets users create intelligent agents that live inside their generated apps. These agents can use the app's own API endpoints as tools, query the app's database, trigger workflows, and interact with users through embedded chat interfaces.

```
Key Insight: Since Tentoro Forge already generates full-stack apps with APIs,
databases, and workflows, an AI agent inside a generated app can use
the app's own endpoints as tools — no external integration needed.

Example:
  User says: "Add an AI assistant that can check inventory levels,
              create purchase orders, and alert me when items are low"

  Tentoro Forge:
    1. Generates agent definition (prompt, tools, config)
    2. Auto-registers /api/products, /api/purchase-orders as agent tools
    3. Connects low-stock workflow as an agent-triggerable action
    4. Generates chat UI component embedded in the app
    5. Sets up conversation history table in the app's PostgreSQL
```

### 20.2 Agent Architecture in Generated Apps

```
┌─────────────────────────────────────────────────┐
│                  Generated App                   │
│                                                  │
│  ┌──────────┐    ┌──────────────┐               │
│  │ Chat UI  │───▶│ /api/agents/ │               │
│  │ Component│◀───│ chat         │               │
│  └──────────┘    └──────┬───────┘               │
│                         │                        │
│                  ┌──────▼───────┐                │
│                  │ Agent Runtime│                │
│                  │              │                │
│                  │ ┌──────────┐ │                │
│                  │ │ System   │ │                │
│                  │ │ Prompt   │ │                │
│                  │ └──────────┘ │                │
│                  │ ┌──────────┐ │  ┌──────────┐ │
│                  │ │ Tool     │─┼─▶│ App APIs │ │
│                  │ │ Registry │ │  └──────────┘ │
│                  │ └──────────┘ │                │
│                  │ ┌──────────┐ │  ┌──────────┐ │
│                  │ │ Memory   │─┼─▶│ PostgreSQL│ │
│                  │ │ Manager  │ │  └──────────┘ │
│                  │ └──────────┘ │                │
│                  │ ┌──────────┐ │  ┌──────────┐ │
│                  │ │Guardrails│─┼─▶│ Rules    │ │
│                  │ │          │ │  │ Engine   │ │
│                  │ └──────────┘ │  └──────────┘ │
│                  └──────────────┘                │
└─────────────────────────────────────────────────┘
```

### 20.3 Agent Definition Schema

```json
// src/agents/definitions/{agent-name}.json — defines agents in the generated app

{
  "agents": [
    {
      "id": "support-agent",
      "name": "Customer Support",
      "description": "Handles customer inquiries, order status, and ticket creation",
      "enabled": true,

      "model": {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "maxTokens": 2048,
        "temperature": 0.3
      },

      "systemPrompt": "You are a helpful customer support agent for {{appName}}.\n\nYou can help customers with:\n- Checking order status\n- Creating support tickets\n- Answering product questions\n- Processing returns and refunds\n\n## Rules\n- Always be polite and professional\n- Never share other customers' data\n- If you can't help, offer to escalate to a human agent\n- Always verify the customer's identity before sharing order details\n\n## Available Data\nYou have access to the following through your tools:\n- Orders (read-only)\n- Products (read-only)\n- Support tickets (read + create)\n- Customer profile (read-only, current user only)",

      "tools": [
        {
          "name": "get_order",
          "description": "Look up an order by ID or order number",
          "source": "api",
          "method": "GET",
          "route": "/api/orders/:id",
          "paramMapping": {"id": "orderId"},
          "responseFilter": ["id", "status", "items", "total", "createdAt"]
        },
        {
          "name": "list_orders",
          "description": "List recent orders for the current customer",
          "source": "api",
          "method": "GET",
          "route": "/api/orders",
          "defaultParams": {"limit": 10, "sort": "createdAt:desc"},
          "responseFilter": ["id", "status", "total", "createdAt"]
        },
        {
          "name": "create_ticket",
          "description": "Create a new support ticket",
          "source": "api",
          "method": "POST",
          "route": "/api/tickets",
          "inputSchema": {
            "subject": {"type": "string", "required": true, "maxLength": 200},
            "description": {"type": "string", "required": true},
            "priority": {"type": "enum", "values": ["low", "medium", "high"], "default": "medium"},
            "category": {"type": "enum", "values": ["order", "product", "billing", "technical", "other"]}
          }
        },
        {
          "name": "search_products",
          "description": "Search products by name or category",
          "source": "api",
          "method": "GET",
          "route": "/api/products",
          "paramMapping": {"query": "search"},
          "responseFilter": ["id", "name", "description", "price", "inStock"]
        },
        {
          "name": "search_faq",
          "description": "Search the knowledge base for relevant articles",
          "source": "custom",
          "file": "src/agents/tools/search-faq.ts",
          "inputSchema": {
            "query": {"type": "string", "required": true}
          }
        }
      ],

      "memory": {
        "type": "conversation",
        "maxMessages": 50,
        "summarizeAfter": 30,
        "persistTable": "agent_conversations"
      },

      "guardrails": {
        "inputValidation": {
          "maxLength": 2000,
          "blockPatterns": ["(?i)ignore previous instructions", "(?i)system prompt"],
          "requireAuth": true
        },
        "outputValidation": {
          "maxTokens": 2000,
          "blockPatterns": ["(?i)password", "(?i)ssn", "(?i)credit.?card.?number"],
          "contentFilter": "standard"
        },
        "toolPermissions": {
          "get_order": {"requireAuth": true, "rateLimit": "10/min"},
          "create_ticket": {"requireAuth": true, "rateLimit": "5/min"},
          "search_products": {"rateLimit": "20/min"},
          "search_faq": {"rateLimit": "20/min"}
        },
        "escalation": {
          "trigger": "user requests human agent OR agent confidence < 0.3",
          "action": "create_ticket with category='escalation' and transfer message"
        }
      },

      "ui": {
        "chatRoute": "/support/chat",
        "widgetPosition": "bottom-right",
        "widgetTitle": "Need help?",
        "widgetSubtitle": "Chat with our AI assistant",
        "avatar": "/images/support-bot.svg",
        "welcomeMessage": "Hi! I'm here to help. What can I assist you with today?",
        "suggestedQuestions": [
          "Where is my order?",
          "I need to return an item",
          "How do I change my address?"
        ],
        "theme": "inherit"
      }
    }
  ],

  "multiAgent": {
    "enabled": false,
    "router": {
      "model": "claude-haiku-4-5-20251001",
      "prompt": "Route the user's message to the most appropriate agent based on the topic.",
      "agents": ["support-agent", "sales-agent"]
    }
  }
}
```

### 20.4 Agent Runtime (in Generated App)

```typescript
// src/agents/runtime.ts — core agent execution engine

import Anthropic from '@anthropic-ai/sdk';
import { db } from '@/infrastructure/db/connection';
import { agentConversations, agentMessages } from '@/infrastructure/db/schema';
import { loadAgentDefinition } from './definitions';
import { resolveTools } from './tools/registry';
import { validateInput, validateOutput } from './guardrails';
import { getConversationHistory, saveMessage, summarizeIfNeeded } from './memory';
import { eq, desc } from 'drizzle-orm';

const anthropic = new Anthropic();

interface AgentResponse {
  message: string;
  toolCalls?: Array<{name: string; input: Record<string, unknown>; result: unknown}>;
  conversationId: string;
}

export async function runAgent(
  agentId: string,
  userMessage: string,
  conversationId: string | null,
  userId: string
): Promise<ReadableStream> {
  const agent = loadAgentDefinition(agentId);
  if (!agent || !agent.enabled) throw new Error(`Agent ${agentId} not found or disabled`);

  // Input validation
  const inputCheck = validateInput(userMessage, agent.guardrails.inputValidation);
  if (!inputCheck.valid) {
    return streamResponse(`I'm sorry, I can't process that request. ${inputCheck.reason}`);
  }

  // Get or create conversation
  const convId = conversationId ?? await createConversation(agentId, userId);

  // Load conversation history
  const history = await getConversationHistory(convId, agent.memory.maxMessages);

  // Resolve tools (convert API route references to Anthropic tool format)
  const tools = resolveTools(agent.tools, userId);

  // Build messages
  const messages = [
    ...history.map(m => ({role: m.role, content: m.content})),
    {role: 'user' as const, content: userMessage}
  ];

  // Save user message
  await saveMessage(convId, 'user', userMessage);

  // Create streaming response
  return new ReadableStream({
    async start(controller) {
      try {
        let fullResponse = '';
        const toolResults: Array<{name: string; input: any; result: any}> = [];

        // Agentic loop — keep running until no more tool calls
        let currentMessages = messages;
        while (true) {
          const stream = await anthropic.messages.stream({
            model: agent.model.model,
            max_tokens: agent.model.maxTokens,
            temperature: agent.model.temperature,
            system: agent.systemPrompt.replace('{{appName}}', process.env.APP_NAME ?? 'the application'),
            messages: currentMessages,
            tools: tools,
          });

          let hasToolUse = false;
          let assistantContent: any[] = [];

          for await (const event of stream) {
            if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
              fullResponse += event.delta.text;
              controller.enqueue(new TextEncoder().encode(
                `data: ${JSON.stringify({type: 'text', content: event.delta.text})}\n\n`
              ));
            }
          }

          const finalMessage = await stream.finalMessage();
          assistantContent = finalMessage.content;

          // Check for tool use
          const toolUseBlocks = assistantContent.filter((b: any) => b.type === 'tool_use');
          if (toolUseBlocks.length === 0) break; // No tool calls, we're done

          hasToolUse = true;

          // Execute each tool call
          const toolResultBlocks = [];
          for (const toolUse of toolUseBlocks) {
            controller.enqueue(new TextEncoder().encode(
              `data: ${JSON.stringify({type: 'tool_call', tool: toolUse.name, input: toolUse.input})}\n\n`
            ));

            // Check tool permissions
            const permission = agent.guardrails.toolPermissions?.[toolUse.name];
            if (permission?.requireAuth && !userId) {
              toolResultBlocks.push({
                type: 'tool_result' as const,
                tool_use_id: toolUse.id,
                content: 'Error: Authentication required for this action.',
                is_error: true
              });
              continue;
            }

            // Execute the tool
            try {
              const result = await executeTool(toolUse.name, toolUse.input, agent.tools, userId);
              toolResults.push({name: toolUse.name, input: toolUse.input, result});
              toolResultBlocks.push({
                type: 'tool_result' as const,
                tool_use_id: toolUse.id,
                content: JSON.stringify(result)
              });
            } catch (error: any) {
              toolResultBlocks.push({
                type: 'tool_result' as const,
                tool_use_id: toolUse.id,
                content: `Error: ${error.message}`,
                is_error: true
              });
            }
          }

          // Continue the conversation with tool results
          currentMessages = [
            ...currentMessages,
            {role: 'assistant' as const, content: assistantContent},
            {role: 'user' as const, content: toolResultBlocks}
          ];
        }

        // Output validation
        const outputCheck = validateOutput(fullResponse, agent.guardrails.outputValidation);
        if (!outputCheck.valid) {
          fullResponse = "I apologize, but I'm unable to provide that information. Please contact support directly.";
        }

        // Save assistant response
        await saveMessage(convId, 'assistant', fullResponse, toolResults);

        // Summarize conversation if needed
        await summarizeIfNeeded(convId, agent.memory);

        // Send completion
        controller.enqueue(new TextEncoder().encode(
          `data: ${JSON.stringify({type: 'done', conversationId: convId})}\n\n`
        ));
        controller.close();
      } catch (error: any) {
        controller.enqueue(new TextEncoder().encode(
          `data: ${JSON.stringify({type: 'error', message: error.message})}\n\n`
        ));
        controller.close();
      }
    }
  });
}
```

### 20.5 Tool Registry (in Generated App)

```typescript
// src/agents/tools/registry.ts — auto-registers app API routes as agent tools

import { type Tool } from '@anthropic-ai/sdk';

interface AgentToolDef {
  name: string;
  description: string;
  source: 'api' | 'custom';
  method?: string;
  route?: string;
  file?: string;
  paramMapping?: Record<string, string>;
  inputSchema?: Record<string, {type: string; required?: boolean; values?: string[]; default?: any; maxLength?: number}>;
  responseFilter?: string[];
}

export function resolveTools(toolDefs: AgentToolDef[], userId: string): Tool[] {
  return toolDefs.map(def => ({
    name: def.name,
    description: def.description,
    input_schema: buildInputSchema(def)
  }));
}

function buildInputSchema(def: AgentToolDef): Record<string, unknown> {
  if (def.inputSchema) {
    const properties: Record<string, unknown> = {};
    const required: string[] = [];
    for (const [key, val] of Object.entries(def.inputSchema)) {
      if (val.type === 'enum') {
        properties[key] = {type: 'string', enum: val.values, description: key};
      } else {
        properties[key] = {type: val.type, description: key};
        if (val.maxLength) (properties[key] as any).maxLength = val.maxLength;
      }
      if (val.required) required.push(key);
    }
    return {type: 'object', properties, required};
  }

  // For API-sourced tools, infer from route params
  if (def.source === 'api' && def.route) {
    const params = def.route.match(/:(\w+)/g)?.map(p => p.slice(1)) ?? [];
    const properties: Record<string, unknown> = {};
    for (const p of params) {
      properties[def.paramMapping?.[p] ?? p] = {type: 'string', description: p};
    }
    return {type: 'object', properties, required: params};
  }

  return {type: 'object', properties: {}};
}

export async function executeTool(
  toolName: string,
  input: Record<string, unknown>,
  toolDefs: AgentToolDef[],
  userId: string
): Promise<unknown> {
  const def = toolDefs.find(t => t.name === toolName);
  if (!def) throw new Error(`Unknown tool: ${toolName}`);

  if (def.source === 'api') {
    // Call the app's own API route internally
    let url = def.route!;
    // Replace route params
    for (const [key, value] of Object.entries(input)) {
      const routeParam = Object.entries(def.paramMapping ?? {}).find(([_, v]) => v === key)?.[0] ?? key;
      url = url.replace(`:${routeParam}`, String(value));
    }

    // Build query params for GET requests
    const baseUrl = process.env.NEXT_PUBLIC_APP_URL ?? 'http://localhost:3000';
    const fullUrl = new URL(url, baseUrl);
    if (def.method === 'GET') {
      for (const [key, value] of Object.entries({...def.defaultParams, ...input})) {
        if (!url.includes(`:${key}`)) {
          fullUrl.searchParams.set(key, String(value));
        }
      }
    }

    const response = await fetch(fullUrl.toString(), {
      method: def.method ?? 'GET',
      headers: {
        'Content-Type': 'application/json',
        'X-Agent-User-Id': userId // Pass user context for access control
      },
      ...(def.method !== 'GET' ? {body: JSON.stringify(input)} : {})
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status} ${response.statusText}`);
    }

    const data = await response.json();

    // Apply response filter
    if (def.responseFilter && Array.isArray(data)) {
      return data.map((item: any) => filterObject(item, def.responseFilter!));
    } else if (def.responseFilter && typeof data === 'object') {
      return filterObject(data, def.responseFilter);
    }
    return data;
  }

  if (def.source === 'custom') {
    // Dynamic import of custom tool
    const toolModule = await import(`@/${def.file!.replace('src/', '')}`);
    return toolModule.default(input, {userId});
  }

  throw new Error(`Unknown tool source: ${def.source}`);
}

function filterObject(obj: Record<string, unknown>, fields: string[]): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const field of fields) {
    if (field in obj) result[field] = obj[field];
  }
  return result;
}
```

### 20.6 Agent Memory System

```typescript
// src/agents/memory.ts — conversation persistence and context management

import { db } from '@/infrastructure/db/connection';
import { agentConversations, agentMessages } from '@/infrastructure/db/schema';
import { eq, desc, count } from 'drizzle-orm';
import Anthropic from '@anthropic-ai/sdk';

interface MemoryConfig {
  type: 'conversation';
  maxMessages: number;
  summarizeAfter: number;
  persistTable: string;
}

export async function getConversationHistory(
  conversationId: string,
  maxMessages: number
): Promise<Array<{role: 'user' | 'assistant'; content: string}>> {
  const messages = await db
    .select()
    .from(agentMessages)
    .where(eq(agentMessages.conversationId, conversationId))
    .orderBy(desc(agentMessages.createdAt))
    .limit(maxMessages);

  // Check if there's a summary for older messages
  const conversation = await db
    .select()
    .from(agentConversations)
    .where(eq(agentConversations.id, conversationId))
    .limit(1);

  const history: Array<{role: 'user' | 'assistant'; content: string}> = [];

  // Prepend summary as system context if exists
  if (conversation[0]?.summary) {
    history.push({
      role: 'user',
      content: `[Previous conversation summary: ${conversation[0].summary}]`
    });
    history.push({
      role: 'assistant',
      content: 'Understood, I have context from our previous conversation.'
    });
  }

  // Add recent messages (reversed to chronological order)
  history.push(...messages.reverse().map(m => ({
    role: m.role as 'user' | 'assistant',
    content: m.content
  })));

  return history;
}

export async function saveMessage(
  conversationId: string,
  role: 'user' | 'assistant',
  content: string,
  toolCalls?: Array<{name: string; input: any; result: any}>
): Promise<void> {
  await db.insert(agentMessages).values({
    conversationId,
    role,
    content,
    toolCalls: toolCalls ? JSON.stringify(toolCalls) : null,
    createdAt: new Date()
  });
}

export async function summarizeIfNeeded(
  conversationId: string,
  config: MemoryConfig
): Promise<void> {
  const messageCount = await db
    .select({count: count()})
    .from(agentMessages)
    .where(eq(agentMessages.conversationId, conversationId));

  if (messageCount[0].count < config.summarizeAfter) return;

  // Get all messages
  const messages = await db
    .select()
    .from(agentMessages)
    .where(eq(agentMessages.conversationId, conversationId))
    .orderBy(agentMessages.createdAt);

  // Keep last N messages, summarize the rest
  const toSummarize = messages.slice(0, -config.maxMessages);
  if (toSummarize.length === 0) return;

  const anthropic = new Anthropic();
  const summaryResponse = await anthropic.messages.create({
    model: 'claude-haiku-4-5-20251001',
    max_tokens: 500,
    messages: [{
      role: 'user',
      content: `Summarize this conversation in 2-3 sentences, focusing on key facts, decisions, and context that would be needed for future messages:\n\n${toSummarize.map(m => `${m.role}: ${m.content}`).join('\n')}`
    }]
  });

  const summary = summaryResponse.content[0].type === 'text'
    ? summaryResponse.content[0].text : '';

  // Update conversation summary and delete summarized messages
  await db.update(agentConversations)
    .set({summary})
    .where(eq(agentConversations.id, conversationId));

  const idsToDelete = toSummarize.map(m => m.id);
  for (const id of idsToDelete) {
    await db.delete(agentMessages).where(eq(agentMessages.id, id));
  }
}
```

### 20.7 Agent Guardrails

```typescript
// src/agents/guardrails.ts — input/output validation and content filtering

interface InputValidation {
  maxLength: number;
  blockPatterns: string[];
  requireAuth: boolean;
}

interface OutputValidation {
  maxTokens: number;
  blockPatterns: string[];
  contentFilter: 'none' | 'standard' | 'strict';
}

interface ValidationResult {
  valid: boolean;
  reason?: string;
}

export function validateInput(input: string, rules: InputValidation): ValidationResult {
  // Length check
  if (input.length > rules.maxLength) {
    return {valid: false, reason: `Message too long (max ${rules.maxLength} characters)`};
  }

  // Injection pattern check
  for (const pattern of rules.blockPatterns) {
    if (new RegExp(pattern).test(input)) {
      return {valid: false, reason: 'Message contains disallowed content'};
    }
  }

  return {valid: true};
}

export function validateOutput(output: string, rules: OutputValidation): ValidationResult {
  // PII/sensitive data pattern check
  for (const pattern of rules.blockPatterns) {
    if (new RegExp(pattern).test(output)) {
      return {valid: false, reason: 'Response contains potentially sensitive information'};
    }
  }

  // Content filter
  if (rules.contentFilter === 'strict') {
    // Additional checks for strict mode
    const sensitivePatterns = [
      /\b\d{3}-\d{2}-\d{4}\b/,      // SSN
      /\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b/, // Credit card
      /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/ // Email (if not needed)
    ];
    for (const pat of sensitivePatterns) {
      if (pat.test(output)) {
        return {valid: false, reason: 'Response may contain sensitive data'};
      }
    }
  }

  return {valid: true};
}
```

### 20.8 Agent Database Schema (in Generated App)

```typescript
// Added to src/infrastructure/db/schema.ts when agents are present

import { pgTable, uuid, text, varchar, timestamp, jsonb, pgEnum } from 'drizzle-orm/pg-core';

export const agentConversations = pgTable('agent_conversations', {
  id: uuid('id').primaryKey().defaultRandom(),
  agentId: varchar('agent_id', {length: 100}).notNull(),
  userId: uuid('user_id').references(() => users.id),
  summary: text('summary'),                    // Rolling summary of older messages
  metadata: jsonb('metadata'),                 // Custom metadata
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull(),
});

export const messageRoleEnum = pgEnum('message_role', ['user', 'assistant']);

export const agentMessages = pgTable('agent_messages', {
  id: uuid('id').primaryKey().defaultRandom(),
  conversationId: uuid('conversation_id').references(() => agentConversations.id, {onDelete: 'cascade'}).notNull(),
  role: messageRoleEnum('role').notNull(),
  content: text('content').notNull(),
  toolCalls: jsonb('tool_calls'),              // [{name, input, result}]
  tokenCount: integer('token_count'),          // For usage tracking
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

// Indexes
// idx_agent_conv_user (userId, createdAt DESC) — for listing user's conversations
// idx_agent_msg_conv (conversationId, createdAt) — for loading conversation history
```

### 20.9 Agent API Routes (in Generated App)

```typescript
// src/app/api/agents/[agentId]/chat/route.ts

import { NextRequest } from 'next/server';
import { runAgent } from '@/agents/runtime';
import { getAuthUser } from '@/infrastructure/auth/middleware';

export async function POST(
  request: NextRequest,
  { params }: { params: { agentId: string } }
) {
  const user = await getAuthUser(request);
  const { message, conversationId } = await request.json();

  if (!message || typeof message !== 'string') {
    return Response.json({error: 'Message is required'}, {status: 400});
  }

  const stream = await runAgent(
    params.agentId,
    message,
    conversationId ?? null,
    user?.id ?? 'anonymous'
  );

  return new Response(stream, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
    }
  });
}

// GET — list conversations for current user
export async function GET(
  request: NextRequest,
  { params }: { params: { agentId: string } }
) {
  const user = await getAuthUser(request);
  if (!user) return Response.json({error: 'Unauthorized'}, {status: 401});

  const conversations = await db
    .select({
      id: agentConversations.id,
      createdAt: agentConversations.createdAt,
      updatedAt: agentConversations.updatedAt,
      summary: agentConversations.summary,
    })
    .from(agentConversations)
    .where(
      and(
        eq(agentConversations.agentId, params.agentId),
        eq(agentConversations.userId, user.id)
      )
    )
    .orderBy(desc(agentConversations.updatedAt))
    .limit(50);

  return Response.json(conversations);
}
```

### 20.10 Agent Chat UI Component (in Generated App)

```typescript
// src/components/agents/ChatWidget.tsx — embeddable chat widget

'use client';

import { useState, useRef, useEffect } from 'react';
import { MessageCircle, X, Send, Loader2, Bot, User } from 'lucide-react';

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  toolCalls?: Array<{name: string; input: any; result: any}>;
  streaming?: boolean;
}

interface ChatWidgetProps {
  agentId: string;
  title?: string;
  subtitle?: string;
  position?: 'bottom-right' | 'bottom-left' | 'full-page';
  welcomeMessage?: string;
  suggestedQuestions?: string[];
}

export function ChatWidget({
  agentId,
  title = 'AI Assistant',
  subtitle = 'How can I help?',
  position = 'bottom-right',
  welcomeMessage,
  suggestedQuestions = []
}: ChatWidgetProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>(
    welcomeMessage ? [{role: 'assistant', content: welcomeMessage}] : []
  );
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({behavior: 'smooth'});
  }, [messages]);

  const sendMessage = async (text: string) => {
    if (!text.trim() || isStreaming) return;

    const userMessage: ChatMessage = {role: 'user', content: text};
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setIsStreaming(true);

    // Add placeholder for assistant response
    setMessages(prev => [...prev, {role: 'assistant', content: '', streaming: true}]);

    try {
      const response = await fetch(`/api/agents/${agentId}/chat`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({message: text, conversationId})
      });

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let fullText = '';

      while (reader) {
        const {done, value} = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split('\n').filter(l => l.startsWith('data: '));

        for (const line of lines) {
          const data = JSON.parse(line.slice(6));

          if (data.type === 'text') {
            fullText += data.content;
            setMessages(prev => {
              const updated = [...prev];
              updated[updated.length - 1] = {
                role: 'assistant',
                content: fullText,
                streaming: true
              };
              return updated;
            });
          }

          if (data.type === 'tool_call') {
            // Show tool call indicator
            setMessages(prev => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              last.toolCalls = [...(last.toolCalls ?? []), {
                name: data.tool,
                input: data.input,
                result: null
              }];
              return updated;
            });
          }

          if (data.type === 'done') {
            setConversationId(data.conversationId);
          }
        }
      }

      // Mark as no longer streaming
      setMessages(prev => {
        const updated = [...prev];
        updated[updated.length - 1].streaming = false;
        return updated;
      });
    } catch (error) {
      setMessages(prev => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          role: 'assistant',
          content: 'Sorry, something went wrong. Please try again.',
          streaming: false
        };
        return updated;
      });
    }

    setIsStreaming(false);
  };

  if (position === 'full-page') {
    return (
      <div className="flex flex-col h-full">
        <ChatHeader title={title} subtitle={subtitle} />
        <ChatMessages messages={messages} messagesEndRef={messagesEndRef} />
        {messages.length === 1 && suggestedQuestions.length > 0 && (
          <SuggestedQuestions questions={suggestedQuestions} onSelect={sendMessage} />
        )}
        <ChatInput
          input={input}
          setInput={setInput}
          onSend={() => sendMessage(input)}
          isStreaming={isStreaming}
          inputRef={inputRef}
        />
      </div>
    );
  }

  // Floating widget mode
  return (
    <>
      {/* Toggle button */}
      {!isOpen && (
        <button
          onClick={() => setIsOpen(true)}
          className={`fixed ${position === 'bottom-right' ? 'right-6' : 'left-6'} bottom-6
            w-14 h-14 rounded-full bg-primary text-white shadow-lg
            flex items-center justify-center hover:scale-105 transition-transform z-50`}
        >
          <MessageCircle className="w-6 h-6" />
        </button>
      )}

      {/* Chat window */}
      {isOpen && (
        <div className={`fixed ${position === 'bottom-right' ? 'right-6' : 'left-6'} bottom-6
          w-[400px] h-[600px] bg-white rounded-2xl shadow-2xl border
          flex flex-col overflow-hidden z-50`}>
          <ChatHeader title={title} subtitle={subtitle} onClose={() => setIsOpen(false)} />
          <ChatMessages messages={messages} messagesEndRef={messagesEndRef} />
          {messages.length <= 1 && suggestedQuestions.length > 0 && (
            <SuggestedQuestions questions={suggestedQuestions} onSelect={sendMessage} />
          )}
          <ChatInput
            input={input}
            setInput={setInput}
            onSend={() => sendMessage(input)}
            isStreaming={isStreaming}
            inputRef={inputRef}
          />
        </div>
      )}
    </>
  );
}

// Sub-components: ChatHeader, ChatMessages, ChatInput, SuggestedQuestions
// (standard chat UI patterns — header with title, scrollable message list,
//  input bar with send button, suggested question chips)
```

### 20.11 Agent Builder Visual Editor (in Tentoro Forge Platform)

```
Library: React Flow

The Agent Builder visual editor lets users design agent behavior visually.
Like all visual editors, actions produce instructions → LLM generates code.

Canvas Layout:
┌─────────────────────────────────────────────────────────┐
│ Agent Builder: Customer Support                    [▶ Test] │
├──────────┬──────────────────────────────┬───────────────┤
│          │                              │               │
│ Node     │     ┌──────────┐             │  Properties   │
│ Palette  │     │ System   │             │  Panel        │
│          │     │ Prompt   │             │               │
│ ┌──────┐ │     └────┬─────┘             │ Name: ...     │
│ │Prompt│ │          │                   │ Model: ...    │
│ └──────┘ │     ┌────▼─────┐             │ Temp: 0.3     │
│ ┌──────┐ │     │ Router   │             │               │
│ │Tool  │ │     │ (intent) │             │ System Prompt │
│ └──────┘ │     └──┬────┬──┘             │ ┌───────────┐ │
│ ┌──────┐ │        │    │                │ │ You are...│ │
│ │Guard │ │   ┌────▼┐ ┌─▼────┐           │ │           │ │
│ └──────┘ │   │Order│ │Ticket│           │ └───────────┘ │
│ ┌──────┐ │   │Tools│ │Tools │           │               │
│ │Memory│ │   └─────┘ └──────┘           │ Tools: 5      │
│ └──────┘ │                              │ Memory: conv  │
│ ┌──────┐ │                              │ Guardrails: 3 │
│ │Human │ │                              │               │
│ └──────┘ │                              │               │
│ ┌──────┐ │                              │               │
│ │Handof│ │                              │               │
│ └──────┘ │                              │               │
├──────────┴──────────────────────────────┴───────────────┤
│ Test Console (expandable)                               │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ User: Where is my order #1234?                      │ │
│ │ Agent: [calling get_order(id: 1234)]                │ │
│ │ Agent: Your order #1234 is currently being shipped  │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘

Node Types:
  SystemPromptNode (purple, brain icon):
    - Rich text editor for the system prompt
    - Variable interpolation: {{appName}}, {{userName}}
    - Every agent starts with one, cannot be deleted

  ToolNode (blue, wrench icon):
    - Select from app's API routes (auto-discovered from AppModel)
    - Or define custom tool (name, description, input schema, handler file)
    - Configure: response filter, rate limit, auth requirement
    - Drag from API routes list → creates ToolNode automatically

  GuardrailNode (red, shield icon):
    - Input validation rules (max length, block patterns)
    - Output validation rules (PII filter, content filter level)
    - Tool-specific permissions (auth, rate limit per tool)
    - Escalation rules (when to hand off to human)

  MemoryNode (green, database icon):
    - Conversation history settings (max messages, summarization threshold)
    - Knowledge base toggle (enable pgvector for RAG)
    - File upload support (PDFs, docs → chunked + embedded)

  HumanHandoffNode (orange, user icon):
    - Trigger conditions (user request, low confidence, specific topics)
    - Handoff action (create ticket, send notification, transfer chat)
    - Return flow (agent resumes after human resolves)

  RouterNode (yellow, git-branch icon):
    - Multi-agent: route to different agents based on topic
    - Configure routing prompt and agent list
    - Fallback agent if no match

Edge Types:
  Flow (solid): normal execution path
  Condition (dashed): conditional routing
  Error (dotted red): error handling path

Properties Panel (right sidebar):
  - Changes based on selected node
  - Immediate preview of prompt changes
  - Tool test button (try a tool with sample input)
  - "Apply" button → builds instruction → sends to Agent Builder agent
```

### 20.12 Agent Builder Instruction Builder

```typescript
// frontend/src/lib/instruction.ts — add to existing instruction builder

// --- Agent Editor Actions ---

interface AgentCreate {
  editor: "agent";
  action: "create_agent";
  name: string;
  description: string;
  model: string;
  systemPrompt: string;
  tools: Array<{
    name: string;
    source: 'api' | 'custom';
    route?: string;
    description: string;
  }>;
  memory: {type: 'conversation'; maxMessages: number};
  chatPosition: 'bottom-right' | 'bottom-left' | 'full-page';
}

interface AgentUpdatePrompt {
  editor: "agent";
  action: "update_prompt";
  agentId: string;
  newPrompt: string;
}

interface AgentAddTool {
  editor: "agent";
  action: "add_tool";
  agentId: string;
  tool: {
    name: string;
    source: 'api' | 'custom';
    route?: string;
    description: string;
    inputSchema?: Record<string, unknown>;
  };
}

interface AgentRemoveTool {
  editor: "agent";
  action: "remove_tool";
  agentId: string;
  toolName: string;
}

interface AgentUpdateGuardrails {
  editor: "agent";
  action: "update_guardrails";
  agentId: string;
  guardrails: {
    inputValidation?: Partial<InputValidation>;
    outputValidation?: Partial<OutputValidation>;
    toolPermissions?: Record<string, {requireAuth?: boolean; rateLimit?: string}>;
  };
}

interface AgentConfigureMemory {
  editor: "agent";
  action: "configure_memory";
  agentId: string;
  memory: {
    maxMessages: number;
    summarizeAfter: number;
    enableKnowledgeBase?: boolean;
  };
}

interface AgentAddHandoff {
  editor: "agent";
  action: "add_handoff";
  fromAgentId: string;
  toAgentId: string;
  condition: string;
}

// Instruction builder for agent actions
function buildAgentInstruction(action: AgentEditorAction): string {
  switch (action.action) {
    case "create_agent": {
      return `Create a new AI agent called "${action.name}".

Description: ${action.description}
Model: ${action.model}

System Prompt:
"""
${action.systemPrompt}
"""

Tools: ${action.tools.map(t =>
  t.source === 'api'
    ? `${t.name} (API: ${t.route}) — ${t.description}`
    : `${t.name} (custom) — ${t.description}`
).join('\n')}

Memory: ${action.memory.type}, max ${action.memory.maxMessages} messages

Generate the following files:
1. Create agent definition at src/agents/definitions/{agent-name}.json
2. Create any custom tool files needed in src/agents/tools/
3. Add agent_conversations and agent_messages tables to src/infrastructure/db/schema.ts (if not present)
4. Create the chat API route at src/app/api/agents/${action.name.toLowerCase().replace(/\s+/g, '-')}/chat/route.ts
5. Create a ChatWidget component at src/components/agents/${action.name.replace(/\s+/g, '')}Chat.tsx
6. Add the chat widget to the appropriate page (position: ${action.chatPosition})
7. If src/agents/runtime.ts doesn't exist, create the agent runtime, tool registry, memory, and guardrails modules`;
    }

    case "add_tool": {
      return `Add a new tool "${action.tool.name}" to agent "${action.agentId}".
Source: ${action.tool.source}${action.tool.route ? `, Route: ${action.tool.route}` : ''}
Description: ${action.tool.description}
Update the agent definition in src/agents/definitions/.
${action.tool.source === 'custom' ? `Create a custom tool handler at src/agents/tools/${action.tool.name.replace(/_/g, '-')}.ts` : ''}`;
    }

    case "update_prompt": {
      return `Update the system prompt for agent "${action.agentId}" to:
"""
${action.newPrompt}
"""
Update the agent definition in src/agents/definitions/.`;
    }

    // ... more cases follow the same pattern
  }
}
```

### 20.13 Platform Agent #11: Agent Builder

```python
# backend/agents/agent_builder.py

AGENT_BUILDER_SYSTEM_PROMPT = """You are a developer creating AI agents within an existing
Next.js + TypeScript application. You generate all the code needed for an AI agent to run
inside the generated app.

## What You Generate

When creating a new agent:
1. Agent definition in src/agents/definitions/{agent-name}.json
2. Agent runtime (src/agents/runtime.ts) — if not already present
3. Tool registry (src/agents/tools/registry.ts) — if not already present
4. Memory manager (src/agents/memory.ts) — if not already present
5. Guardrails (src/agents/guardrails.ts) — if not already present
6. Custom tool handlers (src/agents/tools/*.ts) — for non-API tools
7. Database tables for conversations (update src/infrastructure/db/schema.ts)
8. Chat API route (src/app/api/agents/[agentId]/chat/route.ts)
9. Chat UI component (src/components/agents/*Chat.tsx)
10. Integration into the app's pages (add chat widget)

When modifying an agent:
- Update src/agents/definitions/{agent-name}.json for config changes (prompt, tools, guardrails)
- Update custom tool files for tool logic changes
- Update chat component for UI changes

## Rules

- The agent runtime calls the Anthropic API directly (not through our platform)
- The generated app must have @anthropic-ai/sdk in its package.json dependencies
- Agent tools should use the app's own API routes whenever possible
- Use streaming responses (SSE) for the chat API
- Conversation history is stored in the app's PostgreSQL database
- System prompts should be specific, include available tools, and set clear boundaries
- Always include basic guardrails: input length limit, prompt injection patterns, PII filter
- Rate limit all tools (sensible defaults: 10-20/min for reads, 5/min for writes)
- The agent should authenticate users through the app's existing auth system
- When creating the first agent, scaffold the full agent infrastructure (runtime, registry, etc.)
- When adding subsequent agents, only add the agent-specific files

## Agent Runtime Architecture

The runtime uses a simple agentic loop:
1. Build messages (history + new user message)
2. Call Anthropic API with streaming
3. If tool_use in response → execute tool → append result → go to step 2
4. If text response → stream to client → done

Tool execution calls the app's own API routes internally via fetch().
The X-Agent-User-Id header passes user context for access control.

## Database Tables

agent_conversations: id, agentId, userId, summary, metadata, createdAt, updatedAt
agent_messages: id, conversationId, role, content, toolCalls (jsonb), tokenCount, createdAt

## Test After Generation

After creating/modifying an agent:
1. Verify npm run build passes
2. Check that all imported modules exist
3. Verify the agent definition in src/agents/definitions/ is valid JSON
"""

AGENT_BUILDER_OPTIONS = ClaudeAgentOptions(
    system_prompt=AGENT_BUILDER_SYSTEM_PROMPT,
    allowed_tools=["Write", "Edit", "Read", "Bash", "Glob"],
    permission_mode="bypassPermissions",
    max_turns=30,
    model="claude-sonnet-4-20250514",
)
```

### 20.14 Multi-Agent Orchestration (in Generated App)

```
For apps with multiple agents, the runtime supports a router pattern:

┌────────────┐
│ User Input │
└─────┬──────┘
      │
┌─────▼──────┐     ┌──────────────┐
│   Router   │────▶│ Support Agent│  "I need help with my order"
│   Agent    │     └──────────────┘
│ (Haiku)    │
│            │     ┌──────────────┐
│            │────▶│ Sales Agent  │  "Tell me about pricing"
│            │     └──────────────┘
│            │
│            │     ┌──────────────┐
│            │────▶│ Admin Agent  │  "Show me today's revenue"
└────────────┘     └──────────────┘

Router Configuration (in src/agents/definitions/router.json):

{
  "multiAgent": {
    "enabled": true,
    "router": {
      "model": "claude-haiku-4-5-20251001",
      "prompt": "You are a message router. Based on the user's message, determine which
        agent should handle it. Respond with ONLY the agent ID.

        Available agents:
        - support-agent: Customer questions, orders, returns, complaints
        - sales-agent: Pricing, plans, features, demos, trials
        - admin-agent: Analytics, reports, settings, user management

        If unclear, default to support-agent.",
      "agents": ["support-agent", "sales-agent", "admin-agent"],
      "fallback": "support-agent"
    }
  }
}

The router runs as a quick Haiku call before the main agent.
Cost: ~$0.0001 per routing decision (negligible).
The conversation stays with the routed agent unless explicitly transferred.

Handoff Pattern:
  Agent A can hand off to Agent B mid-conversation:
  - Agent A returns a special tool_result: {"handoff": "agent-b", "reason": "...", "context": "..."}
  - Runtime detects handoff, switches to Agent B with context
  - Agent B picks up the conversation with full context
  - Conversation history is shared via the same conversationId
```

### 20.15 Agent Templates

```
Pre-built agent templates available in the Agent Builder:

1. Customer Support Bot
   - Tools: order lookup, ticket creation, FAQ search, product search
   - Guardrails: PII filter, auth required, escalation to human
   - Memory: conversation with summarization
   - UI: floating widget, bottom-right

2. Data Assistant
   - Tools: natural language SQL query, chart generation, export CSV
   - Guardrails: read-only DB access, query complexity limit, auth required
   - Memory: conversation (tracks query context)
   - UI: full-page chat with data visualization panel

3. Workflow Automation Agent
   - Tools: trigger workflows, check workflow status, list pending tasks
   - Guardrails: restricted to user's permitted workflows, audit log
   - Memory: conversation
   - UI: sidebar chat or slash commands in any page

4. Admin Copilot
   - Tools: all CRUD operations, user management, analytics queries
   - Guardrails: admin role required, audit log, confirmation for destructive ops
   - Memory: conversation with summarization
   - UI: command palette (Cmd+K) or full-page

5. Onboarding Guide
   - Tools: read app structure, check user progress, update user profile
   - Guardrails: read-only access, friendly tone enforcement
   - Memory: persistent per-user (remembers onboarding progress)
   - UI: slide-out panel, auto-appears for new users

Templates are selected in the Agent Builder UI and customized via the visual editor.
Each template pre-populates the system prompt, tools, guardrails, and UI config.
The user then customizes to their app's specific data models and workflows.
```

### 20.16 Knowledge Base (RAG) Support

```
For agents that need to search through documents, FAQs, or other knowledge:

Architecture:
  PostgreSQL + pgvector extension → vector similarity search

Setup (added to docker-compose.yml when knowledge base is enabled):
  - pgvector extension enabled in PostgreSQL
  - Embedding model: text-embedding-3-small (OpenAI) or local alternative
  - Chunk size: 512 tokens with 50-token overlap
  - Index: HNSW for fast approximate nearest neighbor search

Database Schema:
  knowledge_chunks:
    id: uuid
    agentId: varchar(100)
    source: varchar(500)         — file name, URL, or manual entry
    content: text                — the actual text chunk
    embedding: vector(1536)      — embedding vector
    metadata: jsonb              — {page, section, title, etc.}
    createdAt: timestamp

Ingestion Flow:
  1. User uploads document (PDF, DOCX, TXT, MD) in the Agent Builder
  2. Platform extracts text → chunks → embeds → stores in knowledge_chunks
  3. Agent's search_knowledge tool queries by vector similarity

Search Tool (auto-generated):
  name: search_knowledge
  description: "Search the knowledge base for relevant information"
  input: {query: string, limit?: number}
  implementation:
    1. Embed the query
    2. SELECT * FROM knowledge_chunks
       WHERE agent_id = $agentId
       ORDER BY embedding <=> $queryEmbedding
       LIMIT $limit
    3. Return top chunks as context

Note: Knowledge base is optional. Most agents work fine with just API tools.
Enable it when the agent needs to reference static documents, manuals, or FAQs.
```

### 20.17 Agent Analytics & Monitoring

```
Every generated app with agents includes a built-in agent dashboard:

Route: /admin/agents (protected, admin role required)

Dashboard shows:
  - Conversations per day (line chart)
  - Total messages / avg per conversation
  - Tool call frequency (bar chart by tool name)
  - Average response time (latency)
  - Error rate (failed tool calls, guardrail blocks)
  - Token usage and estimated cost
  - Escalation rate (human handoff frequency)

Conversation Inspector:
  - Browse all conversations
  - Filter by agent, user, date range, has-error
  - View full conversation with tool call details
  - Replay conversation step by step
  - Flag conversations for review

Data Source:
  All metrics are derived from the agent_messages table (no extra tracking needed)
  - token_count field tracks usage
  - tool_calls jsonb tracks tool activity
  - Guardrail blocks logged as system messages

Alert Rules (optional):
  - Error rate > 10% → notification
  - Escalation rate > 20% → notification
  - Token usage > daily budget → disable agent or switch to cheaper model
  - New unrecognized intent patterns → suggest new tools or prompt updates
```

---

## 21. AI-Powered Application Features

### 21.1 Overview

Beyond chatbot agents (Section 20), generated apps can embed LLM intelligence directly into their business logic. The platform recognizes when a user's requirement implies AI capabilities and automatically generates the necessary infrastructure.

```
Three Layers of AI in Generated Apps:

Layer 1: App Generation (Platform)
  → LLM builds the application code
  → Already covered in Sections 5-8

Layer 2: Conversational Agents (Agent Builder)
  → Chatbots/assistants running inside the app
  → Already covered in Section 20

Layer 3: Intelligent Features (THIS SECTION)
  → LLM embedded into the app's data processing, UI, and workflows
  → Smart fields, semantic search, content generation, AI decisions
  → The app itself becomes intelligent, not just the chatbot
```

### 21.2 How the Planner Recognizes AI Requirements

The Planner agent (Agent #1) is trained to detect natural language patterns that imply LLM intelligence and automatically include them in the structured plan.

```
User Says                              Planner Generates
─────────────────────────────────────  ──────────────────────────────
"auto-categorize support tickets"    → Smart Field: ai_classify
"summarize meeting notes"            → Smart Field: ai_summarize
"detect sentiment in reviews"        → Smart Field: ai_sentiment
"extract key info from emails"       → Smart Field: ai_extract
"generate product descriptions"      → Smart Field: ai_generate
"translate content to Spanish"       → Smart Field: ai_translate
"find similar products"              → Semantic Search component
"search with natural language"       → Semantic Search component
"smart recommendations"             → AI Recommendation component
"auto-tag content"                   → Smart Field: ai_classify (multi-label)
"detect duplicate entries"           → AI Rule: similarity_check
"moderate user content"              → AI Rule: content_moderation
"route tickets to the right team"    → Workflow AI Decision node
"predict delivery date"              → Smart Field: ai_predict
"score lead quality"                 → Smart Field: ai_score
"generate weekly summary report"     → Scheduled AI Generation
"smart form auto-fill"              → AI-Assisted Input component
```

### 21.3 Smart Fields

Smart Fields are data model fields whose values are computed by an LLM. They are triggered automatically when a record is created or updated.

```
Smart Field Types:

1. ai_classify — Categorize text into predefined labels
   Input: source field (text)
   Output: single label from a set
   Example: Ticket.description → Ticket.category (billing|technical|shipping|account)

2. ai_classify_multi — Multi-label classification
   Input: source field (text)
   Output: array of labels
   Example: Article.body → Article.tags (["react", "nextjs", "performance"])

3. ai_summarize — Generate a summary
   Input: source field (text) or multiple fields
   Output: summary text
   Example: Meeting.transcript → Meeting.summary (2-3 sentence summary)

4. ai_sentiment — Detect sentiment
   Input: source field (text)
   Output: enum (positive|negative|neutral|mixed) + confidence score
   Example: Review.text → Review.sentiment + Review.sentimentScore

5. ai_extract — Extract structured data from unstructured text
   Input: source field (text)
   Output: jsonb with extracted fields
   Example: Email.body → Email.extracted {name, company, phone, intent, urgency}

6. ai_generate — Generate content from other fields
   Input: multiple fields as context
   Output: generated text
   Example: Product.{name, specs, features} → Product.description (marketing copy)

7. ai_translate — Translate text to target language
   Input: source field (text) + target language
   Output: translated text
   Example: Article.body → Article.bodyEs (Spanish translation)

8. ai_score — Score/rank based on criteria
   Input: multiple fields
   Output: numeric score (0-100) + reasoning
   Example: Lead.{company, title, engagement} → Lead.qualityScore + Lead.scoreReason

9. ai_predict — Predict a value based on patterns
   Input: multiple fields + historical data
   Output: predicted value + confidence
   Example: Order.{items, shipping, warehouse} → Order.estimatedDelivery
```

#### Smart Field Schema in Plan Output

```json
{
  "data_models": [
    {
      "name": "SupportTicket",
      "fields": [
        {"name": "id", "type": "uuid", "constraints": ["pk", "auto"]},
        {"name": "subject", "type": "varchar(255)", "constraints": ["not_null"]},
        {"name": "description", "type": "text", "constraints": ["not_null"]},
        {"name": "category", "type": "varchar(50)", "constraints": [],
         "smart": {
           "type": "ai_classify",
           "source": "description",
           "labels": ["billing", "technical", "shipping", "account", "feature_request"],
           "trigger": "on_create"
         }
        },
        {"name": "priority", "type": "varchar(20)", "constraints": [],
         "smart": {
           "type": "ai_classify",
           "source": "description",
           "labels": ["low", "medium", "high", "critical"],
           "trigger": "on_create",
           "prompt": "Classify priority based on urgency indicators, impact scope, and emotional tone."
         }
        },
        {"name": "sentiment", "type": "varchar(20)", "constraints": [],
         "smart": {
           "type": "ai_sentiment",
           "source": "description",
           "trigger": "on_create"
         }
        },
        {"name": "summary", "type": "text", "constraints": [],
         "smart": {
           "type": "ai_summarize",
           "source": "description",
           "maxLength": 100,
           "trigger": "on_create"
         }
        },
        {"name": "extracted", "type": "jsonb", "constraints": [],
         "smart": {
           "type": "ai_extract",
           "source": "description",
           "fields": ["customerName", "accountNumber", "product", "errorMessage"],
           "trigger": "on_create"
         }
        }
      ]
    }
  ]
}
```

#### Smart Field Runtime (in Generated App)

```typescript
// src/infrastructure/ai/smart-fields.ts — LLM-powered field computation

import Anthropic from '@anthropic-ai/sdk';

const anthropic = new Anthropic();

interface SmartFieldConfig {
  type: string;
  source: string | string[];
  trigger: 'on_create' | 'on_update' | 'on_create_update' | 'manual';
  labels?: string[];
  fields?: string[];
  maxLength?: number;
  targetLanguage?: string;
  prompt?: string;
}

// Called from API routes after record creation/update
export async function computeSmartFields(
  record: Record<string, unknown>,
  smartFields: Record<string, SmartFieldConfig>
): Promise<Record<string, unknown>> {
  const results: Record<string, unknown> = {};

  // Batch all smart field computations into a single LLM call when possible
  const fieldsToCompute = Object.entries(smartFields);
  if (fieldsToCompute.length === 0) return results;

  // Build a combined prompt for all fields
  const sourceText = typeof smartFields[fieldsToCompute[0][0]].source === 'string'
    ? String(record[smartFields[fieldsToCompute[0][0]].source as string] ?? '')
    : (smartFields[fieldsToCompute[0][0]].source as string[])
        .map(s => `${s}: ${record[s] ?? ''}`).join('\n');

  const prompt = buildSmartFieldPrompt(record, fieldsToCompute);

  const response = await anthropic.messages.create({
    model: 'claude-haiku-4-5-20251001',  // Haiku for speed + cost efficiency
    max_tokens: 1024,
    messages: [{role: 'user', content: prompt}]
  });

  const text = response.content[0].type === 'text' ? response.content[0].text : '';

  // Parse structured response
  try {
    const parsed = JSON.parse(text);
    for (const [fieldName] of fieldsToCompute) {
      if (parsed[fieldName] !== undefined) {
        results[fieldName] = parsed[fieldName];
      }
    }
  } catch {
    // Fallback: run fields individually if batch parse fails
    for (const [fieldName, config] of fieldsToCompute) {
      results[fieldName] = await computeSingleField(record, fieldName, config);
    }
  }

  return results;
}

function buildSmartFieldPrompt(
  record: Record<string, unknown>,
  fields: [string, SmartFieldConfig][]
): string {
  let prompt = `Analyze the following record and compute the requested fields.
Respond with a JSON object containing the results for each field.

Record:
${JSON.stringify(record, null, 2)}

Compute these fields:\n`;

  for (const [fieldName, config] of fields) {
    switch (config.type) {
      case 'ai_classify':
        prompt += `\n"${fieldName}": Classify into ONE of: [${config.labels!.join(', ')}]`;
        if (config.prompt) prompt += ` — ${config.prompt}`;
        break;
      case 'ai_classify_multi':
        prompt += `\n"${fieldName}": Classify into ALL applicable labels from: [${config.labels!.join(', ')}]. Return as array.`;
        break;
      case 'ai_summarize':
        prompt += `\n"${fieldName}": Summarize in ${config.maxLength ?? 100} characters or less`;
        break;
      case 'ai_sentiment':
        prompt += `\n"${fieldName}": Classify sentiment as "positive", "negative", "neutral", or "mixed"`;
        break;
      case 'ai_extract':
        prompt += `\n"${fieldName}": Extract these fields: {${config.fields!.join(', ')}}. Return as object.`;
        break;
      case 'ai_generate':
        prompt += `\n"${fieldName}": Generate ${config.prompt ?? 'descriptive text'} based on the record fields`;
        break;
      case 'ai_translate':
        prompt += `\n"${fieldName}": Translate the source text to ${config.targetLanguage}`;
        break;
      case 'ai_score':
        prompt += `\n"${fieldName}": Score 0-100 based on ${config.prompt ?? 'quality/relevance'}. Return as number.`;
        break;
    }
  }

  prompt += '\n\nRespond with ONLY valid JSON, no explanation.';
  return prompt;
}
```

#### Integration with API Routes

```typescript
// Example: how smart fields are called in a generated API route
// src/app/api/tickets/route.ts — thin handler delegates to service

import { TicketService } from '@/application/support/ticket.service';
import { createTicketSchema } from '@/application/support/ticket.schema';

export async function POST(request: NextRequest) {
  const body = await request.json();
  const parsed = createTicketSchema.parse(body);
  const ticket = await TicketService.create(parsed, user.id);
  return Response.json(ticket, { status: 201 });
}

// The service handles DB insert + async smart field computation:
// src/application/support/ticket.service.ts
import { TicketRepository } from '@/infrastructure/db/repositories/ticket.repository';
import { computeSmartFields } from '@/infrastructure/ai/smart-fields';

export class TicketService {
  static async create(data: CreateTicketInput, userId: string) {
    const ticket = await TicketRepository.insert({ ...data, createdBy: userId });

    // Compute smart fields asynchronously (don't block the response)
    computeSmartFields(ticket, ticketSmartFields)
      .then(async (smartValues) => {
        await TicketRepository.update(ticket.id, smartValues);
      })
      .catch(err => console.error('Smart field computation failed:', err));

    return ticket;
  }
}
```

#### Smart Field UI Indicator

```
In the generated app's UI, smart fields have a visual indicator:

┌─────────────────────────────────────────────────────┐
│ Ticket #1234                                        │
│                                                     │
│ Subject: Can't access my account                    │
│ Description: I've been trying to log in for the...  │
│                                                     │
│ ✦ Category: account          (auto-classified)      │
│ ✦ Priority: high             (auto-classified)      │
│ ✦ Sentiment: negative        (auto-detected)        │
│ ✦ Summary: Customer unable to login, tried          │
│           password reset without success.            │
│                                                     │
│ [✎ Override]  [↻ Recompute]                         │
└─────────────────────────────────────────────────────┘

The ✦ icon indicates an AI-computed field.
Users can override the value manually if the AI got it wrong.
"Recompute" re-runs the LLM on the current source text.
```

### 21.4 Semantic Search

Beyond keyword search, generated apps can include semantic (meaning-based) search powered by embeddings and pgvector.

```
When the Planner sees requirements like:
  "find similar products"
  "search using natural language"
  "smart search"
  "content-aware search"

It generates:
  1. Embedding column on the searchable model (vector(1536))
  2. Embedding computation on create/update (via smart field trigger)
  3. Search API endpoint with hybrid search (keyword + semantic)
  4. Search UI component with natural language input
```

#### Semantic Search Runtime

```typescript
// src/infrastructure/ai/semantic-search.ts

import Anthropic from '@anthropic-ai/sdk';
import { db } from '@/infrastructure/db/connection';
import { sql } from 'drizzle-orm';

// Embedding via Anthropic's Voyager or OpenAI's text-embedding-3-small
// (configurable per project)
async function embed(text: string): Promise<number[]> {
  // Using Anthropic's embedding endpoint (or OpenAI if configured)
  const response = await fetch('https://api.openai.com/v1/embeddings', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${process.env.OPENAI_API_KEY}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      model: 'text-embedding-3-small',
      input: text
    })
  });
  const data = await response.json();
  return data.data[0].embedding;
}

export async function semanticSearch(
  table: string,
  query: string,
  options: {
    embeddingColumn?: string;
    textColumns?: string[];    // for keyword fallback
    limit?: number;
    threshold?: number;        // minimum similarity score
    filters?: Record<string, unknown>;
  } = {}
): Promise<Array<{record: any; score: number; matchType: 'semantic' | 'keyword'}>> {
  const {
    embeddingColumn = 'embedding',
    textColumns = ['name', 'description'],
    limit = 20,
    threshold = 0.3,
    filters = {}
  } = options;

  const queryEmbedding = await embed(query);

  // Hybrid search: semantic + keyword
  // Semantic: cosine similarity via pgvector
  // Keyword: PostgreSQL full-text search as fallback

  const results = await db.execute(sql`
    WITH semantic AS (
      SELECT *, 1 - (${sql.raw(embeddingColumn)} <=> ${JSON.stringify(queryEmbedding)}::vector) AS score,
             'semantic' AS match_type
      FROM ${sql.raw(table)}
      WHERE 1 - (${sql.raw(embeddingColumn)} <=> ${JSON.stringify(queryEmbedding)}::vector) > ${threshold}
      ORDER BY score DESC
      LIMIT ${limit}
    ),
    keyword AS (
      SELECT *, ts_rank(
        to_tsvector('english', ${sql.raw(textColumns.map(c => `COALESCE(${c}, '')`).join(" || ' ' || "))}),
        plainto_tsquery('english', ${query})
      ) AS score, 'keyword' AS match_type
      FROM ${sql.raw(table)}
      WHERE to_tsvector('english', ${sql.raw(textColumns.map(c => `COALESCE(${c}, '')`).join(" || ' ' || "))})
            @@ plainto_tsquery('english', ${query})
      LIMIT ${limit}
    )
    SELECT DISTINCT ON (id) * FROM (
      SELECT * FROM semantic
      UNION ALL
      SELECT * FROM keyword
    ) combined
    ORDER BY id, score DESC
    LIMIT ${limit}
  `);

  return results.rows;
}
```

#### Search UI Component

```
The generated search component supports both modes:

┌─────────────────────────────────────────────────┐
│ 🔍 Find products that are good for outdoor use  │
│                                  [⚡ AI Search]  │
├─────────────────────────────────────────────────┤
│ ✦ Waterproof Hiking Boots      score: 0.92      │
│   Durable boots for all-terrain outdoor...       │
│                                                  │
│ ✦ UV-Protection Sunglasses     score: 0.87      │
│   Polarized lenses for bright outdoor...         │
│                                                  │
│ ✦ Camping Backpack 65L         score: 0.84      │
│   Large capacity pack with rain cover...         │
│                                                  │
│ ─── Also matching by keyword ───                 │
│ • Outdoor Furniture Set        score: 0.65      │
│ • Garden Outdoor Lights        score: 0.52      │
└─────────────────────────────────────────────────┘

✦ = semantic match (meaning-based)
• = keyword match (text-based)
```

### 21.5 Workflow AI Nodes

The Workflow Engine (Section 15) gains new AI-powered node types that use LLM for intelligent decision-making within workflows.

```
New Workflow Node Types:

AI Classification Node (purple, brain icon):
  Input: data from previous step
  Config: classification labels, custom prompt
  Output: {label, confidence, reasoning}
  Example: Route incoming email to the right department

  ┌────────────────────────┐
  │ ⚡ AI Classify          │
  │                        │
  │ Input: {{trigger.body}}│
  │ Labels:                │
  │  • billing             │
  │  • technical           │
  │  • sales               │
  │  • hr                  │
  │ Confidence ≥ 0.7       │
  │                        │
  │ Output: {{step.label}} │
  └──────┬────┬────┬───┬───┘
    billing tech sales  hr

AI Extraction Node (purple, scan icon):
  Input: text data from previous step
  Config: fields to extract, output schema
  Output: structured object with extracted fields
  Example: Extract invoice details from email attachment

  ┌─────────────────────────┐
  │ ⚡ AI Extract            │
  │                         │
  │ Input: {{trigger.text}} │
  │ Extract:                │
  │  • invoiceNumber: string│
  │  • amount: number       │
  │  • vendor: string       │
  │  • dueDate: date        │
  │                         │
  │ Output: {{step.data}}   │
  └─────────┬───────────────┘

AI Decision Node (purple, git-branch icon):
  Input: context from workflow
  Config: decision prompt, options
  Output: chosen option + reasoning
  Example: Decide if a refund should be auto-approved or needs review

  ┌──────────────────────────────┐
  │ ⚡ AI Decision                │
  │                              │
  │ Context:                     │
  │  Order: {{trigger.order}}    │
  │  Customer: {{step1.customer}}│
  │  Reason: {{trigger.reason}}  │
  │                              │
  │ Question: Should this refund │
  │ be auto-approved?            │
  │                              │
  │ Options: approve | review    │
  │                              │
  │ Rules:                       │
  │  - Auto-approve if < $50     │
  │  - Auto-approve if loyal     │
  │    customer (>10 orders)     │
  │  - Review if > $200          │
  │  - Review if suspicious      │
  └────────┬─────────┬───────────┘
        approve    review

AI Generation Node (purple, sparkles icon):
  Input: context data
  Config: generation prompt, output format
  Output: generated text/content
  Example: Generate a personalized email response

  ┌────────────────────────────┐
  │ ⚡ AI Generate              │
  │                            │
  │ Prompt: Write a friendly   │
  │ response to the customer   │
  │ acknowledging their issue  │
  │ and providing the status   │
  │ update.                    │
  │                            │
  │ Context:                   │
  │  {{trigger.ticket}}        │
  │  {{step1.status}}          │
  │                            │
  │ Max length: 300 words      │
  │ Tone: professional, warm   │
  │                            │
  │ Output: {{step.text}}      │
  └────────────┬───────────────┘
```

#### Workflow AI Node Runtime

```typescript
// Added to src/workflows/runtime.ts — new step types

import Anthropic from '@anthropic-ai/sdk';

const anthropic = new Anthropic();

async function executeAIStep(
  step: StepDefinition,
  context: Record<string, any>
): Promise<Record<string, unknown>> {
  const resolvedConfig = resolveVariables(step.config, context);

  switch (step.type) {
    case 'ai_classify': {
      const response = await anthropic.messages.create({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 256,
        messages: [{
          role: 'user',
          content: `Classify the following into ONE of these categories: [${resolvedConfig.labels.join(', ')}]

${resolvedConfig.prompt ? `Instructions: ${resolvedConfig.prompt}\n` : ''}
Input: ${resolvedConfig.input}

Respond with JSON: {"label": "chosen_label", "confidence": 0.0-1.0, "reasoning": "brief explanation"}`
        }]
      });
      return JSON.parse(response.content[0].text);
    }

    case 'ai_extract': {
      const response = await anthropic.messages.create({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 512,
        messages: [{
          role: 'user',
          content: `Extract the following fields from this text:
Fields: ${JSON.stringify(resolvedConfig.fields)}

Text: ${resolvedConfig.input}

Respond with ONLY a JSON object containing the extracted values. Use null for fields you can't find.`
        }]
      });
      return {data: JSON.parse(response.content[0].text)};
    }

    case 'ai_decide': {
      const response = await anthropic.messages.create({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: 256,
        messages: [{
          role: 'user',
          content: `${resolvedConfig.prompt}

Context: ${JSON.stringify(resolvedConfig.context)}

Options: [${resolvedConfig.options.join(', ')}]

${resolvedConfig.rules ? `Rules:\n${resolvedConfig.rules.map((r: string) => `- ${r}`).join('\n')}` : ''}

Respond with JSON: {"decision": "chosen_option", "confidence": 0.0-1.0, "reasoning": "explanation"}`
        }]
      });
      return JSON.parse(response.content[0].text);
    }

    case 'ai_generate': {
      const response = await anthropic.messages.create({
        model: 'claude-haiku-4-5-20251001',
        max_tokens: resolvedConfig.maxTokens ?? 1024,
        messages: [{
          role: 'user',
          content: `${resolvedConfig.prompt}

Context: ${JSON.stringify(resolvedConfig.context)}

${resolvedConfig.tone ? `Tone: ${resolvedConfig.tone}` : ''}
${resolvedConfig.maxLength ? `Max length: ${resolvedConfig.maxLength} words` : ''}

Generate the content directly, no preamble.`
        }]
      });
      return {text: response.content[0].text};
    }
  }

  throw new Error(`Unknown AI step type: ${step.type}`);
}
```

### 21.6 AI-Assisted UI Components

Generated apps can include UI components that use LLM for enhanced user experience.

```
AI-Assisted Component Types:

1. SmartFormField — Auto-suggests values based on context
   ┌────────────────────────────────────────┐
   │ Product Description                    │
   │ ┌──────────────────────────────────┐   │
   │ │ Premium wireless headphones with │   │
   │ │ active noise cancellation...     │   │
   │ └──────────────────────────────────┘   │
   │ ✦ [Generate from name + specs]         │
   └────────────────────────────────────────┘
   - "Generate" button calls LLM to fill field from other form values
   - User can edit the generated text before saving

2. InlineAssistant — Writing helper for text areas
   ┌────────────────────────────────────────┐
   │ Reply to customer                      │
   │ ┌──────────────────────────────────┐   │
   │ │ Thank you for reaching out. I've │   │
   │ │ looked into your issue and...    │   │
   │ └──────────────────────────────────┘   │
   │ ✦ Improve  ✦ Shorten  ✦ More formal   │
   └────────────────────────────────────────┘
   - Quick action buttons for LLM-powered text transformations
   - Operates on the current text in the field

3. DataInsightsPanel — Auto-generated insights from data
   ┌────────────────────────────────────────┐
   │ ✦ Insights                        [↻]  │
   │                                        │
   │ • Revenue is up 12% from last month    │
   │ • 3 products are below reorder point   │
   │ • Customer satisfaction dropped in     │
   │   the "shipping" category              │
   │ • Top seller: Widget Pro (142 units)   │
   │                                        │
   │ [Ask a question about this data...]    │
   └────────────────────────────────────────┘
   - Reads aggregated data from the app's API
   - LLM generates natural language insights
   - Users can ask follow-up questions

4. SmartFilterBar — Natural language filtering
   ┌────────────────────────────────────────┐
   │ 🔍 Show me overdue orders over $500    │
   │                  that were placed last  │
   │                  month                  │
   │                           [⚡ Apply]    │
   ├────────────────────────────────────────┤
   │ Applied: status=overdue AND            │
   │          total>500 AND                 │
   │          createdAt>=2026-01-01 AND     │
   │          createdAt<=2026-01-31         │
   │                          [Clear all]   │
   └────────────────────────────────────────┘
   - LLM converts natural language to structured filters
   - Shows the interpreted filters for transparency
   - Users can clear or modify individual filters

5. NaturalLanguageQuery — Ask questions about app data
   ┌────────────────────────────────────────┐
   │ ✦ Ask about your data                  │
   │ ┌──────────────────────────────────┐   │
   │ │ What were our top 5 products by  │   │
   │ │ revenue last quarter?            │   │
   │ └──────────────────────────────────┘   │
   │                                        │
   │ Generated SQL:                         │
   │ SELECT p.name, SUM(oi.quantity *       │
   │   oi.unit_price) as revenue            │
   │ FROM products p JOIN order_items oi... │
   │                                        │
   │ Results:                               │
   │ ┌──────────────────────┬──────────┐   │
   │ │ Product              │ Revenue  │   │
   │ ├──────────────────────┼──────────┤   │
   │ │ Widget Pro           │ $14,200  │   │
   │ │ Gadget Max           │ $11,800  │   │
   │ │ Tool Deluxe          │ $9,450   │   │
   │ │ Part Standard        │ $7,200   │   │
   │ │ Component Basic      │ $6,100   │   │
   │ └──────────────────────┴──────────┘   │
   │                                        │
   │ ✦ Summary: Widget Pro leads with       │
   │   $14,200 in revenue, 20% more than   │
   │   the next product.                    │
   └────────────────────────────────────────┘
   - LLM reads the database schema from Drizzle
   - Generates safe, read-only SQL
   - Executes query and formats results
   - Adds natural language summary
   - Guards: read-only (SELECT only), query complexity limits,
     no access to sensitive columns (passwords, tokens)
```

### 21.7 AI Rules

The Rules Engine (Section 14) gains AI-powered rule types that use LLM for fuzzy, context-aware enforcement.

```
New Rule Types:

1. content_moderation — LLM-based content policy enforcement
   {
     "type": "ai_content_moderation",
     "model": "Review",
     "field": "body",
     "policy": "No hate speech, no spam, no personal attacks. Marketing links are OK.",
     "action": "flag",           // "flag" | "reject" | "redact"
     "enforce": ["api"]
   }

   How it works:
   - On create/update, the API route sends the field value to LLM
   - LLM evaluates against the policy
   - Returns: {allowed: bool, reason: string, confidence: float}
   - If not allowed: flag for review, reject with message, or redact offending content

2. similarity_check — Detect near-duplicate records
   {
     "type": "ai_similarity_check",
     "model": "Product",
     "fields": ["name", "description"],
     "threshold": 0.85,
     "action": "warn",           // "warn" | "block" | "merge_suggest"
     "enforce": ["api", "ui"]
   }

   How it works:
   - On create, compute embedding of the new record
   - Query pgvector for records above similarity threshold
   - If found: warn user ("Similar product exists: Widget Pro"),
     block creation, or suggest merging

3. ai_validation — Complex validation that can't be expressed as a simple rule
   {
     "type": "ai_validation",
     "model": "Expense",
     "fields": ["description", "amount", "category", "receipt"],
     "prompt": "Validate that the expense description matches the category and
       the amount is reasonable for the category. Flag suspicious patterns like
       round numbers over $500 or luxury items categorized as office supplies.",
     "action": "flag",
     "enforce": ["api"]
   }

4. ai_enrichment — Auto-enrich records with external context
   {
     "type": "ai_enrichment",
     "model": "Lead",
     "triggerField": "email",
     "enrichFields": ["companyName", "industry", "companySize", "linkedinUrl"],
     "prompt": "Based on the email domain, infer the company and fill in available details.",
     "enforce": ["api"]
   }
```

### 21.8 Scheduled AI Tasks

Generated apps can include scheduled LLM tasks that run periodically.

```
Scheduled Task Types:

1. Periodic Summary Report
   Config: {
     schedule: "0 9 * * 1",           // Every Monday at 9am
     type: "ai_summary_report",
     dataQuery: "SELECT * FROM orders WHERE created_at > NOW() - INTERVAL '7 days'",
     prompt: "Generate a weekly sales summary highlighting trends, top products, and concerns",
     deliverTo: "email:admin@company.com",
     format: "markdown"
   }

2. Anomaly Detection
   Config: {
     schedule: "0 */6 * * *",          // Every 6 hours
     type: "ai_anomaly_detection",
     dataQuery: "SELECT * FROM transactions WHERE created_at > NOW() - INTERVAL '6 hours'",
     prompt: "Identify any unusual patterns: sudden spikes, amounts far from average,
       unusual timing, or suspicious sequences",
     action: "create_alert",
     threshold: "medium"               // low | medium | high sensitivity
   }

3. Data Quality Check
   Config: {
     schedule: "0 2 * * *",            // Daily at 2am
     type: "ai_data_quality",
     tables: ["customers", "products", "orders"],
     checks: ["missing_required", "inconsistent_formats", "orphaned_records",
       "duplicate_detection", "value_outliers"],
     action: "create_report"
   }

Implementation: These are generated as workflow definitions with a schedule trigger
and an AI Generation node. No new runtime infrastructure needed — they use the
existing Workflow Engine (Section 15) + Workflow AI Nodes (Section 21.5).
```

### 21.9 AI Configuration in Generated Apps

```
Every generated app with AI features includes:

1. src/infrastructure/ai/config.ts — Central AI configuration
   {
     provider: "anthropic",
     models: {
       fast: "claude-haiku-4-5-20251001",      // Smart fields, classification, extraction
       standard: "claude-sonnet-4-20250514",    // Complex generation, decisions
     },
     embedding: {
       provider: "openai",                      // or "local" for self-hosted
       model: "text-embedding-3-small",
       dimensions: 1536
     },
     rateLimits: {
       smartFields: "100/min",                  // Per-model rate limit
       search: "50/min",
       generation: "20/min",
       nlQuery: "10/min"
     },
     costTracking: true,                        // Log token usage per feature
     fallback: {
       onError: "skip",                         // "skip" | "retry" | "default_value"
       retryAttempts: 2,
       retryDelayMs: 1000
     }
   }

2. src/infrastructure/ai/usage.ts — Token usage tracking
   - Logs every LLM call: model, tokens_in, tokens_out, feature, cost_usd
   - Stored in ai_usage_log table
   - Dashboard shows cost breakdown by feature type
   - Budget alerts when daily/monthly spend exceeds threshold

3. Environment variables:
   ANTHROPIC_API_KEY=sk-ant-...
   OPENAI_API_KEY=sk-...              # For embeddings (if using OpenAI)
   AI_RATE_LIMIT_PER_MINUTE=100
   AI_MONTHLY_BUDGET_USD=50
   AI_FALLBACK_ON_ERROR=skip
```

### 21.10 AppModel Index — AI Features Section

```json
// Added to app-model.json

"aiFeatures": {
  "smartFields": [
    {
      "model": "SupportTicket",
      "field": "category",
      "type": "ai_classify",
      "source": "description",
      "labels": ["billing", "technical", "shipping", "account"],
      "trigger": "on_create",
      "model_used": "claude-haiku-4-5-20251001"
    },
    {
      "model": "SupportTicket",
      "field": "summary",
      "type": "ai_summarize",
      "source": "description",
      "trigger": "on_create",
      "model_used": "claude-haiku-4-5-20251001"
    }
  ],

  "semanticSearch": [
    {
      "model": "Product",
      "embeddingColumn": "embedding",
      "sourceColumns": ["name", "description"],
      "searchRoute": "/api/products/search"
    }
  ],

  "aiComponents": [
    {
      "type": "NaturalLanguageQuery",
      "page": "/dashboard",
      "component": "DataQueryPanel",
      "file": "src/components/shared/DataQueryPanel.tsx"
    },
    {
      "type": "SmartFilterBar",
      "page": "/orders",
      "component": "OrderFilters",
      "file": "src/components/orders/OrderFilters.tsx"
    }
  ],

  "workflowAINodes": [
    {
      "workflow": "wf-ticket-routing",
      "node": "classify-department",
      "type": "ai_classify",
      "labels": ["billing", "technical", "sales"]
    }
  ],

  "aiRules": [
    {
      "id": "r-content-mod",
      "type": "ai_content_moderation",
      "model": "Review",
      "field": "body"
    }
  ],

  "scheduledAI": [
    {
      "name": "Weekly Sales Summary",
      "schedule": "0 9 * * 1",
      "type": "ai_summary_report"
    }
  ],

  "config": {
    "primaryModel": "claude-haiku-4-5-20251001",
    "embeddingModel": "text-embedding-3-small",
    "costTrackingEnabled": true,
    "monthlyBudget": 50
  }
}
```

### 21.11 AI Features Visual Editor (in Tentoro Forge Platform)

```
A dedicated panel in the Data Model Editor and Workflow Editor for configuring
AI features — no separate editor needed.

In Data Model Editor — Smart Field Configuration:
  When clicking a field in the ERD, the properties panel shows:

  ┌─ Field Properties ─────────────────────┐
  │ Name: category                         │
  │ Type: varchar(50)                      │
  │ Constraints: □ not_null  □ unique      │
  │                                        │
  │ ═══ AI Smart Field ═══                 │
  │ ☑ Enable AI computation                │
  │                                        │
  │ Type: [ai_classify      ▾]            │
  │ Source field: [description ▾]          │
  │ Labels: billing, technical, shipping   │
  │         account, feature_request       │
  │ Trigger: [on_create ▾]                │
  │ Custom prompt: (optional)              │
  │ ┌──────────────────────────────────┐   │
  │ │ Classify based on urgency        │   │
  │ │ indicators and customer impact   │   │
  │ └──────────────────────────────────┘   │
  │                                        │
  │ [Test with sample data]                │
  │ Input: "I can't access my account"     │
  │ Result: "account" (confidence: 0.94)   │
  │                                        │
  │ [Apply]                                │
  └────────────────────────────────────────┘

In Workflow Editor — AI Node Configuration:
  (Already covered in Section 21.5 — AI nodes appear in the node palette
   alongside regular action/condition nodes)

In Rules Editor — AI Rule Configuration:
  When creating a new rule, "AI Rules" appears as a rule category:

  ┌─ New Rule ─────────────────────────────┐
  │ Category: [AI Rules    ▾]              │
  │ Type: [Content Moderation ▾]           │
  │                                        │
  │ Model: [Review ▾]                      │
  │ Field: [body   ▾]                      │
  │ Policy:                                │
  │ ┌──────────────────────────────────┐   │
  │ │ No hate speech, no spam, no      │   │
  │ │ personal attacks. Marketing      │   │
  │ │ links are OK if relevant.        │   │
  │ └──────────────────────────────────┘   │
  │ Action: [Flag for review ▾]           │
  │ Enforce at: ☑ API  □ UI              │
  │                                        │
  │ [Test with sample]                     │
  │ Input: "This product is terrible..."   │
  │ Result: ✓ Allowed (negative but valid) │
  │                                        │
  │ [Save Rule]                            │
  └────────────────────────────────────────┘

Dashboard Page — AI Features Overview:
  Route: /projects/[id]/ai (or tab within Settings)

  ┌─ AI Features ──────────────────────────┐
  │                                        │
  │ Smart Fields (5 active)                │
  │  SupportTicket.category  ai_classify   │
  │  SupportTicket.priority  ai_classify   │
  │  SupportTicket.sentiment ai_sentiment  │
  │  SupportTicket.summary   ai_summarize  │
  │  Product.description     ai_generate   │
  │                                        │
  │ Semantic Search (1 model)              │
  │  Product — name, description           │
  │                                        │
  │ AI Workflow Nodes (2 active)           │
  │  ticket-routing: classify-department   │
  │  refund-flow: auto-approve-decision    │
  │                                        │
  │ AI Rules (1 active)                    │
  │  content-moderation on Review.body     │
  │                                        │
  │ ── Usage (this month) ──               │
  │  Tokens: 245,000 in / 89,000 out      │
  │  Cost: $3.20 / $50.00 budget           │
  │  Calls: 1,247 (avg 24ms latency)      │
  │  Errors: 3 (0.2%)                     │
  └────────────────────────────────────────┘
```

---

## 22. Organization & Multi-Tenancy

### 22.1 Overview

Tentoro Forge is a multi-tenant platform. Developers create organizations, define their org structure (departments, teams, roles, reporting lines), and build multiple apps within the org. All apps share the same identity system — end users don't create separate accounts per app.

```
Tentoro Forge Platform (multi-tenant SaaS)
│
├── Organization: Acme Corp (Tenant 1)
│   ├── Org Structure
│   │   ├── Departments: Sales, Engineering, Finance, HR
│   │   ├── Teams: Sales-East, Sales-West, Dev-Frontend, Dev-Backend
│   │   ├── Users: 150 employees
│   │   ├── Roles: staff, lead, manager, director, VP, CEO
│   │   └── Groups: Audit Committee, Safety Team, Product Council
│   │
│   ├── RBAC Policies (span all apps)
│   │   ├── App access: which roles can access which apps
│   │   ├── Field access: which roles can see/edit which fields
│   │   ├── Record scope: which records are visible (dept/team/user scoped)
│   │   └── Workflow assignments: which roles handle which approvals
│   │
│   ├── App: Inventory Management
│   │   ├── Own PostgreSQL database (Docker Compose)
│   │   ├── Users synced from org (filtered by app access policies)
│   │   ├── Field-level access enforced in API routes
│   │   └── Workflows assign tasks to org users/roles
│   │
│   ├── App: Expense Tracker
│   ├── App: CRM
│   └── App: HR Portal
│
├── Organization: Beta Inc (Tenant 2)
│   └── Completely separate org, users, apps
│
└── Organization: Gamma Ltd (Tenant 3)
    └── ...
```

### 22.2 Organization Lifecycle

```
1. Developer signs up to Tentoro Forge (platform_users)
2. Developer creates Organization (organizations)
3. Developer sets up org structure:
   a. Upload CSV of people (name, email, department, title, manager)
   b. OR manually add via org chart editor
   c. OR sync from AD/LDAP/HR system (future)
4. System auto-creates default roles: admin, manager, staff, viewer
5. Developer customizes roles, creates groups
6. Developer creates first app → Planner reads org structure → auto-infers RBAC
7. App is generated with org-aware auth, field access, workflow assignments
8. End-users are invited or synced → they log into the org portal
9. Org portal shows apps the user has access to
10. User clicks an app → authenticated with org identity, sees only permitted data
```

### 22.3 Org Structure Data Model

```
The org structure is stored in the platform database (not in generated apps).
Generated apps consume it via sync on preview start / deploy.

Entity Relationships:

Organization (1) ──── (N) Department
Department   (1) ──── (N) Department (self-referencing: sub-departments)
Department   (1) ──── (N) Team
Department   (1) ──── (N) OrgPerson (belongs to)
Team         (1) ──── (N) OrgPerson (belongs to)
OrgPerson    (1) ──── (N) OrgPerson (manager → reports)
OrgPerson    (N) ──── (M) OrgRole (person has roles)
OrgPerson    (N) ──── (M) OrgGroup (person belongs to groups)
Organization (1) ──── (N) OrgRole
Organization (1) ──── (N) OrgGroup
Organization (1) ──── (N) Project (org has apps)

Key attributes:

OrgPerson:
  - email, name, title, avatarUrl
  - departmentId (which department they belong to)
  - teamId (which team, optional)
  - managerId (who they report to → org chart hierarchy)
  - status: active | inactive | invited
  - metadata: jsonb (phone, location, hireDate, custom fields)

OrgRole:
  - name (admin, manager, staff, viewer, or custom)
  - level (integer: 0=lowest, higher=more authority)
  - isSystem (true for default roles, can't be deleted)

Department:
  - name, parentId (hierarchy), headUserId (department head)
  - metadata: jsonb (cost center, location, etc.)
```

### 22.4 Org Chart Visual Editor

```
Library: React Flow
Location: /orgs/[orgId]/org-chart

┌─────────────────────────────────────────────────────────────────┐
│ Org Chart: Acme Corp                    [Import CSV] [+ Person] │
├────────┬────────────────────────────────────────────┬───────────┤
│        │                                            │           │
│ Dept   │           ┌────────────┐                   │Properties │
│ Filter │           │  CEO       │                   │           │
│        │           │ John Smith │                   │Name: ...  │
│ □ All  │           └─────┬──────┘                   │Title: ... │
│ ■ Sales│        ┌────────┼────────┐                 │Dept: [▾]  │
│ □ Eng  │   ┌────▼─────┐ ┌▼──────┐ ┌▼──────────┐    │Manager:[▾]│
│ □ Fin  │   │VP Sales  │ │VP Eng │ │VP Finance │    │Role: [▾]  │
│ □ HR   │   │Jane Doe  │ │Bob Lee│ │Sara Kim   │    │Email: ... │
│        │   └──┬───┬───┘ └──┬────┘ └──┬────────┘    │           │
│ View:  │   ┌──▼┐ ┌▼──┐  ┌─▼──┐   ┌──▼──┐          │ Roles:    │
│ ○ Tree │   │SA │ │SB │  │Dev │   │Acct │          │ ☑ manager │
│ ● Chart│   │5pp│ │4pp│  │12pp│   │6pp  │          │ □ admin   │
│ ○ List │   └───┘ └───┘  └────┘   └─────┘          │ □ finance │
│        │                                            │           │
├────────┴────────────────────────────────────────────┴───────────┤
│ Drag person between departments to restructure.                 │
│ Click person to view/edit properties. Right-click for actions.  │
└─────────────────────────────────────────────────────────────────┘

Interactions:
  - Drag person → different department/team: updates departmentId/teamId
  - Drag person → under another person: changes managerId (reporting line)
  - Click person → properties panel shows details, inline edit
  - Right-click person → Change manager, Change dept, Deactivate, Remove
  - Right-click department → Add sub-department, Add team, Rename, Delete
  - "+ Person" button → form: name, email, title, department, manager, roles
  - "Import CSV" → upload dialog with column mapping preview

CSV Import Format:
  name,email,title,department,team,manager_email,role
  "Alice Smith","alice@acme.com","Sales Rep","Sales","Sales-East","jane@acme.com","staff"
  "Bob Jones","bob@acme.com","Senior Dev","Engineering","Backend","bob.lee@acme.com","lead"

Import Preview:
  ┌─ Import Preview (47 people) ─────────────────────────────┐
  │ Column Mapping:                                          │
  │  name → Name ✓    email → Email ✓   title → Title ✓     │
  │  department → Department ✓   manager_email → Manager ✓   │
  │                                                          │
  │ New departments to create: 2 (Marketing, Legal)          │
  │ New people: 32    Updates: 15    Skipped: 0              │
  │ Unresolved managers: 1 (ceo@acme.com — not in file)      │
  │                                                          │
  │ [Cancel]  [Import]                                       │
  └──────────────────────────────────────────────────────────┘
```

### 22.5 RBAC Architecture

Three layers of access control compose together:

```
Layer 1: Org-Level Roles
━━━━━━━━━━━━━━━━━━━━━
  Defines WHO the person is in the organization.
  Set once, applies across all apps.

  Default roles (auto-created per org):
    admin    (level: 100) — full access to everything
    director (level: 80)  — department-level authority
    manager  (level: 60)  — team-level authority
    lead     (level: 40)  — senior individual contributor
    staff    (level: 20)  — standard user
    viewer   (level: 10)  — read-only access
    extern   (level: 5)   — contractors, external users

  Custom roles: org can define any additional roles
  Level-based comparison: "manager+" means level >= 60

Layer 2: App-Level Roles
━━━━━━━━━━━━━━━━━━━━━
  Defines WHAT the person can do in a specific app.
  Mapped from org roles (automatic) or assigned explicitly.

  Example mappings for Inventory app:
    inventory_admin  ← maps from org role "admin" + "manager" in warehouse dept
    warehouse_staff  ← maps from org role "staff" in warehouse department
    inventory_viewer ← maps from org role "staff" (all departments)
    procurement      ← maps from org group "Procurement Team"

  Mapping rules:
    {"appRole": "inventory_admin", "when": [
      {"orgRole": "admin"},
      {"orgRole": "manager", "department": "warehouse"}
    ]}

Layer 3: Field/Record-Level Access
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Defines granular data visibility and editability.

  Field-level:
    - Which roles can VIEW each field
    - Which roles can EDIT each field
    - Default: all fields visible and editable to all app users

  Record-level (data scoping):
    - Which records the user can see
    - Based on: department, team, ownership (created_by), manager chain
    - Example: "staff sees only records from their department"
    - Example: "manager sees records from their dept + all sub-departments"
    - Example: "admin sees all records"

Composition example:
  User: Alice (Sales Manager, NY Office)

  Org roles: manager (level 60), sales_department
  App roles (CRM): crm_admin
  App roles (Inventory): inventory_viewer

  In CRM app:
    ✓ Can see all customers (crm_admin: full access)
    ✓ Can edit deals she owns (record-level: owner = self)
    ✓ Can see commission field (field-level: sales_department)
    ✗ Cannot see customer SSN (field-level: restricted to compliance)

  In Inventory app:
    ✓ Can view products (inventory_viewer: read-only)
    ✗ Cannot create/edit products (viewer role)
    ✓ Can see prices (field-level: visible to manager+)
    ✗ Cannot see cost/margin (field-level: restricted to finance_dept)
```

### 22.6 Field-Level Access Enforcement

```
Field-level access is enforced at THREE layers:

1. API Layer (mandatory — security boundary)
   Every API route filters response fields based on the user's roles.

   // Generated in API routes:
   const userRoles = getUserRoles(request);
   const allowedFields = getViewableFields('Product', userRoles);
   const products = await db.select(
     ...allowedFields.map(f => products[f])
   ).from(products);

   For writes:
   const editableFields = getEditableFields('Product', userRoles);
   const filteredBody = filterObject(body, editableFields);
   await db.update(products).set(filteredBody).where(...);

2. UI Layer (convenience — better UX)
   Components hide fields the user can't see, disable fields they can't edit.
   The UI reads the access matrix from a /api/me/permissions endpoint.

   // Generated in components:
   const { canView, canEdit } = useFieldPermissions('Product');
   {canView('unitCost') && <td>{product.unitCost}</td>}
   {canEdit('name') ? <input .../> : <span>{product.name}</span>}

3. Database Layer (optional — defense in depth)
   For highly sensitive fields, a PostgreSQL row-level security policy
   can be applied. This is only used for fields marked as "restricted"
   in the access matrix (e.g., SSN, salary).

   -- Generated RLS policy:
   CREATE POLICY product_cost_access ON products
     FOR SELECT
     USING (current_setting('app.user_role') IN ('finance', 'admin')
            OR unitCost IS NULL);
```

### 22.7 Record-Level Access (Data Scoping)

```
Record-level access controls WHICH records a user can see.
Based on the user's position in the org structure.

Scope Types:

1. Department scope
   "User sees records belonging to their department"
   Implementation: WHERE department_id = :userDepartmentId

2. Department + sub-departments scope
   "Manager sees records from their dept and all sub-departments"
   Implementation: WHERE department_id IN (
     SELECT id FROM departments WHERE id = :userDeptId
     UNION
     SELECT id FROM department_closure WHERE ancestor_id = :userDeptId
   )

3. Team scope
   "User sees records belonging to their team"
   Implementation: WHERE team_id = :userTeamId

4. Owner scope
   "User sees only records they created"
   Implementation: WHERE created_by = :userId

5. Manager chain scope
   "Manager sees records created by their direct reports"
   Implementation: WHERE created_by IN (
     SELECT id FROM org_people WHERE manager_id = :userId
   )

6. Unrestricted
   "User sees all records" (admin, finance, etc.)
   Implementation: no WHERE clause added

Scope Resolution:
  Each model can have a scope rule in the access matrix.
  The highest-privilege scope wins (if user has multiple roles).
  Scopes are additive: if any role grants access, the record is visible.

Generated Middleware:
  // src/infrastructure/auth/rbac.ts
  export function applyScopeFilter(
    query: DrizzleQuery,
    model: string,
    user: AuthUser
  ): DrizzleQuery {
    const scope = getScopeRule(model, user.appRoles);
    switch (scope.type) {
      case 'department':
        return query.where(eq(table.departmentId, user.departmentId));
      case 'department_tree':
        return query.where(inArray(table.departmentId, user.departmentTree));
      case 'owner':
        return query.where(eq(table.createdBy, user.id));
      case 'unrestricted':
        return query;
    }
  }
```

### 22.8 Workflow Assignments & Approvals

Workflows in generated apps can assign tasks to people based on their position in the org structure.

```
Assignment Types:

1. By Role
   Assign to anyone with a specific org or app role.
   Config: {"type": "role", "role": "manager", "scope": "department"}
   Resolved: finds all managers in the requester's department

2. By Org Position
   Assign to a specific position relative to the requester.
   Config: {"type": "manager_of", "target": "requester"}
   Resolved: looks up requester.managerId in org_people

3. By Department
   Assign to the department head or any member.
   Config: {"type": "department_head", "department": "finance"}
   Resolved: looks up departments.headUserId where name = 'finance'

4. By Group
   Assign to any member of a specific group.
   Config: {"type": "group", "group": "Audit Committee"}
   Resolved: random or round-robin from group members

5. By Specific Person
   Assign to a named individual.
   Config: {"type": "person", "personId": "uuid-xxx"}
   Resolved: directly assigned

6. Dynamic Rule
   Assign based on a computed expression.
   Config: {"type": "rule", "expression": "person with fewest open tasks in role 'reviewer'"}
   Resolved: LLM or query-based resolution

Task Assignment Flow:
  1. Workflow reaches an AssignmentNode or ApprovalNode
  2. Runtime resolves the assignment target from org structure
  3. Creates a task record in the app's tasks table
  4. Sends notification (email + in-app) to assignee(s)
  5. Task appears in assignee's task inbox (cross-app portal)
  6. Assignee completes task (fills form, clicks approve/reject)
  7. Workflow resumes with the task result

Approval Types:
  - Single: one person approves → done
  - Sequential: A approves → B approves → C approves (in order)
  - Parallel (all): all approvers must approve (any reject = rejected)
  - Parallel (any): first approval wins
  - Threshold: 3 of 5 must approve

Escalation:
  If task not completed within SLA:
    1. Send reminder notification
    2. After 2nd reminder: escalate to next level in org chart
    3. Escalation target: explicitly configured OR auto (requester's manager's manager)
    4. Log escalation event in workflow execution log

Generated Schema (in app):
  tasks:
    id, workflowId, workflowRunId, nodeId,
    title, description, formSchema (jsonb),
    assigneeId, assigneeType (person|role|group),
    status (pending|claimed|completed|expired|escalated),
    result (jsonb), dueAt, completedAt, completedBy,
    slaHours, escalatedAt, escalatedTo,
    createdAt

  task_comments:
    id, taskId, authorId, content, createdAt
```

### 22.9 Multi-App Portal

End-users of generated apps need a single entry point to access all their apps.

```
The org portal is auto-generated as a special app within each org.
It aggregates data from all apps the user has access to.

Route: https://{org-slug}.tentoroforge.app/ (or self-hosted equivalent)

┌─────────────────────────────────────────────────────────┐
│ Acme Corp                              Welcome, Alice ▾ │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ Your Applications                                       │
│ ┌──────────┐  ┌──────────┐  ┌──────────┐              │
│ │   📦     │  │   👥     │  │   💰     │              │
│ │Inventory │  │   CRM    │  │ Expenses │              │
│ │          │  │          │  │          │              │
│ │ 2 alerts │  │ 5 leads  │  │ 1 pending│              │
│ └──────────┘  └──────────┘  └──────────┘              │
│                                                         │
│ Pending Tasks (3)                          [View All →] │
│ ┌───────────────────────────────────────────────────┐  │
│ │ ⏳ Approve expense #4521 from Bob ($340)          │  │
│ │    Expenses app · Due in 4 hours                  │  │
│ ├───────────────────────────────────────────────────┤  │
│ │ ⏳ Review Purchase Order #892                     │  │
│ │    Inventory app · Due tomorrow                   │  │
│ ├───────────────────────────────────────────────────┤  │
│ │ ⏳ Sign off on Q1 budget                          │  │
│ │    Finance app · Due in 3 days                    │  │
│ └───────────────────────────────────────────────────┘  │
│                                                         │
│ Recent Activity                                         │
│ • Inventory: 3 products below reorder point  (2h ago)  │
│ • CRM: New lead assigned to your team        (5h ago)  │
│ • Expenses: Monthly report ready             (1d ago)  │
│                                                         │
└─────────────────────────────────────────────────────────┘

Portal Features:
  - App grid with role-based visibility (shows only apps user can access)
  - Badge counts from each app (pending tasks, alerts, new items)
  - Unified task inbox (tasks from all apps in one list)
  - Cross-app notifications
  - Quick search across all apps
  - User profile and settings
  - App switching without re-authentication (shared SSO token)

Implementation:
  The portal is a generated Next.js app like any other.
  It queries each app's API for:
    GET /api/portal/tasks → pending tasks for current user
    GET /api/portal/badges → alert counts
    GET /api/portal/activity → recent activity feed
  These endpoints are auto-generated in every app that has the portal module.
```

### 22.10 Org-Aware App Generation

```
When the Planner generates an app plan, it reads the org structure
and auto-infers the access model. The developer does NOT need to specify
roles, permissions, or approval chains — the Planner infers them.

Example:
  Developer: "Build me an expense approval system"

  Planner reads org structure:
    - 4 departments: Sales (25), Engineering (40), Finance (15), HR (10)
    - Roles: staff, lead, manager, director, VP, CEO
    - Reporting: staff → lead/manager → director → VP → CEO

  Planner auto-generates access_control in the plan:
    - App roles mapped from org roles
    - Field access for sensitive fields
    - Record scope based on department
    - Workflow assignments using org hierarchy
    - Approval chain following reporting lines

  The developer reviews the plan and can adjust before approving.
```

### 22.11 Multi-Tenancy Architecture

```
Multi-tenancy operates at TWO levels:

Level 1: Platform (Tentoro Forge itself)
  Strategy: Shared database with org_id column
  - All organizations share the same platform PostgreSQL
  - Every query is scoped by org_id
  - Platform tables: organizations, org_people, org_roles, projects, etc.
  - Middleware automatically injects org_id filter
  - This is standard SaaS multi-tenancy

Level 2: Generated Apps (what users build)
  Strategy: Database-per-app (already in the blueprint)
  - Each generated app gets its own Docker Compose + PostgreSQL
  - Complete data isolation between apps
  - Apps within the same org share IDENTITY but not DATA
  - Identity is synced from platform org_people → app's users table
  - Each app is a standalone deployment

Data Flow:
  ┌──────────────────────────────────────────────┐
  │          Tentoro Forge Platform DB                 │
  │                                              │
  │  organizations ──┐                           │
  │  org_people ─────┤                           │
  │  org_roles ──────┤                           │
  │  org_groups ─────┤                           │
  │  field_access ───┤                           │
  │  projects ───────┘                           │
  └────────────────┬──────────┬──────────────────┘
                   │          │
            ┌──────▼────┐ ┌──▼──────────┐
            │ App 1 DB  │ │ App 2 DB    │
            │           │ │             │
            │ users ←───┤ │ users ←─────┤ (synced from org_people)
            │ roles ←───┤ │ roles ←─────┤ (synced from org_roles)
            │ policies  │ │ policies    │ (synced from field_access)
            │ ...data...│ │ ...data...  │
            └───────────┘ └─────────────┘

Sync triggers:
  - On preview start: full sync (org_people → app users table)
  - On org structure change: incremental sync to all running previews
  - On deploy: full sync embedded in the app's startup script
  - App checks for updates every 5 minutes in production

What gets synced:
  - People: id, email, name, title, departmentId, teamId, managerId, roles
  - Roles: id, name, level
  - Field access policies: model, field, role → view/edit permissions
  - Workflow assignments: which roles handle which workflow steps
  - Groups: id, name, member IDs

What stays in the app DB:
  - All business data (products, orders, tickets, etc.)
  - Conversations (agent chat history)
  - Workflow execution logs
  - Task assignments and completions
  - File uploads
```

### 22.12 Org Structure in AppModel Index

```json
// Added to app-model.json when org structure is active

"orgAware": {
  "enabled": true,
  "syncedFrom": "platform",

  "appRoles": [
    {
      "name": "expense_submitter",
      "mapsFrom": [{"type": "all"}],
      "permissions": ["expense:create", "expense:read:own"]
    },
    {
      "name": "expense_approver",
      "mapsFrom": [{"type": "org_role", "role": "manager", "level_gte": 60}],
      "permissions": ["expense:read:reports", "expense:approve"]
    },
    {
      "name": "expense_admin",
      "mapsFrom": [{"type": "department", "department": "Finance"}],
      "permissions": ["expense:read:all", "expense:edit:all", "expense:admin"]
    }
  ],

  "fieldAccess": [
    {"model": "Expense", "field": "receiptUrl", "view": ["*"], "edit": ["expense_submitter"]},
    {"model": "Expense", "field": "approverNotes", "view": ["expense_approver", "expense_admin"], "edit": ["expense_approver"]},
    {"model": "Expense", "field": "costCenter", "view": ["expense_admin"], "edit": ["expense_admin"]}
  ],

  "recordScope": [
    {
      "model": "Expense",
      "rules": [
        {"role": "expense_submitter", "scope": "owner", "column": "created_by"},
        {"role": "expense_approver", "scope": "manager_chain", "column": "created_by"},
        {"role": "expense_admin", "scope": "unrestricted"}
      ]
    }
  ],

  "workflowAssignments": [
    {
      "workflow": "expense-approval",
      "node": "manager-approve",
      "assignTo": {"type": "manager_of", "target": "requester"},
      "slaHours": 48,
      "escalateTo": {"type": "manager_of", "target": "current_assignee"}
    }
  ]
}
```

---

## 23. Discovery & Templates

### 23.1 Overview

Not every user arrives with clear requirements or a Figma design. The Discovery system handles four entry points:

1. **Problem-first**: "Our onboarding takes too long" → Discovery Agent identifies the problem, asks about current process, proposes an app
2. **Reference-based**: "Build something like Trello" → Agent identifies the reference app's features, asks which are relevant, builds a tailored plan
3. **Department-need**: "I need something for my HR team" → Agent checks org structure, identifies the department's gaps, suggests apps
4. **Vague idea**: "I want to track something" → Agent guides through structured exploration to clarify what, who, and why

All paths converge on a **structured brief** that feeds into the Planner agent — so the downstream pipeline is unchanged.

### 23.2 Discovery Agent (#12)

```python
# backend/agents/discovery.py

DISCOVERY_SYSTEM_PROMPT = """You are a product discovery agent. Your job is to help users who
don't have clear requirements figure out what application they need.

You are warm, patient, and curious. You ask focused questions and build understanding
incrementally. Never overwhelm with options — guide the conversation naturally.

## Your Context

You have access to:
- The user's organization structure (departments, teams, roles, people)
- The org's existing apps (so you don't suggest duplicates)
- A template library of pre-built app plans

## Discovery Types

Detect which type of discovery the user needs:

### PROBLEM_FIRST
User describes a pain point, not a solution.
Strategy: Understand the current process → identify bottlenecks → propose a solution.
Questions:
  1. "Walk me through how this works today — step by step."
  2. "Where does it break down? What takes too long or goes wrong?"
  3. "Who's involved in this process? What are their roles?"
  4. "What would 'fixed' look like? What's the ideal outcome?"

### REFERENCE_BASED
User names an existing product ("like Trello", "like Salesforce").
Strategy: Identify the reference → list its key features → ask which matter → customize.
Questions:
  1. "What do you like most about [reference]? Which features do you actually use?"
  2. "What's missing or annoying about it?"
  3. "Who on your team would use this? How many people?"
  4. "Any specific workflows you need that [reference] doesn't handle well?"

### DEPARTMENT_NEED
User mentions a team or department without specifying what they need.
Strategy: Check org structure → identify department's function → suggest relevant apps.
Questions:
  1. "I can see your [department] has [N] people. What are their main responsibilities?"
  2. "What tools do they currently use? Spreadsheets, email, other software?"
  3. "What's the biggest time sink for the team right now?"
  4. "Are there any compliance or reporting requirements I should know about?"

### VAGUE_IDEA
User has a loose concept but can't articulate requirements.
Strategy: Structured exploration through who/what/why framework.
Questions:
  1. "Who will use this app? Just you, your team, or the whole org?"
  2. "What's the core thing they need to do? (Track something? Approve something? Report?)"
  3. "How often will they use it — daily, weekly, occasionally?"
  4. "Is there a deadline or event driving this? Why now?"

## Rules

- Ask 3-5 questions total, not all at once. One question per turn, maybe two.
- After each answer, summarize your understanding and ask the next question.
- When you have enough info, produce a STRUCTURED BRIEF (see format below).
- If a template matches well (>70% fit), suggest it and ask about customizations.
- Always check existing org apps to avoid suggesting duplicates.
- Include org structure context: suggest using existing roles for RBAC.

## Structured Brief Format

When you have enough information, produce this JSON:

{
  "discovery_type": "problem_first|reference_based|department_need|vague_idea",
  "app_name": "Suggested name",
  "description": "One-paragraph summary of what the app does",
  "target_users": {
    "departments": ["HR"],
    "roles": ["HR Manager", "Recruiter"],
    "estimated_users": 15
  },
  "core_entities": ["Candidate", "Interview", "JobPosting", "Offer"],
  "key_workflows": [
    "Job posting approval flow",
    "Interview scheduling",
    "Offer approval chain"
  ],
  "must_have_features": [
    "Candidate pipeline view (kanban)",
    "Interview calendar integration",
    "Offer letter generation"
  ],
  "nice_to_have_features": [
    "AI resume screening",
    "Automated reference check emails"
  ],
  "matched_template": "hr-recruiting" or null,
  "template_customizations": ["Add interview scoring rubric", "Remove onboarding module"],
  "rbac_suggestions": {
    "HR Manager": "full access",
    "Recruiter": "own candidates only",
    "Hiring Manager": "view assigned candidates, approve/reject"
  },
  "integrations": ["email", "calendar"],
  "complexity": "medium"
}

This brief will be handed to the Planner agent to produce a full technical plan.
"""

DISCOVERY_OPTIONS = ClaudeAgentOptions(
    system_prompt=DISCOVERY_SYSTEM_PROMPT,
    allowed_tools=["Read"],  # Can read org structure, existing apps, templates
    permission_mode="bypassPermissions",
    max_turns=20,
    model="claude-sonnet-4-20250514",
)
```

### 23.3 Template Library

Templates are pre-built Planner-format plans that can be used as-is or customized.

#### Template Categories

```
Category        Templates
───────────────────────────────────────────────────────────────────
Operations      Task Manager, Project Tracker, Asset Manager,
                Inventory System, Facility Booking, Incident Tracker

Sales           CRM Basic, CRM Advanced, Lead Pipeline,
                Quote Generator, Commission Tracker, Partner Portal

HR              Employee Directory, PTO Tracker, Recruiting Pipeline,
                Onboarding Checklist, Performance Reviews, Training LMS

Finance         Expense Tracker, Invoice Manager, Budget Planner,
                Purchase Orders, Reimbursement System, Petty Cash

Support         Help Desk, Knowledge Base, Bug Tracker,
                Customer Feedback, SLA Monitor, Escalation Manager

IT              Change Request, Service Catalog, License Manager,
                Device Inventory, Access Request, Audit Logger

Marketing       Campaign Tracker, Content Calendar, Event Manager,
                Lead Scoring, Survey Builder, Brand Asset Library

Legal           Contract Manager, NDA Tracker, Compliance Checklist,
                Policy Library, Case Manager, Document Approval
```

#### Template Structure

```typescript
interface AppTemplate {
  slug: string                    // "crm-basic"
  name: string                   // "Basic CRM"
  description: string
  category: string               // "Sales"
  subcategory?: string           // "Pipeline"
  icon: string                   // lucide icon name
  tags: string[]                 // ["crm", "sales", "pipeline"]
  complexity: 'simple' | 'medium' | 'complex'
  estimatedModules: number

  // The full plan in Planner output format
  plan: {
    entities: EntityDefinition[]
    pages: PageDefinition[]
    workflows: WorkflowDefinition[]
    rules: RuleDefinition[]
    modules: ModuleDefinition[]
    navigation: NavigationDefinition
    seedData: SeedDataDefinition
    access_control?: AccessControlDefinition
    ai_features?: AIFeaturesDefinition
    agents?: AgentDefinition[]
  }

  // Org awareness
  relevantDepartments: string[]   // ["Sales", "Marketing"]
  suggestedRoles: {               // default RBAC for this template
    roleName: string
    accessLevel: string
    description: string
  }[]

  // Customization hints
  customizableAreas: {
    area: string                  // "entities", "workflows", "pages"
    description: string           // "Add custom fields to Contact"
    optional: boolean
  }[]

  previewImage?: string
}
```

### 23.4 Org-Aware Suggestions

When an org has departments set up, the platform proactively suggests relevant apps:

```typescript
// Suggestion engine logic (backend)

interface AppSuggestion {
  template: AppTemplate
  reason: string               // "Your HR department has 12 people but no HR apps"
  relevance: number            // 0-100 score
  existingApps: string[]       // apps already covering this area
  gap: string                  // "No recruiting pipeline tool found"
}

async function getSuggestedTemplates(orgId: string): Promise<AppSuggestion[]> {
  const org = await getOrgWithStructure(orgId)
  const existingApps = await getOrgProjects(orgId)
  const templates = await getAllTemplates()

  const suggestions: AppSuggestion[] = []

  for (const dept of org.departments) {
    // Find templates relevant to this department
    const relevant = templates.filter(t =>
      t.relevantDepartments.some(d =>
        d.toLowerCase() === dept.name.toLowerCase()
      )
    )

    // Check which areas are already covered by existing apps
    for (const template of relevant) {
      const covered = existingApps.some(app =>
        app.tags?.some(tag => template.tags.includes(tag))
      )
      if (!covered) {
        suggestions.push({
          template,
          reason: `Your ${dept.name} department (${dept.people.length} people) has no ${template.category.toLowerCase()} tools`,
          relevance: calculateRelevance(dept, template, org),
          existingApps: [],
          gap: `No ${template.name.toLowerCase()} found`
        })
      }
    }
  }

  return suggestions.sort((a, b) => b.relevance - a.relevance)
}
```

#### Suggestions UI (on Org Dashboard)

```
┌────────────────────────────────────────────────────────────────┐
│ 💡 Suggested Apps for Your Organization                        │
│                                                                │
│ Based on your org structure, these apps might help:            │
│                                                                │
│ ┌──────────────────────┐  ┌──────────────────────┐            │
│ │ 📋 Recruiting        │  │ 💰 Expense Tracker   │            │
│ │ Pipeline             │  │                      │            │
│ │                      │  │ Your Finance team    │            │
│ │ Your HR dept (12     │  │ (8 people) has no    │            │
│ │ people) has no       │  │ expense management   │            │
│ │ recruiting tool      │  │                      │            │
│ │                      │  │ [Use Template]       │            │
│ │ [Use Template]       │  │ [Customize First]    │            │
│ │ [Customize First]    │  │ [Dismiss]            │            │
│ │ [Dismiss]            │  └──────────────────────┘            │
│ └──────────────────────┘                                       │
└────────────────────────────────────────────────────────────────┘
```

### 23.5 Template Gallery Page

```
┌────────────────────────────────────────────────────────────────┐
│ Template Gallery                                    🔍 Search  │
│                                                                │
│ Categories: [All] [Operations] [Sales] [HR] [Finance]          │
│             [Support] [IT] [Marketing] [Legal]                 │
│                                                                │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│ │ 📊           │ │ 👥           │ │ 📋           │            │
│ │ Basic CRM    │ │ Employee     │ │ Task         │            │
│ │              │ │ Directory    │ │ Manager      │            │
│ │ Track leads, │ │ Searchable   │ │ Kanban       │            │
│ │ deals, and   │ │ org-wide     │ │ boards,      │            │
│ │ pipeline     │ │ people       │ │ deadlines,   │            │
│ │              │ │ directory    │ │ assignments  │            │
│ │ Sales        │ │ HR           │ │ Operations   │            │
│ │ ●●○ Medium   │ │ ●○○ Simple   │ │ ●●○ Medium   │            │
│ │              │ │              │ │              │            │
│ │ [Preview]    │ │ [Preview]    │ │ [Preview]    │            │
│ │ [Use →]      │ │ [Use →]      │ │ [Use →]      │            │
│ └──────────────┘ └──────────────┘ └──────────────┘            │
│                                                                │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ Template Detail (expanded on click)                      │   │
│ │                                                          │   │
│ │ Basic CRM                                    [Use →]     │   │
│ │                                                          │   │
│ │ Data Models: Contact, Company, Deal, Activity, Pipeline  │   │
│ │ Pages: Dashboard, Contacts, Deals, Pipeline Board        │   │
│ │ Workflows: Deal stage change → notify, Weekly forecast   │   │
│ │ Modules: 3 (Core, Pipeline, Reporting)                   │   │
│ │                                                          │   │
│ │ Customizations available:                                │   │
│ │ ☑ Add custom fields to Contact                          │   │
│ │ ☑ Change pipeline stages                                │   │
│ │ ☑ Add email integration                                 │   │
│ │ ☐ Add AI lead scoring (requires AI features)            │   │
│ │                                                          │   │
│ │ Suggested roles: Sales Rep, Sales Manager, Admin         │   │
│ │ [Customize & Create]  [Use As-Is]                       │   │
│ └──────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────┘
```

### 23.6 Discovery Conversation UI

```
┌────────────────────────────────────────────────────────────────┐
│ ← Back to Org Dashboard                                        │
│                                                                │
│ Let's figure out what you need                                 │
│                                                                │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ 🤖 I can help you figure out what app to build.          │   │
│ │                                                          │   │
│ │ Tell me about:                                           │   │
│ │ • A problem your team faces                             │   │
│ │ • An existing tool you want to replace                  │   │
│ │ • A department that needs better tools                  │   │
│ │ • Or just a rough idea — we'll work it out together     │   │
│ └──────────────────────────────────────────────────────────┘   │
│                                                                │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ 👤 Our HR team spends hours every week tracking PTO     │   │
│ │    requests through email. It's a mess.                  │   │
│ └──────────────────────────────────────────────────────────┘   │
│                                                                │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ 🤖 I see your HR department has 12 people. Let me       │   │
│ │    understand the current process:                       │   │
│ │                                                          │   │
│ │    How does someone request PTO today — do they email    │   │
│ │    their manager directly, or is there a shared inbox?   │   │
│ └──────────────────────────────────────────────────────────┘   │
│                                                                │
│ ... (conversation continues) ...                               │
│                                                                │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ 🤖 I have a good understanding now. Here's what I       │   │
│ │    recommend:                                            │   │
│ │                                                          │   │
│ │    ┌────────────────────────────────────────────────┐    │   │
│ │    │ 📋 PTO & Leave Manager                        │    │   │
│ │    │                                                │    │   │
│ │    │ • PTO request form with date picker            │    │   │
│ │    │ • Manager approval workflow                    │    │   │
│ │    │ • Leave balance tracking (accrual rules)       │    │   │
│ │    │ • Team calendar view                           │    │   │
│ │    │ • HR dashboard with reports                    │    │   │
│ │    │                                                │    │   │
│ │    │ Based on template: PTO Tracker                 │    │   │
│ │    │ Customized: + approval chain via managers,     │    │   │
│ │    │ + accrual rules, + Slack notifications         │    │   │
│ │    │                                                │    │   │
│ │    │ RBAC: HR Manager (full), Managers (approve     │    │   │
│ │    │ for team), Employees (own requests only)       │    │   │
│ │    │                                                │    │   │
│ │    │ [Build This App →]  [Adjust Requirements]      │    │   │
│ │    └────────────────────────────────────────────────┘    │   │
│ └──────────────────────────────────────────────────────────┘   │
│                                                                │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ Type a message...                              [Send]    │   │
│ └──────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────┘
```

### 23.7 Template-to-Project Flow

```
Template Selected
    │
    ├── "Use As-Is" ─────────────────────────────────────────┐
    │                                                        │
    ├── "Customize First"                                    │
    │     │                                                  │
    │     ├── Customize modal:                               │
    │     │   ├── App name                                   │
    │     │   ├── Toggle optional modules                    │
    │     │   ├── Add custom fields                         │
    │     │   ├── Select org roles → app roles mapping       │
    │     │   └── [Create App →]                            │
    │     │                                                  │
    │     └── Creates project with customized plan ─────────┤
    │                                                        │
    └── Both paths:                                          │
        │                                                    │
        ▼                                                    │
    Create project in org ◄──────────────────────────────────┘
        │
        ▼
    Skip Planner (plan already exists from template)
        │
        ▼
    Run Code Generator with template plan
        │
        ▼
    Normal flow: Validate → Index → Preview
```

### 23.8 Discovery-to-Project Flow

```
Discovery Session
    │
    ├── User provides initial input
    │
    ▼
Discovery Agent (multi-turn conversation)
    │
    ├── Reads org structure (departments, roles, people)
    ├── Reads existing apps (avoid duplicates)
    ├── Reads template library (find matching templates)
    │
    ├── Asks 3-5 clarifying questions
    │
    ▼
Produces Structured Brief
    │
    ├── If template match found (>70% fit):
    │     ├── Suggest template with customizations
    │     ├── User confirms → Template-to-Project flow
    │     └── User rejects → Brief goes to Planner
    │
    ├── If no template match:
    │     └── Brief goes to Planner
    │
    ▼
Planner Agent receives brief as input
    │
    ├── Brief contains: entities, workflows, roles, features
    ├── Planner may ask 1-2 additional technical questions
    │
    ▼
Normal planning → generation → preview flow
```

---

## 24. Implementation Phases

### Phase 0: Organization Foundation (Weeks 1-2) — STATUS: ~85% COMPLETE

```
Goal: Multi-tenant org structure with people, roles, and groups

Tasks:
✅ Platform PostgreSQL schema: organizations, org_members, departments,
   teams, org_people, org_roles, org_person_roles, org_groups, org_group_members
✅ Platform auth (signup/login/JWT with orgId in token, refresh tokens, account lockout)
✅ Organization CRUD endpoints (orgs.py — 952 lines)
✅ Org membership and invitation flow
✅ Org people CRUD endpoints
✅ Department and team CRUD endpoints
✅ Org role management (default roles auto-created on org creation)
✅ Group management endpoints
✅ CSV/JSON import for bulk people upload with column mapping
✅ Org chart API endpoint (full tree for React Flow)
✅ Frontend: org creation wizard
✅ Frontend: org dashboard (apps grid + sidebar navigation)
□ Frontend: org chart visual editor (React Flow: departments, people, drag) — PAGE EXISTS, MINIMAL UI
□ Frontend: people directory table with search/filter — PAGE EXISTS, MINIMAL UI
□ Frontend: role and group management pages — PAGES EXIST, MINIMAL UI
□ Frontend: CSV import with preview and column mapping — PAGE EXISTS, MINIMAL UI

Deliverable: Developer can create an org, upload their people via CSV,
visually arrange the org chart, define roles and groups.

NOTE: Backend is fully complete. Frontend org management pages exist as route
shells but have minimal UI implementation. All data flows work via API.
```

### Phase 1: Foundation (Weeks 3-5) — STATUS: ~95% COMPLETE

```
Goal: Basic conversational app generation with live preview (org-scoped)

Tasks:
✅ Set up monorepo structure (backend + frontend)
✅ Project model scoped to org (org_id foreign key)
✅ Project CRUD endpoints (projects.py — 327 lines)
✅ Code Generator agent (Agent #4) with PostgreSQL/Drizzle prompt (307 lines)
✅ Validator agent (Agent #8)
✅ Indexer agent (Agent #7) — basic version
✅ Preview manager with Docker Compose support
✅ SSE streaming infrastructure (with reconnect buffering via generation_buffer.py)
✅ Frontend: project list, creation, chat panel (with quest/XP tracking)
✅ Frontend: progress stream display (ProgressStream component)
✅ Frontend: live preview iframe with device frames (PreviewFrame)
✅ Frontend: basic file tree + Monaco code editor (CodeEditor, CodePanel)
✅ Version history via git (git_service.py, VersionSidebar component)
✅ Template DB tables and seed with initial templates (seeds/templates.py)
✅ Template gallery page (TemplateCard, TemplateDetailModal components)
✅ "New App" creation options (describe / template / discover / figma)

Deliverable: User can describe an app in chat, get it generated with
PostgreSQL, preview it live, browse the source code, or start from a template.
```

### Phase 2: Refinement & Chat (Weeks 6-7) — STATUS: ~90% COMPLETE

```
Goal: Conversational refinement of generated apps

Tasks:
✅ Orchestrator agent (Agent #0) — intent classification (orchestrator.py)
✅ Refiner agent (Agent #2) — index-aware code editing (refiner.py)
✅ Planner agent (Agent #1) — multi-turn planning with structured output (planner.py)
✅ Explainer agent (Agent #3) (explainer.py)
✅ Scaffolder agent (Agent #6) — add features to existing apps (scaffolder.py)
✅ Code Editor agent (Agent #5) — focused single-file edits (code_editor.py)
✅ Conversation persistence (platform DB — Conversation model)
✅ Plan approval UI (PlanCard component with approve/reject)
✅ Undo/revert via git (git_service.py, VersionSidebar)
✅ Frontend: refine bar below preview
✅ Frontend: chat history persistence
✅ Discovery Agent (Agent #12) — system prompt and multi-turn (discovery.py)
✅ "DISCOVER" intent in Orchestrator routing
✅ Discovery session persistence (DiscoverySession model)
✅ Discovery conversation UI page
✅ Org-aware template suggestions engine (suggestion_service.py)
✅ Template-to-project and discovery-to-project flows
□ Suggested apps section on org dashboard — PARTIAL (portal store has scaffolding)

Deliverable: User can have multi-turn conversations, plan modules,
refine the app through chat, undo changes, discover requirements
through guided conversation, or start from suggested templates.
```

### Phase 3: Data Model Editor (Weeks 8-9) — STATUS: ~95% COMPLETE

```
Goal: Visual ERD editor for data models

Tasks:
✅ ERD canvas with React Flow (ERDCanvas.tsx with dagre auto-layout)
✅ Entity cards with field lists (EntityCardNode.tsx)
✅ Add/edit/delete models (AddModelDialog, DeleteConfirmDialog)
✅ Add/edit/delete fields (type picker, constraint checkboxes, smart field support)
✅ Relationship drawing (RelationshipEditor.tsx)
✅ Enum editor (EnumEditor.tsx)
✅ Index editor (IndexEditor.tsx)
✅ Seed data table editor (SeedDataEditor.tsx)
✅ "Generate realistic data" button (LLM call via data_model router)
✅ Impact analysis on model changes (ImpactAnalysis.tsx)
✅ Instruction builder for data editor actions
✅ Schema change → drizzle-kit push integration (SchemaChangeProgress.tsx, useSchemaChange.ts)
✅ Database browser (DatabaseBrowser.tsx)
✅ SQL console (SqlConsole.tsx)

Deliverable: User can visually manage all data models, see relationships,
edit seed data, and browse the live database.
```

### Phase 4: Rules, Decisions & Access Control Editor (Weeks 10-13) — STATUS: ~85% COMPLETE

```
Goal: Visual rules management + decision builder + org-aware access control

Tasks — Rules:
✅ Rules table with filtering (tabs: Rules | Decision Tables | All)
✅ Validation rule form (ValidationRuleForm.tsx)
✅ Access control rule form (AccessControlRuleForm.tsx, FieldAccessMatrix.tsx)
✅ Business rule form (BusinessRuleForm.tsx)
✅ Computed field rule form (ComputedFieldRuleForm.tsx)
✅ State machine editor (StateMachineEditor.tsx — React Flow mini-diagram)
✅ Trigger rule form (TriggerRuleForm.tsx)
✅ Instruction builder for rule actions (rule-instruction-builder.ts)
□ Cross-reference: show rules in data model editor field properties — NOT WIRED
□ Cross-reference: show access rules in UI editor component properties — NOT WIRED

Tasks — FEEL-lite Expression Engine:
✅ FEEL-lite parser: tokenizer + AST builder (backend: feel_lite/tokenizer.py 281 lines,
   parser.py 335 lines; frontend: lib/feel-lite/tokenizer.ts, parser.ts)
✅ FEEL-lite evaluator: AST walker (backend: feel_lite/evaluator.py 609 lines;
   frontend: lib/feel-lite/evaluator.ts)
✅ Expression types: comparisons, ranges, lists, negation, null checks,
   string ops, regex, arithmetic, conditionals, date/duration, variable refs
✅ Expression validator (frontend: lib/feel-lite/validator.ts)
□ Expression autocomplete provider: suggests variables and operators from schema — PARTIAL

Tasks — Condition Builder (enhanced):
✅ No-code mode: field picker, operator picker, value input, AND/OR group nesting
   (ConditionRow.tsx, ConditionBuilder.tsx)
✅ Expression mode: raw FEEL-lite editor
✅ Toggle between no-code and expression modes
✅ Generated expression preview in no-code mode
✅ Backwards compatibility: existing structured field/operator/value conditions still work

Tasks — Decision Table Editor:
✅ Spreadsheet-like grid component (decision store + types)
✅ Hit policy selector (U, F, A, P, C, R) — types/decision.ts
✅ Cell editor with FEEL-lite expression autocomplete
✅ Column binding: bind input columns to workflow variables / model fields
✅ Row drag-to-reorder (for First/Priority hit policies)
✅ Add/remove rows and columns
✅ Empty cell = wildcard behavior
□ Copy/paste rows from spreadsheet apps — NOT IMPLEMENTED
✅ Decision table evaluator (backend: decision_evaluator.py 462 lines;
   frontend: lib/decision/table-evaluator.ts)

Tasks — Decision Testing & Validation:
✅ Decision test panel: enter inputs, see matched row + output
✅ Save/load test cases with expected outputs (decision store)
✅ Batch test runner with pass/fail summary
✅ Coverage indicator: highlight untested rows
✅ Static analysis: completeness check (lib/decision/analysis.ts)
✅ Static analysis: overlap detection
✅ Static analysis: subsumption check (dead/shadowed rows)
□ Type checking: verify expressions match bound variable types — PARTIAL

Tasks — Decision Graph (DRD):
✅ Decision graph evaluator (frontend: lib/decision/graph-evaluator.ts)
□ Mini React Flow canvas for DRD visual editing — NOT IMPLEMENTED
□ DRD node types: InputData (oval), Decision (rectangle), KnowledgeSource (wavy) — NOT IMPLEMENTED
✅ Topological sort evaluator for dependency-ordered execution
✅ Upstream decision outputs available as inputs to downstream decisions

Tasks — Rule Templates:
✅ Decision templates (lib/decision/templates.ts)
□ Full gallery UI for rule templates — PARTIAL (templates exist, gallery UI incomplete)

Tasks — Decision Versioning & Audit:
✅ Decision version snapshots on save (DecisionTableVersion model)
□ Version diff view (side-by-side comparison) — NOT IMPLEMENTED
□ Effective dating (schedule version activation) — NOT IMPLEMENTED
✅ Execution audit log (DecisionExecutionLog model)

Tasks — Access Control:
✅ Field Access Editor: model × role matrix (FieldAccessMatrix.tsx)
✅ Record Scope editor (RecordScopeEditor.tsx)
✅ App-role mapping: org roles → app roles (AppRoleMapping.tsx)
✅ App access policies (AppAccessPolicies.tsx)
✅ RBAC middleware template for generated apps (field filter + scope filter)
□ Org structure sync: platform org_people → generated app users table — NOT IMPLEMENTED
✅ Planner agent: auto-infer access_control from org structure in plans
□ useFieldPermissions React hook template for generated app components — NOT IMPLEMENTED
□ /api/me/permissions endpoint template for generated apps — NOT IMPLEMENTED

Tasks — Code Generation:
□ FEEL-lite parser template for generated apps (src/shared/feel-lite/) — NOT IMPLEMENTED
□ Decision table evaluator template for generated apps (src/shared/decisions/) — NOT IMPLEMENTED
□ Decision graph evaluator template for generated apps — NOT IMPLEMENTED
□ Standalone decision files: src/domain/{module}/decisions/{name}.ts — NOT IMPLEMENTED
□ Decision schema in Drizzle: decision_versions, decision_execution_logs tables — NOT IMPLEMENTED

Deliverable: User can create rules with rich expressions (no-code builder or
FEEL-lite), build decision tables with hit policies and multi-row logic, test
decisions inline, chain decisions via DRD, and configure field/record-level RBAC.
Generated apps include FEEL-lite parser, decision evaluator, and RBAC enforcement.

NOTE: Platform-side rules, decisions, and RBAC editors are largely complete.
The main gap is code generation templates — outputting FEEL-lite parser, decision
evaluator, and RBAC enforcement code into the generated apps themselves.
DRD visual editor (React Flow canvas) is also missing.
```

### Phase 5: Workflow Editor (Weeks 14-16) — STATUS: ~85% COMPLETE

```
Goal: Visual workflow builder with execution + decision node integration

Tasks:
✅ Workflow canvas with React Flow (WorkflowCanvas.tsx)
✅ Node types: 19 types including trigger, action, condition, decision, wait, end,
   assignment, approval, task pool, escalation, AI nodes (types/workflow.ts)
✅ Node palette (draggable node types, "Decisions" category)
✅ Edge types: default, then, else, error
✅ Node properties panel (NodePropertiesPanel.tsx)
✅ Variable picker with autocomplete (VariablePicker.tsx)
✅ Workflow definition JSON format (including decision step type)
✅ Workflow runtime engine (runtime/engine.py — 465 lines, gateway_controller.py — 323 lines)
✅ Trigger registration system
□ Workflow action generator agent (Agent #10) — AGENT EXISTS, INTEGRATION PARTIAL
✅ Instruction builder for workflow actions (workflow-instruction-builder.ts)
✅ Workflow tester (WorkflowTester.tsx)
✅ Execution log viewer (ExecutionLogViewer.tsx)
✅ Built-in action types: DB query, HTTP call, email, notification, custom
   (runtime/actions/ — 6 action modules)
✅ Decision node: inline decision table editor in properties panel
✅ Decision node: output mapping to workflow variables
✅ Decision node: collapsed view shows rule count, hit policy, column names
✅ Condition node: enhanced with FEEL-lite expression support
✅ Assignment node: assign task to user/role/manager/dept/group (runtime/assignment.py)
✅ Approval node: single/sequential/parallel approval with SLA
✅ Task pool node: claim model, round-robin
□ Escalation node: SLA breach → escalate up org chart — PARTIAL (timer_scheduler exists)
□ Task inbox page template for generated apps — NOT IMPLEMENTED
✅ Org structure integration: resolve "requester's manager" dynamically
✅ Notification system: email + in-app (email_service.py, notification_service.py)

Deliverable: User can visually design workflows with decision tables for
complex routing, FEEL-lite expressions for conditions, and human-in-the-loop
assignments and approvals that resolve against the org structure.

NOTE: The workflow runtime engine is fully implemented on the platform backend.
The main gap is generating workflow runtime code into the generated apps themselves
(task inbox page, workflow executor, trigger registration).
```

### Phase 6: UI Editor (Weeks 17-20) — STATUS: ~80% COMPLETE (ARCHITECTURE PIVOTED)

```
Goal: Visual UI editing with component drag-and-drop

ARCHITECTURE NOTE: The original plan called for GrapesJS white-labeled with
custom shadcn/ui panels. The implementation pivoted to an "Agentic React Builder"
approach — a 3-panel visual page builder where TSX source code is the source of
truth, using bridge.js for iframe communication, AST parsing for structure, and
AI agents for generative work. This is documented in section 8.2.1. The pivot
is an improvement: source-of-truth is TSX (not a JSON canvas), edits are real
code changes committed to git, and the approach composes better with the agent
pipeline. GrapesJS is NOT used.

Tasks (Agentic React Builder — actual implementation):
✅ Bridge.js injection/removal into generated app iframe (bridge_injector.py)
✅ Source annotation with data-source-* attributes (source_annotator.py, annotate-source.mjs)
✅ 3-panel layout: outline + canvas + context (VisualEditor.tsx)
✅ Section outline panel (SectionOutlinePanel.tsx — tree view from bridge DOM)
✅ Canvas iframe with highlight/scroll-to (CanvasFrame.tsx)
✅ Context panel: element info, Tailwind class chips, props, actions (ContextPanel.tsx)
✅ AI edit input with context-aware suggestion chips (AIEditInput.tsx)
✅ Component palette: section template browser + custom prompt (ComponentPalette.tsx)
✅ Element action popover on selected element (ElementActionPopover.tsx)
✅ Quick Tailwind style editor (QuickStylePopover.tsx)
✅ Section reordering via HTML5 drag (section_reorder_service.py, reorder-section.mjs)
✅ Direct Tailwind/text/prop edits (visual_edit_service.py)
✅ AI-mediated edits via code_editor agent (SSE stream)
✅ Section template catalog (section_templates.py — 15 templates, 12 categories)
✅ Section instruction builder for agent prompts (section_instruction_builder.py)
✅ Device preview (desktop/tablet/mobile)
✅ Undo/redo via git revert
✅ Page section parser for route → AST tree (page_section_parser.py, parse-sections.mjs)
□ Field mapper — bind data model fields to component traits — NOT IMPLEMENTED
□ Canvas component views — rich editor previews (DataTable, Chart) — NOT APPLICABLE (real TSX renders)

Deliverable: User can visually edit UI components, bind data models,
and see changes reflected in the live preview.
```

### Phase 7: Navigation & Module System (Weeks 21-22) — STATUS: ~70% COMPLETE

```
Goal: Multi-module apps with visual navigation editing

Tasks:
✅ Navigation editor (NavigationEditor.tsx — React Flow screen diagram)
✅ Screen nodes with route (ScreenNode.tsx)
□ Screen nodes with thumbnail preview — NOT IMPLEMENTED
✅ Navigation wiring (draw links between screens — edges in navigation store)
✅ Sidebar/navbar menu configuration (NavigationPanel.tsx, ScreenProperties.tsx)
✅ Module management UI (ModuleManager.tsx)
□ Cross-module dependency tracking — TYPES EXIST (navigation.ts), UI PARTIAL
□ Module creation wizard (triggers Planner agent) — NOT WIRED
□ Connections map (visual overview of all module relationships) — NOT IMPLEMENTED
□ Module-scoped file organization — NOT IMPLEMENTED
□ Module-scoped AppModel index sections — NOT IMPLEMENTED

Deliverable: User can build multi-module apps, manage module dependencies,
and configure navigation between modules.

NOTE: Navigation editor visuals are built. Module system is the main gap —
the pipeline for creating new modules via Planner, scoping files to modules,
and tracking cross-module dependencies is not yet wired end-to-end.
```

### Phase 8: AI Agent Builder (Weeks 23-25) — STATUS: ~80% COMPLETE (PLATFORM SIDE)

```
Goal: Visual agent builder with runtime in generated apps

Tasks — Platform Visual Builder:
✅ Agent Builder visual editor (AgentCanvas.tsx — React Flow canvas)
✅ Node types: SystemPrompt, Tool, Guardrail, Memory, HumanHandoff, Router
   (nodes/ directory — 6 node components)
✅ Node palette and drag-to-canvas (AgentNodePalette.tsx)
✅ Properties panel for each node type (AgentNodeProperties.tsx)
✅ System prompt editor with variable interpolation
✅ Tool picker — auto-discover from AppModel API routes
✅ Custom tool editor (name, description, input schema, handler file)
✅ Guardrail configuration forms (input/output validation, rate limits)
✅ Memory configuration (conversation, summarization, knowledge base toggle)
✅ Multi-agent router configuration
✅ Instruction builder for agent editor actions (agent-instruction-builder.ts)
✅ Agent templates (AgentTemplateSelector.tsx)
✅ Test console in agent builder (AgentTestConsole.tsx)
✅ "AGENT" intent in Orchestrator routing
✅ Agent definition CRUD endpoints (agent_builder.py router — 423 lines)
□ Agent Builder agent (Agent #11) — system prompt and orchestration — AGENT FILE EXISTS, INTEGRATION PARTIAL

Tasks — Generated App Runtime Templates:
□ Agent runtime template (src/agents/runtime.ts) — NOT IMPLEMENTED
□ Tool registry template (src/agents/tools/registry.ts) — NOT IMPLEMENTED
□ Memory manager template (src/agents/memory.ts) — NOT IMPLEMENTED
□ Guardrails template (src/agents/guardrails.ts) — NOT IMPLEMENTED
□ Chat API route template (src/app/api/agents/[agentId]/chat/route.ts) — NOT IMPLEMENTED
□ ChatWidget component template (floating + full-page modes) — NOT IMPLEMENTED
□ Agent conversation tables in generated app schema — NOT IMPLEMENTED
□ Knowledge base: pgvector setup, document upload, chunking, embedding — NOT IMPLEMENTED
□ Agent analytics dashboard template — NOT IMPLEMENTED
□ AppModel index: agents section — NOT IMPLEMENTED

Deliverable: User can visually create AI agents that run inside their generated app,
using the app's own APIs as tools, with conversation memory, guardrails, and embedded chat UI.

NOTE: The visual agent builder UI is fully complete. The main gap is generating the
agent runtime code into the generated apps — the runtime templates, tool registry,
memory management, guardrails, chat API, and ChatWidget component.
```

### Phase 9: AI-Powered App Features (Weeks 26-28) — STATUS: ~40% COMPLETE

```
Goal: Intelligent features embedded in generated apps

Tasks — Platform Configuration UI (DONE):
✅ AI features panel in project settings (AIFeaturesPanel.tsx)
✅ AI configuration endpoints (ai_features.py router — 283 lines)
✅ Smart field configuration in Data Model Editor (SmartFieldEditor.tsx)
✅ Workflow AI node types defined (types/workflow.ts)
✅ AI workflow actions on backend (runtime/ai/ — generate, extract, classify, decide)
✅ AI rule forms in Rules Editor (AIRuleForms.tsx)
✅ Planner agent: auto-detect AI requirements from user descriptions
✅ Cost tracking panel (CostTrackingPanel.tsx)

Tasks — Generated App Templates (NOT IMPLEMENTED):
□ Smart field runtime (src/infrastructure/ai/smart-fields.ts template)
□ Smart field types: ai_classify, ai_summarize, ai_sentiment, ai_extract,
  ai_generate, ai_translate, ai_score
□ Smart field test console ("Test with sample data" button)
□ Smart field UI indicators (✦ icon, override, recompute)
□ Async smart field computation (non-blocking API response)
□ Semantic search: pgvector setup, embedding computation, hybrid search
□ Semantic search UI component with score display
□ AI-assisted UI components: SmartFormField, InlineAssistant
□ NaturalLanguageQuery component (text → SQL → results → summary)
□ SmartFilterBar component (natural language → structured filters)
□ DataInsightsPanel component (auto-generated insights)
□ Scheduled AI tasks via workflow engine
□ AI configuration file template (ai-config.ts, ai-usage.ts)
□ Code Generator: generate smart field configs and AI components

Deliverable: Generated apps can include AI-powered features like
auto-categorization, semantic search, content generation, intelligent
workflow decisions, and natural language data queries — all configured
visually and running on the app's own Anthropic API key.

NOTE: Platform-side AI config and workflow AI actions are built.
The gap is code generation templates for generated apps.
```

### Phase 10: Multi-App Portal & Polish (Weeks 29-31) — STATUS: ~30% COMPLETE

```
Goal: Production readiness

Tasks (Polish):
✅ Export: ZIP download with README (main.py download endpoint)
□ Export: git push to user's repository — NOT IMPLEMENTED
□ Export: Dockerfile generation for production deployment — NOT IMPLEMENTED
✅ Error handling: graceful agent failures (ErrorHandlerMiddleware)
□ Error handling: preview server crash recovery — PARTIAL
□ Performance: agent response caching for common patterns — NOT IMPLEMENTED
□ Performance: incremental AppModel updates (not full re-index) — NOT IMPLEMENTED
✅ UX: keyboard shortcuts for common actions (useKeyboardShortcuts.ts)
✅ UX: command palette (Cmd+K) — portal store has command palette state
□ UX: onboarding tutorial for new users — PARTIAL (portal store has onboarding state)
✅ UX: template apps (seeds/templates.py)
✅ Testing: integration tests (test_api_integration.py, test_auth.py, test_workflows.py)
□ Testing: E2E tests for visual editors — NOT IMPLEMENTED
□ Documentation: user guide — NOT IMPLEMENTED
✅ Monitoring: agent cost tracking per project (CostTrackingPanel, MetricsMiddleware)
✅ Monitoring: error logging and alerting (Sentry integration, structured logging)

Deliverable: Production-ready platform with multi-app portal,
SSO across apps, and enterprise-grade deployment options.

Tasks (Portal):
□ Multi-app portal generation (auto-generated per org) — PORTAL STORE EXISTS, NOT GENERATING
□ App grid with role-based visibility — PARTIAL (portal.py router)
□ Unified task inbox (pending approvals/tasks across all apps) — NOT IMPLEMENTED
□ Cross-app notifications and activity feed — PARTIAL (notification_service.py)
□ Portal API endpoints in generated apps (/api/portal/tasks, badges, activity) — NOT IMPLEMENTED
□ SSO token sharing across apps in same org — SSO ROUTER EXISTS, NOT COMPLETE
□ Quick search across all apps — NOT IMPLEMENTED

Tasks (Polish):
□ Export: ZIP download with README
□ Export: git push to user's repository
□ Export: Dockerfile generation for production deployment
□ Error handling: graceful agent failures with retry
□ Error handling: preview server crash recovery
□ Performance: agent response caching for common patterns
□ Performance: incremental AppModel updates (not full re-index)
□ UX: keyboard shortcuts for common actions
□ UX: command palette (Cmd+K)
□ UX: onboarding tutorial for new users
□ UX: template apps (task manager, CRM, inventory — pre-built plans)
□ Testing: integration tests for agent pipelines
□ Testing: E2E tests for visual editors
□ Documentation: user guide
□ Monitoring: agent cost tracking per project
□ Monitoring: error logging and alerting
```

### Timeline Summary

```
Phase 0:  Org Foundation          Weeks 1-2    ~85%  (backend done, frontend org pages minimal)
Phase 1:  Foundation              Weeks 3-5    ~95%  (core generation + preview + templates)
Phase 2:  Refinement & Chat       Weeks 6-7    ~90%  (conversational editing + discovery agent)
Phase 3:  Data Model Editor       Weeks 8-9    ~95%  (visual ERD + DB browser)
Phase 4:  Rules, Decisions & ACL  Weeks 10-13  ~85%  (rules + FEEL-lite done; DRD visual + codegen gaps)
Phase 5:  Workflow Editor         Weeks 14-16  ~85%  (runtime + visual done; generated app templates gap)
Phase 6:  UI Editor               Weeks 17-20  ~80%  (PIVOTED to Agentic React Builder — working)
Phase 7:  Navigation & Modules    Weeks 21-22  ~70%  (nav editor done; module pipeline incomplete)
Phase 8:  AI Agent Builder        Weeks 23-25  ~80%  (visual builder done; generated app runtime gap)
Phase 9:  AI-Powered Features     Weeks 26-28  ~40%  (platform config done; generated app templates gap)
Phase 10: Portal & Polish         Weeks 29-31  ~30%  (monitoring done; portal/export/E2E gaps)

Total: ~31 weeks (7.75 months) for a small team (2-3 developers)

Status as of 2026-03-06: Approximately 75-80% overall completion.
Core generation pipeline, all visual editors, workflow runtime, FEEL-lite engine,
and authentication are production-grade. Main remaining work is:
  1. Generated app code templates (FEEL-lite, decisions, RBAC, AI, agents, workflows)
  2. Module system pipeline (multi-module generation, dependency tracking)
  3. Frontend org management pages (flesh out placeholder UIs)
  4. Multi-app portal (cross-app SSO, task inbox, activity feed)
  5. Export/deployment (Dockerfile, git push)
  6. DRD visual editor (React Flow for decision requirement diagrams)
```

### Team Composition

```
Developer 1 (Backend/AI):
  - All agent prompts and orchestration (including Agent Builder, Discovery agents)
  - Discovery Agent system prompt and multi-turn conversation logic
  - Template library curation and seed data
  - Org-aware suggestion engine
  - Backend API endpoints (org, RBAC, projects, templates, discovery)
  - Org structure APIs and CSV import
  - RBAC policy engine (field-level, record-level, workflow assignment)
  - Preview manager + Docker integration
  - Org-to-app identity sync system
  - Workflow runtime (including assignment/approval/escalation + decision evaluation)
  - FEEL-lite parser and evaluator (backend validation + generated app template)
  - Decision table evaluator engine (shared by rules engine + workflow engine)
  - Decision graph (DRD) evaluator with topological sort
  - Decision versioning and execution audit logging
  - Agent runtime templates (for generated apps)
  - Agent guardrails and memory system

Developer 2 (Frontend/Visual):
  - All visual editors (React Flow, Agentic React Builder)
  - Org chart visual editor (React Flow)
  - Field access matrix editor
  - Decision table editor component (spreadsheet grid, hit policy selector, cell editor)
  - Decision graph (DRD) mini-canvas (React Flow)
  - No-code condition builder (field/operator/value with AND/OR nesting)
  - Expression editor with FEEL-lite syntax highlighting and autocomplete
  - Decision test panel (inline tester, saved test cases, coverage indicator)
  - Decision validation overlays (completeness, overlap, subsumption highlighting)
  - Rule templates gallery (score card, routing matrix, discount ladder, etc.)
  - Agent Builder visual editor (React Flow canvas)
  - Template gallery page and template detail/customization views
  - Discovery conversation UI
  - Org dashboard suggested apps section
  - "New App" creation flow (describe / template / discover / figma)
  - Frontend pages and components (org dashboard, app workspace)
  - State management (Zustand stores)
  - Instruction builder (including agent + RBAC + decision actions)
  - Code editor (Monaco)
  - Multi-app portal

Developer 3 (Full-stack/Integration):
  - AppModel index system (including agents, orgAware, decisions sections)
  - Binding and rules propagation
  - Decision table code generation templates (for generated apps)
  - Schema-aware variable binding (autocomplete provider from AppModel)
  - Module system and cross-module dependencies
  - Multi-tenancy middleware (org_id scoping)
  - SSO and cross-app auth token system
  - Agent tool registry and API-to-tool mapping
  - Knowledge base (pgvector integration)
  - Export/deployment features
  - Testing and DevOps
```

---

## Appendix A: Environment Variables

```env
# Platform
DATABASE_URL=postgresql://tentoroforge:tentoroforge@localhost:5432/tentoroforge
ANTHROPIC_API_KEY=sk-ant-...
JWT_SECRET=your-jwt-secret
FRONTEND_URL=http://localhost:3000

# Ports
BACKEND_PORT=6500
FRONTEND_PORT=3000

# Preview port ranges
PREVIEW_PORT_MIN=3200
PREVIEW_PORT_MAX=3299
DB_PORT_MIN=5500
DB_PORT_MAX=5599

# Agent config
DEFAULT_MODEL=claude-sonnet-4-20250514
UTILITY_MODEL=claude-haiku-4-5-20251001
MAX_GENERATION_TURNS=80
MAX_REFINEMENT_TURNS=30
```

## Appendix B: Key Dependencies

```
# Backend (requirements.txt)
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
claude-agent-sdk>=0.1.0
sqlalchemy[asyncio]>=2.0.0
asyncpg>=0.30.0
alembic>=1.14.0
python-dotenv>=1.0.0
sse-starlette>=2.2.0
httpx>=0.28.0
pydantic>=2.10.0
python-jose>=3.3.0     # JWT
passlib>=1.7.4          # password hashing
docker>=7.0.0           # Docker SDK

# Frontend (package.json)
next: ^15.0.0
react: ^19.0.0
typescript: ^5.7.0
tailwindcss: ^4.0.0
@tailwindcss/postcss: ^4.0.0
zustand: ^5.0.0
@tanstack/react-query: ^5.0.0
@xyflow/react: ^12.0.0        # React Flow (for visual editors)
grapesjs: ^0.22.0              # GrapesJS core (UI editor engine)
@grapesjs/react: ^2.0.0       # React wrapper (white-label via <Canvas/>)
@monaco-editor/react: ^4.6.0  # Monaco editor
@dnd-kit/core: ^6.0.0         # drag and drop
lucide-react: ^0.468.0
react-hook-form: ^7.54.0
zod: ^3.24.0
ky: ^1.7.0

# Generated App — AI Dependencies (added when AI features are present)
@anthropic-ai/sdk: ^0.39.0    # Anthropic SDK for agent runtime + smart fields
pgvector: ^0.2.0              # pgvector client (semantic search + knowledge base)
openai: ^4.76.0               # OpenAI SDK for embeddings (text-embedding-3-small)
```

## Appendix C: Design Decisions Log

```
Decision 1: Code as source of truth (not AppModel)
  Why: Bidirectional sync between model and code is extremely hard.
       The LLM can read code naturally. The AppModel index is just
       a navigation aid to help the LLM find files faster.

Decision 2: LLM for all code changes (not AST)
  Why: Simpler architecture. One pipeline for chat + visual editors.
       AST manipulation requires building parsers for every pattern.
       LLM handles all patterns naturally. Speed tradeoff is acceptable
       for an app builder (not a real-time design tool).
  Future: Add thin AST layer for high-frequency property changes
       (color picker, spacing slider) if latency becomes an issue.

Decision 3: PostgreSQL from day one (not SQLite)
  Why: Real types, real constraints, real enums. Same database in
       dev and production. Docker Compose makes it zero-config.
       Enterprise apps need Postgres features (JSONB, full-text search,
       proper transactions, concurrent writes).

Decision 4: Drizzle ORM (not Prisma)
  Why: Schema is TypeScript (LLM already knows TypeScript).
       No code generation step. No binary engine dependency.
       drizzle-kit push for instant schema changes during development.
       Easier for the LLM to edit (it's just a .ts file).

Decision 5: Module-based architecture for generated apps
  Why: Enterprise apps are too large for single-pass generation.
       Modules keep each generation task manageable (10-30 files).
       Cross-module dependencies are explicit and tracked.
       Modules can be added/removed independently.

Decision 6: Thin workflow runtime + LLM-generated action functions
  Why: Runtime handles flow control (simple, deterministic).
       LLM handles business logic (complex, needs context).
       Visual editor writes workflow JSON (instant, no LLM needed).
       Only action function generation needs LLM.
       Best of both worlds: visual editing speed + LLM flexibility.

Decision 7: Haiku for utility agents, Sonnet for creative agents
  Why: Orchestrator, Indexer, and Validator don't need creative
       problem-solving — they classify, extract, and verify.
       Haiku is 10x cheaper and faster for these tasks.
       Code Generator, Refiner, and Planner need strong reasoning
       and code generation capability — Sonnet is appropriate.

Decision 8: Agent runtime in generated app calls Anthropic API directly
  Why: Agents run inside the generated app, not through our platform.
       The generated app owns its own Anthropic API key.
       This means deployed apps are independent — they don't need
       our platform running to serve agent requests.
       The platform only creates the agent code; it doesn't proxy requests.
       This architecture means generated apps are fully self-contained.

Decision 9: Agent tools use the app's own API routes (not direct DB)
  Why: Reuses existing validation, auth, and business logic in API routes.
       No duplicate code. Access control is already enforced at the API layer.
       Tools are auto-discovered from the AppModel — no manual mapping.
       If the API changes, the tool automatically gets the new behavior.
       Only custom tools (knowledge base search, external APIs) need
       dedicated handler files.

Decision 10: pgvector for knowledge base (not external vector DB)
  Why: The app already has PostgreSQL. pgvector is a simple extension.
       No additional infrastructure (no Pinecone, Weaviate, etc.).
       Keeps the generated app self-contained and easy to deploy.
       HNSW indexes provide fast enough search for most use cases.
       For very large knowledge bases (>1M chunks), can switch to
       dedicated vector DB — but that's an edge case for app builders.

Decision 11: Haiku for smart fields and AI workflow nodes
  Why: Smart fields run on every record create/update — they must be
       fast and cheap. Haiku handles classification, extraction, and
       summarization well enough. Only complex generation tasks
       (e.g., content generation, nuanced decisions) use Sonnet.
       Typical cost: ~$0.001 per smart field computation.
       At 1000 records/day with 3 smart fields each = ~$3/day.

Decision 12: Async smart field computation (non-blocking)
  Why: LLM calls take 200-2000ms. Blocking the API response would
       make the UI feel slow. Instead, the API returns immediately
       and smart fields populate asynchronously. The UI shows a
       loading indicator on smart fields until they're computed.
       For use cases requiring synchronous computation (e.g., AI
       validation that must block), a sync mode is available.

Decision 13: Planner auto-detects AI requirements from natural language
  Why: Users shouldn't have to explicitly request "AI features."
       When someone says "auto-categorize tickets," the Planner
       should recognize this implies a smart field. This makes the
       platform feel intelligent — it understands intent, not just
       explicit instructions. The mapping table in Section 21.2
       covers common patterns.

Decision 14: Organization as root entity (not project)
  Why: Enterprise apps don't exist in isolation. An org has multiple
       apps, shared users, shared roles, and cross-app workflows.
       Making organization the root entity enables:
       - Single identity across all apps (no duplicate accounts)
       - Org-wide RBAC that the Planner can auto-infer
       - Cross-app task inbox and portal
       - Consistent access control patterns across apps

Decision 15: Org structure in platform DB, synced to generated apps
  Why: The org structure is the developer's concern, not the app's.
       Storing it in the platform DB means:
       - One place to manage people, roles, departments
       - Changes propagate to all apps automatically
       - Generated apps are simpler (they consume, not define)
       - No risk of org data drifting between apps
       Sync is lightweight: just users, roles, and policies.

Decision 16: Planner auto-infers RBAC from org structure
  Why: The developer should NOT have to manually specify "who can
       see what field." The Planner knows the org has departments
       and roles — it can infer sensible defaults:
       - Sensitive fields (cost, salary) restricted to relevant dept
       - Record scope based on department ownership
       - Approval chains follow reporting lines
       The developer reviews and adjusts, not builds from scratch.

Decision 17: Three-layer RBAC (org → app → field/record)
  Why: Single-layer RBAC (just roles) is too coarse for enterprise.
       Field-level access is critical: a sales manager should see
       deal amounts but not employee salaries. Record-level scoping
       is critical: a regional manager should only see their region.
       Three layers give maximum flexibility with minimum config.
       Each layer has a sensible default (visible to all) so the
       developer only configures what needs restricting.

Decision 18: Discovery Agent produces a structured brief, not code
  Why: The Discovery Agent's output is a requirements document (brief),
       not a technical plan. This keeps the pipeline clean:
       Discovery → Brief → Planner → Plan → Code Generator → Code.
       The Planner already knows how to turn requirements into plans.
       Making Discovery produce plans would duplicate Planner logic.
       The brief format is simple enough for the user to review and
       approve before passing to the Planner.

Decision 19: Template library with Planner-format plans (not generated code)
  Why: Templates store structured plans (entities, pages, workflows),
       not pre-generated source code. This means:
       - Templates work with any future code generation improvements
       - Templates can be customized before generation
       - The same template produces different code for different orgs
         (because the Code Generator adapts to org structure and RBAC)
       - No maintenance burden of keeping template code up to date
       - Templates are small (JSON) and easy to version

Decision 20: GrapesJS over Craft.js for UI editor
  Why: GrapesJS provides 6-12 months of built-in features we'd have to
       build from scratch with Craft.js:
       - Style Manager (visual CSS editor, 50+ properties, per-breakpoint)
       - Layer Manager (component tree)
       - Device Manager (responsive preview)
       - Undo/Redo Manager (reliable, keyboard shortcuts)
       - Block Manager, Selector Manager, Asset Manager
       Craft.js is headless — zero built-in UI, everything from scratch.
       Craft.js also has 225 open issues, last npm publish >1 year ago,
       and the maintainer is focused on Reka.js rewrite.
       GrapesJS: 25K stars, 110K weekly downloads, actively maintained.
       Using @grapesjs/react with <Canvas/> we disable all default UI
       and build our own panels with shadcn/ui — fully white-labeled.
       The canvas renders in an iframe (style isolation is a feature,
       not a bug — generated app CSS can't break our editor chrome).
       Neither library generates React source code, but our architecture
       doesn't need that — the editor produces instructions, the LLM
       generates the code. GrapesJS just needs to be a great editor.

Decision 21: No separate Form Builder — forms are UI editor components
  Why: A form is just a section of a page. Having a separate Form Builder
       and Page Builder forces users to choose "which editor?" — unnecessary
       friction. Instead, the UI Editor's component palette includes a rich
       Form category with 25+ field types (text, select, date, file, etc.).
       Each form component has traits for validation, data binding,
       conditional visibility, and submit actions. A multi-step wizard is
       just form groups inside a FormStepper component. This is what modern
       tools (Retool, Webflow) do — forms are components, not a separate editor.

Decision 22: Clean Architecture for generated apps
  Why: The original flat structure (API routes with inline DB queries,
       business logic mixed with HTTP handling, grab-bag lib/ folder)
       made generated apps hard to test, extend, and reason about.
       Clean Architecture enforces strict layer separation:
       - domain/ — pure business logic, zero framework dependencies
       - application/ — services orchestrating use cases
       - infrastructure/ — DB repositories, auth, AI, email adapters
       - app/ — thin HTTP handlers delegating to services
       - components/ — presentation only
       This structure gives the LLM agents clear placement rules for
       every type of code. Import direction is enforced: domain has
       zero dependencies, services coordinate domain + infrastructure,
       route handlers never touch the database directly. Generated apps
       become testable (domain logic is pure functions), maintainable
       (each layer can change independently), and production-ready.
       The cost is slightly more files, but the benefit is that both
       humans and LLMs always know where to put new code.

Decision 23: Server Components by default, Client Components only for interactivity
  Why: Generated apps are enterprise CRUD tools — 80% of pages are
       read-heavy lists and detail views. Server Components eliminate
       client-side JS for these pages, giving instant first paint.
       Server Components can call services directly (no API fetch
       roundtrip for reads), which pairs naturally with Clean
       Architecture's service layer. Client Components are reserved
       for forms with state, real-time UI, and interactive tables.
       API routes remain the primary mutation pattern (not Server
       Actions) because they're more portable, testable, and the
       agents already know how to generate them. Server Actions may
       be used as thin wrappers calling the same services when
       convenient, but they're optional.

Decision 24: Socket.IO for real-time push, SSE for agent streaming
  Why: Generated apps need real-time for specific features: smart
       field completion (async compute → push result), workflow task
       assignments (instant notification), live data refresh (another
       user updates a record), and collaborative editing (future).
       Socket.IO over raw WebSockets because:
       - Automatic reconnection + fallback to long-polling
       - Room-based broadcasting (per-org, per-user, per-record)
       - Works behind corporate proxies that block WS upgrades
       - Next.js lacks native WS support; Socket.IO's standalone
         server attaches to the same HTTP server cleanly
       Real-time is NOT added to every app — only when the Planner
       detects features that need it (agents, workflows with
       assignments, smart fields, collaboration). This keeps simple
       apps simple. SSE stays for agent chat streaming because it's
       simpler, one-directional, and already works well. Using both
       SSE and Socket.IO is intentional: right tool for each job.
       Real-time files live in src/infrastructure/realtime/ — isolated
       from business logic per Clean Architecture.
```

---

## 25. Virtual Office

A canvas-based 2D visualization of AI agents working in a virtual office, rendered at 60fps. Provides real-time feedback during app generation — users see agents walking between rooms, collaborating, working at desks, and celebrating when the build succeeds.

### 25.1 Architecture

```
frontend/src/components/virtual-office/
├── VirtualOffice.tsx       # React wrapper: canvas setup, mouse events, HUD overlay
├── OfficeRenderer.ts       # Canvas 2D renderer: game loop, camera, drawing layers
├── OfficeStateManager.ts   # Zustand store: agent lifecycle, event processing
├── AgentCharacter.ts       # Per-agent state machine: idle/walking/working/celebrating
├── Pathfinder.ts           # A* grid pathfinding on walkable tiles
├── SpriteLoader.ts         # Async sprite sheet loading with colored-circle fallback
├── layout.ts               # 3×3 room grid (28×22 tiles), desks, furniture, corridors
├── types.ts                # Agent registry, event types, AGENT_PHASE_MAP, PHASE_ROOM_MAP
├── index.ts                # Re-exports
├── hud/                    # HTML overlay components
│   ├── PipelineProgress.tsx    # Top progress bar
│   ├── AgentTooltip.tsx        # Hover tooltip with agent role/status
│   ├── MiniMap.tsx             # Bottom-right minimap
│   ├── SpeedControls.tsx       # Bottom-left speed (1×/2×/4×)
│   └── AgentPanel.tsx          # Right slide-out panel on agent click
└── utils/
    ├── camera.ts               # Camera pan/zoom/follow, smooth interpolation
    └── animation.ts            # Bob/walk/work frame helpers
```

### 25.2 Office Layout

- **3×3 grid** of themed rooms with corridors between them
- **28×22 tile grid**, each tile is a fixed pixel size
- **Lobby** at grid center (14, 11) — celebration and protest gathering point
- Each room has: walls, floor color, furniture (desks, whiteboards, servers), assigned desks per agent
- Corridors are walkable tiles connecting rooms, used by A* pathfinder

### 25.3 Agent States

| State | Sprite | Animation | Trigger |
|-------|--------|-----------|---------|
| `idle` | idle | Slight bob (0.5×) | Default, after goIdle() |
| `waiting` | idle | Slight bob (0.5×) | Waiting for handoff |
| `walking` | idle | Double bob (2×), follows A* path | moveTo() called |
| `working` | working | No bob, orbiting sparkles | startWorking() |
| `reading` | working | No bob, glow | startReading() |
| `celebrating` | idle | Big bounce (-6px) + lateral sway (±4px) | celebrate() |
| `protesting` | walk | Fast lateral shake + vertical bounce, red glow, "!!" | protest(sign) |
| `error` | idle | Shake effect (±1.5px) | setError() |
| `handoff` | idle | Double bob, walking to target | During handoff transit |

### 25.4 Event System

Events flow: **Backend SSE → Frontend chat.ts → OfficeStateManager → OfficeRenderer**

| Event | Behavior |
|-------|----------|
| `agent_start` | Agent pathfinds to desk, starts working, shows speech bubble |
| `agent_status` | Updates speech bubble text, optional progress |
| `agent_complete` | Shows "Done!" / "Complete!", walks back to home desk, goes idle |
| `agent_handoff` | From-agent walks to to-agent, shows handoff bubble, to-agent starts working, from-agent walks home after 1.5s |
| `agent_error` | Red error state, error speech bubble |
| `phase_start` | Activates phase-specific agents via `AGENT_PHASE_MAP` (not all room agents) |
| `phase_complete` | Completes phase agents, walks them home, updates progress bar |
| `parallel_start` | Multiple agents start simultaneously |
| `build_success` | All agents pathfind to lobby, celebrate, confetti spawns |
| `credits_exhausted` | All agents scatter around lobby, protest with randomized signs |

**Phase mapping:** `AGENT_PHASE_MAP` maps each agent ID to its pipeline phase. `PHASE_ROOM_MAP` maps phases to rooms. Only the agents assigned to a phase are activated by `phase_start`, preventing unrelated agents from starting work.

### 25.5 Rendering Layers (back to front)

1. **Floors** — Colored tiles per room
2. **Paths** — Corridor tiles
3. **Active Room Highlights** — Pulsing glow overlay + animated border for rooms with working agents
4. **Walls** — Room borders with colored outlines
5. **Furniture** — Sprites with themed fallback icons (desks, whiteboards, servers, plants)
6. **Characters** — Sorted by Y for depth, sprites with fallback colored circles + initial
7. **Room Labels** — Room names above each room
8. **Speech Bubbles** — Timed display (5s + 1s fade), color-coded borders (green=success, red=error)
9. **Effects** — Orbiting sparkles around working agents
10. **Confetti** — Particle system during celebration

### 25.6 Confetti System

Triggered when any agent enters the `celebrating` state (typically after `build_success`):

- **120 particles** spawned around the lobby
- **Physics:** gravity (0.08 per frame), air resistance (0.99× velocity), rotation
- **12 colors:** bright palette including red, yellow, green, blue, pink, purple
- **Lifetime:** 3–5 seconds with 0.5s fade-out
- **Shape:** Small colored rectangles with rotation
- Spawns once per celebration cycle (resets when no agents are celebrating)

### 25.7 Canvas Interaction

- **Pan:** Click + drag (3px distance threshold distinguishes drag from click)
- **Zoom:** Mouse wheel (0.3× to 6× range), targets `camera.targetZoom`
- **Agent click:** Selects agent, opens AgentPanel slide-out
- **Agent hover:** Shows AgentTooltip with role and current status
- **Camera:** Smooth interpolation between current and target position/zoom
- **Cursors:** `cursor-grab` default, `cursor-grabbing` while dragging

### 25.8 Event Bridge (chat.ts → OfficeStateManager)

The frontend chat store bridges SSE events to the office in two ways:

1. **Direct office events:** Backend sends `sse_event("office", {...})` — forwarded directly to `officeStore.handleEvent()`
2. **Log tag detection:** Log/message events prefixed with `[Tag]` (e.g., `[Schema]`, `[QA]`) are mapped via `LOG_TAG_TO_AGENT` to agent IDs, triggering `agent_start` or `agent_status` events
3. **Phase transitions:** Status messages are parsed by `detectPhaseIndex()` to trigger `phase_start` / `phase_complete` in the office

---

## 26. Domain Context System

### 26.1 Purpose

Every agent in the pipeline receives a domain-specific persona that grounds its output in real-world industry knowledge. A Healthcare app gets agents who think like hospital IT architects; a Finance app gets agents who know SOX compliance and trading workflows.

### 26.2 Detection

`services/domain_context.py` classifies the domain from the user's app description using keyword matching:

- **17 supported domains:** Healthcare, Hospitality & Food, Finance & Banking, E-Commerce & Retail, Education, Human Resources, Real Estate & Property, Manufacturing, Logistics & Supply Chain, Legal, Project Management, CRM & Sales, Government & Public Sector, Non-Profit, Media & Content, Agriculture, Energy & Utilities
- **Fallback:** "General Business" when no keywords match
- **Ordered matching:** More specific domains checked first (e.g., "restaurant" matches Hospitality before E-Commerce's broader keywords)
- Keywords list uses tuples (not dict) to guarantee check order

### 26.3 Persona Generation

For each of the 9 agent roles, a persona string is generated:

```python
{
    "planner": "You are a senior product owner with 20+ years building {domain} systems...",
    "contract_writer": "You are a principal software architect specializing in {domain} platforms...",
    "schema_designer": "You are a database architect with deep experience in {domain} data modeling...",
    "auth_agent": "You are a security engineer specializing in {domain} applications...",
    "api_generator": "You are a backend engineer who has built production {domain} APIs...",
    "business_logic": "You are a domain expert with extensive experience in {domain} business processes...",
    "component_builder": "You are a senior UI/UX engineer who has designed interfaces for {domain} apps...",
    "page_assembler": "You are a frontend architect who has built complete {domain} applications...",
    "qa_tester": "You are a QA engineer with domain expertise in {domain} applications...",
}
```

### 26.4 Injection

Each agent's `run_*()` function accepts `domain_context: dict | None`. The persona is appended to the system prompt as:

```
## YOUR DOMAIN EXPERTISE
{persona string}
```

This is injected via `get_agent_persona(domain_ctx, role)` which returns empty string if no context is available, so agents degrade gracefully to their generic prompts.


---

## 27. Current State Audit (2026-07-21)

The core narrative in §1–§26 was last touched in May 2026 (`d56e023`).
Below is an authoritative overlay of every material capability that has shipped
since — organized by the §1–§26 section each item modifies or extends. When §1–§26
and §27 disagree, **§27 wins** (it was generated by a multi-agent scan of the
actual on-disk code on 2026-07-21).

Drift tags: 🆕 NEW = not in blueprint · ⚠️ CORRECTS = doc has wrong info ·
➕ EXTENDS = mentioned but incomplete · ✓ CONFIRMS = §1–§26 already describes this accurately


### 27.1 Updates to §1 Platform Overview

**Top-level architecture: FastAPI backend + Next.js frontend + generated-app output tree** — ➕ EXTENDS

Runtime today: FastAPI (uvicorn) backend on port 6500, Next.js 15 / React 19 frontend on port 6501, per-project generated apps in /output/<short_id>/ each with their own Postgres DB (per-project db_port), plus a Playwright-based render-service subpackage. The FastAPI app registers 36 routers and 5 middleware layers (ErrorHandler → Metrics → StructuredLogging → SecurityHeaders → RateLimit → CORS), and boots a background TimerScheduler at startup for workflow timer fire-and-forget.

Files: `backend/main.py`, `frontend/package.json`, `output`

**Agent surface (backend/agents/)** — 🆕 NEW

Agents/ ships 40+ LLM-agent modules including the new Smith orchestrator (smith_agent), planner + plan_critic, domain_agent, discovery, contract_agent, schema_agent + page_schema_agent + feature_slice_schema_agent + shell_layout_agent + page_layout_agent, api_agent, business_logic_agent, component_agent, page_agent, qa_agent, rules_agent, seed_generator, ahtml_conversion_agent + figma_ir_agent + figma_mcp_agent + figma_schema_refiner + figma_ui_agent, fix_agent + fix_chat_agent + fix_diagnoser, refiner, patch_agent, peer_patcher, wiring_guard, validator, indexer, orchestrator, app_map_agent, ir_edit_agent + ir_qa_agent + ir_router, code_editor + code_generator, design_analyzer + design_researcher, completeness_checker, tool_app_modifier.

Files: `backend/agents`

**Startup lifecycle — TimerScheduler + preview cleanup** — 🆕 NEW

On startup FastAPI instantiates and awaits app.state.timer_scheduler = TimerScheduler() (fires workflow_instances waiting on timer nodes). On shutdown it calls stop_all_previews() (kills every dev-server subprocess spawned via preview.py) and stops the timer scheduler. Preview lifecycle is per-project: start_preview/stop_preview/get_preview_port persist in an in-process registry.

Files: `backend/main.py`, `backend/runtime/timer_scheduler.py`, `backend/preview.py`

**Deployment surface — Docker only, no k8s** — ⚠️ CORRECTS

Deployment today is Docker Compose only (root docker-compose.prod.yml plus backend/docker-compose.yml plus per-service Dockerfiles for backend and frontend). No Kubernetes manifests are checked in yet (a K8s brainstorm exists in the task history but was not shipped). Local dev boots via ./start-all.sh which pins ports to backend 6500 / frontend 6501.

Files: `docker-compose.prod.yml`, `backend/Dockerfile`, `backend/docker-compose.yml`, `frontend/Dockerfile`

**Runtime workflow engine inside the platform** — 🆕 NEW

backend/runtime/ is a first-class in-platform execution layer: engine.py (workflow interpreter), state_manager.py, task_executor.py, timer_scheduler.py, decision_evaluator.py, gateway_controller.py, variable_resolver.py, execution_logger.py, assignment.py (task assignment strategies), feel_lite/ (expression sub-language), ai/ (AI-node handlers), actions/. This is distinct from the runtime SHIPPED INTO generated apps under backend/templates/runtime/.

Files: `backend/runtime`


### 27.2 Updates to §2 Tech Stack

**Backend tech stack — SQLAlchemy 2 async + Alembic + asyncpg** — ➕ EXTENDS

Backend runs SQLAlchemy 2 with the async extension over asyncpg, migrations managed by Alembic (18 revision files under backend/alembic/versions, including enterprise_readiness_tables and merge_divergent_heads). Pydantic v2 (with email extra) is used for schemas. python-jose + passlib[bcrypt] + python-multipart provide the auth stack.

Files: `backend/requirements.txt`, `backend/alembic.ini`

**Backend tech stack — observability additions** — 🆕 NEW

Observability is first-class: a MetricsMiddleware exposes GET /metrics in Prometheus format, StructuredLoggingMiddleware ships JSON logs, and Sentry (sentry-sdk[fastapi] with FastApiIntegration + StarletteIntegration) is initialised when SENTRY_DSN is set with per-env sample rates. In production the /docs and /redoc routes are hidden.

Files: `backend/middleware/metrics.py`, `backend/middleware/logging.py`, `backend/requirements.txt`

**Backend tech stack — Redis, S3, Playwright, image/brand deps** — 🆕 NEW

New optional deps: redis (caching/job queues), boto3 (S3 file storage), Playwright 1.49.0 (render-service browser automation), Pillow+numpy+scikit-learn (brand_extractor for palette extraction from screenshots/logos), jsonpatch 1.33 (RFC-6902 for the fidelity-loop patch applier), Faker 30.6 (fixture/seed generation).

Files: `backend/requirements.txt`, `backend/services/brand_extractor.py`, `backend/services/render_service`

**Backend tech stack — Claude Agent SDK subprocess model** — ⚠️ CORRECTS

Agents run via claude-agent-sdk (>=0.1.0), which spawns a bundled Claude CLI subprocess. main.py deletes CLAUDECODE / CLAUDE_CODE_ENTRYPOINT env vars on startup so nested Claude Code sessions can spawn the CLI, and setdefaults CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000 to avoid 32k truncation on large plans.

Files: `backend/main.py`, `backend/agent.py`

**Frontend tech stack** — ➕ EXTENDS

Frontend is Next.js 15.1 + React 19 + TypeScript 5.7, styled with Tailwind v4 (@tailwindcss/postcss) and shadcn 3.8, state via Zustand 5 + TanStack Query 5.90, flow/canvas via @xyflow/react 12 + dagre, radix-ui + cmdk + lucide-react + sonner for UI, next-themes for theming, react-markdown + remark-gfm for chat/narrative rendering, prism-react-renderer for code, @monaco-editor/react for the code panes, and canvas-confetti. It consumes 7 workspace packages (@tentoroforge/schema/renderer/library/editor/engine, @forge/patches, @forge/registry). Tests via Vitest 3 + jsdom 25.

Files: `frontend/package.json`


### 27.3 Updates to §3 Project Structure

**Project structure — monorepo workspaces** — ➕ EXTENDS

Root is an npm workspace (not pnpm-workspace despite pnpm-lock files) with workspaces: packages/*, apps/*, frontend, frontend/src/lib/feel-lite. Thirteen packages ship: @tentoroforge/{schema, renderer, library, editor, engine, ir, ahtml, compiler, patterns, figma-parser, roundtrip} and @forge/{registry, patches}. Build split into two waves: build:engine-stack (schema→renderer→library→engine) then build:editor-stack (registry→patches→editor). apps/ contains render-scaffold and visual-regression.

Files: `package.json`, `packages`

**Project structure — top-level directories** — ⚠️ CORRECTS

Repo root now contains: backend/, frontend/, packages/, apps/, output/ (per-project generated apps, 300+ dirs), docs/ (superpowers + product briefs + roadmap + generation-map), scripts/, tools/, plus BLUEPRINT.md/pdf and legacy TASKPLAN/DEVELOPMENT_PLAN/pipeline.md docs. docker-compose.prod.yml lives at root; backend has its own Dockerfile + docker-compose.yml; frontend has a Dockerfile. No k8s manifests currently checked in.

Files: `/Users/m/Work/code/poc/design2ui-forge-v3`

**Project structure — backend/services module count** — 🆕 NEW

backend/services/ is now ~297 files — dwarfing every other backend subdir. It hosts the entire generation pipeline (schema/planner/registry/binding/guards/self-heal), Smith orchestration (~20 smith_*.py files), workflow translation and executability, deterministic pages/forms/shells, actor onboarding, discovery transformer, brand/design extraction, and a substantial guard/repair layer (drizzle_check_guard, fk_type_guard, list_data_source_guard, chart_data_source_guard, surface_wrap_guard, route_content_guard, etc.).

Files: `backend/services`

**Project structure — new backend subpackages** — 🆕 NEW

New backend subpackages: runtime/ (in-platform workflow execution — engine, state_manager, task_executor, timer_scheduler, decision_evaluator, gateway_controller, variable_resolver, execution_logger, assignment, feel_lite/, ai/, actions/), jobs/ (generation_job + worker), middleware/ (5 middleware modules), templates/ (app-foundation, standalone-app, runtime, workflow-engine, workflow-api-routes, api-tasks, plus data-api-route.ts and instrumentation.ts), alembic/, seeds/, fixtures/, contracts/, illustrations_mcp/.

Files: `backend/runtime`, `backend/jobs`, `backend/middleware`, `backend/templates`

**Project structure — routers surface** — 🆕 NEW

36 routers registered on the FastAPI app: auth, orgs, projects, output_projects (filesystem-backed schema editor), generate, templates, discovery, data_model, rules, workflows, decisions, pages, navigation, agent_builder, ai_features, portal, health, runtime_exceptions, notifications, sso, audit, files, environments, webhooks, visual_editor, modules, export, ir, design, brand, app_actions, project_events, plus two debug routers (_debug_schema, _debug_fidelity). output_projects is deliberately mounted BEFORE projects so non-UUID short-ids route to the filesystem editor first.

Files: `backend/routers`

**Frontend project structure — stores** — 🆕 NEW

Frontend uses Zustand stores per subsystem: agent-builder, ai-features, auth, chat, data-model, decision, design-editor, ir-editor, navigation, portal, rules, visual-editor, workflow, and workflow-sim (the visual workflow simulator with its own state machine).

Files: `frontend/src/stores`

**Generated-app template surface (backend/templates/)** — 🆕 NEW

The platform ships several template trees copied/rendered into each generated app: app-foundation (providers, schema-page, layout primitives), standalone-app (Next.js scaffold with next.config.js, tailwind.config.ts, package.json.tmpl), runtime/ (a large in-generated-app runtime: workflows/{engine.ts, index.ts, ai.ts, input-assembly.ts, escalation.ts, audit-log.ts}, data-engine/{aggregate-window, aggregations, saved-views}, api-{cron,documents,export,files,notifications}, feel-lite/, rules/, db/, storage.ts, pdf.ts, seed.ts, error_reporter.ts, event-registry.ts, global-error.tsx, instrumentation.ts, vercel.json), plus workflow-engine/, workflow-api-routes/, api-tasks/, data-api-route.ts, and instrumentation.ts.

Files: `backend/templates`


### 27.4 Updates to §4 Platform Database Schema

**Platform DB — Project + Module + Conversation + AgentJob + Version** — ➕ EXTENDS

projects table: id (uuid), short_id (varchar 16, filesystem key), org_id, name, description, owner_id, status (enum project_status), output_dir, preview_port, db_port, timestamps. Companion tables: modules (project sub-units with slug+config), module_dependencies (typed dependency graph), module_files (typed file inventory), conversations (project chat: role+content+message_type+metadata), agent_jobs (agent_type enum + status enum + instruction/result/error tracking), versions (git-style: commit_hash, message, agent_job_id, files_changed JSONB).

Files: `backend/models/project.py`

**Platform DB — Organization / identity tables** — 🆕 NEW

platform_users (email, password_hash, auth_provider, external_id, avatar_url) plus a rich enterprise-org schema: organizations, org_members (with invite_status enum), departments (self-referencing parent + head_person_id), teams (department-scoped + lead_person_id), org_people (email/name/title/department/team/manager + is_active), org_roles + org_person_roles (RBAC), org_groups + org_group_members (group membership). Backs the actors/roles emitted by planner into generated-app RBAC.

Files: `backend/models/org.py`, `backend/models/auth.py`

**Platform DB — DiscoverySession** — 🆕 NEW

discovery_sessions table (added May, alembic a51e0d4dfcf4): status enum, discovery_type, title, messages JSONB (chat transcript), brief JSONB (StructuredBrief — actors/journeys/authoritative inputs), org_id, user_id, project_id (linked once discovery converts to a project). Persists the pre-plan conversational discovery flow.

Files: `backend/models/discovery.py`

**Platform DB — WorkflowInstance + TaskInstance + NodeExecutionLog** — 🆕 NEW

workflow_instances (project_id, workflow_id, current_node_ids JSONB, variables JSONB, initiated_by, status enum, started/completed_at), task_instances (workflow_instance_id, node_id, task_type enum, status, assignee_id + assignee_type, input/output_data JSONB, due_at), node_execution_logs (per-node lifecycle: input/output snapshots, error_message, duration_ms), and workflow_assignment_policies (per-node assign_type/assign_target/sla_hours/escalate_to). These back the in-platform workflow engine under backend/runtime/.

Files: `backend/models/workflow_instance.py`, `backend/models/node_execution_log.py`, `backend/models/workflow.py`

**Platform DB — DecisionTable + versions + execution log** — 🆕 NEW

decision_tables (project-scoped named DMN-style tables: definition JSONB, versioned), decision_table_versions (immutable history with created_by), decision_execution_logs (inputs, outputs, matched_rule_ids, hit_policy, duration_ms) — supports the /decisions router and the runtime decision_evaluator.

Files: `backend/models/decision.py`

**Platform DB — RuntimeException** — 🆕 NEW

runtime_exceptions table (alembic a9b7c2e8f4d1): kind enum, message/stack, source_file/line, workflow_id/node_id, page_route, request_url/method/body, user_context JSONB, dedup_key + occurrence_count (first_seen_at/last_seen_at), status enum, heal_attempts, resolved_at + resolution_commit + resolution_summary, smith_conversation_id. Powers the immediate self-heal chip / SelfHealCard and Smith's diagnostic loop.

Files: `backend/models/runtime_exception.py`

**Platform DB — Rules + Access Policies** — 🆕 NEW

project_rules (rule_type, model/field, config JSONB, is_active), app_access_policies (target_type user/role/group + target_id + access_level), field_access_policies (per-model/per-field can_view/can_edit with optional condition text). Feed the generated app's RBAC and validation runtime.

Files: `backend/models/rules.py`

**Platform DB — Notification, Webhook, Environment, Audit, AppTemplate, PageDefinition** — 🆕 NEW

Six additional platform tables landed in the enterprise-readiness batch (alembic d1e2f3a4b5c6): notifications (user_id, type, title, content, link, metadata JSONB, read_at), webhooks (project_id, url, secret, events JSONB, is_active, failure_count, last_triggered_at), environments (per-project named env with config+secrets JSONB, is_active), audit_logs (user_id, action, resource_type/id, changes JSONB, ip_address, user_agent, request_id), app_templates (slug/name/category/tags/plan/complexity/relevant_departments — starter templates browseable in-app), page_definitions (project-scoped name/route/html/css/data_bindings JSONB for the visual page editor).

Files: `backend/models/notification.py`, `backend/models/webhook.py`, `backend/models/environment.py`, `backend/models/audit.py`

**Alembic migration surface** — 🆕 NEW

18 alembic revisions on disk, notably: 2cd38d3a50ff initial_org_and_identity_tables, d12dc29cafa1 add_project_conversation_agent_job, c3d4e5f6a7b8 add_module_system_tables, a7b3c1d2e4f6 add_rules_and_access_tables, b8c4d2e5f7a1 add_workflow_assignment_policies, a1b2c3d4e5f6 add_node_execution_logs, c9d5e3f6a8b2 add_page_definitions_table, a51e0d4dfcf4 add_discovery_sessions_table, b51008900481 add_app_templates_table, 1dbaa6f922f4 add_relevant_departments_to_app_templates, d1e2f3a4b5c6 enterprise_readiness_tables (notifications+webhooks+environments+audit_logs), a9b7c2e8f4d1 add_runtime_exceptions, e24244544c86 + f3a8c2b91d57 add_new_agent_type_enum_values (+ seed_generator agent), f3ffbf62087c merge_divergent_heads.

Files: `backend/alembic/versions`


### 27.5 Updates to §5 Agent System

**Smith conversational build agent** — 🆕 NEW

Smith (backend/agents/smith_agent.py) is the platform's conversational build/fix agent: given a user turn plus a recall dossier and cross-turn memory block, it picks tools from services/smith_tools.py, observes results, and terminates with one of three tools — propose_fix(diagnosis) which streams as a fix_proposal SSE event and stashes pending_fix for the Apply-fix chip flow, answer(text) for explain-only replies, or ask_user(question). Structural utilities (Diagnosis validation, iterator bounding, SDK query loop) are imported from agents/fix_chat_agent.py; the tool palette is broader and the system prompt frames Smith as a build partner. Mutating asks are delegated to agents/tool_app_modifier.py, a Claude-Code-style ReAct sub-agent with a Read/Bash/Edit/Write/RegistryPatch palette that enforces the 7-step Read-Registry → Read-Contract → Find-Files → Impact-Analysis → Modify → Validate → Update-Registry-and-Plan ordering, then runs apply_post_generate_fixes to keep files/registry/contract coherent.

Files: `backend/agents/smith_agent.py`, `backend/services/smith_tools.py`, `backend/agents/tool_app_modifier.py`

**Fix-Assistant loop + symptom diagnoser** — 🆕 NEW

The Fix-Assistant is a closed-palette ReAct loop (agents/fix_chat_agent.py) that never writes — it only calls read-only inspectors from services/fix_agent_tools.py plus two terminals, propose_fix(diagnosis) and ask_user(question). Diagnoses are produced by a two-step pipeline in agents/fix_diagnoser.py: cheap_locate uses a deterministic symptom taxonomy + registry/grep to shortlist real on-disk workflows/schemas, then diagnose invokes an injectable query_fn LLM seam to return a Diagnosis targeting one of three deterministic seams — workflow_node_config, page_schema_patch, or (low-confidence fallback) code_edit. workflow_node_config proposals are re-validated by services.workflow_value_types.analyze_workflow_values before the confidence is finalised; the Diagnosis shape is a hard contract shared with the applier.

Files: `backend/agents/fix_chat_agent.py`, `backend/agents/fix_diagnoser.py`, `backend/services/fix_agent_tools.py`

**App-map (skeleton) planner for large apps** — 🆕 NEW

agents/app_map_agent.py runs the FIRST pass of large-app decomposition: a small bounded LLM call emits a lean skeleton (entity names + field:type summary, pages as route+archetype+entity+one-liner, workflows as id+trigger+target, roles) rather than the full plan. The skeleton is normalised through the same planner._normalize_oneshot_plan so it is directly consumable by services.resource_registry.build_canonical_registry; per-page and per-form detail is authored later in bounded registry-slice contexts. The LLM seam is injectable; on parse failure the caller falls back to the one-shot planner via AppMapError.

Files: `backend/agents/app_map_agent.py`, `backend/agents/planner.py`

**Plan Critic (actor-critic loop)** — 🆕 NEW

agents/plan_critic.py is the Critic half of an actor-critic plan-refinement loop. critique_plan composes a five-discipline prompt via services/plan_critic_prompt.build_critic_prompt, calls the LLM through an injectable seam, and returns a normalised verdict {inferred_domain, scores{entities/relationships/workflows/user_journeys/data_integrity}, verdict:approve|revise|reject, gaps[{severity,lens,dimension,suggestion,evidence,confidence}], future_considerations, kept}. Parsing is defensive — any malformed reply degrades to verdict:approve with a note so a broken critic never blocks a generation.

Files: `backend/agents/plan_critic.py`, `backend/services/plan_critic_prompt.py`

**Page Schema Agent (JSON pages replacing TSX)** — 🆕 NEW

Pages are now authored as JSON Page schemas (validated against @tentoroforge/schema Page Zod) rather than TSX. agents/page_schema_agent.py runs once per plan page: builds the prompt via services/schema_prompt, normalises the response with services/schema_normalizer.normalize_v2_schema, bundles illustrations via services/illustration_bundler, and writes src/schemas/<slug>.json. The agent also registers the local unDraw illustrations MCP server as a stdio subprocess so the LLM can call mcp__illustrations__list_illustrations / get_illustration_svg while composing the schema. agents/feature_slice_schema_agent.py handles the per-entity slice case (list/detail/form defaults, or a custom entity.pages array). The old TSX page_agent is legacy — pages are consumed by the renderer, not compiled to TSX.

Files: `backend/agents/page_schema_agent.py`, `backend/agents/feature_slice_schema_agent.py`

**Shell Layout Agent** — 🆕 NEW

agents/shell_layout_agent.py generates the app's persistent chrome — a single PageV2 shell.json with header, optional sidebar, and optional footer regions annotated with data-shell-region and exactly one PageOutlet node where page content slots in. The LLM picks among top-bar, sidebar, command-bar, split-workspace, and icon-rail flavors informed by plan/nav-flow/brand/domain context, and is instructed against defaulting to a dark-sidebar admin layout — two apps in different domains must produce structurally different shells.

Files: `backend/agents/shell_layout_agent.py`

**Peer patcher one-shot artifact bundle** — 🆕 NEW

agents/peer_patcher.py collapses design → contract → schema → page → ... into a single LLM invocation via Anthropic's tool-use writeArtifacts that returns page schemas map + nav-flow + design tokens in one shot. The bundle is committed via one replaceArtifacts action so undo restores the prior project state exactly; peer_patcher_schemas provides the JSON schema/Pydantic contract and services/artifact_validator gates the result before it lands.

Files: `backend/agents/peer_patcher.py`, `backend/agents/peer_patcher_schemas.py`, `backend/services/artifact_validator.py`

**Figma substack: schema refiner + IR agent + MCP agent** — 🆕 NEW

Figma imports flow through a dedicated substack. figma_mcp_agent calls the local Figma Dev Mode MCP server's get_design_context and extracts JSX for a frame. figma_ir_agent narrows Claude's job to spatial-layout analysis, element classification, text/color extraction, and interaction inference — producing IR metadata that the compiler turns into code deterministically instead of Claude authoring TSX. figma_schema_refiner takes a deterministic fixed-pixel Figma-mapped Page schema and restructures it into a responsive component-library Page schema, preserving content and returning None on any failure so the caller can safely fall back to the deterministic schema.

Files: `backend/agents/figma_schema_refiner.py`, `backend/agents/figma_ir_agent.py`, `backend/agents/figma_mcp_agent.py`, `backend/agents/figma_ui_agent.py`

**Design Researcher — live-web templates** — 🆕 NEW

agents/design_researcher.py is a live-web design agent that, given industry/domain/requirement, researches how real products look and returns N DesignTemplate objects (palette, density, light/dark, sidebar/topbar, rounded/sharp, type) in a capability-bounded schema. Every template is passed through guard_template so it can only express values the design system can actually render; any failure (no API key, web error, bad JSON) degrades to deterministic house presets so generation never blocks. Web page text is treated as untrusted data — never as instructions — and no remote assets are loaded.

Files: `backend/agents/design_researcher.py`

**Fallback chain (model degradation)** — 🆕 NEW

agents/fallback.py implements a resilience wrapper: a MODEL_CHAIN [claude-sonnet-4-6 → claude-haiku-4-5-20251001] with MAX_RETRIES=2 and RETRY_DELAY_SECONDS=2, so any agent that opts into it degrades from Sonnet to Haiku instead of failing outright.

Files: `backend/agents/fallback.py`

**RFC 6902 patch_agent from vision critique** — 🆕 NEW

agents/patch_agent.py is a narrow single-purpose agent that consumes a Page schema plus a vision-evaluator Critique and emits RFC 6902 JSON Patches (capped at _MAX_PATCHES=8) targeting the critique's specific issues — no refactoring, no restructuring, no new features. Model is configurable via PATCH_AGENT_MODEL (default claude-sonnet-4-5-20250929).

Files: `backend/agents/patch_agent.py`, `backend/services/vision_evaluator/types.py`

**Wiring guard — LLM completeness safety net** — 🆕 NEW

agents/wiring_guard.py is an LLM safety net over the deterministic binding pass: it walks Page schemas for actionable Button/IconButton/Form nodes lacking real workflow or navigate wiring and proposes repairs. Repairs are only applied when they reference a workflow or route that actually exists in the registry, and the guard degrades to a no-op without an API key so it can never make things worse.

Files: `backend/agents/wiring_guard.py`

**Orchestrator classification vocabulary expanded** — ⚠️ CORRECTS

The orchestrator's classification set is broader than the original PLAN/REFINE/EXPLAIN: it now classifies into APPROVE, PLAN, REFINE, EXPLAIN, SCAFFOLD, AGENT, DISCOVER, NAVIGATE, UNDO, FIX, AMBIGUOUS, and recognises meta-approvals ("use your best judgment", "skip questions") as APPROVE against a pending plan. It runs on Haiku and streams through sse_helpers.billing_safe_query to surface Anthropic billing errors distinctly.

Files: `backend/agents/orchestrator.py`

**Agent __init__ roster is out of date** — ⚠️ CORRECTS

backend/agents/__init__.py still documents a numbered #0–#12 roster (Orchestrator, Planner, Refiner, Explainer, Code Generator, Code Editor, Scaffolder, Indexer, Validator, Seed Generator, Discovery) but the shipping agent set is roughly 3× that: add Smith, tool_app_modifier, fix_chat_agent, fix_diagnoser, plan_critic, app_map_agent, page_schema_agent, feature_slice_schema_agent, shell_layout_agent, business_logic_agent, rules_agent, domain_agent, contract_agent, component_agent, page_layout_agent, ahtml_conversion_agent, design_agent, design_researcher, design_analyzer, ir_router, ir_edit_agent, ir_qa_agent, figma_mcp_agent, figma_ir_agent, figma_schema_refiner, peer_patcher, patch_agent, wiring_guard, completeness_checker. The blueprint's roster table should be rebuilt from the actual file list rather than the docstring.

Files: `backend/agents/__init__.py`

**Design Agent extracts language from Figma screenshots** — ➕ EXTENDS

agents/design_agent.py runs after the planner and before code generation, producing a design specification (colors, typography, layout flavor, density, patterns, responsive strategy, imagery recommendations) that flows into the IR compiler. When reference*.png files are present in the output dir it switches modes and extracts the visual design language from the screenshots — preserving the Figma identity rather than overriding it with industry defaults — and picks navigation/density from the plan's information architecture instead of defaulting to a dark sidebar.

Files: `backend/agents/design_agent.py`

**Contract Agent produces cross-agent contracts** — 🆕 NEW

agents/contract_agent.py runs early in the pipeline and produces the shared contract files every downstream agent reads: src/contracts/design-system.tsx (ListPageShell/DetailPageShell/FormPageShell/DashboardShell + column renderers), api-client.ts, services.ts, app-model.json, seed-plan.json, plus consumers of the design-spec.json the design agent already wrote. These files are the single source of truth for the relay team — agents downstream import from them rather than re-inventing shells or client shapes.

Files: `backend/agents/contract_agent.py`

**SDK transport swap (sdk_agent_runner)** — 🆕 NEW

The heavy code-writing agents (contract, schema, api, components, qa, auth, business_logic, design) do not use claude_agent_sdk.query directly — they import query from services/sdk_agent_runner.py, which is a reliable Anthropic-SDK transport introduced because the bundled CLI wedges under throttle. Lightweight agents (planner, explainer, refiner, orchestrator, etc.) still use the SDK's query and go through sse_helpers.billing_safe_query for billing-error surfacing.

Files: `backend/agents/contract_agent.py`, `backend/agents/schema_agent.py`, `backend/agents/api_agent.py`, `backend/agents/component_agent.py`

**Smith-as-architect stack (blueprint + session + chat-v2 + move dispatcher + orchestrator)** — 🆕 NEW

Smith is now the single conversational entry point behind FORGE_SMITH_ARCHITECT (default on). Every project carries a persistent .forge/blueprint.json (services/smith_blueprint.py, atomic write + content fingerprint) that captures why every entity/page/workflow/design-decision exists; blueprint_pipeline_hooks.py populates it at discovery/planner/generation time and blueprint_backfill.py backfills pre-blueprint projects. A SmithSession (smith_session.py) is instantiated per turn: it loads/slices the blueprint (smith_blueprint_context.py), runs the chat router (smith_chat_router.py — bootstrap vs iteration vs ask_user), understands the ask, dispatches through smith_move_dispatcher.py's seam table (edit_page / add_page / edit_workflow / add_workflow / add_entity / edit_file / replan), and verifies the outcome against ground truth (services/ground_truth.py — real git diff + guard results, never Smith's self-report). smith_orchestrator.py wraps the loop with actor-critic bounded turns, guard-fail corrective replay, and git-revert on turn exhaustion. smith_chat_v2.py is the pure handler; smith_architect_wire.py is the production wiring that binds real seams (fix_applier, edit_workflow_seam, post_generate_fixes) into the session.

Files: `backend/services/smith_blueprint.py`, `backend/services/smith_session.py`, `backend/services/smith_chat_v2.py`, `backend/services/smith_chat_router.py`

**Smith blueprint memory and cross-turn context (verbatim + rolling + app-map + recall + resource slice + grounding)** — 🆕 NEW

Smith's context on every turn is composed from: smith_memory (verbatim last-N user/assistant pairs + rolling deterministic state from Conversation.metadata_), app_map (deterministic mental-model dict built from resource-registry + action-contract + generation-dossier + page schemas, cached by output_dir/contracts-mtime), app_recall (per-app generation dossier: original prompt + finalized plan + contracts snapshot + recent change history, written by emit_generation_dossier at gen-time), smith_recall_enrich (adds component catalog + data-engine endpoints + workflow node contracts + seam palette), smith_resource_slice (focal entity slice for the touched route), and smith_grounding (deterministic proper-noun → registry lookup prepended before the ReAct loop). narrator_artifacts.py + smith_narrator.py let internal agents produce structured artifacts while Smith speaks in-voice. smith_concurrency.py adds optimistic locking (save_if_unchanged, ConcurrentModificationError) and an EditorMirror so visual-editor writes appear in Smith's change_log with source=editor.

Files: `backend/services/smith_memory.py`, `backend/services/app_map.py`, `backend/services/app_recall.py`, `backend/services/smith_recall_enrich.py`

**Smith's tool palette (edit_file / read_file / verify_promise / find_resources / find_source / plus fix_agent_tools)** — 🆕 NEW

Smith calls a curated tool palette. smith_tools.py catalogs the read-only inspectors reused from services.fix_agent_tools plus a component-contracts reader (packages/registry/dist/component-contracts.json) and terminal tools propose_fix / answer / ask_user. smith_edit_tools.py adds Claude-Code-style read_file / edit_file (exact-string replace, refuses ambiguous/no-op) / verify_promise sandboxed to output_dir. smith_find_resources.py collapses the multi-round-trip resource traversal (entity → pages/workflows/FK dependents) into one call with confidence scoring; smith_find_source.py maps a symptom to the backend emitter module most likely responsible so Smith can escalate to a source fix instead of N per-page edits. llm_edit.py is the smart_edit_page primitive Smith uses for scoped page-schema mutations.

Files: `backend/services/smith_tools.py`, `backend/services/smith_edit_tools.py`, `backend/services/smith_find_resources.py`, `backend/services/smith_find_source.py`

**Atomic multi-file apply primitive + composite add_page/add_workflow/add_entity seams** — 🆕 NEW

services/atomic_apply.py provides apply_bundle: stages every BundleOp in memory, snapshots pre-image bytes (including absence), writes all files, runs a caller-supplied verify callback, and either single-commits or restores every path (deleting newly-created files) on failure — with git-stash preservation of any pre-existing dirty tree. Smith's new-thing seams build on it: add_page_seam.py synthesizes a planner-shaped page dict and delegates to deterministic_pages.build_crud_page (deterministic archetypes list/form/create/edit/detail/kanban/calendar; LLM path deferred); add_workflow_seam.py delegates to crud_workflow_generator.build_crud_workflow (create/update/delete); add_entity_seam.py appends to resource-registry.json + emits src/db/schema/<slug>.ts via schema_builder helpers + updates the schema barrel. Sibling remove_page_seam.py and edit_workflow_seam.py round out Smith's tool surface.

Files: `backend/services/atomic_apply.py`, `backend/services/add_page_seam.py`, `backend/services/add_workflow_seam.py`, `backend/services/add_entity_seam.py`

**Conversational fix-assistant tools + probe + A/B logging** — 🆕 NEW

The fix-assistant is a bounded ReAct loop with three seams: workflow_node_config (shallow-merge into data.config via routers.workflows.merge_node_config), page_schema_patch (RFC-6902 through services/patch_applier), and code_edit (deferred). fix_applier is transactional (pre-image restored on error), heals the whole app after apply, and re-verifies. fix_agent_tools exposes read-only inspectors (registry, schemas, workflows, action-contract) sandboxed to output_dir. fix_probe is the read-only, localhost-only, byte/line-capped runtime evidence seam. patch_coherence checks Smith's natural-language explanation against his RFC-6902 patch so the drift where he says 'remove password' while patching a Switch is caught. fix_ab_log records propose/reemit/clarify/error/applied phases so the agentic vs single-shot mode can be compared without touching SSE or the frontend.

Files: `backend/services/fix_applier.py`, `backend/services/fix_agent_tools.py`, `backend/services/fix_probe.py`, `backend/services/fix_ab_log.py`

**Plan authoring pipeline (validator + critic + input rendering + completeness + transformer)** — ➕ EXTENDS

The planner runs behind an actor-critic loop: plan_critic_prompt.py drafts a universal senior-BA + architect adversarial review (bounded to 3 blockers / 5 important / 3 nice, each with a plan reference); plan_validator.py enforces the deterministic cross-cutting rules downstream can't recover from (FK targets resolve, actor FK relations exist, page.entity exists, etc.); plan_completeness_validator.py + a REVISE loop guard against a planner producing a plan the downstream pipeline can't consume. planner_input_render.py renders the discovery StructuredBrief (services/structured_brief.py, produced by discovery_transformer.py) as the AUTHORITATIVE INPUTS block the planner sees. plan_field_lookup helps downstream guards read plan fields (semantic_type / fk target / enum_values / trigger_inputs / sidebar) so plan-declared truth wins over heuristic guessing. plan_wire_pipeline.py orchestrates the wire passes that turn plan declarations (field_visibility, actor onboarding, workflow triggers, etc.) into per-artifact metadata.

Files: `backend/services/plan_validator.py`, `backend/services/plan_critic_prompt.py`, `backend/services/plan_completeness_validator.py`, `backend/services/planner_input_render.py`

**Ground-truth verification for Smith turns** — 🆕 NEW

services/ground_truth.py is the invariant that Smith's self-report is never trusted. Every function reads real disk / real subprocess output and returns plain data — no model, no state, no writes. Public surface: git_status_modified (every modified/added/untracked path relative to the repo root), plus helpers for git diff and guard summarization. SmithSession credits Smith with what the working-tree actually shows, and OrchestratorResult.answer is synthesized from the diff (Smith's own answer text becomes advisory). This structurally kills the 'believes he did it' class where Smith would claim one edit path and edit another.

Files: `backend/services/ground_truth.py`


### 27.6 Updates to §6 Backend API

**Generation-session buffering + SSE reconnect** — 🆕 NEW

Long generations survive tab reload via a per-session event buffer. buffered_event_stream() in backend/routers/generate.py creates a GenerationSession, drains the source generator into an in-memory buffer while yielding a `session` event with session_id, then tails the buffer with 10s heartbeats and injects an ordered `_idx` into every event. GET /api/projects/{id}/generation/active reports whether a session is running; GET /api/projects/{id}/generation/{session_id}/events?since=N replays via reconnect_event_stream. Contract: the client tracks the highest _idx it has processed and resumes from there — nothing is lost across a reconnect.

Files: `backend/routers/generate.py`, `backend/services/generation_buffer.py`

**App actions — seed and validate→repair loop** — 🆕 NEW

backend/routers/app_actions.py exposes two SSE-streamed chat actions. POST /api/projects/{id}/app/seed runs `bash start.sh --seed-only` in a thread, detects `SEEDED_OK`, and returns admin credentials via services.post_gen_actions.admin_credentials. POST /api/projects/{id}/app/validate boots the app and runs services.validate_repair_loop.run_validate_repair (click-through crawl → auto-fix → re-validate), reporting rounds + remaining. Both surface post-seed action chips.

Files: `backend/routers/app_actions.py`, `backend/services/validate_repair_loop.py`, `backend/services/post_gen_actions.py`

**SSE convention across routers** — ➕ EXTENDS

All long-running router endpoints follow the same SSE convention: sse_helpers.sse_event(type, data) emits `{event, data:json}` frames; stream_agent_messages() wraps a Claude Agent SDK query and rolls up an `agent_result` with num_turns/cost_usd/duration_ms plus `message`/`log` frames. Endpoints wrap streams in sse_starlette.EventSourceResponse with ping=15. Generation additionally passes through buffered_event_stream (session + _idx). Any new SSE endpoint MUST use this pair — the frontend event handler is written against it.

Files: `backend/sse_helpers.py`, `backend/routers/generate.py`, `backend/routers/workflows.py`, `backend/routers/navigation.py`

**FK-label expansion in list queries** — 🆕 NEW

`attachFkLabels` in `backend/templates/runtime/data-engine.ts` batch-resolves every FK id in a `query()` result to a human label read from `src/lib/fk-labels.json` (emitted at generation time from the registry with `{targetEntity, labelField}` per FK column). It attaches the label as a companion `<fkProp>Label` field on each row so tables can render `memberName` instead of a raw UUID while the real id stays available for row actions. The map is keyed with several aliases per entity (lowercase, slug, plural); a shape-match fallback catches friendly-name routes the aliases missed. Absent metadata → no expansion, never an error.

Files: `backend/templates/runtime/data-engine.ts`

**Cursor pagination + aggregation route stubs** — 🆕 NEW

`handleListPaginated` in `backend/templates/runtime/data-engine.ts` implements base64-cursor pagination (default 50, max 200, `hasMore` via +1 fetch), and `handleAggregate` delegates to `executeAggregation` in `data-engine/aggregations.ts` for the `POST /api/data/{table}/aggregate` route (count/sum/avg/min/max with optional `groupBy`+`filter`). A `saved-views.ts` module co-lives for persistent filter/sort presets.

Files: `backend/templates/runtime/data-engine.ts`, `backend/templates/runtime/data-engine/aggregations.ts`, `backend/templates/runtime/data-engine/saved-views.ts`


### 27.7 Updates to §7 Frontend Pages & Components

**Navigator seam (soft nav for routed modals)** — 🆕 NEW

`NavigatorContext` (packages/renderer/src/client/Navigator.tsx) is the single navigation seam for schema Button `navigate`, Table `rowHref`, Link, and the post-workflow redirect. Default is `window.location.assign`/`.replace`/`.back`/`.reload` so nothing regresses when unprovided; a host app in the generated shell supplies a Next.js `useRouter()`-backed Navigator so parallel/intercepting `@modal` routes fire instead of a full page load. `useNavigator()` returns the host value or the default. Engine uses this Navigator for both delegated nav-trigger clicks and the post-submit redirect, so soft-navigation is uniform.

Files: `packages/renderer/src/client/Navigator.tsx`, `packages/engine/src/Engine.tsx`

**DialogStateContext + ShellStateContext (delegated open/close)** — 🆕 NEW

Two engine-level state contexts live in the renderer to avoid a library→engine cycle. `DialogStateProvider` owns a `{id: open}` map; the Engine's delegated click handler translates `[data-dialog-open]` attributes into `openDialog(id)`, and the library's Dialog component reads via `useDialogState()`. `ShellStateProvider` owns mobile sidebar state; its delegated handler responds to `[data-sidebar-toggle]`, `[data-sidebar-backdrop]`, and links inside `[data-shell-sidebar]`, auto-closing on Escape and on a resize past 768px. Both are mounted unconditionally by `Engine`.

Files: `packages/renderer/src/client/DialogState.tsx`, `packages/renderer/src/client/ShellState.tsx`, `packages/engine/src/Engine.tsx`

**Form Interaction engine (computed fields + topo order + whitelisted fn library)** — 🆕 NEW

`packages/renderer/src/runtime/formInteraction.ts` owns the FieldInteraction contract (`computed`, `optionsFrom`, `dependsOn`, `onChange.fetch/set`) and a pure `evaluateComputed(formula, values)` that resolves innermost-first whitelisted-function calls to synthetic scope symbols and hands the residual to FEEL-lite — no eval, no new language. `INTERACTION_FUNCTIONS` covers daysBetween, hoursBetween, sum/min/max, round/abs/ceil/floor, ifElse — every function total (missing → 0). `computedEvalOrder(fields)` topologically sorts computed fields, breaking cycles deterministically. Exported at the renderer package root so the library's reactive Form controller, the generator, and the editor all import the same evaluator.

Files: `packages/renderer/src/runtime/formInteraction.ts`, `packages/renderer/src/index.ts`

**Responsive prop resolution** — 🆕 NEW

`useViewport` reports one of `default | sm | md | lg | xl` (packages/engine/src/responsive/useViewport.ts). Before rendering, Engine walks the tree via `resolveTreeBreakpoint`, and any prop shaped like `{default, sm, md, lg, xl}` collapses to the value for the active breakpoint (with xl→lg→md→sm→default fallback). Plain literals pass through unchanged, so components consume the resolved concrete value. The active breakpoint is also published via `ViewportContext` for descendants that need it directly.

Files: `packages/engine/src/responsive/useViewport.ts`, `packages/engine/src/Engine.tsx`

**Nav-flow guards + auth-route bypass** — ➕ EXTENDS

`NavFlow` (packages/schema/src/nav-flow.ts) now carries `auth_routes`, `post_login_redirect`, `post_logout_redirect`, and per-page `shell: boolean` (false = bare auth-style pages). `useNavigate` (packages/engine/src/nav/useNavigate.ts) resolves a trigger to a page, evaluates the page's `guard.condition` via FEEL-lite, and redirects to `guard.redirectTo` when it fails; params substitute into `[k]` placeholders in the target route. Engine's delegated click handler consumes `data-nav-trigger`/`data-nav-params` attributes and calls `nav.push(result.url)`.

Files: `packages/schema/src/nav-flow.ts`, `packages/engine/src/nav/useNavigate.ts`

**Chat SSE dispatcher & event vocabulary** — ⚠️ CORRECTS

The chat store (`frontend/src/stores/chat.ts`, ~1,250 lines) is the SSE control plane for a generation run: `useChatStore.handleSSEEvent` handles ~40 event kinds — `status`, `log`, `tool_call`, `file_created`, `resource`, `intent`, `message`, `plan_ready`, `discovery_started/complete/approval_needed/approved`, `planner_thought`, `smith_thought`, `critic_*`, `narrative_expansion_*`, `planner_call_*`, `planner_decompose_*`, `unit_authored`, `smith_narration`, `fix_proposal`, `fix_applied`, `agent_result`, `office`, `page_iter_done`, `page_skipped`, `phase_start/complete/warning`, `navigate`, `undo_complete`, `error`, `smith_needs_user`, `smith_error`, `answer`, `question`, `handoff`, `apply_start/end`, `complete`, `refine_complete`. State is split into `messages`, `streaming` (logs / toolCalls / filesCreated / smithThoughts / plannerThoughts / resources), `quest`, `designTemplates`, and completion stats — the blueprint should replace the older 'ChatMessage list + logs' description with this fuller event map.

Files: `frontend/src/stores/chat.ts`

**QuestState + fidelity/phase progress chips** — 🆕 NEW

Generation shows a gamified 'Quest' with 9 phases (contracts → foundation → backend → components → pages → seed → qa → validate → index) plus a Figma-only 'Channel the Design' phase, defined in `frontend/src/lib/quest-phases.ts` with XP totals (MAX_XP). `QuestState` in the chat store tracks `activePhaseIndex`, `completedPhaseIndices`, `totalXp`, `phaseStartTimes` and `streamStartedAt`. `frontend/src/lib/generation-progress.ts` (`computeGenerationProgress`) turns these plus empirical per-phase baselines (planning=60s … index=15s, total ≈455s) into a circular progress ring with an ETA — pure, tested. `page_iter_done` / `page_skipped` / fidelity `phase_complete` events also stream inline into chat as fidelity-loop feedback.

Files: `frontend/src/stores/chat.ts`, `frontend/src/lib/quest-phases.ts`, `frontend/src/lib/generation-progress.ts`

**Portal store (My-Apps + command palette + onboarding)** — 🆕 NEW

`frontend/src/stores/portal.ts` (`usePortalStore`) backs the end-user portal: `apps`, `tasks`, `activity`, `stats`, `suggestions`, plus search/filters (`taskFilter`, `activityFilter`), a `commandPaletteOpen` + `commandItems` state, and a persistent onboarding state (`currentStep: OnboardingStep`, `completedSteps`, `dismissed`) with `setOnboardingStep` / `completeOnboardingStep` / `dismissOnboarding`. Separate from the builder-side stores.

Files: `frontend/src/stores/portal.ts`

**Voice input/output for chat** — 🆕 NEW

`frontend/src/lib/voice.ts` provides `useSpeechRecognition` (Web Speech API, `continuous:false` so a natural pause ends the utterance and auto-sends) and TTS helpers for spoken replies plus a markdown-flattener for speakable prose. Browser-native — no external service or API keys — Chrome-targeted. Powers the mic button and read-aloud affordances on the chat surface.

Files: `frontend/src/lib/voice.ts`

**Project workspace tab shell (18 tabs)** — ⚠️ CORRECTS

The project workspace is a single client page at app/org/[orgId]/projects/[projectId]/page.tsx that mounts ~18 tabbed panels behind a left icon rail: chat, preview, code, data, rules, decisions, workflows, editor (visual), design (VisualEditorWorkspace), design-editor (GrapesJS), ir-editor, navigation, agents, ai, monitoring, versions, office (virtual office). Tab identity is a single Tab union in the file; keyboard shortcuts and CommandPalette route between them. There is no per-tab route — deep-linking is limited to /editor/[projectId] and /editor/[projectId]/[...slug] which mount the visual editor standalone.

Files: `frontend/src/app/org/[orgId]/projects/[projectId]/page.tsx`

**Chat card taxonomy (Plan, Discovery, FixProposal, FixResult, NeedsUser, SelfHeal, PlanCard journeys)** — 🆕 NEW

ChatMessage dispatches to typed cards based on message_type + metadata rather than rendering markdown: PlanCard (planner output incl. journeys section), DiscoveryCard (dossier from run_domain_discovery with inline edit of domain/complianceNotes before [APPROVE_DISCOVERY]), FixProposalCard/FixResultCard (conversational fix-assistant apply flow), NeedsUserCard (Smith's status='needs_user' TurnResult with clickable options that post back verbatim), SelfHealCard (SH-1 four-state upsert: in_progress/resolved/failed/asked). ActionButtons appends contextual chips (approve, undo, validate-repair, seed-data) computed from the last message.

Files: `frontend/src/components/chat/ChatMessage.tsx`, `frontend/src/components/chat/PlanCard.tsx`, `frontend/src/components/chat/DiscoveryCard.tsx`, `frontend/src/components/chat/FixProposalCard.tsx`

**Slash commands + voice I/O in chat composer** — 🆕 NEW

ChatInput has a SlashCommandPalette (typed / triggers filter suggestions like /add-page, /add-entity, /add-workflow, /fix, /undo) that expands to a templated user message with a caret marker (⎽). Voice input via useSpeechRecognition and voice output (spoken reply) via useSpeechSynthesis + stripForSpeech; toggle button hidden when unsupported. Screenshot attach is also wired.

Files: `frontend/src/components/chat/ChatInput.tsx`, `frontend/src/components/chat/SlashCommands.tsx`, `frontend/src/lib/voice.ts`

**GenerationRing + phase-based progress** — 🆕 NEW

GenerationRing is a circular SVG progress ring shown in SSEStatusBar during streaming. It reads chat store fields quest.streamStartedAt, activePhaseIndex, completedPhaseIndices, phaseStartTimes and calls computeGenerationProgress every ~500ms to display a live % + ETA (indeterminate arc when signal is insufficient). Replaces the previous plain Loader2 spinner.

Files: `frontend/src/components/chat/GenerationRing.tsx`, `frontend/src/lib/generation-progress.ts`, `frontend/src/components/chat/ChatHistory.tsx`

**SSE reconnect + persistent project event stream** — 🆕 NEW

ChatPanel opens a persistent EventSource on /api/projects/{id}/events (self_heal_message payloads upserted into the chat store; server pings ~25s keep it alive) and, on mount, polls /api/projects/{id}/generation/active to auto-reconnect to any in-progress generation via /generation/{sessionId}/events?since=0. It also fires a fire-and-forget POST /api/projects/{id}/smith/warmup to preload the app-map cache before the first turn.

Files: `frontend/src/components/chat/ChatPanel.tsx`, `frontend/src/hooks/useSSE.ts`

**Smith bracketed control messages + [VALIDATE_REPAIR]/[SEED_DATA] chips** — 🆕 NEW

Post-build action chips ([VALIDATE_REPAIR], [SEED_DATA]) are not chat turns — ChatPanel.handleSend detects them and streams from /api/projects/{id}/app/validate or /api/projects/{id}/app/seed. Bracketed control signals matching /^\[[A-Z_]+(:[^\]]*)?\]$/ (like [APPROVE_PLAN], [APPROVE_DISCOVERY], [SELECT_TEMPLATE:id]) are sent through /chat but not rendered as user bubbles. All other messages go through the single /chat front door so Smith owns lifecycle including bootstrap (discovery→plan→gen).

Files: `frontend/src/components/chat/ChatPanel.tsx`, `frontend/src/components/chat/ActionButtons.tsx`

**Onboarding + CommandPalette + keyboard shortcuts** — 🆕 NEW

First-run UX: OnboardingWizardDialog + OnboardingTutorial walk new users through creating their first project. Across the workspace, CommandPalette (Cmd+K) exposes CommandItem entries for tab switching, project actions, and Smith commands; useKeyboardShortcuts + useKeymap register per-view bindings (editor keymap wires save, undo, delete, escape, zoom).

Files: `frontend/src/components/onboarding/OnboardingTutorial.tsx`, `frontend/src/components/onboarding/OnboardingWizardDialog.tsx`, `frontend/src/components/CommandPalette.tsx`, `frontend/src/hooks/useKeyboardShortcuts.ts`


### 27.8 Updates to §8 Visual Editors

**IR router + IR edit agent + IR QA** — 🆕 NEW

For projects that have an IR, ir_router.py intercepts edit requests: UI-touching instructions (matched against a keyword vocabulary) are routed to agents/ir_edit_agent.py which emits structured IR operations (setProp, addChild, removeChild, …) applied deterministically instead of LLM-rewriting TSX. agents/ir_qa_agent.py replaces the build-and-fix loop with a structured pipeline — validate IR schema, compile IR via services.ir_compiler, then classify and structurally fix errors, only escalating to an LLM for Custom-node repairs.

Files: `backend/agents/ir_router.py`, `backend/agents/ir_edit_agent.py`, `backend/agents/ir_qa_agent.py`, `backend/services/ir_compiler.py`

**Editor output-directory API (schema-list, load, save, theme, CSS, illustrations)** — 🆕 NEW

backend/routers/output_projects.py (prefix /api/projects) is the canonical editor surface for generated apps on disk. _resolve_root maps a DB UUID → short_id → output/<short_id> (or an absolute output_dir). Endpoints: GET /{id}/pages (schema paths), /{id}/schema-list (flat routes with derived page_type/entity), /{id}/load?path, POST /{id}/save (atomic tmp-rename), GET/POST /{id}/theme (tokens.custom.json), GET /{id}/css (raw globals.css), GET /{id}/illustrations/{slug}.svg. This is the API the visual editor calls; it coexists with the DB-backed /api/projects/{uuid} routes and is disambiguated by UUID validation.

Files: `backend/routers/output_projects.py`, `backend/services/project_paths.py`, `backend/services/route_slug.py`

**Editor↔Smith mirror + app-map warmup** — 🆕 NEW

POST /api/projects/{id}/editor/mirror records every editor save into the Blueprint change_log (services.smith_concurrency.EditorMirror.record_edit) so Smith's next turn sees the delta — best-effort, always returns 200 (mirrored=true/false) to never block the editor. POST /api/projects/{id}/smith/warmup pre-builds the app-map cache (services.app_map.get_app_map) when the chat panel mounts, returning intent + entity/page/workflow counts so Smith's first mutation ask has zero cold-start cost.

Files: `backend/routers/output_projects.py`, `backend/services/smith_concurrency.py`, `backend/services/app_map.py`

**Editor save endpoint — Zod + cross-ref validate + atomic write + FastAPI followup** — ✓ CONFIRMS

POST /api/editor/save runs the incoming schema through Zod (Page), then validateCrossRefs against a ValidationContext built from registry.json (entities+workflows), libraryRegistry.list(), and the merged theme tokens; entity/workflow errors are downgraded when the manifest is missing. Successful saves atomic-write (.tmp + rename) into src/schemas/{path}.json and fire a best-effort FASTAPI_URL /agents/schema-followup call whose suggestions/autoApplied are returned to the editor. `_layouts/<name>` paths write to the workspace-linked @tentoroforge/library layouts directory instead of the app schemas tree.

Files: `backend/templates/app-foundation/src/app/(dev-only)/api/editor/save/route.ts`

**Editor mount + suggest/load/pages/theme APIs** — ➕ EXTENDS

/editor/[...slug] is a thin server wrapper that resolves the slug and defers to <EditorMount>, a client component that imports the library registry and theme tokens on its side of the RSC boundary (function-valued registry entries can't cross RSC). It talks to /api/editor/{load,save,pages,suggest,theme} — the LLM `suggest` endpoint proxies FASTAPI_URL just like save's followup — and its bundle is prod-tree-shaken by the (dev-only) null-loader rule.

Files: `backend/templates/app-foundation/src/app/(dev-only)/editor/[...slug]/page.tsx`, `backend/templates/app-foundation/src/lib/editor-mount.tsx`

**IR editor store (undo/redo tree ops)** — 🆕 NEW

`frontend/src/stores/ir-editor.ts` (`useIREditorStore`) is the visual-editor store operating on the IR tree — `AppIR`/`PageIR`/`IRNode` with `NodePath = number[]`. `applyOps(ops)` runs an in-place clone-and-apply for eight `IROperation` types (`setProp`, `addChild`, `removeChild`, `moveChild`, `wrapWith`, `unwrap`, `duplicate`, `replace`) and pushes typed inverses onto `undoStack`; `undo`/`redo` roundtrip inverses to keep operations reversible. Also owns editor UI state (selectedPath/hoveredPath, devicePreview, left/right panel widths, showCode, isDirty). Kept separate from the `@forge/patches`-based editor-store (which drives the schema-page editor).

Files: `frontend/src/stores/ir-editor.ts`

**editor-store (@forge/patches) + persistence auto-save** — ⚠️ CORRECTS

The schema-page editor stack is `frontend/src/lib/editor-store.ts` (`useEditorStore`) + `frontend/src/lib/persistence.ts`. Store dispatches actions through `@forge/patches`' `applyAction`, records typed inverses on the undo stack, and validates every commit via `validateForCommit(next, starterRegistry)` — commits that would break rendering (duplicate ids, unknown component types) are rejected into `lastError`. Multi-selection is first-class (`selectedNodeIds` + toggle/extend/clear). `attachPersister(projectId)` subscribes and writes on `isDirty`; `buildPersister` debounces 500 ms, serializes concurrent saves, POSTs each page schema individually to `/api/_debug/project-file/{shortId}/{path}` at the path declared in `nav-flow.pages[].schemaFile` (falling back to `src/schemas/<id>.json`) and mirrors `src/contracts/nav-flow.json` + `src/contracts/tokens.json`. `flushPersister()` awaits any in-flight save.

Files: `frontend/src/lib/editor-store.ts`, `frontend/src/lib/persistence.ts`

**Design editor store (AHTML/GrapeJS)** — 🆕 NEW

`frontend/src/stores/design-editor.ts` (`useDesignEditorStore`) is a separate store for the GrapeJS-based Annotated-HTML editor (the AHTML system). Owns `projectId`, an array of `{pageId, route, title, html, css}` pages, `EditorStatus` (`idle|loading|saving|compiling|error`), device preview, `isDirty`, `lastCompileResult` (`{files, errors, warnings}`), and `themeCSS` (the project's `globals.css` variables injected into the canvas iframe so the editor renders with the app's actual tokens). Coexists with the IR editor (`ir-editor.ts`) and the schema-page editor (`lib/editor-store.ts`).

Files: `frontend/src/stores/design-editor.ts`

**Visual-editor store (canvas selection + quick-style)** — ✓ CONFIRMS

`frontend/src/stores/visual-editor.ts` (`useVisualEditorStore`) is a light coordination store for the live-preview visual editor: `currentRoute`, `selectedElement` / `hoveredElement` (`ElementInfo`), `devicePreview`, `isEditing` + `editProgress`, an ActionPopover position + `quickStyleTarget` ('bg'|'text'|'spacing'|'font'|'border'), left/right panel open state, and a `sectionTree` + `selectedSectionId` derived by `frontend/src/lib/section-tree-utils.ts`. It's separate from ir-editor.ts (which mutates IR) — this store only tracks canvas UI, mutations go through the instruction-builder pipeline.

Files: `frontend/src/stores/visual-editor.ts`, `frontend/src/lib/section-tree-utils.ts`

**Standalone editor deep-link route** — 🆕 NEW

Two Next.js routes host the visual editor outside the project workspace shell: /editor/[projectId] mounts VisualEditorWorkspace at the initial page (default from nav-flow.initialPage), and /editor/[projectId]/[...slug] mounts EditorMount with a specific schema path (e.g. /editor/foo/products/list). This is the URL used for pop-out editing and deep-linking from other panels.

Files: `frontend/src/app/editor/[projectId]/page.tsx`, `frontend/src/app/editor/[projectId]/[...slug]/page.tsx`, `frontend/src/components/schema-editor/EditorMount.tsx`

**UnifiedEditor two-mode shell** — 🆕 NEW

UnifiedEditor wraps two editing paradigms in a single canvas with a ModeBar: Live (edit the running Next.js iframe via VisualEditor — style tweaks, text, AI edits) and Build (GrapesJS DesignEditor for structure/drag-drop). Both mount lazily and stay alive via display:none so switching modes preserves state. useAutoFix runs alongside for inline error remediation.

Files: `frontend/src/components/unified-editor/UnifiedEditor.tsx`

**VisualEditorWorkspace canvas + panels** — 🆕 NEW

VisualEditorWorkspace is the shared editor implementation used by both the standalone /editor route and the workspace 'editor' tab. It composes EditorToolbar, PageTabs, Palette, Canvas (with DropIndicator/ReorderIndicator/SelectionOverlay/ZoomControls), and RightPanel (PropertiesPanel + StylePanel + BindingsPanel + BreakpointSwitcher). Editor state is a zustand store (editor-store) with attachPersister/flushPersister — every edit debounce-writes to disk; Save flushes and clears the dirty flag. Initial page is chosen from nav-flow.initialPage (cached under queryKey ['nav-flow', projectId]).

Files: `frontend/src/components/visual-editor/VisualEditorWorkspace.tsx`, `frontend/src/components/canvas/Canvas.tsx`, `frontend/src/components/palette/Palette.tsx`, `frontend/src/components/properties/RightPanel.tsx`

**IR editor (component tree, binding + workflow binding panels, IR renderer)** — ➕ EXTENDS

The 'ir-editor' tab still exists alongside the newer AHTML/visual editor: IREditor composes IRCanvas + ComponentTree + ComponentPalette + PropertiesPanel + dedicated DataBindingPanel and WorkflowBindingPanel. /ir-demo is a demo route for the IR pipeline. Per MEMORY.md, AHTML is intended to replace this — worth flagging in the blueprint that both surfaces currently ship.

Files: `frontend/src/components/ir-editor/IREditor.tsx`, `frontend/src/components/ir-editor/IRCanvas.tsx`, `frontend/src/components/ir-editor/ComponentTree.tsx`, `frontend/src/components/ir-editor/ComponentPalette.tsx`


### 27.9 Updates to §9 Generated App Structure

**AHTML → TSX conversion agent** — 🆕 NEW

agents/ahtml_conversion_agent.py converts Annotated HTML pages (data-source / data-source-method / data-source-path / data-bind / data-action / data-if attributes) into valid Next.js "use client" TSX components. It receives page metadata, data sources, state bindings and actions alongside the raw AHTML body; this is the seam that lets AHTML replace JSON IR as the visual-editing source of truth for projects that opt into it.

Files: `backend/agents/ahtml_conversion_agent.py`

**Runtime error reporter (self-heal seam)** — 🆕 NEW

Every generated app ships `src/lib/error_reporter.ts`, which posts caught exceptions to Forge's `/api/projects/{id}/runtime-exceptions` so Smith's self-heal loop can pick them up. `reportRuntimeException`/`reportFromError` are called from every workflow db_* catch site with `__nodeId` + `__workflowId` locators injected by the engine (`handleAction`), and a `bootstrapBrowserReporter()` auto-runs on module load to install `window.error` / `unhandledrejection` handlers (filtering out resource-load errors). Client-side fingerprint dedup within a 5-second window avoids hammering Forge while the backend does authoritative dedup. Configured via `FORGE_URL` + `FORGE_PROJECT_ID` env vars seeded into `.env.local`; missing config → silent no-op.

Files: `backend/templates/runtime/error_reporter.ts`, `backend/templates/runtime/workflows/index.ts`

**renderSchemaPage — server dataSource resolution + client Engine bridge** — 🆕 NEW

Every generated page is rendered by renderSchemaPage in src/lib/schema-page.tsx. It loads the validated Page JSON via getSchema, resolves each dataSource server-side through dataEngine.run / resolveAggregate / resolveSeries (backed by data-engine-bridge.ts, which wraps the CRUD data-engine and translates op:list/get/aggregate/series into query/findById/etc.), and passes the resolved map as `previewData` to the client `Engine` inside a `WorkflowDispatchProvider`. Detail-shaped ops (get/detail/find/one) unwrap the single-row array so `{{project.name}}` binds render. previewData is only passed when at least one source resolved — an empty object would flip the Engine into preview mode and no-op form submits. This replaces the aspirational per-entity hand-rolled pages the blueprint sketches.

Files: `backend/templates/app-foundation/src/lib/schema-page.tsx`, `backend/templates/app-foundation/src/lib/data-engine-bridge.ts`

**AppNavigator — routed overlay for /new, /[id], /[id]/edit** — 🆕 NEW

Wraps the dashboard tree with a NavigatorProvider that intercepts schema-driven navigations (Button.navigate, Table rowHref, Link, post-submit redirects). URLs matching `/{entity}/new`, `/{entity}/[id]/edit`, or `/{entity}/[id]` are opened as a Dialog (forms) or Drawer (detail) via RouteModal, with `history.pushState` so they are deep-linkable and Back closes them; anything else does a normal router.push. Overlay schemas get client-fetchable `source` URLs injected onto their dataSources (/api/data/{name}[/{id}]) so the Engine can populate them without SSR. The doc explicitly forbids Next.js parallel/intercepting routes here because the (dashboard) group + [entity] dynamic segment breaks resolution.

Files: `backend/templates/app-foundation/src/components/AppNavigator.tsx`, `backend/templates/app-foundation/src/components/RouteModal.tsx`, `backend/templates/app-foundation/src/app/(dashboard)/layout.tsx`

**Dynamic-segment aware catch-all router** — ➕ EXTENDS

The standalone-app catch-all does more than a literal file match: given /a/b/c it tries a/b/c.json, then a/b/[id].json, then a/[id]/c.json, then [id].json, and threads the id through as `?id=…` on an internal Request so data-engine-bridge picks it up for findById. This is what makes URLs like /drives/{uuid} resolve to the `/drives/[id]` schema and hydrate the record — dropping this fallback returns blank {{binding}} pages.

Files: `backend/templates/standalone-app/src/app/[...slug]/page.tsx`

**WizardShell — multi-step form driver** — 🆕 NEW

Pages whose JSON carries a `page.wizard = { steps: [{title, field_names}] }` block (emitted by backend/services/wizard_wire.py) are routed to WizardShell instead of the plain Engine. It filters fields by matching `wizard_step`, suppresses submit on non-last steps, and only exposes `page.actions` on the final step; each step remounts the Engine to reset validation state. Runtime pair for the wizard wire-pass primitive.

Files: `backend/templates/app-foundation/src/lib/WizardShell.tsx`

**(dashboard) layout with generated SideNav + fallback nav-flow menu** — 🆕 NEW

Authenticated dashboard layout renders the @tentoroforge/library SideNav under a ShellStateProvider (rail collapses/expands on hover, mobile off-canvas via hamburger). Nav props are loaded from src/schemas/shell.json (a schema tree whose SideNav node carries groups/palette/frame authored by the shell generator); if shell.json is absent it falls back to a flat menu built from src/contracts/nav-flow.json (top-level shell:true pages only, dedup, keyword-driven ICON_MAP for lucide icons). Wraps children in AppNavigator so navigation stays soft/overlay-aware.

Files: `backend/templates/app-foundation/src/app/(dashboard)/layout.tsx`

**Client Providers — SessionProvider + React Query + Sonner + error_reporter** — 🆕 NEW

The single client Providers component composes NextAuth SessionProvider, a per-app QueryClient (staleTime 60s, retry 1), the sonner Toaster (used by the workflow dispatcher), and side-effect imports @/lib/error_reporter which installs window.onerror + unhandledrejection handlers that POST to Forge's self-healing endpoint. Self-heal is opt-out only by removing the import.

Files: `backend/templates/app-foundation/src/app/providers.tsx`

**Theme tokens — client re-export vs server-only custom merge** — 🆕 NEW

Theme split into two entry points to keep `fs` out of client bundles: `theme/tokens.ts` is a plain re-export of defaultTokens from @tentoroforge/library (client-safe), while `theme/tokens.server.ts` (marked "server-only") merges defaultTokens with src/theme/tokens.custom.json via loadCustomTokens. Client code that needs the merged theme reads it via GET /api/editor/theme rather than importing the server module.

Files: `backend/templates/app-foundation/src/theme/tokens.ts`, `backend/templates/app-foundation/src/theme/tokens.server.ts`, `backend/templates/app-foundation/src/theme/load-custom.ts`

**useEntity* hooks — hand-rolled CRUD hooks alongside the schema Engine** — 🆕 NEW

The template ships React-Query hooks (useEntityList/Detail/Form + useLogin) that hit /api/data/{entity}[/{id}] plus a /stats sibling. Used by seed products/* pages and available to any hand-written page that opts out of the schema Engine path; they are not on the primary render seam (renderSchemaPage/AppNavigator do their own fetching) but remain the fallback for non-schema screens.

Files: `backend/templates/app-foundation/src/hooks/useEntityList.ts`, `backend/templates/app-foundation/src/hooks/useEntityForm.ts`, `backend/templates/app-foundation/src/hooks/useEntityDetail.ts`, `backend/templates/app-foundation/src/hooks/useLogin.ts`

**Deterministic CRUD builders and route synthesis** — ⚠️ CORRECTS

The routine 80% of CRUD pages/routes is deterministic and never LLM-authored. deterministic_pages.build_crud_page emits list/form/create/edit/detail schemas (schemaVersion "2") from real entity columns + design spec, using the live component contracts so validateProps never strips props. crud_route_generator ensures /api/<slug>/{route.ts,[id]/route.ts,stats/route.ts} exists non-destructively even when the LLM api-agent wedges at 600s. crud_workflow_generator emits Create/Update/Delete<Entity> workflow files whose single node runs db_insert/db_update/db_delete. ensure_edit_routes clones each /new form into /[entity]/[id]/edit, adds a get dataSource, prefills defaultValues from {{record.field}}, and repoints Edit buttons. stub_page_backfill detects a page-agent minimal_schema (Stack+Heading with no dataSources) and fills it deterministically from registered entities; singleton_page_reconciler + create_page_coverage close the remaining coverage holes.

Files: `backend/services/deterministic_pages.py`, `backend/services/crud_workflow_generator.py`, `backend/services/crud_route_generator.py`, `backend/services/ensure_edit_routes.py`

**Nav-flow + shell menu + auth-gate + workflow_launch_forms navigation** — ➕ EXTENDS

nav-flow.json is the authoritative navigation model. nav_flow_from_plan builds it from the planner (auto-classifying auth vs shell routes, and honoring an authGated decision), nav_flow_emitter extracts transitions from schemas after emission, and nav_flow_from_schemas.py is a lazy fallback that rebuilds an equivalent nav-flow purely from src/schemas so the visual editor's Canvas can open any project including pre-nav-flow apps. nav_apply.py + nav_guard.py + nav_route_reconcile_guard.py apply/validate transitions and ensure every navigate prop resolves. workflow_launch_forms.py registers its synthesized run-page routes into nav-flow. shell_menu_sync.py derives the sidebar menu from nav-flow (nav_icon_map.py picks icons by label heuristic). auth_gate_guard.py reads authGated and neutralizes the scaffold's (dashboard)/layout.tsx session redirect for public apps.

Files: `backend/services/nav_flow_from_plan.py`, `backend/services/nav_flow_emitter.py`, `backend/services/nav_flow_from_schemas.py`, `backend/services/nav_apply.py`


### 27.9A Updates to §9A Schema / Renderer Contract

**Schema registry + advisory Zod loader** — 🆕 NEW

src/schemas/registry.ts maps route-key → dynamic JSON import and is the sole discovery seam for the [entity] and catch-all routers (`route in schemas` is the notFound gate). loadSchema (schemas/load.ts) validates each raw JSON against the @tentoroforge/schema Page zod at first access, caches in-process, but validation is ADVISORY — generated schemas legally use `{{binding}}` strings in typed fields, so a mismatch logs a warn and returns the raw schema. A hard schema throw here would black-hole any page whose bindings the Page zod can't type-check.

Files: `backend/templates/app-foundation/src/schemas/registry.ts`, `backend/templates/app-foundation/src/schemas/load.ts`

**LibraryDispatcher + NodeErrorBoundary + registry-driven fallback** — ➕ EXTENDS

Unknown node types fall through to a registry lookup: `renderNode` calls `registry.validateProps(type, props)` eagerly and, on failure, renders an inline `⚠ Type: invalid props` chip with the zod message in a `title`; on unknown type it renders a `⚠ Type` placeholder. Valid nodes dispatch through `LibraryDispatcher`, which wraps output in `<span data-node-id … style={{display: 'contents'}}>` so the editor overlay can target every node without perturbing layout, and in `NodeErrorBoundary` so a single component crash doesn't kill the page. Nodes without an id get a stable `syntheticNodeId(node)` on first render.

Files: `packages/renderer/src/nodes/library/LibraryDispatcher.tsx`, `packages/renderer/src/nodes/library/NodeErrorBoundary.tsx`, `packages/renderer/src/runtime/dispatch.tsx`

**content/children root aliases + Icon defaults** — ✓ CONFIRMS

`synthesiseRoot` in Engine.tsx tolerates schemas that emit `content: {...}` (shadcn convention) or a bare `children: [...]` array in place of the spec's `root`, so the page renders instead of hitting the empty-page placeholder. The dispatcher also gives `Icon` nodes an implicit `w-5 h-5` when the schema hasn't specified sizing — Figma-exported SVGs carry natural 1000px dimensions and would otherwise dominate every layout.

Files: `packages/engine/src/Engine.tsx`, `packages/renderer/src/runtime/dispatch.tsx`

**layout Slot resolution + slots map** — ✓ CONFIRMS



Files: `packages/renderer/src/runtime/layouts.ts`, `packages/renderer/src/SchemaRenderer.tsx`

**StyleSlot token→CSS-var resolver (backgrounds, position, motion)** — ✓ CONFIRMS

`applyStyleSlot` (packages/renderer/src/runtime/style-slot.ts) is the shared renderer-side resolver for the schema `StyleSlotT` — it maps token references like `tokens.color.surface.0` or `spacing.4` to `var(--token-…)` CSS custom properties, handles the `BackgroundT` discriminated union (solid/gradient/image/pattern) plus bare token-string backgrounds, and inlines `position` fields and a `data-motion` attribute. Kept in renderer to avoid a runtime dependency on @tentoroforge/library, so structural nodes render without pulling the component library.

Files: `packages/renderer/src/runtime/style-slot.ts`

**Custom node HTML block with customRenderer hook** — 🆕 NEW

The `Custom` node type renders sanitized HTML via `CustomHtml`, which lazy-imports DOMPurify on the client so the renderer never drags the ESM-only isomorphic-dompurify onto the server bundle. `DispatchContext.customRenderer` is an optional editor-only override the visual editor sets to mount its own CustomNodePreview (edit chip + pointer-events guard) without forking the dispatch switch.

Files: `packages/renderer/src/runtime/dispatch.tsx`, `packages/renderer/src/nodes/library/CustomHtml.tsx`

**Repeat v1/v2 shape + Conditional condition-alias tolerance** — ⚠️ CORRECTS

The data nodes accept both v1 and v2 authoring shapes. `Repeat` reads the source from top-level `bind` (v2) or `props.source` (v1) and supports `props.path`, `props.as` (default `item`), `props.keyPath` (default `id`); each rendered iteration is wrapped in a `<div data-repeat-item>`. `Conditional` accepts either `props.when` or `props.condition`, and when both are missing renders children unconditionally rather than crashing — LLM-generated schemas frequently omit the field.

Files: `packages/renderer/src/nodes/data/Repeat.tsx`, `packages/renderer/src/nodes/data/Conditional.tsx`

**validatePage is advisory (never throws)** — ⚠️ CORRECTS

`validatePage` returns a warning-only pass-through: on schema mismatch it logs `[renderer] Page did not strictly validate (...)` and returns the input verbatim so the page still renders. This is deliberate — generated schemas legitimately place `{{...}}` templates in typed fields that only resolve at render time, and node-level renderNode is tolerant enough to cope. Any blueprint text implying strict page validation blocks rendering is out of date.

Files: `packages/renderer/src/runtime/validate.ts`

**Schema editor mount + iteration/critique** — 🆕 NEW

EditorMount is the entrypoint from /editor/[projectId]/[...slug]: it fetches the schema, mounts SchemaEditorPanel, and stitches together CritiquePanel (LLM critique of the current schema), IterationHistory + IterationDiffViewer (compare planner iterations), and PreviewTab (rendered result). Bridges the schema↔renderer contract by keeping human review and LLM iteration co-located.

Files: `frontend/src/components/schema-editor/EditorMount.tsx`, `frontend/src/components/schema-editor/SchemaEditorPanel.tsx`, `frontend/src/components/schema-editor/CritiquePanel.tsx`, `frontend/src/components/schema-editor/IterationHistory.tsx`

**Post-generate guard suite orchestrator + structured GuardResult** — 🆕 NEW

services/post_generate_fixes.py is the single deterministic entry point that runs the ~30-guard suite over a generated app tree; apply_post_generate_fixes_with_result wraps it in a scoped log capture so any WARNING/ERROR any guard emits becomes a structured GuardFailure in the returned GuardResult (services/guard_result.py). Smith's orchestrator + tests consume the GuardResult as its actor-critic pass/fail verdict, and a failing guard's message becomes the next-turn corrective prompt. The guard suite covers workflow_completeness/executability/graph_gate/mutation/value_types/table/trigger_button/launch_forms/resume_idempotency, binding_validator + read_binding_guard + list/widget/chart/detail data-source guards, submit_authority + action_contract, form_field_align + semantic_field_types + fk_source/fk_type/fk_semantics, schema_references + registry_repair, ensure_edit_routes + create_page_coverage + stub_page_backfill + singleton_page_reconciler, nav_flow_from_schemas + nav_guard + auth_gate_guard + shell_menu_sync, next_config_guard + drizzle_check_guard + api_route_prune.

Files: `backend/services/post_generate_fixes.py`, `backend/services/guard_result.py`


### 27.10 Updates to §10 Preview System

**Editor preview data resolver (source-name bridge)** — 🆕 NEW

`frontend/src/lib/preview-resolve.ts` (`resolvePreviewSources`) mirrors the generated app's server-side resolvers (`resolveAggregate` / `resolveSeries` / list) inside the editor canvas. `/api/_debug/preview-data` returns fixture rows keyed by entity name; page bindings reference dataSource names (e.g. `dashboardStats.activeDispatches`). This module walks each `PageIR.dataSources` entry, resolves it over the fixtures (aggregate/stats → object of metrics; series → grouped `{label,value}` sorted by bucket/value/label with optional limit; get/detail/find/one → first row; default → filtered+limited list) and merges the results into `previewData` under the source name so bindings like `{{dispatchByWeek}}` and `{{dashboardStats.x}}` render in the editor. Pure and defensive — try/catch per source so one bad source never blanks the canvas.

Files: `frontend/src/lib/preview-resolve.ts`

**Runtime injector + self-healing runtime-exception loop** — ⚠️ CORRECTS

services/runtime_injector.py copies the embedded runtime (workflows engine, rules, FEEL-lite, workflow_tasks schema) from backend/templates/runtime into {output_dir}/src/lib and generates /api/workflows/[id]/execute, /api/workflows/event/[event], WorkflowTriggerButton, and rules/index.json for each app. services/self_healing.py is the RUNTIME-error loop: when a browser/server exception is captured, it invokes Smith with the exception context, runs the guard suite over his writes, single-commits, and records the turn as a system-authored assistant message. Bounded: 5 concurrent heals per project, 20 attempts per hour, 3 attempts per exception before marking unresolvable. Distinct from services/self_heal.py, which only regenerates deterministically-derivable missing artifacts (a Create/Update/Delete<Entity> workflow for a real entity a button references but that was never written) at gen-time.

Files: `backend/services/runtime_injector.py`, `backend/services/self_healing.py`, `backend/services/self_heal.py`


### 27.11 Updates to §11 Module System

**Navigation store (screens + modules split)** — 🆕 NEW

`frontend/src/stores/navigation.ts` (`useNavigationStore`) drives the navigation/module editor: `screens` + `edges` (React Flow serialized), `sidebarLinks`, `topbarLinks`, `modules` + `moduleDependencies`, `defaultScreen`, `errorScreen`, and an `activeSubTab: 'screens' | 'modules'` toggle. `frontend/src/lib/flow-generator.ts` (`generateFlowFromIR`) auto-generates the screen graph from an `AppIR` by detecting list/detail/create patterns per entity and laying them out on a grid (COL_WIDTH=280, ROW_HEIGHT=140).

Files: `frontend/src/stores/navigation.ts`, `frontend/src/lib/flow-generator.ts`

**Navigation FlowEditor + ModuleWizard** — ➕ EXTENDS

The navigation tab hosts two editors backed by nav-flow.json: FlowEditor (React-Flow graph of ScreenNodes and typed edges with FlowEdgeProperties for transitions) plus ScreenProperties for per-page settings; and NavigationEditor for the shell menu. ModuleManager + ModuleWizard let the user add/remove modules (bundles of pages+workflows+entities) at authoring time — the frontend counterpart to the backend's module system.

Files: `frontend/src/components/navigation/NavigationPanel.tsx`, `frontend/src/components/navigation/FlowEditor.tsx`, `frontend/src/components/navigation/FlowEdgeProperties.tsx`, `frontend/src/components/navigation/ScreenNode.tsx`


### 27.12 Updates to §12 AppModel Index

**Refresh-index endpoint** — 🆕 NEW

POST /api/projects/{id}/refresh-index (backend/routers/generate.py) rebuilds the AppModel index on demand — used by Smith and the editor after out-of-band file changes to force a fresh scan without waiting for the contracts-mtime cache key to naturally invalidate get_app_map.

Files: `backend/routers/generate.py`

**Canonical resource registry as sole naming authority** — ⚠️ CORRECTS

One deterministic registry at contracts/resource-registry.json is now the naming authority every downstream generator READS instead of re-deriving. resource_registry.build_canonical_registry(plan) computes each entity's name-family (table/slug via name_normalizer), relationships, interactions (page↔workflow with inputMap), and roles. resource_registry_context.build_resource_context injects the CLOSED set (real entity slugs + columns + drizzle types + FK targets + workflow ids + trigger types + input columns) into the page/schema agent as a bind-only prompt block. resource_registry_validator asserts internal consistency (every relationship/FK/interaction resolves). After schema files are emitted, registry_schema_reconcile.reconcile_registry_to_schema overwrites the plan-inferred type/notNull/enum/primaryKey with ground-truth values parsed from Drizzle so the page agent and the form guards see the same required-flags and enum values.

Files: `backend/services/resource_registry.py`, `backend/services/resource_registry_context.py`, `backend/services/resource_registry_validator.py`, `backend/services/registry_schema_reconcile.py`

**Deterministic app-model + per-unit authoring for enterprise-scale plans** — ⚠️ CORRECTS

app_model_builder.py expands the plan into a page/route manifest + bidirectional dependency graph, reading from the canonical resource_registry so entity route/table segments never re-derive names. For large apps the planner emits a LEAN skeleton and per_unit_authoring.py (with app_decomposition.py) authors each page's fields/widgets/actions in its own bounded resource-registry SLICE — same output shape as a one-shot plan so downstream consumers are unchanged. peer_shape_analyzer.py flags pages whose dataSource shape signature diverges from same-archetype siblings (the class of bug that made Smith miss the extra filter on /drives/[id]).

Files: `backend/services/app_model_builder.py`, `backend/services/per_unit_authoring.py`, `backend/services/app_decomposition.py`, `backend/services/peer_shape_analyzer.py`


### 27.13 Updates to §13 Binding System

**Editor-side navigation config + deterministic apply** — 🆕 NEW

backend/routers/navigation.py owns /api/projects/{id}/navigation. GET reconciles a persisted navigation.json against on-disk schemas (falls back to building nav from AppModel + derived edges); POST persists. POST /navigation/apply first runs a DETERMINISTIC fast path — services.nav_apply.apply_editor_nav translates editor edges into nav-flow.json transitions and rewrites navigate props — and only falls through to code_editor + validator agents for anything deterministic apply can't express. Also serves /modules/layout (file-based module layout for the editor).

Files: `backend/routers/navigation.py`, `backend/services/nav_apply.py`

**FK-role authority (actor vs domain FKs)** — 🆕 NEW

Both `dataEngine.create` and workflow `db_insert` consult `FK_ROLES`/`fkRole`/`isDomainFk` (from `src/lib/fk-roles.ts`, emitted from the canonical registry) before auto-filling any FK from the current user. `_finalizeInsert` in `backend/templates/runtime/workflows/index.ts` and the create path in `data-engine.ts` only fill columns whose role is `actor`; a `domain` FK (e.g. `pets.ownerId → owners`) is never populated with the acting user's id, closing the class of `*_fk` constraint violations that legacy name-matching produced. When the registry is absent, a legacy name-based owner-FK list (`landlordId`/`ownerId`/`userId`/`createdById`/`authorId` + a regex) remains as fallback.

Files: `backend/templates/runtime/data-engine.ts`, `backend/templates/runtime/workflows/index.ts`

**Aggregate/series/ratio/delta dataSource resolvers** — 🆕 NEW

The data engine resolves two dashboard dataSource shapes directly (no per-app code). `resolveAggregate` handles `op:"aggregate"` with a `metrics` map — each metric is a `SimpleMetric` (count/sum/avg/min/max with optional `window`+`dateField`+`filter`), a `RatioMetric` (numerator/denominator, optional percent), or a `DeltaMetric` (this-window vs prior-window, percent or absolute). `resolveSeries` handles `op:"series"` — a real SQL GROUP BY over a normal column, or a whitelisted `date_trunc` bucket (`day|week|month`); returns `[{label,value}]` for charts. Any failing metric degrades to `0` / `[]` so a page never blanks or shows a literal `{{binding}}`.

Files: `backend/templates/runtime/data-engine.ts`, `backend/templates/runtime/data-engine/aggregate-window.ts`

**Mustache interpolation + FEEL-lite binding runtime** — ➕ EXTENDS

The renderer resolves every `{{expr}}` in a node's props via `interpolateDeep` before dispatch (packages/renderer/src/runtime/interpolate.ts). Whole-string templates preserve native type (e.g. `"{{count}}"` → number); mixed strings substitute in place; unresolved bindings whose ROOT symbol exists in scope render `""` (rather than leaking the raw template) while pure editor-preview keeps the placeholder visible. `evalExpression` (bindings.ts) delegates to shared FEEL-lite via runtime/expressions.ts, but detours plain identifier/index paths like `arr[0].field` through a manual `walkPath` because FEEL-lite throws on `[n]` subscripts. `==` is normalized to FEEL's `=`.

Files: `packages/renderer/src/runtime/interpolate.ts`, `packages/renderer/src/runtime/bindings.ts`, `packages/renderer/src/runtime/expressions.ts`

**Dynamic Select options via props.optionsFrom** — 🆕 NEW

`Select`, `Combobox`, and `MultiSelect` may declare `props.optionsFrom = {source, value, label}`; `renderNode` expands that against the loaded `dataSources` before validation and strips the helper field so component zod schemas don't need to know it. If the source resolves to an empty array or every row lacks the value key, the node keeps its static `options` as a fallback — that guarantees the min(1) contract and preserves editor-preview placeholders.

Files: `packages/renderer/src/runtime/dispatch.tsx`

**get-op FK lift + list-envelope unwrap in data loader** — 🆕 NEW

`fetchDataSources` (packages/engine/src/data/loader.ts) unwraps the list API's `{data,total,page,limit}` envelope down to the bare array so consumers like Select `optionsFrom` receive rows, not the envelope. For `op:'get'` sources it additionally lifts top-level OBJECT keys of the returned record to the root of the data context, so `{{employee.name}}` bindings resolve without forcing every author to prefix them with the parent source name. `source` may itself be a Mustache template resolved against previously-loaded sources.

Files: `packages/engine/src/data/loader.ts`

**FEEL-lite expression engine (frontend)** — 🆕 NEW

`frontend/src/lib/feel-lite/` is a full FEEL-lite implementation used by the visual editor for binding/condition expressions: tokenizer → parser (produces typed AST nodes: `NumberLiteral`, `Identifier`, `Unary/Binary/Comparison/Logical/Range/List/In/Not/If/FunctionCall/MemberExpression/Wildcard/BetweenExpression`) → `evaluate(ast, ctx)` with `matchValue`, plus `validateExpression` with a `VariableSchema` for editor-side lint. Convenience `evaluateExpression(expr, ctx)` returns null for empty input. The `{{path}}` renderer routes plain array-index paths through `walkPath` instead — FEEL-lite is used for real expressions (comparisons, ranges, function calls) not simple lookups.

Files: `frontend/src/lib/feel-lite/index.ts`, `frontend/src/lib/feel-lite/tokenizer.ts`, `frontend/src/lib/feel-lite/parser.ts`, `frontend/src/lib/feel-lite/evaluator.ts`

**ActionPicker (workflow-aware) + property panel PropControls** — 🆕 NEW

The right-hand PropertiesPanel routes typed control edits through PropControls: ActionPicker replaces free-text with a real Select of {none|navigate|workflow|submitForm|openModal} and, for workflow, fetches the project's workflows and maps each declared input to a literal or {{expr}} template. BindingControl + DataKeyControl + BindToggle drive the FEEL-lite {{binding}} authoring in BindingsPanel. Contract: the ActionValue shape is what the runtime dispatcher (SLICE-A-T9) reads at click time.

Files: `frontend/src/components/properties/PropControls/ActionPicker.tsx`, `frontend/src/components/properties/PropControls/BindingControl.tsx`, `frontend/src/components/properties/PropControls/DataKeyControl.tsx`, `frontend/src/components/properties/BindingsPanel.tsx`

**Build-time binding contract (author-time context + gate + repair)** — ⚠️ CORRECTS

Binding is now a formal three-slice contract. binding_validator.validate_bindings(output_dir) is the build-time gate (FORGE_BINDING_GATE=warn|strict): registered entity slugs are the pgTable const names across src/db/schema/*.ts, plus per-entity columns/drizzle types and per-workflow input columns + trigger type. It checks button→workflow, form→resource, dataSource/optionsFrom→slug, {{binding}}→dataSource-name, and workflow-input↔column-type. resource_registry_context injects the same closed set into the authoring prompt so the LLM binds only to real resources. schema_references.py is the reference reconciler that walks every reference-bearing node and classifies as exact/derived/fuzzy/unresolved, writing contracts/references-report.json. list_data_source_guard reconciles the two independent naming drifts (binding↔name and source↔table) that cause empty tables.

Files: `backend/services/binding_validator.py`, `backend/services/resource_registry_context.py`, `backend/services/schema_references.py`, `backend/services/list_data_source_guard.py`

**Read-binding contract (materialize derived dataSources; semantic-prefix decode)** — 🆕 NEW

Read bindings ({{name}} on Table.rows, List.items, Chart.data, Stat.value, map resources) go through read_binding_guard.py, the read-side twin of the action-contract: for every read binding it resolves (already a dataSource), remaps (naming-drift orphan → real compatible-op source), or materializes a missing derived dataSource by decoding a semantic prefix (active/recent/upcoming/pending/completed/closed/latest/open) or a By<Col> grouping into a real filter/sort/limit over the entity's actual columns (read_binding_semantics.py). Never invents: unknown base entity stays unresolved so the validator errors on it. Deterministic, idempotent, produces byte-identical schemas and contracts/data-contract.json on re-run.

Files: `backend/services/read_binding_guard.py`, `backend/services/read_binding_semantics.py`

**Field/form correctness pipeline (semantic types, FK semantics, field visibility, alignment)** — ➕ EXTENDS

Form correctness is enforced by a stack of deterministic passes. semantic_field_types re-types every form field from column type + seed plan (enum→Select with real options, numeric→NumberInput, date→DatePicker, bool→Switch, long text→Textarea). fk_semantics is the single authority classifying each FK column's role (tenancy / actor-ownership / domain-FK) by reading the registry's REAL fk target rather than name-matching — killing the ownerId→users mistake. fk_source_guard reads .references(() => t.id) in the emitted Drizzle and rewrites Select.optionsFrom.source to the true target slug + promotes uuid FK Inputs to Selects. fk_type_guard makes every FK column's SQL type match its target PK (fixes integer↔uuid drizzle constraint errors that would silently zero out seeding). form_field_align renames LLM-invented form fields to real registry column names via exact/prefix-strip/synonym matching and appends inputs for missing NOT-NULL columns. field_visibility_wire turns plan['field_visibility'] into hidden_from_roles metadata downstream builders consume.

Files: `backend/services/semantic_field_types.py`, `backend/services/fk_semantics.py`, `backend/services/fk_source_guard.py`, `backend/services/fk_type_guard.py`

**Chart / list / widget data-source guards** — 🆕 NEW

Post-generate guards rebind hardcoded literals from the dashboard exemplar to real dataSources. chart_data_source_guard replaces a Chart's literal data array with a generated op:'series' dataSource (GROUP BY → [{label, value}]) when the chart maps confidently to an entity + column. widget_data_source_guard covers the other two families: Stat/KPI/progress/gauge with a literal number (→ op:'aggregate' count) and List/DataList/Table with a literal rows array (→ op:'list'). Both are conservative — a static widget beats a broken binding, so a literal is only converted with entity-confidence. list_data_source_guard reconciles the binding↔name and source↔table drifts that produce empty tables. All are deterministic, idempotent, and never raise.

Files: `backend/services/chart_data_source_guard.py`, `backend/services/widget_data_source_guard.py`, `backend/services/list_data_source_guard.py`, `backend/services/detail_action_guard.py`


### 27.14 Updates to §14 Rules Engine & Decision Builder

**Rules Agent (prose → structured ProjectRule)** — 🆕 NEW

agents/rules_agent.py converts the planner's prose access-control rules (plan.access_control.rules) into structured ProjectRule records the runtime rules engine can execute, matching the ProjectRule shape {name, rule_type, model_name, field_name?, config, is_active} across validation/access/business/computed/state_machine/trigger types. Rules are written to registry.rules for services/runtime_injector.py to export as rules/index.json, and — when a project_id is passed — persisted to the project_rules table (prior rows wiped first for idempotent re-runs) so the editor's RulesPanel picks them up.

Files: `backend/agents/rules_agent.py`, `backend/services/runtime_injector.py`

**Decision engine (tables + DRD graph)** — ➕ EXTENDS

The decision subsystem is `frontend/src/lib/decision/`: `evaluateDecisionTable`, `evaluateDecisionGraph`, `analyzeDecisionTable` (completeness/overlap/dead-rule analysis), plus `RULE_TEMPLATES`. `useDecisionStore` (`frontend/src/stores/decision.ts`) owns both a table view (`activeTable`, `testCases`, `testResults`, `analysisResult`, `highlightedRuleIds`) and a Decision Requirements Diagram (`currentGraph`, `selectedDRDNodeId`, add/update/remove DRD nodes + edges, `upsertDecisionTable`). It also carries a client-side version history (`DecisionVersion[]`, `saveVersion`, compare/selected indices) for snapshotting a table across edits — a feature the blueprint's rules-engine section doesn't mention.

Files: `frontend/src/lib/decision/index.ts`, `frontend/src/lib/decision/table-evaluator.ts`, `frontend/src/lib/decision/graph-evaluator.ts`, `frontend/src/lib/decision/analysis.ts`

**DRD (Decision Requirements Diagram) editor** — 🆕 NEW

A full DRD editor (React-Flow canvas with DRDNode/DRDNodePanel/DRDToolbar) plus a DecisionTableEditor with HitPolicySelector, DecisionCellEditor, DecisionColumnHeader, DecisionRuleRow, ExpressionAutocomplete, DecisionAnalysisOverlay, DecisionDiffView, DecisionTestPanel and DecisionVersionPanel. Mounted as the 'decisions' tab in the project workspace. Extends the blueprint's Rules Engine section into a first-class DMN-style modeling surface.

Files: `frontend/src/components/decision/DRDEditorPanel.tsx`, `frontend/src/components/decision/DRDCanvas.tsx`, `frontend/src/components/decision/DecisionTableEditor.tsx`, `frontend/src/components/decision/DecisionTestPanel.tsx`


### 27.15 Updates to §15 Workflow Engine

**Business Logic Agent — workflow JSON only** — ⚠️ CORRECTS

agents/business_logic_agent.py is now the sole authoring path for domain logic and its ONLY deliverable is complete executable workflow JSON under workflows/*.json — it writes no TypeScript, no services, no API routes. The workflow engine (src/lib/workflows/engine.ts), the standard /api/workflows/* API, and the Data Engine catch-all (/api/data/[...path]) execute the JSON directly; any per-app service or route the LLM slips in is pruned by services/api_route_prune.py. The agent is skipped entirely when the plan has no workflows.

Files: `backend/agents/business_logic_agent.py`, `backend/services/api_route_prune.py`

**Workflow lifecycle runtime endpoints** — ➕ EXTENDS

routers/workflows.py now surfaces the full runtime lifecycle backed by runtime.engine.WorkflowRuntimeEngine: POST /workflows/start (creates a WorkflowInstance), GET /workflow-instances (list, filter by status/workflow_id), GET /workflow-instances/{id} (detail with task_instances), POST /workflow-instances/{id}/cancel, POST /tasks/{task_id}/complete (advances the workflow), GET /tasks (filter by assignee_id/status/instance_id), and GET /workflow-instances/{id}/logs for NodeExecutionLog audit rows. Assignment policies (WorkflowAssignmentPolicy) get their own CRUD.

Files: `backend/routers/workflows.py`, `backend/runtime/engine.py`

**Workflow apply — template copy + drizzle push + build** — ⚠️ CORRECTS

POST /api/projects/{id}/workflows/{workflow_id}/apply is now a deterministic template copy (no LLM): copies templates/workflow-engine → src/lib/workflow-engine, templates/workflow-api-routes → src/app/api/workflows, appends wfInstances/wfTaskInstances/wfExecutionLogs re-exports to src/db/schema.ts, adds @anthropic-ai/sdk to package.json (npm install), runs `drizzle-kit push --force` to create the tables, then `npm run build` to verify, and finally git commits + records an AgentJob/Version + assistant message. Streamed over SSE.

Files: `backend/routers/workflows.py`

**Workflow resume-idempotency (T5)** — 🆕 NEW

The workflow engine implements resume-idempotency so a paused-then-resumed workflow does not re-run completed steps. In `executeNode` (`backend/templates/runtime/workflows/engine.ts`), each non-human node sets `__step_<id>_completed`, `__step_<id>_output`, and — for conditions/gateways — `__step_<id>_branch` on `ctx.variables`. On resume the engine short-circuits at the entry check, emits a synthetic `skippedResume` log entry, and replays the cached branch edges so the same path is taken. Human-task nodes (`user_task`, `approval`) are excluded because they already have their own decision-based short-circuit that reads `__step_<id>_decision`/`_comment` and writes them into the node's declared outputParams.

Files: `backend/templates/runtime/workflows/engine.ts`

**SUBMIT-AUTHORITY input assembly** — 🆕 NEW

`assembleWorkflowInputs` in `backend/templates/runtime/workflows/input-assembly.ts` is the runtime half of the SUBMIT-AUTHORITY contract: given a workflow's declared `inputs[]` and an `AssemblyContext` of `{form, route, auth}`, it resolves each input from one of five source kinds — `form_field`, `route`, `auth`, `static` (with `{{now}}`/`{{uuid}}` templates), or `computed` (a FEEL-lite expression that sees `form.*`, `route.*`, `auth.*`, and previously-resolved `inputs.*`). Missing values on required inputs produce typed `AssemblyError` entries; the helper never throws so the caller can refuse dispatch cleanly. This is what the generated Form/Button dispatch seam calls before `executeWorkflow`.

Files: `backend/templates/runtime/workflows/input-assembly.ts`, `backend/templates/runtime/feel-lite/index.ts`

**Dynamic task-assignment strategies** — 🆕 NEW

`_resolveAssignee` in `backend/templates/runtime/workflows/index.ts` implements eight advertised strategies for pending user_task/approval assignment: `static`, `role`, `round_robin`, `load_balanced`, `creator`, `entity_field`, `reporting_manager`, `department_head`, and `group`. Pool-based strategies rotate by counting prior tasks in `workflow_tasks`; `load_balanced` picks the pool member with fewest currently-pending rows; `reporting_manager`/`department_head` query `users.manager_id` / `users.department_id`; `group` reads `user_groups`. Every DB query is try/caught so a schema without the optional columns falls back to `task.assignee || role || 'admin'` instead of crashing. The Python `services.task_assignment_strategies` mirrors this menu exactly.

Files: `backend/templates/runtime/workflows/index.ts`

**Universal pending-task persistence** — 🆕 NEW

`persistPendingTask` in `backend/templates/runtime/workflows/index.ts` funnels every entry point that starts a workflow — `triggerWorkflow`, `triggerWorkflowEvent`, the `/execute` route — through the same INSERT into `workflow_tasks` (schema at `backend/templates/runtime/db/workflow-tasks.schema.ts`, emitted as `forge_workflow_tasks`). Before persist it resolves the effective assignee via `_resolveAssignee` and derives `entityType`/`entityId` from the trigger input. Best-effort: if the `workflow_tasks` table is absent the call warns and returns rather than throwing. Previously only `/execute` persisted, so event-started workflows paused invisibly.

Files: `backend/templates/runtime/workflows/index.ts`, `backend/templates/runtime/db/workflow-tasks.schema.ts`

**PDF generation + pluggable storage (generate_document)** — 🆕 NEW

The `generate_document` action in `backend/templates/runtime/workflows/index.ts` composes a `spec` from workflow variables (`title`, `subtitle`, `footer`, `fields[]` or a `record` var expanded to fields, optional `table`), calls `buildPdf` from `backend/templates/runtime/pdf.ts`, then hands the bytes to `saveFile` in `backend/templates/runtime/storage.ts`. Storage backend auto-selects S3 when `FORGE_S3_BUCKET` + `@aws-sdk/client-s3` are present, otherwise writes to `FORGE_UPLOAD_DIR` (`./data/uploads`). File metadata always lives in the `forge_files` table; the file is served from `/api/files/[id]`.

Files: `backend/templates/runtime/workflows/index.ts`, `backend/templates/runtime/pdf.ts`, `backend/templates/runtime/storage.ts`

**send_notification / send_email real handlers** — ➕ EXTENDS

`send_notification` inserts into `forge_notifications` (queryable via `/api/notifications`, displayable via ActivityFeed/Banner/List), accepting `{title|subject, message|body, to|userId, toRole|assigneeRole, type, entityId}` with `{{var}}` interpolation. `send_email` posts to Resend when `RESEND_API_KEY` is set (HTTP, no npm dep) and falls back to persisting an in-app notification so the message is never lost. Both live in `backend/templates/runtime/workflows/index.ts`.

Files: `backend/templates/runtime/workflows/index.ts`, `backend/templates/runtime/db/forge-notifications.schema.ts`

**handleAction failure surfacing (error-returning handlers)** — 🆕 NEW

A handler that returns `{ error }` (e.g. `db_insert` on an unknown table) no longer completes silently — the engine's action case in `executeNode` throws with the node label and the error string, so the workflow reports `failed` and the UI shows the real cause instead of a green tick. Combined with the runtime error reporter, this failure also flows to Forge with `__nodeId`+`__workflowId` context for Smith to act on.

Files: `backend/templates/runtime/workflows/engine.ts`

**WHERE-clause empty-value guard (db_update/db_delete/db_query)** — 🆕 NEW

`_buildWhere` in `backend/templates/runtime/workflows/index.ts` throws with the offending field name when a `where` ref resolves to `''`/`null`/`undefined`, rather than letting Postgres fail on `22P02 invalid input syntax for type uuid: ''` or (worse) letting an untyped column match every row. This turns "trigger form is missing an input" into a loud, addressable failure at the offending node.

Files: `backend/templates/runtime/workflows/index.ts`

**Wave-5 approval extensions (parallel approvers, routing, delegation, escalation)** — 🆕 NEW

The workflow types add `ParallelApproverGroup`, `RoutingCondition`, `DelegationRule`, `ReminderConfig`, `EscalationConfig`, and `StageV2` alongside legacy `Stage`/`Workflow` aliases. The engine exports `resolveApprovers` (applies delegation rules to user/role/field/delegated selectors), `canAdvanceStage` (any/all modes with short-circuit rejection), `nextStage` (honours routing conditions), and `evalCondition` (simple `path OP value`). `escalation.ts` implements a cron-driven `processEscalations(db, pending, notify)` that sends reminders and escalates per stage config and appends `appendAuditEntry` rows for each event.

Files: `backend/templates/runtime/workflows/engine.ts`, `backend/templates/runtime/workflows/escalation.ts`, `backend/templates/runtime/workflows/types.ts`, `backend/templates/runtime/workflows/audit-log.ts`

**Table-name canonical resolver + tolerant matching** — 🆕 NEW

Both engines resolve table names tolerantly so snake / camel / kebab / Pascal / singular / plural variants of the same table hit the right Drizzle export. `_resolveTable` in `workflows/index.ts` canonicalises via `_canonTable` (strip separators, lowercase); `getEntity`/`registerEntity` in `data-engine.ts` index each entity under name, slug, aliases from the canonical registry, plus a separator-stripped canonical key + its plurality. This closes the class of runtime `unknown table` errors on multi-word entities that single-word tables happened to hide.

Files: `backend/templates/runtime/workflows/index.ts`, `backend/templates/runtime/data-engine.ts`

**Event registry (declarative data→workflow bindings)** — 🆕 NEW

`backend/templates/runtime/event-registry.ts` reads `contracts/event-bindings.json` at boot and wires data-engine mutation events (`data:<entity>:<create|update|delete>`) to workflow triggers, with optional `EventCondition` filters (`changed`, `newValue`/`oldValue`, `operator: eq|ne|in|not_in|exists`). Registration is declarative — adding a binding is a JSON edit, no code change — and every binding hop is fire-and-forget so a workflow failure never crashes the mutation.

Files: `backend/templates/runtime/event-registry.ts`

**custom action runs FEEL-lite (not eval)** — 🆕 NEW

The `custom` action handler in `backend/templates/runtime/workflows/index.ts` evaluates `config.expression`/`code` through the sandboxed FEEL-lite engine — expressions only, no host access — against the process variables, then optionally assigns the result to `config.assignTo`. Empty or comment-only code returns `{ran:false}` without crashing. This replaces earlier eval-shaped stubs and keeps design-time compute steps safe.

Files: `backend/templates/runtime/workflows/index.ts`, `backend/templates/runtime/feel-lite/evaluator.ts`

**WorkflowDispatchProvider — client dispatch to /api/workflows/[name]/execute** — 🆕 NEW

Client provider that satisfies the renderer's WorkflowDispatcherContext. Any schema Form or Button carrying a `workflow` action calls createWorkflowDispatch (from @tentoroforge/renderer), which POSTs field values to /api/workflows/{name}/execute; on success it calls router.refresh() to refetch server components and surfaces state via sonner (`Running…` / `Done` / error). This is the only workflow seam a generated form uses at runtime — the previous inline server stub in schema-page could never be a valid client dispatch.

Files: `backend/templates/app-foundation/src/lib/WorkflowDispatchProvider.tsx`

**/tasks inbox + [id] detail pages (Slice E)** — 🆕 NEW

Every generated app ships a shared human-task UI. /tasks (server component) fetches /api/tasks?status=pending using the forwarded session cookie and renders a keyboard-navigable inbox; /tasks/[id] (client component) shows process_variables read-only plus Approve/Reject buttons that POST `{taskId, input:{__decision, comment, entityId, entityType}}` to /api/workflows/{workflow_id}/execute — the runtime treats a POST-with-taskId as a resume. Injected by services.runtime_injector._inject_task_inbox_pages and paired with the workflow_tasks Drizzle schema.

Files: `backend/templates/app-foundation/src/app/tasks/page.tsx`, `backend/templates/app-foundation/src/app/tasks/[id]/page.tsx`

**WorkflowDispatcher context + createWorkflowDispatch transport** — 🆕 NEW

The client-side seam that lets any schema Button or Form fire a workflow is `WorkflowDispatcherContext` in packages/renderer/src/client/WorkflowDispatcher.tsx. `createWorkflowDispatch({apiBase, fetchImpl, onStart, onSuccess, onError})` returns a dispatch that POSTs `{input: args}` to `/api/workflows/{name}/execute`; it never rejects, routing failures to `onError`. The Engine (packages/engine/src/Engine.tsx) installs a live dispatch when `live` is true and a no-op when the editor renders a preview, so the same schema behaves correctly in both surfaces. On success, if the current path ends in `/new` or `/edit` it soft-navigates to the parent via the injected Navigator and calls `nav.refresh()`, so a create/edit form doesn't sit there after submission.

Files: `packages/renderer/src/client/WorkflowDispatcher.tsx`, `packages/engine/src/Engine.tsx`

**Workflow simulator store + sim boundary** — 🆕 NEW

The workflow editor has an in-browser simulator: `frontend/src/lib/workflow-sim/` defines `SimApi` (injectable transport for start / getInstance / getLogs / completeTask / cancel), the `TaskDTO`/`InstanceDetailDTO`/`NodeLogDTO`/`RunPhase`/`NodeVisualStatus` types, `computeNodeStatuses` for per-node visual status, plus `trigger-form` / `task-form` extractors that produce form specs from workflow definitions (`taskFormSpec`, `buildTaskOutput`). `useWorkflowSim` (`frontend/src/stores/workflow-sim.ts`) is the state machine: `idle | starting | running | awaitingInput | completed | failed | cancelled`, staggered `pendingReveal` reveal-queue for animating newly-visited nodes, `poll` (parallel getInstance + getLogs), `submitTask` (dynamically imports task-form to compute output), `cancel`, and `fastForwardTimer` for timer/wait/SLA tasks (`isTimerTask` covers `timer_event`/`timer`/`wait`).

Files: `frontend/src/stores/workflow-sim.ts`, `frontend/src/lib/workflow-sim/sim-api.ts`, `frontend/src/lib/workflow-sim/node-status.ts`, `frontend/src/lib/workflow-sim/task-form.ts`

**Workflow simulator (canvas overlay + trigger/task forms)** — 🆕 NEW

WorkflowSimulator orchestrates a live simulation of a WorkflowDefinition inside WorkflowPanel. It polls sim-api (POLL_MS 800), extracts trigger inputs into TriggerInputForm, renders per-user-task TaskInputPanel forms, and overlays node visual statuses + taken edges on WorkflowCanvas via computeTakenEdges. State machine lives in the useWorkflowSim zustand store (submitTask resume, cancel, timer fast-forward against a backend endpoint). Includes isTimerTask helper for wait/timer node UX.

Files: `frontend/src/components/workflow/simulator/WorkflowSimulator.tsx`, `frontend/src/components/workflow/simulator/TriggerInputForm.tsx`, `frontend/src/components/workflow/simulator/TaskInputPanel.tsx`, `frontend/src/stores/workflow-sim.ts`

**Rich workflow editor (nodes, edges, palette, properties, expression + trigger mapping)** — ➕ EXTENDS

The workflow editor is far more than a canvas: NodePalette + typed WorkflowNode/edges; NodePropertiesPanel with per-actionType configs (AssignmentStrategyEditor for the 5 human-task strategies, ExpressionEditor with FEEL-lite autocomplete, TriggerMappingEditor for form→workflow input binding, ProcessVariablesEditor, FormFieldEditor, VariablePicker, NodeIOParamsEditor, DecisionNodeProps); ExecutionLogViewer replays runs. All backed by definitions in types/workflow.

Files: `frontend/src/components/workflow/WorkflowCanvas.tsx`, `frontend/src/components/workflow/WorkflowPanel.tsx`, `frontend/src/components/workflow/NodePalette.tsx`, `frontend/src/components/workflow/NodePropertiesPanel.tsx`

**SUBMIT-AUTHORITY contract (page.submit + workflow.source + inputs[].source with post-gen guards)** — 🆕 NEW

Every form-typed page declares page.submit (workflow or data_api); every workflow declares workflow.source (dispatching UI); every workflow input declares inputs[].source (form_field/route param/auth claim/static/computed). submit_authority.py provides pure resolve/validate helpers consumed by the form scaffolder, deterministic page builder, and plan validator. submit_authority_guards.py runs LAST in apply_post_generate_fixes and reports residual violations (orphan workflow, form with no target). action_contract_guard.py reconciles each page action against reality — verifies the workflow exists, validates/derives input_map by name-matching form fields to real db_insert/db_update input columns, sets requires_record from trigger + steps — writing contracts/action-contract.json. wire_form_workflow.py + orphan_wiring_pass.py auto-wire unwired forms to compatible orphan workflows above a confidence threshold. workflow_launch_forms.py synthesizes trigger-input forms for bare-button manual workflows so an empty dispatch payload can never crash. workflow_input_map_backfill.py fills db_insert/db_update values maps whose unmapped_fields list is non-empty.

Files: `backend/services/submit_authority.py`, `backend/services/submit_authority_guards.py`, `backend/services/action_contract_guard.py`, `backend/services/wire_form_workflow.py`

**Workflow engine: rich planner-step translation, executability, graph gate, mutation heal, value-type checker, node-contract extraction** — ⚠️ CORRECTS

Workflow generation is now a source→translate→gate→heal pipeline. workflow_step_translator faithfully consumes the planner's rich step schema (config/branches/next) and emits engine-faithful {nodes, edges} with real then/else branching. workflow_completeness enforces the loadability floor (trigger + nodes + edges); workflow_executability enforces per-actionType required-param contracts (db ops need table/values/where; send_email needs to+body; etc.) with an LLM refiner for non-executable domain workflows. workflow_graph_gate statically simulates the graph (reachability + variable availability) and repairs dangling edges, unreachable nodes, dead-ends, planner-only node types, unknown actionTypes, and unassigned user_tasks — all deterministic + idempotent. workflow_mutation_guard heals self-referential {{status}}/{{pickedUpAt}} values into literals derived from the node label / CURRENT_TIMESTAMP. workflow_value_types is the column-type checker (timestamp→uuid, string→enum, etc.). workflow_variable_contract detects branch expressions reading variables that no node produces. workflow_node_contracts auto-extracts the NodeType/ActionType union + handler registrations from templates/runtime/workflows/*.ts so the planner catalog can never drift from what the engine executes. workflow_table_guard heals casing/separator drift between workflow config.table and real pgTable declarations. workflow_trigger_button_guard neutralizes buttons that dispatch event-driven (api_event/db_change/schedule) workflows from a page with no record context. workflow_action_mapper indexes status-transition workflows so page-invented Confirm/Cancel action refs rewrite to the real domain workflow.

Files: `backend/services/workflow_generator.py`, `backend/services/workflow_step_translator.py`, `backend/services/workflow_executability.py`, `backend/services/workflow_completeness.py`

**Slice E — human-task engine (workflow_tasks table + assignment strategies + notifications + resume idempotency + submit)** — 🆕 NEW

Slice E hardens the human-task path. A workflow_tasks Drizzle schema is now runtime-injected into every generated app plus /tasks inbox + [id] detail templates (backend/templates/runtime + standalone-app). task_assignment_strategies.py implements the five advertised strategies (specific_user, role, least_loaded, round_robin, previous_actor). task_notification_defaults.py auto-emits a send_notification action before every user_task so assignees are actually pinged. workflow_resume_idempotency.py names per-node completion markers (__step_<id>_completed / _output / _branch) that the engine writes on step completion and short-circuits on resume — so a workflow resuming after an approval or user_task never re-runs upstream db_insert/db_update/http_call/send_email a second time. A dedicated submit kind (workflow_resume) is threaded through the dispatcher for task-completion forms.

Files: `backend/services/workflow_resume_idempotency.py`, `backend/services/task_assignment_strategies.py`, `backend/services/task_notification_defaults.py`


### 27.16 Updates to §16 Database Management

**Deterministic seed with token → UUID mint** — 🆕 NEW

`backend/templates/runtime/seed.ts` is a deterministic emitter run at `start.sh` time: it upserts an admin user (bcrypt) using `SEED_ADMIN_EMAIL/SEED_ADMIN_PASSWORD`, then walks `contracts/seed-plan.json` in table order. Placeholder id tokens the LLM emits (`uuid-1`, `member-3`) are minted to stable real UUIDs via a shared `tokenMap`, so a child row's FK token resolves to the parent PK minted earlier. ISO strings become `Date`s, missing columns are dropped, and each table is skipped when it already has rows — the seed is idempotent.

Files: `backend/templates/runtime/seed.ts`

**Data model panel: ERD, DatabaseBrowser, SQL console, seed/enum editors, impact analysis** — ➕ EXTENDS

The data tab is a full data-modeling and admin surface: ERDCanvas (React-Flow, EntityCardNode, erd-layout auto-layout) with click-through to DatabaseBrowser (paginated + sortable via nextSortState + dbRowsUrl helpers backed by /db/rows); SqlConsole for ad-hoc queries; SmartFieldEditor + IndexEditor + RelationshipEditor + EnumEditor for schema edits; SeedDataEditor for seed rows; ImpactAnalysis + SchemaChangeProgress for migration preview. Admin-only entry points gated by useIsOrgAdmin.

Files: `frontend/src/components/data-model/DataModelPanel.tsx`, `frontend/src/components/data-model/ERDCanvas.tsx`, `frontend/src/components/data-model/EntityCardNode.tsx`, `frontend/src/components/data-model/erd-layout.ts`

**Generated-app database — deterministic Drizzle schema + Data Engine catch-all** — 🆕 NEW

Each generated app owns a Postgres database whose schema is authored deterministically by backend/services/schema_builder.py — one src/db/schema/<slug>.ts pgTable per entity plus barrels — and never emitted by an LLM in schema-mode. RESERVED_TABLES = {'users'} is honored so the auth-template's user table is not clobbered; extra planned columns on User are merged into the reserved table. Rows are seeded deterministically by seed_synthesizer.py, which parses the emitted schema (pgTable / pgEnum / FK regexes), orders tables topologically, mints UUIDs, and writes into contracts/seed-plan.json (both seed_data and top-level sample_data) — the shipped runtime seeder (templates/runtime/seed.ts) then loads that file. drizzle_check_guard rewrites LLM-authored check(name, str) into sql`…` so drizzle-kit push never aborts on a bad check. Runtime CRUD flows through ONE catch-all Next route — backend/templates/data-api-route.ts — that auto-registers every schema table with @/lib/data-engine and serves list/create/get/update/delete + stats without per-entity handlers.

Files: `backend/services/schema_builder.py`, `backend/services/schema_pipeline.py`, `backend/services/schema_references.py`, `backend/services/seed_synthesizer.py`

**Platform database admin — /db/tables, /db/rows, /db/query, /db/seed** — 🆕 NEW

The platform exposes admin database inspection endpoints per generated project under /api/projects/{project_id}/db/*: GET /db/tables (list), GET /db/rows (paginated/sortable rows built through build_rows_query), GET/POST /db/query (read/write SQL), and POST /db/seed (rerun the seeder). These back the in-editor DatabaseBrowser and ERD click-through and are gated by an admin check. The generated app's own Postgres is bootstrapped by shelling into its start.sh --seed-only from backend/routers/app_actions.py, which returns the seeded admin login for the chat UI.

Files: `backend/routers/data_model.py`, `backend/routers/output_projects.py`, `backend/routers/app_actions.py`


### 27.17 Updates to §17 Authentication & Authorization

**NextAuth Credentials + signup** — ⚠️ CORRECTS

Auth is NextAuth v4 with a Credentials provider (bcryptjs, JWT sessions, id+role callbacks). authorize() defensively probes for isActive/name/firstName+lastName so it works across the different user-schema shapes the schema builder emits. src/middleware.ts uses withAuth with a matcher that excludes login/signup/api/auth AND /editor + /api/editor + /api/figma (dev-only routes never require login). Signup is a first-class POST /api/auth/signup route that zod-validates, checks conflict, bcrypts at 12 rounds, and adapts the insert to whichever of {name} or {firstName,lastName} exists on the users table.

Files: `backend/templates/app-foundation/src/auth.ts`, `backend/templates/app-foundation/src/middleware.ts`, `backend/templates/app-foundation/src/app/api/auth/signup/route.ts`

**Auth store + shared api client with token refresh** — ➕ EXTENDS

`frontend/src/stores/auth.ts` (`useAuthStore`) owns `token` + `user` (with `orgs: OrgMembership[]`) and exposes signup/login/logout/fetchUser/hydrate. It talks through `frontend/src/lib/api.ts`, which auto-attaches the bearer token, retries once on 401 by POSTing `/api/auth/refresh` with `refresh_token`, and hard-redirects to `/login` on refresh failure. Also handles 204s, JSON error unwrapping (`error.message`/`detail`/`message`), and `upload` for `FormData` (empty content-type so the browser sets the multipart boundary). `frontend/src/lib/org-admin.ts` exposes `isOrgAdmin`/`useIsOrgAdmin` for admin-gated views (e.g. DB browser).

Files: `frontend/src/stores/auth.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/org-admin.ts`

**Access-control panel suite (policies, role mapping, field matrix, record scope, state machine)** — 🆕 NEW

RulesPanel now exposes a dedicated access-control surface: AppAccessPolicies (top-level per-role policies), AppRoleMapping (org role → app role), FieldAccessMatrix (per-entity per-field per-role read/write/hidden matrix), RecordScopeEditor (row-level scope conditions), AccessControlRuleForm + AccessSubPanel wrappers. Plus StateMachineEditor (React-Flow state graph for entity lifecycles) and RuleCrossReferences (impact map from rules to entities/pages). This is the primary RBAC authoring UI called out by the Actors/RBAC slices.

Files: `frontend/src/components/rules/AppAccessPolicies.tsx`, `frontend/src/components/rules/AppRoleMapping.tsx`, `frontend/src/components/rules/FieldAccessMatrix.tsx`, `frontend/src/components/rules/RecordScopeEditor.tsx`

**Auth + auth-guard + dev-only playgrounds** — ➕ EXTENDS

Frontend auth lives in the (auth) route group with login/signup pages and a shared layout; auth-guard.tsx wraps protected routes. A (dev-only) group hosts component-playground and progress-preview for internal iteration on library components and the generation ring — not shipped to end users.

Files: `frontend/src/app/(auth)/login/page.tsx`, `frontend/src/app/(auth)/signup/page.tsx`, `frontend/src/app/(auth)/layout.tsx`, `frontend/src/components/auth-guard.tsx`

**Platform authentication — JWT with refresh rotation + org membership** — 🆕 NEW

Platform users (developers of the tool) live in platform_users (models/auth.py — email/name/password_hash/auth_provider/external_id/avatar_url). backend/routers/auth.py exposes POST /api/auth/{signup,login,refresh,logout} + GET /api/auth/me. Passwords are bcrypt-hashed with strength validation; login checks a lockout counter and clears it on success. Access + refresh tokens are issued via create_access_token/create_refresh_token; /refresh rotates by blacklisting the old refresh token. /me eagerly loads accepted OrgMember rows and returns an orgs array (org_id/slug/role) so the shell can pick a workspace.

Files: `backend/routers/auth.py`, `backend/models/auth.py`, `backend/services/auth_secret.py`, `backend/services/auth_email_ci.py`

**Generated-app authentication — NextAuth CredentialsProvider + middleware + actor onboarding** — 🆕 NEW

Generated apps ship a NextAuth (JWT session strategy) setup with a single CredentialsProvider that verifies bcrypt-hashed passwords against the reserved users table; role is copied into the JWT + session as role. A signup POST route at /api/auth/signup creates users (adapting to either name or firstName/lastName column shapes). middleware.ts wraps every non-auth, non-static, non-editor route with withAuth and redirects unauthenticated requests to /login. Login/signup pages are shipped by the template but the SCHEMAS for them are emitted by auth_page_schema when needed. actor_onboarding_expand.py derives per-actor onboarding surfaces: self_signup reuses the public signup page, invited_by adds a role-scoped list + /new invite form and an Invite<Actor> workflow, and platform_org adds a list + /link form. NEXTAUTH_SECRET defaults to dev-secret in code and is set to a stronger value at emit time; there is no OAuth/SSO in generated apps.

Files: `backend/templates/app-foundation/src/auth.ts`, `backend/templates/app-foundation/src/app/api/auth/[...nextauth]/route.ts`, `backend/templates/app-foundation/src/app/api/auth/signup/route.ts`, `backend/templates/app-foundation/src/app/login/page.tsx`


### 27.19 Updates to §19 Deployment & Export

**dev-only route group + null-loader prod exclusion** — 🆕 NEW

Editor UI and its APIs live under Next.js route group `(dev-only)/` (editor/[...slug], api/editor/{load,save,pages,suggest,theme}, api/figma/extract). next.config.ts installs a webpack rule that replaces any module whose path contains /(dev-only)/ with null-loader when NODE_ENV=production, so those routes and their imports are fully tree-shaken from prod bundles. This — not Next's experimental.outputFileTracingExcludes — is the load-bearing exclusion mechanism; the middleware matcher additionally leaves those paths unauthenticated so the editor works without a login.

Files: `backend/templates/app-foundation/next.config.ts`, `backend/templates/app-foundation/src/app/(dev-only)/editor/[...slug]/page.tsx`, `backend/templates/app-foundation/src/app/(dev-only)/api/editor/save/route.ts`

**standalone-app package.json.tmpl vendoring contract** — ➕ EXTENDS

Every generated app depends on file:./vendor/@tentoroforge/{engine,library,renderer,schema} — the pipeline copies the four package dists into vendor/ so the app builds without network install. The template also pins runtime deps needed for the shipped seams: next-auth+bcryptjs (auth), drizzle-orm+postgres+drizzle-kit+tsx (DB/migrations), @tanstack/react-query, sonner, pdf-lib, @anthropic-ai/sdk (AI nodes), and the Radix primitives the library uses. Placeholder `<<project_short_id>>` becomes the package name at emit time.

Files: `backend/templates/standalone-app/package.json.tmpl`

**App-emitter with runtime vendoring + staleness rebuild** — ➕ EXTENDS

app_emitter.py copies the standalone-app template into each project's output_dir and vendors the engine/library/renderer/schema packages. _ensure_package_built rebuilds a package's dist/ when the newest src mtime beats the newest dist mtime (dist is gitignored — without this, a source fix without a manual rebuild would silently ship stale code in every new app); falls back to the existing dist if the build fails so a rebuild issue never blocks a gen. Idempotent — re-emitting overwrites templated files but never touches LLM-generated src/schemas, src/contracts, or src/app/globals.css.

Files: `backend/services/app_emitter.py`, `backend/services/app_emitter_constants.py`

**Local self-contained deployment — emit + vendor + docker-compose + start.sh** — 🆕 NEW

There is no cloud deploy target — 'deployment' means producing a runnable local Next.js project. app_emitter.py copies the standalone-app template and vendors the four engine-stack packages (engine/library/renderer/schema) into vendor/@tentoroforge/<pkg> with a build-if-stale check, so the app installs offline via file:./vendor/... runtime_injector.py drops in the runtime files, the Data Engine, the workflows engine, and generates start.sh — a bash script that derives DB_NAME from .env.local, picks a free host port for Postgres (5432→5600), exports DATABASE_URL, boots the template's docker-compose Postgres, runs drizzle-kit push --force (FATAL on failure), seeds, and then next dev. start.sh --seed-only is used by the chat 'Seed demo data' action. preview_manager.py wraps the same lifecycle from the platform side, allocating ports in the 3200–3299 (app) and 5500–5599 (db) ranges with health-check + restart supervision.

Files: `backend/services/app_emitter.py`, `backend/services/runtime_injector.py`, `backend/templates/app-foundation/docker-compose.yml`, `backend/templates/standalone-app/package.json.tmpl`

**Portal export — Zip + optional Dockerfile / docker-compose** — 🆕 NEW

POST /api/projects/{project_id}/export in backend/routers/portal.py packages a generated project as a zip. format=dockerfile returns a generated multi-stage Dockerfile (node:20-alpine base, pnpm+corepack build, runner stage) and optionally a docker-compose.yml with Postgres. The README embedded in the zip advertises docker compose up -d or pnpm build && pnpm start as the two deploy paths — there is no Kubernetes, no cloud provider integration, no CI wiring emitted (K8s work remains pending in docs/superpowers).

Files: `backend/routers/portal.py`


### 27.20 Updates to §20 AI Agent Builder

**Fix-Assistant A/B summary + preview endpoints** — 🆕 NEW

GET /api/projects/{id}/fix/ab-summary reads recent assistant Conversation rows that carry a fix_ab metadata dict and returns services.fix_ab_log.summarize() — proposal/approve/resolve rates and avg iterations/elapsed comparing the ReAct agent vs single_shot Fix-Assistant. Complements the [APPLY_FIX] chip handled in /chat which loads the pending diagnosis, previews changes via _preview_fix_changes, and applies through deterministic seams.

Files: `backend/routers/generate.py`, `backend/services/fix_ab_log.py`

**Instruction-builder libs (visual editors → NL prompts)** — ➕ EXTENDS

Every visual editor round-trips through a natural-language instruction builder that feeds `code_editor`. `frontend/src/lib/instruction-builder.ts` (`buildDataInstruction`) covers data-model actions (add/delete model, add/edit/delete field with `SmartFieldConfig` sub-language for ai_classify/summarize/extract/translate, add_relation, enums, indexes). Parallel builders exist for agents (`agent-instruction-builder.ts`), rules (`rule-instruction-builder.ts`), workflows (`workflow-instruction-builder.ts`), UI (`ui-instruction-builder.ts`) and RBAC (`rbac-instruction-builder.ts`). This is how the visual editors talk to the backend refine pipeline — worth calling out that visual mutations don't apply directly, they synthesize prompts for the LLM.

Files: `frontend/src/lib/instruction-builder.ts`, `frontend/src/lib/agent-instruction-builder.ts`, `frontend/src/lib/rule-instruction-builder.ts`, `frontend/src/lib/workflow-instruction-builder.ts`

**AI-features / data-model / agent-builder / rules stores** — 🆕 NEW

Smaller domain stores round out the state layer: `useDataModelStore` (schema editor ERD), `useAgentBuilderStore` (AI agent visual builder — nodes/edges/system prompt), `useAiFeaturesStore` (SmartField configuration), `useRulesStore` (rules list with type/model filters). All follow the same Zustand pattern: `set*` setters + `reset()`, no persistence, coordinated with the backend via the shared `api` client and the instruction-builder libs.

Files: `frontend/src/stores/ai-features.ts`, `frontend/src/stores/data-model.ts`, `frontend/src/stores/agent-builder.ts`, `frontend/src/stores/rules.ts`

**Agent builder panel** — 🆕 NEW

AgentBuilderPanel is the 'agents' workspace tab — a node-based canvas (AgentCanvas + AgentNodePalette + AgentNodeProperties) with an AgentTemplateSelector and an inline AgentTestConsole for iterating on user-authored AI agents inside the generated app. Complements the AIFeaturesPanel (§21) which configures classify/extract/generate/decide capabilities per entity.

Files: `frontend/src/components/agent-builder/AgentBuilderPanel.tsx`, `frontend/src/components/agent-builder/AgentCanvas.tsx`, `frontend/src/components/agent-builder/AgentNodePalette.tsx`, `frontend/src/components/agent-builder/AgentNodeProperties.tsx`


### 27.21 Updates to §21 AI-Powered Application Features

**Real AI action handlers (workflow runtime)** — ⚠️ CORRECTS

`registerAIActions` in `backend/templates/runtime/workflows/ai.ts` registers real Claude-backed handlers for `ai_generate`, `ai_classify`, `ai_extract`, and `ai_decide` (no longer stubs). Config keys are canonicalised (`aiModel`, `aiPrompt`, `aiInput`, `aiLabels`, `aiExtractFields`, `aiOptions`, `aiRules` …) and match the editor/generator contract. `ai_extract` accepts file descriptors — a `setFileLoader` seam lets `storage.ts` resolve a stored file id into `{base64, mediaType}` that becomes a Claude document/image block, so PDFs and images are extracted natively. Missing `ANTHROPIC_API_KEY` falls back to a deterministic mock so dev boots green.

Files: `backend/templates/runtime/workflows/ai.ts`, `backend/templates/runtime/workflows/index.ts`, `backend/templates/runtime/storage.ts`

**Fix-proposal / self-heal message types on chat store** — 🆕 NEW

chat.ts carries the conversational fix-assistant + self-heal loop end-to-end on the frontend. `fix_proposal` SSE arrives with `{diagnosis, changes, applyToken}` and is appended as a chat message with `metadata.fixProposal` so `FixProposalCard` renders it; `fix_applied` updates the most recent proposal (`metadata.fixApplied=true`) and adds a result message with `metadata.fixResult` (resolved / remaining). `smith_needs_user` produces a `NeedsUserCard` (answer + options + diff_summary + touched_paths); `smith_error`, `answer`, `question`, `handoff` all render as distinct assistant intents. `apply_start`/`apply_end` toggle the streaming status. Together these implement the in-app fix-assistant loop the blueprint describes only abstractly.

Files: `frontend/src/stores/chat.ts`


### 27.22 Updates to §22 Organization & Multi-Tenancy

**Portal aggregation + monitoring endpoints** — 🆕 NEW

backend/routers/portal.py provides the org-portal API: /api/orgs/{id}/portal/dashboard, /portal/apps, /portal/tasks, /portal/activity, /portal/stats. All gated by _require_org_member (accepted OrgMember). Per-project monitoring lives here too: GET /api/projects/{id}/monitoring/costs (aggregates AgentJob.result cost_usd + duration into a CostEntry list) and /monitoring/errors (ErrorLogEntry list). POST /api/projects/{id}/export streams a zip of the generated app.

Files: `backend/routers/portal.py`

**Org RBAC surface (people/departments/teams/roles/groups)** — ➕ EXTENDS

backend/routers/orgs.py owns a large RBAC surface: OrgPerson/Department/Team/OrgRole/OrgGroup CRUD, role assign/unassign on person, group members bulk update, invite create/accept, and CSV import. Access is gated by _require_org_member with an owner>admin>member hierarchy — the DEFAULT_ROLES seed (Admin/Manager/Member) is created on org creation. Discovery + Portal both reuse the same OrgMember-accepted check pattern.

Files: `backend/routers/orgs.py`

**Tenancy-scoped create** — 🆕 NEW

`dataEngine.create` in `backend/templates/runtime/data-engine.ts` server-fills a NOT NULL workspace/tenant FK from the acting user, so a form doesn't have to collect it. It looks at `workspaceId`/`tenantId`/`orgId`/`organizationId` columns; if `ctx.user.workspaceId` is absent it reads `users.workspaceId`, and as a last resort picks the single row from `workspaces`/`tenants`/`organizations`. Combined with the FK-role authority this guarantees a create satisfies tenancy NOT NULL without the LLM having to model the tenancy column at all.

Files: `backend/templates/runtime/data-engine.ts`

**Portal surfaces (dashboard, task inbox, activity feed, search)** — ✓ CONFIRMS

The org portal at /org/[orgId]/portal mounts PortalDashboard, TaskInbox (human-task list mirroring SLICE-E's workflow_tasks), ActivityFeed and PortalSearch — a non-project surface for org members to see and act on tasks/events across all projects in the org.

Files: `frontend/src/components/portal/PortalDashboard.tsx`, `frontend/src/components/portal/TaskInbox.tsx`, `frontend/src/components/portal/ActivityFeed.tsx`, `frontend/src/components/portal/PortalSearch.tsx`

**Org-level admin routes (people, teams, roles, departments, groups, org-chart, discover, import, templates, settings)** — ✓ CONFIRMS

A full org admin section lives under app/org/[orgId]: people, teams, roles, departments, groups, org-chart, plus org-scoped discover, import (bulk data import), templates gallery, and settings. Layout provides shared org chrome. These sit outside a project and drive the multi-tenant/org data model referenced by AppRoleMapping and RBAC.

Files: `frontend/src/app/org/[orgId]/people/page.tsx`, `frontend/src/app/org/[orgId]/teams/page.tsx`, `frontend/src/app/org/[orgId]/roles/page.tsx`, `frontend/src/app/org/[orgId]/departments/page.tsx`

**Platform org model — Organization, OrgMember, People/Departments/Teams/Roles/Groups + invites** — ✓ CONFIRMS

The platform is multi-tenant: every top-level artifact hangs off Organization (models/org.py). OrgMember links platform_users to organizations with a role enum {owner, admin, member} and invite_status {pending, accepted, declined, expired}. Around that sit OrgPerson (end-users referenced by generated apps — org-scoped by unique (org_id, email)), Department (self-parent-referencing, head_person_id), Team (department-scoped, lead_person_id), OrgRole (per-org RBAC with a JSONB permissions bag), OrgPersonRole (person↔role), and OrgGroup/OrgGroupMember. backend/routers/orgs.py exposes ~35 endpoints under /api/orgs/{org_id}/… for CRUD on all of the above plus /invite, /invite/{id}/accept, /people/import, /org-chart, and a portal dashboard/apps/tasks/activity/stats family at /api/orgs/{org_id}/portal/*. All endpoints go through _require_org_member for authorization.

Files: `backend/models/org.py`, `backend/routers/orgs.py`, `backend/routers/portal.py`

**Multi-tenancy in generated apps — currently absent** — 🆕 NEW

Multi-tenancy is a PLATFORM property, not a generated-app property. Each generated app has its own Postgres database and its own users table; the Data Engine catch-all route (backend/templates/data-api-route.ts) does not filter by org_id or tenant, and the NextAuth session carries user id + role but no organization context. The generated users schema baked into schema_builder.py's _AUTH_USERS_BASE has no org_id column. Tenanting a generated app to the emitting organization is future work — today the emitted app is single-tenant and org-agnostic even though the platform launching it is fully multi-tenant.

Files: `backend/templates/data-api-route.ts`, `backend/templates/app-foundation/src/auth.ts`, `backend/services/schema_builder.py`


### 27.23 Updates to §23 Discovery & Templates

**Discovery agent — 4 discovery types** — ➕ EXTENDS

agents/discovery.py handles vague-idea intake with an explicit taxonomy of four discovery types — PROBLEM_FIRST, REFERENCE_BASED, DEPARTMENT_NEED, VAGUE_IDEA — each with its own multi-turn question set. It is org-aware (consumes departments/teams/roles/existing-apps from injected context) and produces a structured brief that hands off directly to the Planner rather than living as free-form chat.

Files: `backend/agents/discovery.py`

**Discovery-first pre-planning flow on /generate + /chat** — ⚠️ CORRECTS

POST /api/projects/{id}/generate no longer starts code generation when there's no plan — it runs agents.domain_agent.run_domain_discovery, persists a pending dossier (services.blueprint_pipeline_hooks.record_discovery), and returns `discovery_approval_needed` with an editable-fields list. The user then sends `[APPROVE_DISCOVERY] {...edits}` on POST /api/projects/{id}/chat which triggers planning, and `[APPROVE_PLAN]` which dispatches generation. Approval signals, [APPLY_FIX], and [SELECT_TEMPLATE:<id>] are all recognised chip protocols short-circuited before intent classification. Figma flow bypasses discovery — the frames drive the plan.

Files: `backend/routers/generate.py`

**Multi-turn discovery-session endpoints (org-scoped)** — ➕ EXTENDS

backend/routers/discovery.py adds a full org-scoped session API separate from the /generate discovery path: POST /api/orgs/{org_id}/discovery/start creates a DiscoverySession, POST .../message runs a discovery agent turn (SSE), .../preview-brief extracts the ```discovery-brief JSON``` block, .../convert creates a Project seeded with the brief, and GET returns list/detail. Org context (name, departments, people count, existing projects) is injected into the agent prompt. All endpoints require accepted OrgMember membership.

Files: `backend/routers/discovery.py`, `backend/models/discovery.py`

**Template gallery + new-app + version sidebar + project delete/export** — ➕ EXTENDS

Template selection is a two-step flow: TemplateGallery renders TemplateCards which open TemplateDetailModal for preview + [SELECT_TEMPLATE:id] chat signal; NewAppDialog drives project creation. Per project, the workspace also mounts VersionSidebar (history/rollback), ExportDialog (deploy/export), and DeleteProjectDialog (destructive confirm).

Files: `frontend/src/components/templates/TemplateCard.tsx`, `frontend/src/components/templates/TemplateDetailModal.tsx`, `frontend/src/components/generation/TemplateGallery.tsx`, `frontend/src/components/projects/NewAppDialog.tsx`

**Discovery StructuredBriefPreview + PlanCard journeys** — 🆕 NEW

The Journeys+StructuredBrief pipeline (JT-T1..T11) is surfaced by StructuredBriefPreview (renders the parsed brief), by DiscoveryCard (dossier edit + [APPROVE_DISCOVERY] with optional inline overrides), and by PlanCard's journeys section (actors, actor-journeys, per-step page references). The 'authoritative inputs' contract from JT-T2 is what these cards visualize.

Files: `frontend/src/components/discovery/StructuredBriefPreview.tsx`, `frontend/src/components/chat/DiscoveryCard.tsx`, `frontend/src/components/chat/PlanCard.tsx`


### 27.24 Updates to §24 Implementation Phases

**Fidelity + cost admin, monitoring panel, achievement banner** — 🆕 NEW

Admin observability: /admin/fidelity-cost renders global fidelity vs LLM-cost. Per project, CostTrackingPanel (the 'monitoring' tab) charts spend by phase/agent. FidelityScoreBadge and PageScoreBadge annotate the schema editor with per-page scores. On successful generation, AchievementBanner fires confetti with CompletionStats (duration, tokens, cost, iterations).

Files: `frontend/src/app/admin/fidelity-cost/page.tsx`, `frontend/src/components/monitoring/CostTrackingPanel.tsx`, `frontend/src/components/schema-editor/FidelityScoreBadge.tsx`, `frontend/src/components/schema-editor/PageScoreBadge.tsx`


### 27.25 Updates to §25 Virtual Office

**Per-project real-time SSE event bus** — 🆕 NEW

A persistent per-project SSE stream lives at GET /api/projects/{project_id}/events (backend/routers/project_events.py) backed by the in-process pub/sub in services.project_event_bus. The endpoint sends a `ready` event on connect, `ping` every 25s to survive proxy idle-cut, and forwards every event published for that project_id — currently `self_heal_message` and `chat_message`, and any future push event. Each subscriber gets its own queue via a subscribe() context; client disconnect cancels the loop and cleans up. Frontend opens exactly one EventSource per project view.

Files: `backend/routers/project_events.py`, `backend/services/project_event_bus.py`

**Runtime-exception ingest + self-heal trigger** — 🆕 NEW

Generated apps POST every caught runtime error to POST /api/projects/{project_id}/runtime-exceptions (backend/routers/runtime_exceptions.py). The endpoint is intentionally unauthenticated; it dedupes by SHA256 of (kind, first-line message, source_file, source_line, workflow_id, node_id), upserts a RuntimeException row (occurrence_count/last_seen_at on repeats), and on FIRST occurrence schedules services.self_healing.invoke_smith_on_exception as a background task — gated by FORGE_SELF_HEAL. Repeats of an `unresolvable` reset to `open` so the next heal window can retry; `resolved` is sticky. GET list/detail endpoints back the monitoring UI.

Files: `backend/routers/runtime_exceptions.py`, `backend/services/self_healing.py`, `backend/models/runtime_exception.py`

**Chat → Virtual Office bridge** — 🆕 NEW

chat.ts explicitly bridges SSE traffic to the Virtual Office store. `startStreaming` calls `useOfficeStore.getState().reset()`+`initialize()`; phase transitions emit `phase_complete`/`phase_start` office events via `QUEST_TO_OFFICE_PHASE`; log/message lines starting with `[Tag]` are routed to agent-ids via `LOG_TAG_TO_AGENT` (Contract→contract_writer, Schema→schema_designer, etc.) and fire `agent_start` / `agent_status`; billing errors (detected by `isBudgetError`) fire a `credits_exhausted` `triggerOfficeProtest`. Raw `office` SSE events are forwarded directly. This is the sole coupling between the generation pipeline and the office visualization.

Files: `frontend/src/stores/chat.ts`

**Virtual office live dashboard (HUD, minimap, agent panel, speed controls)** — ➕ EXTENDS

Virtual office is a canvas-rendered top-down office scene (OfficeRenderer + OFFICE_LAYOUT) whose state is fed by OfficeStateManager (zustand) from backend SSE OfficeEvent[]. Sprites are streamed via SpriteLoader/preloadAll from a manifest; AgentCharacter animates positions with a Pathfinder. A HUD overlay (PipelineProgress, MiniMap, AgentPanel, AgentTooltip, SpeedControls) sits above the canvas. VirtualOffice accepts events + isGenerating and is embedded as the 'office' workspace tab.

Files: `frontend/src/components/virtual-office/VirtualOffice.tsx`, `frontend/src/components/virtual-office/OfficeRenderer.ts`, `frontend/src/components/virtual-office/OfficeStateManager.ts`, `frontend/src/components/virtual-office/Pathfinder.ts`


### 27.26 Updates to §26 Domain Context System

**Domain Agent replaces curated knowledge folder** — ⚠️ CORRECTS

agents/domain_agent.py has replaced the curated backend/knowledge/<domain>/ folder as the source of the domain profile. Given the project description (and optional plan) it produces a structured dossier — per-agent persona blocks, design patterns with evidence citations, visual language tendencies, entity suggestions, compliance notes, common pitfalls — which services/domain_context.build_domain_profile renders as the [DOMAIN PROFILE] block injected into each downstream agent's system prompt. Unlike other agents it uses the direct anthropic.AsyncAnthropic SDK because it attaches the server-side web_search tool for grounded research; output is validated by pydantic models before use.

Files: `backend/agents/domain_agent.py`, `backend/services/domain_context.py`


---

*Audit synthesized from 10 subagent scans across 2 workflow runs plus one
deterministic reconciliation pass on 2026-07-21 (`wf_b2f53118-bbe` +
`wf_ca04a15d-d9d`, ~1.06M subagent tokens). 191 distinct findings
across §1–§26. Drift breakdown: {'partial': 32, 'missing': 129, 'stale': 22, 'accurate': 8}. Reconciliation promoted
7 findings from 🆕 NEW → ✓ CONFIRMS after checking each feature's
name-phrase + distinctive-token co-occurrence against the original section text.*

---

## 28. Business Rules Editor & Data-Model Binding (added 2026-06-19)

A no-code **Business Rules editor** in the project workspace (sidebar "Model" group, ⚖️ icon; tab id `business-rules` in `frontend/src/app/org/[orgId]/projects/[projectId]/page.tsx`). It follows the Power-Apps model (declarative *condition → action*) with a Drools/DMN-style decision-table mode, and is bound to the project's data model. Relates to §14 (Rules Engine & Decision Builder). Full design + roadmap: `docs/superpowers/plans/2026-06-18-business-rules-engine-and-visual-editor.md`.

### 28.1 Two editors
- **Condition → Action** (`components/business-rules/RuleEditor.tsx`): reuses the recursive `components/rules/ConditionBuilder` for the IF; a new `ActionEditor` for THEN/ELSE actions; live **Playground** (`RulePlayground`) that compiles the condition to FEEL and evaluates a sample record via `@/lib/feel-lite`. Action vocabulary (`types/business-rules.ts`): set_field, set_default, clear_field, show_error (reject), set_visibility, set_required, set_readonly, recommendation (form-only); trigger_workflow, send_notification (extensions). Scope = entity | form | server; salience (priority); active toggle.
- **Decision table** (`DecisionTableMode.tsx`): reuses `components/decision/DecisionTableEditor` (DMN: input/output columns, rule rows, 6 hit policies U/F/A/P/C/R, FEEL cells).

### 28.2 Persistence (no new model / no migration)
Rules persist as **`ProjectRule`** rows via the existing `/api/projects/{id}/rules` CRUD, with `rule_type` ∈ {`condition_action`,`decision_table`} (added to `valid_types` in `routers/rules.py`) and `config.source="manual"`. `config` for `condition_action` = `{ when (ConditionExpression tree), whenFeel (compiled FEEL), then[], otherwise[], scope, salience }`; for `decision_table` = `{ table: DecisionTableDefinition }`. The classic Rules tab filters these two types out. **Regeneration safety:** `agents/rules_agent._sync_rules_to_db` preserves `config.source == "manual"` rows (deletes only AI rows, via `IS DISTINCT FROM`), so a re-generation never wipes editor-authored rules.

### 28.3 Data-model binding
Canonical source = `useProjectDataModel(projectId)` (`frontend/src/hooks/`), reading the SAME `GET /api/projects/{id}/app-model` the Data Model editor + ERD use → models, typed columns (`ColumnModel`), enums. `lib/field-types.ts` maps Drizzle types → categories → valid operators + value control. Effects:
- Condition rows (type-aware, additive enhancement to the shared `ConditionRow`/`ConditionBuilder` via an optional `fieldMeta` prop — the classic Rules tab passes none and is unchanged): field picker with type chips, operators filtered by field type, typed value controls (enum dropdown / boolean / number / date / list).
- FEEL compiler (`lib/condition-to-feel.ts`, `conditionToFeel(expr, fieldTypes?)`): string/enum/date values quoted, number/boolean bare (the same string runs in the playground and the future runtime). Verified to parse + evaluate on both the frontend and backend `feel_lite`.
- Action editor: typed field pickers; enum fields get a value dropdown on set_field/set_default.
- Decision table: receives the real `appModel` (cell autocomplete on real `entity.field`) + a "bind input/output column to a field" affordance (sets column name + type from the model). When no data model exists, field pickers fall back to free-text with a clear hint.

### 28.4 Status & next phase
**DONE (2026-06-19):** both editors, data-model binding, type-awareness, persistence, playground — built, adversarially reviewed (two passes, all high/medium findings fixed), tsc-clean, route-compiling, API CRUD verified. **NOT YET (next phase, plan Part D):** request-time *execution* in generated apps — a rule **action dispatcher** + `runtime_injector` emission so rules actually fire on create/update. Authoring is complete; runtime enforcement is the next build.

---

## 29. Pre-approval re-plan gate — chat returns the whole updated plan (added 2026-06-19)

Before any code exists, a user message that changes the plan now **re-runs the planner and re-presents the COMPLETE updated plan** for confirmation, instead of being mis-routed to the code refiner. Lives in `routers/generate.py::chat_with_project`. (Status: implemented and **uncommitted on `forge-v3`** — `git status` shows `M backend/routers/generate.py`; senior decides commit/push.) Relates to §6.2 (SSE protocol, `plan_ready` event).

### 29.1 Routing
When `not project_has_code`, the build/modify intents `_planning_intents = (PLAN, REFINE, SCAFFOLD, AGENT, DISCOVER, APPROVE)` enter the **planning branch** and re-run `agents.planner.run_planner` with the conversation history (which carries the prior plan + the user's new change). The planner emits a fresh ```plan-json``` block; `_extract_plan_json` parses the FULL plan, register classification is injected, and it is re-emitted via the `plan_ready` SSE event and persisted in the assistant message's `metadata_["plan"]`. Status SSE reads **"Updating your plan…"** when a plan is already pending (`_replanning = has_pending_plan`) vs "Planning your application…" on the first pass.

### 29.2 Approval is explicit
Code generation fires ONLY on an explicit approval: the deterministic `[APPROVE_PLAN]` sentinel (the "Begin Quest" button), or an `APPROVE` intent when a plan is pending (`has_pending_approval`). `APPROVE` with no saved plan re-routes to the planner to (re)produce plan-json.

### 29.3 Frontend
`useSSE` → `stores/chat.ts::handleSSEEvent` `case "plan_ready"` swaps the last assistant message to `message_type: "plan"` with `metadata.plan` and sets `pendingPlan`. `components/chat/ChatMessage.tsx` renders `components/chat/PlanCard` (full plan: data models, pages, workflows, access-control) with **Approve** (`onSend("[APPROVE_PLAN]")`) and **Adjust strategy** buttons.

### 29.4 The bug it replaced
Previously, before any code existed, a change request classified `REFINE` fell through to the code refiner → a meaningless "Changes applied successfully" with 0 files; and `PLAN`/`SCAFFOLD`/`DISCOVER` on a pending plan were wrongly auto-approved. Both are fixed: every pre-code build/modify intent now re-plans and re-presents the whole plan; only explicit approval generates code.

## 30. Visual-editor hardening — drag-drop validation, component sizing, on-canvas CRUD (added 2026-07-22, branch `component-fixes`)

Regression-validated the live visual editor (`VisualEditorWorkspace` — the `/editor/[projectId]` + workspace "editor" tab surface, NOT the older `@tentoroforge/editor` at `/editor/[id]/[...slug]`) across **all 106 registry components** and the four inspector tabs, then added component sizing + on-canvas add/remove/update affordances. All changes are uncommitted on `component-fixes`; senior decides push to `forge-v3-smith-orchestrator-v2`.

### 30.1 Regression suite (new)
`frontend/src/__tests__/editor-validation.test.tsx` drives the REAL code paths (imports `validateDrop`/`buildDroppedNode` from `useDrop`, dispatches through the real `editor-store`, renders via the real `@tentoroforge/engine`). It asserts: every one of the 106 components builds a node, passes `validateDrop` into a container, and commits (no `validateForCommit` reject); 102 render with a selectable `data-node-id` (the 4 that don't — `Repeat`/`Conditional`/`DataBoundary`/`Slot` — are data-driven control-flow that correctly render only once bound); reorder/move; duplicate (leaf + container); delete + delete-root-guard; and each of the 4 tabs' write actions (`updateProp`/`updateStyle`/`bindProp`/`updateToken`) with undo. Plus a sizing block (raw width/height render on structural + library nodes).

### 30.2 Four drag-drop / CRUD bugs fixed
- **`TableSortable` unregistered** — it was in `@forge/registry` (palette) + had a library component + prop-remap, but `buildDefaultRegistry` never `reg(...)`'d it → dropped as an unselectable `⚠ unknown` orphan. Registered it with a new `TableSortableProps` (tolerant, preserves `onSort`; `Table.schema.ts`).
- **`duplicateNode` container bug** — `apply.ts` re-id'd only the top node → duplicating any container produced duplicate child ids → `validateForCommit` rejected → Cmd+D silently no-op. Now re-ids the whole subtree (children + slots).
- **Delete-root crash** — `applyAction` throws on `removeNode`/`moveNode` of the root; `editor-store.dispatch` had no try/catch → uncaught editor crash. Dispatch now catches and surfaces `lastError`.
- **Dialog `['*']` wildcard** — `validateDrop`/`accepts` did a literal `accepts.includes(childType)`, so `['*'].includes('Button')` was false → nothing could drop/reorder into a Dialog. Wildcard now honored in `useDrop` + `useReorder`.

### 30.3 Auth hydration race (fixed)
`AuthGuard` redirected to `/login` on `!isLoading && !token` before the parent `AuthHydrator` effect ran `hydrate()` → every full page load / deep link bounced an authed user out. Added a `hydrated` flag to `stores/auth`; `AuthGuard` now waits for hydration before redirecting (shows the spinner meanwhile). `isLoading`/login-page UX untouched.

### 30.4 Component sizing (§8 / §13 extension)
Sizing rides the existing `node.style` StyleSlot channel via `updateStyle` (already undo-aware — no patches change). Added `width/height/minWidth/maxWidth/minHeight/maxHeight` to the `StyleSlot` Zod (`schema/style-slot.ts`) + the strict `StyleProps` (`schema/tokens.ts`), emitted **raw** (never token-wrapped) by `applyStyleSlot` (`renderer/runtime/style-slot.ts`, which wins over `tokens.resolveStyle` by spread order for structural nodes) and by the library `resolveStyle` (`library/style/resolveStyle.ts`, for library components). UI: a **Size** section in `StylePanel` (freeform px/%/rem/auto inputs, commit-on-blur = one undo step) that works for every component; plus the previously-decorative 8 `SelectionOverlay` handles are now **drag-to-resize** (derives canvas zoom from `rect.width/offsetWidth`, live preview, commits `updateStyle` on release; single-select only).

### 30.5 On-canvas add / remove / update
Add = palette drop (all 106, verified). Update = the 4 inspector tabs. Remove/duplicate were keyboard-only (`keymap.ts` Delete/Cmd+D, ignored while an input is focused) → added a `SelectionOverlay` action bar (duplicate + delete buttons, single non-root selection) dispatching the same reducer actions. `zero regressions`: frontend 177, patches 48, schema 204 green; the pre-existing library (3) + renderer (29) failures are branch debt (proven independent of these edits by stash-diff).

### 30.6 New Page → Layout → Form scaffolding
`frontend/src/lib/page-scaffold.ts` — a pure `scaffoldPage(config)` that emits a valid Page: `Container → Stack → [Heading?, Card? → Form]`. The Form uses DECLARATIVE mode (`props.fields`, matching the strict discriminated union in `library/components/Form/Form.schema.ts`) so all 8 field kinds (text/email/number/textarea/select/checkbox/date/switch) render with zero invalid-props. `NewPageDialog` (title → deduped kebab route, layout preset, dynamic field builder) → `dispatch(addPage)` → `flushPersister()` → invalidate the nav-flow query → activate. Trigger lives in `PagePicker`. 13 unit tests + verified end-to-end in-browser.

### 30.7 Editor hardening — adversarial audit + fixes (2026-07-22)
A 7-dimension adversarial audit (each finding independently verified) surfaced 46 confirmed defects/UX-gaps. **≈33 fixed + regression-locked** (pushed on `component-fixes`; zero regressions — frontend 199, patches 48, schema 204 green), highest-severity first:
- **Persistence/data-loss:** `saveFile` now THROWS on non-2xx (was `console.warn` → `markClean` → silent loss with a false "Saved"); `flush()` chains onto an in-flight background save (no clobber); undo/redo set `isDirty` (so an undo after autosave re-persists); a `beforeunload`/`pagehide` guard + flush-on-unmount; save failures surface via a persistent `saveError` banner; the persister only re-arms on an actual `artifacts` reference change (no debounce starvation).
- **CRUD correctness:** a `dispatchBatch` transaction makes multi-delete/duplicate + corner-resize ONE undo step; `keymap` prunes descendants (no "unknown node" error on parent+child delete); `undo/redo` gained the same try/catch as `dispatch`; the reducer's `findNode` now returns the real containing array so slot-resident remove/move/duplicate no longer corrupt a sibling (+ `insertNode` carries `slotKey`); on-canvas delete selects the parent.
- **Drag-drop:** the drop indicator now resolves + highlights the REAL accepting ancestor (via a shared `lib/palette-drag` ref, since `dataTransfer` is unreadable during `dragover`) instead of the innermost leaf the drop would skip; `maxChildren`/`rejects`/`single` are enforced on both drop and reorder (Split/Sidebar can no longer overfill); drop ids are collision-proof; a rejected drop sets a user-visible message + a no-drop cursor.
- **Sizing/render:** sized library components (Chart/DataGrid/…) now honor `node.style` sizing via a real box wrapper in `LibraryDispatcher` (only when sized — zero change for existing schemas); library/leaf nodes are draggable (Canvas sets `draggable` on the resolved box, not the `display:contents` span); invalid/unknown-type placeholders carry `data-node-id` so the broken node is selectable/deletable; a 0×0 empty container stays selectable; the SelectionOverlay observes the resolved box so it tracks a library-node resize live.
- **Inspector/UX/a11y:** Bindings tab traverses slots (parity with Props/Style); Style & Bindings show a multi-select guard; Style tab has a "select a node" empty state; the generic-fallback prop editor preserves value types (no number→string coercion); palette icons fall back to each registry entry's own `icon` (was 53 generic squares); the phantom `home` tab is dropped on projects without a real home page; per-project UI prefs (device/zoom/rail-collapse) persist across reloads; page tabs are keyboard-operable (role=tab, arrow keys, aria-selected). Auth `AuthGuard` hydration-race fix (§30.3) lands the reload/deep-link bounce.

**Remaining (~13, tracked; none block correctness — every data-loss/corruption bug is fixed):** responsive drawer triggers <1280px (HIGH); TokenEditor commit-on-blur; breakpoint "inherits base" display; removePage orphaned-schema-file cleanup; positional palette drop + insertion line; representative sample data on dropped Table/Chart; palette click-to-add + keyboard; live px readout during drag-resize; resize-handle a11y (role/arrow-nudge); true fit-to-screen zoom; multi-select drag reorder; page rename/delete in the PagePicker; Size-input CSS-unit validation + min>max warning.

### 30.8 Generated-app routing + nav-visibility + workflow-picker fixes (2026-07-23)
Three serious defects surfaced by generating + running a real app (cat-feeding, `a23jul`/`g4e8ksop`), each root-caused across the pipeline (adversarial workflow) and fixed at the source so **no future app can regress**. Backend runs with `--reload`; generated apps are re-emitted from templates, so template + editor fixes propagate on the next generation.

- **Issue 1 — `/` → 404 (redirect to a dynamic route).** `app_emitter.py` wrote `DEFAULT_INITIAL = "/invite/[token]"` because its landing fallback picked the *first non-auth page* with no guard against dynamic `[param]` / `/new` / `/edit` / `shell:false` / auth routes. Extracted the logic into a pure `derive_root_redirect(nav)` + `_is_safe_landing(route,page)` predicate (module-level, unit-tested in `test_root_redirect.py`, 12 cases incl. the exact shipped bug). Candidate cascade: `/dashboard` → `post_login_redirect` → initialPage route → first static shell page → `/` (and when `/`, the emitter **unlinks** `page.tsx` so the `(dashboard)` group serves `/` without a self-loop). Per-role `initialFor` values are validated the same way. `/home` seeds fixed to `/`. (Also flagged, not yet changed: the same missing guard exists upstream in `nav_flow_from_plan/_from_schemas/_emitter` + `figma_mcp_pipeline`, and the post-gen `nav_route_reconcile_guard._fix_root_redirect` regex only matches a string-literal `redirect("…")`, never `redirect(route)`, so that safety net never fired.)
- **Issue 2 — editor-created pages orphaned from the app (no sidebar, don't render).** Three layers: (a) editor `addPage` (`packages/patches`) emitted `shell:false` → now `shell: action.shell ?? true` (+ `shell?` on the action type + the `removePage` inverse preserves it); (b) the generated sidebar read a **frozen `shell.json`** SideNav and ignored nav-flow — `(dashboard)/layout.tsx` `loadNavProps` now **merges nav-flow shell pages into the SideNav** (deduped by route across flat + grouped items, auth/param/`[`/`…/new` filtered; also fixes a latent bug where login/signup leaked into the fallback menu); (c) `(dashboard)/[entity]` `notFound()`'d any route missing from the static `registry.ts`, and `getSchema` **threw** for it — `renderSchemaPage` now falls back to reading `src/schemas/<route>.json` from disk (server-only, since `registry.ts` is client-imported by `AppNavigator`), and `[entity]` renders when the file exists. Net: any page added post-generation appears in the sidebar AND renders in-shell. (Pages & Nav "not connected" is cosmetic — the sidebar derives from nav-flow pages, not graph edges.)
- **Issue 3 — Form workflow picker "registry empty".** `GET /api/projects/{id}/registry/workflows` (`routers/ir.py`) read only `registry.json`'s `workflows` map (empty in practice) while the actual ~50 workflows live as `workflows/*.json`. It now **falls back to the on-disk workflow files** (id/name/description, `trigger` from `definition.trigger`, `inputs` from `processVariables`), deduped against registry.json — so the editor's ActionPicker dropdown populates for every project.

Regression-locked: `test_root_redirect.py` (12) + `test_app_emitter.py` (+2 root-page integration) + `page-scaffold` `shell:true` assertion; full suites green (frontend 199, patches 48; 1 pre-existing `globals.css` emitter failure unrelated). Live `g4e8ksop` patched in place for immediate retest.

## 31. Per-app Design DNA — every generated app gets a distinct, premium, domain-appropriate design (2026-07-26)

**Problem.** Every generated app converged on one look. A 7-agent adversarial map of the whole design pipeline found the sameness was *systemic*, not one bug: (1) the design agent's own prompt schema taught prose inside values (`"0.5rem (8px) — buttons"`), which the compiler passed VERBATIM into `tokens.custom.json` and the browser silently dropped — so radius/type-scale/line-height/semantic-spacing never differentiated apps even when specs varied; (2) prose-contaminated hex **silently deleted whole color ramps** (`hsl_ramp` ValueError swallowed; `_rewrite_globals_root` skipped non-`#`-prefixed values) — two real apps shipped with NO primary; (3) `--radius` was hardcoded `0.5rem` for every app and `_resolve_radius_scale` floored `sharp`→`soft` (homogenizing all registers); (4) `--font-heading` was emitted with ZERO consumers and the prompt never asked for `headingFontFamily`; the dead domain-fallback pinned fontless apps to Inter; (5) `design_spec` NEVER reached page generation (`plan["design_spec"]`/`plan["_output_dir"]` never set → the whole design-brief/register-exemplar system silently disabled); (6) the compiler never emitted the Wave-2 personality knobs (`density`/`elevation`/`motionLevel`/`scaleMode`) so every app rendered the default personality; (7) shell-less apps hardcoded the identical navy rail, and `TokensProvider` never received per-app tokens (`cssVarTokens` fed CSS vars only); (8) `compileTokens` emitted group-DROPPED var names (`--token-primary-500`) while every consumer references group-PREFIXED (`--token-color-primary-500`) — all schema-level `node.style` token refs resolved to nothing in generated apps.

**Architecture (all deterministic, zero API cost):**
- **`services/design_dna.py`** — the identity generator. 14 domain **archetypes** (fintech/healthcare/consumer-warm/legal/creative/developer/logistics/education/hospitality/hr-people/commerce/industrial/analytics/default-saas), each an art-directed stance: hue bands, saturation/lightness bands, **neutral temperature** (warm/cool/graphite/steel/ink), font-pairing pool, radius scale (incl. TRUE sharp), elevation, density, motion, type-scale mode, rail recipe (dark/light/brand/tinted), surface treatment, and written design principles. 18 curated **Google-Fonts pairings** (Inter-precision, Geist, Sora, Space Grotesk+Plex Mono, Bricolage Grotesque, Fraunces, Newsreader, Manrope, Plus Jakarta+Figtree, Nunito, Gabarito+Hanken, Outfit+Karla, Archivo, Schibsted, Lora+Karla, Instrument, IBM Plex, Work Sans) with weights/letter-spacing/tabular-numerals. **Seeded per-project variety** (sha256 of project id + domain): same project → same DNA; six same-domain projects → 6 distinct primaries. **WCAG floors enforced**: white-on-primary ≥ 4.0 (warm hues kept RICH — capped lightness instead of muddy darkening), ink-on-bg ≥ 7, rail text ≥ 4. Consumers: `to_design_spec()` (complete machine-valid spec), `prompt_brief()` (art-direction brief for agents), `to_css_variables()` + `google_fonts_import()`.
- **`services/css_sanitize.py`** — total value-sanitizers (`extract_hex/css_length/font_stack/shadow/number/ms/weight/letter_spacing`, Tailwind `text-3xl`→rem mapping) that recover the machine value from LLM-annotated strings or return None.
- **`design_compiler.py`** — every mapper sanitizes (radius/scale/lineHeight/letterSpacing/spacing.semantic/shadows/status/palette-hex); `sharp` honored; Wave-2 knobs emitted; `compile(spec, dna=)` deep-merges the DNA UNDER the agent spec (agent wins where valid, DNA fills every gap). **Acid test: recompiling all 10 real apps' design-specs now yields 100% CSS-valid tokens (was: broken values in every app).**
- **`design_agent.py`** — prompt schema rewritten to machine-clean example values (serif/forest example, NOT Inter+indigo) + a VALUE-HYGIENE contract; asks for `headingFontFamily` + radius/elevation/motion/scale knobs; DNA brief injected into the user prompt; ingest tolerates annotated hex; `--radius` now derived from spec `borderRadius.md`; **`h1-h6 { font-family: var(--font-heading) }` rule finally gives the heading font a consumer**; line-height sanitized; domain fallback reads the plan.
- **`generate.py`** — derives DNA before the design agent (logs the identity), passes the brief, merges DNA under the extracted spec, **fence-miss now falls back to the DNA spec** (not generic industry defaults), DNA-aware token compile runs even when FIDELITY_MODE is off, and **GAP-1 fixed**: `plan["design_spec"]` + `plan["_output_dir"]` set so page authors finally receive the design brief. Shell brand key mismatch fixed (`primaryColor`).
- **Runtime plumbing** — `EngineProvider` deep-merges `cssVarTokens` into the `TokensProvider` context (hooks now see per-app values); standalone-app layout loads `tokens.custom.json` and passes it; `compileTokens` dual-emits group-prefixed AND legacy var names (fixes the schism + the radius/shadow `--token-sm` collision); `SideNav` falls back to `tokens.color.sidebar` with luminance-computed light/dark chrome; the `(dashboard)` fallback rail is painted from the app's design-spec instead of hardcoded navy.

**Proof (no credits spent):** three DNAs pushed through the REAL pipeline functions (`save_design_spec` → globals rewrite + typography injection; `compile_to_file`) against the live g4e8ksop app produced three unmistakably different premium identities — fintech (Geist, deep indigo #322489, sharp, cool neutrals), consumer-warm (Bricolage Grotesque, honey #ad6d1e, pill-round, cream paper), legal (Fraunces serif headings, oxblood #73303f, sharp, warm paper) — imagery preserved throughout. Tests: `test_design_dna.py` (23: determinism, cross-domain distinctness, same-domain variety, contrast floors, CSS validity, font-bank shape) + `test_css_sanitize.py` (19, fixtures = the exact shipped-broken values) + `test_design_compiler.py` updated to lock sanitize behavior (78 total in the design suites). Regression: frontend 199 ✓, patches 48 ✓, schema 204 ✓, backend services zero NEW failures (2 stale pre-existing tests fixed; renderer/library suite failures proven pre-existing via pristine-worktree + stash+dist-rebuild isolation).

**Round 2 (2026-07-26, same day):** the residual gaps were closed before the first credit-funded test:
- **Shell STRUCTURE variety** — exported apps now support a second frame: `(dashboard)/layout.tsx` renders a premium **TopNav topbar** (horizontal header nav painted from the app's identity, mobile overflow-scroll, soft-nav via AppNavigator) when `design-spec.layout.navigation` is `topbar`. The DNA emits the frame per archetype (`frames` — creative/commerce/education/hospitality can draw topbar; verified ~50/50 across eligible draws) and the hardcoded `bg-slate-50` canvas became `bg-background` (the app's own tinted surface). Verified live: topbar layout compiles clean on g4e8ksop (307 + zero server errors).
- **Per-app icon voice** — every archetype carries an `iconStroke` (1.5 elegant-thin → 2.25 friendly-bold); emitted as `--icon-stroke` in `:root` + one `svg.lucide { stroke-width: var(--icon-stroke) }` rule (CSS beats the SVG attribute), theming every icon app-wide.
- **Dominant components consume the personality knobs** — MetricTile (radius scale, was hardcoded rounded-lg/md; elevation already wired), Stat (radius + density padding + elevation depth), Table (container radius). Library suite: same 3 pre-existing failures, 683 passed — zero new.

**Still open (enhancements, not blockers):** split/list-detail shell frames; deterministic CRUD builders consume density only (LLM pages carry the structural variance via the now-connected design brief); fidelity scoring env-gated off; upstream nav-flow writers lack the dynamic-route guard (app_emitter sanitizes as last line of defense).

### 31.1 Composition engine — apps differ in STRUCTURE, not just paint (2026-07-27)
Round 1+2 varied colour, type, radius and icon weight, but two generated apps
still shared a skeleton: a **byte-identical** login (`build_login_schema()` was a
constant function, and the React template hard-coded one split layout over a
stock photo), the same `tiles → charts → table` dashboard (`deterministic_pages`
documents that it "emits the SAME Page schema"), and one rail. Anyone could tell
they came from the same generator. This round fixes the cause.

- **Discovery dossier is now a HARD input.** `_dossier_signals()` reads the
  researched `visualLanguage` (paletteCharacter / typographyTone /
  densityPreference / colorAnchors) and overrides archetype defaults: named
  colours map to hue bands, "electric/neon" boosts saturation, "muted" damps it,
  the tone selects a font-pairing family, density is taken verbatim. The
  pipeline had already researched the right aesthetic and was discarding it.
- **Light/DARK canvas per app.** Archetypes (and dossiers saying
  "dark/charcoal/midnight") select a dark identity: near-black tinted canvas,
  surfaces lighter than the page (depth by luminance, not shadow), bright
  brand/accent, and contrast enforced in the correct direction. A workout app
  now ships dark charcoal + neon lime; a law firm warm paper + oxblood.
- **New `fitness` archetype** (dark-first, technical type, compact logging
  density, expressive motion) — the workout app previously fell to
  `default-saas` and rendered magenta-on-white.
- **LAYOUT_RECIPES — the composition layer.** Per-archetype tasteful subsets of
  6 auth layouts, 6 dashboard compositions, 5 list patterns, 4 detail patterns
  and 5 shell chromes, chosen by seeded draw and emitted on the DNA + design-spec.
- **Auth pages are composed per app.** `login/page.tsx` (and `signup`) render one
  of six layouts (split-editorial / centered-minimal / brand-wash / side-panel /
  top-anchored / split-reversed) via the `__AUTH_LAYOUT__` placeholder that
  `runtime_injector` fills from `design-dna.json`. The brand surface is painted
  from the app's OWN palette (layered gradients + a fine grid), so the stock
  purple photo is gone. `callbackUrl || "/"` is preserved.
- **Dashboards compose per app.** `_dashboard_composition()` + `_compose_dashboard()`
  arrange the SAME validated widgets into six structurally different shapes
  (stat-strip / stat-grid / hero-led / feed-led / split-focus / board-first).
  Bindings and dataSources are untouched, so data wiring cannot break; an app
  without a DNA falls back to the historical `stat-grid`.
- **Fixed a bug this work exposed:** passing `cssVarTokens` to `EngineProvider`
  in generated apps re-emitted the shadcn vars as RAW HEX, but their Tailwind
  reads `hsl(var(--x))` → `hsl(#2c8003)` → invalid → black text (fatal on dark
  themes). `EngineProvider` gained `semanticVars` (default true, preserving the
  render-scaffold) and the generated layout passes `false`, since its
  `globals.css` already declares those vars in HSL-channel form.

Verified live on two real generated apps: the fitness app renders a dark
top-anchored neon sign-in; the law firm a warm side-panel with a forest→plum
brand wall. Tests: design suites 110 green (composition vocabulary, dark-mode
contrast floors, dossier→palette, cross-domain structural difference,
40-project spread, determinism). Full `tests/services` sweep: **24 failures vs
25 on the pristine baseline — zero regressions, one pre-existing failure fixed.**
Frontend 199 / patches 48 / schema 204 green.

### 31.2 Structural identity — shell chrome, personality CSS, list shapes (2026-07-27)
Round 3 attacked the remaining shared pixels: the always-visible chrome.

- **Shell chrome variants are real components now.** The generated
  `(dashboard)/layout.tsx` template renders one of five shells chosen by
  `design-dna.json → layout.chrome`: `standard-rail` (legacy SideNav),
  **`wide-rail`** (272px sectioned rail, uppercase group labels, pill actives,
  brand block + account footer), **`icon-rail`** (64px icon-only with
  tooltips), **`topbar`** (horizontal nav), and **`floating-rail`** (detached
  rounded-2xl rail floating on the canvas with a page gutter). Lucide glyphs
  are matched per nav label (`GLYPHS`/`RailGlyph`), so icon voice varies too.
- **Personality CSS layer** (`design_dna.to_personality_css`, injected
  idempotently by `design_agent.save_design_spec` inside
  `/* tentoro:personality */` markers): per-archetype page texture (top-wash
  gradient / radial tint / grid-paper), h1 voice (accent-bar / rounded-bar /
  rule / none — hero headlines excluded via `[data-hero-content]`), table voice
  (striped / hairline-lined / airy), plus per-app `::selection` and
  `:focus-visible` colours. The micro-signals no longer match across apps.
- **List pages escape the Table monoculture.** `build_list_page` reads
  `spec.layout.list`: **`board`** delegates to the deterministic Kanban builder
  whenever the entity has a status-like column (Table fallback otherwise);
  **`card-grid`** emits `Grid → Repeat → Card` bound with the established
  `{{item.field}}` convention (title/badge/subtitle from `pick_card_props`,
  per-card detail Link). No DNA → byte-stable legacy Table.
- **Body contrast bug (dark-mode fatal).** LLM-authored `globals.css` drops the
  template's `@layer base` body rule, leaving body text browser-default BLACK —
  invisible on light themes, black-on-near-black on dark apps. The injected
  typography block now anchors `body { background-color/color }` to the
  semantic tokens.
- **Hero crash fix.** `_compose_dashboard("hero-led")` emitted `subheadline`
  (not a Hero prop) and no `ctas`; the library `Hero` indexed `ctas.length` and
  crashed into its error boundary. Builder now emits `headline/subhead/ctas:[]`
  and `Hero` defaults `ctas = []` (library rebuilt; vendored dists patched in
  the two live apps).
- **Live retrofit as proof (no credits burned):** LexFlow (legal, light paper,
  wide-rail, rule-underlined h1s, grid-paper texture, stat-strip dashboard with
  full-width stacked panels) vs IronLog (fitness, near-black neon, floating
  rounded rail, accent-bar h1s, top-wash texture, hero-led dashboard with
  greeting band → KPI tiles → 2-col blocks). Their dashboards, shells, auth
  pages, textures and tables now share no structural DNA.

Tests: +6 (`test_list_layout_dna.py`: list-composition dispatch, board
fallback, hero-props schema regression). `tests/services`: **24 failures =
baseline minus one, zero new**. Library: 683 pass / same 3 pre-existing
failures. Both live apps verified in-browser: zero console errors.

### 31.3 Round 4 — post-audit closure: every audited sameness vector fixed (2026-07-27)
A 3-agent adversarial audit (DNA-spread Monte Carlo · pipeline-coverage ·
live-app shared-pixels) produced 21 findings (4 critical, 9 major). All fixed
deterministically, zero API credits:

**DNA spread (same-domain apps were 6.5/11-axis siblings):**
- Word-boundary archetype matching (`\b`) — "blog"/"harvest logs" no longer
  bin to developer via the "log" substring.
- 3rd hue band + wider bands for the five 2-band archetypes; ≥2 radius
  options in ALL archetypes; seeded icon-stroke jitter (±0.25); seeded
  light/dark mode for developer + analytics; Inter-body swapped out of 5
  pairings (Albert Sans / Figtree / Source Sans 3 / Barlow / Mulish);
  developer recipes diverged from fintech/analytics.
- **Seeded BRAND NAME** (`brand_name()`, per-archetype fragments): plans
  carry no product name (module_name is the vertical — apps literally
  introduced themselves as "Legaltech"/"Fitness"). Two law firms now ship as
  e.g. VerdictFlow vs BriefDesk; the runtime injector prefers a distinct
  user-supplied name, else the DNA brand.
- **Per-archetype auth copy** (`AUTH_COPY`) + **action-verb voice**
  (New/Add/Create · View/Open) emitted on the DNA and consumed downstream.
- Same-domain Monte Carlo after: avg shared axes 45% (was 59%), ≥9-of-13
  twins 4–10%, brand-name dupes ≤5%.

**Pipeline coverage (structurally DNA-blind slices):**
- `build_detail_page` implements all four DETAIL_LAYOUTS (split-detail via
  Split 2:1 + meta rail · profile-detail via Avatar identity band + Badge ·
  timeline-detail via key-fact strip · tabbed-hero via title band); legacy
  single-card stack preserved for pre-DNA specs.
- `build_form_page` consumes new `layout.form` vocabulary (single-column /
  two-column / sectioned "Basics·More detail" / side-summary via Split with a
  requirements rail); LAYOUT_RECIPES gained a per-archetype `form` key.
- Timeline lists implemented (`_timeline_collection`: date-rail Repeat feed,
  `_timeline_date` accepts audit timestamps); split-list removed from the
  vocabulary until it has a real renderer (DNA stays honest).
- `_merge_dna_composition` in schema_prompt: design-spec.json that lost its
  composition keys (refine passes, template seeds) is backfilled from
  design-dna.json — the silent stat-grid/table fallback is gone.
- LLM pages now RECEIVE the composition DNA: `format_design_brief_for_schema`
  emits a "Composition DNA" block with concrete per-shape directives, and
  `prompt_brief` carries the layout dict.

**Shared pixels (the "clockable in two minutes" list):**
- Deterministic nav IA: detail pages demoted from rails (raw-title +
  route detection), " List" suffixes stripped, >7-item flat menus clustered
  into labeled families (People/Billing/Documents/Insights/System) — in BOTH
  `shell_templates.build_sidenav_groups` and the app-layout fallback.
- GLYPHS map extended 16 → 60+ names covering the shell generator's full
  icon vocabulary (audit: 12/18 nav items rendered the Circle fallback).
- Login form copy per app via `__AUTH_FORM_TITLE__/__AUTH_FORM_SUB__`
  placeholders filled from DNA authCopy; signup brand-name plumbing fixed
  (was the vertical).
- Content frame varies with density DNA (`frameClass`: compact 1440px/tight,
  spacious max-w-6xl/airy).
- Tables: raw leading "Id" column dropped when the row links; per-entity
  `emptyText` ("No matters yet…"), also on dashboard widget tables.
- Dark-mode `--color-*` ramps invert (deep tints / bright shades + dark
  surface) — dark apps no longer render light-mode Badge/Chart chips.
- `--primary/accent/destructive-foreground` picked by CONTRAST (`_fg_for`):
  neon/bright primaries get ink labels instead of unreadable white.

Both live apps retrofitted (typography-from-DNA incl. IronLog's Geist/Inter
mismatch, mode-aware color ramps, regrouped rails with real icons, brand
names, per-app auth copy, de-slopped tables) and verified in-browser. Tests:
+13 `test_structural_identity.py`, mode-aware contrast floor in
`test_design_dna.py`; suite: 47 identity tests green; full `tests/services`
sweep **24 failures = pristine baseline − 1, zero new**.

### 31.4 Component SKINS — per-app design languages (2026-07-27)
Even with palettes/shells/compositions varying, every app still DREW its
components one way (bordered cards, left-accent KPI tiles, one button shape) —
users read four real generations as one product. Root causes (4-agent deep
research): (1) the design DNA was fed STARVED inputs — planner `domain` is a
5-value enum ('general|hr|fintech|healthcare|saas') that shadowed the rich
discovery label; `description` at the approval path was the user's APPROVAL
message, not the original prompt; a failed-validation discovery salvage left
poisonous pydantic defaults ("neutral"/"corporate") that steered every app
muted-corporate; (2) a 5-variant component system (workday/linear/stripe/
notion/figma for Card/MetricTile/Hero) existed, fully wired — but every app
picked "workday" (selector got the garbage brief; rule fallback defaults
workday); (3) no component-level styling varied per app at all.

Fixes:
- **Inputs**: original_prompt now feeds the pipeline; generic domains bypass
  to the discovery label; context concatenates discovery description +
  app/module name + entity names + page names; VisualLanguage defaults are
  empty strings; discovery salvage validates sub-models per-field and stamps
  source="validation_salvage".
- **8 COMPONENT SKINS** (`SKINS` + `to_component_css()` in design_dna),
  grounded in reference research (Mercury, Linear/Vercel, Notion, Ramp,
  Airtable, Retool/neo-brutalism, Stripe/Arc, print-ledger editorial):
  inkwell · monoline · manuscript · signal · meadow · gridwork · aurora ·
  broadsheet. Each restyles stat-tile anatomy, card language, buttons,
  tables, callouts and edges; seeded per archetype (2–6 options each); the
  skin OWNS the register (single authority — the second classifier at
  generate.py is now a fallback). Emitted as a `/* tentoro:skin */` block in
  globals.css scoped under `[data-tentoro-engine]` (beats every Tailwind
  utility at (0,2,0) specificity; !important only for audited inline-style
  hazards). Icon-tolerant `:first-of-type` selectors.
- **Library**: data hooks added (data-card + data-slot on Card + variants,
  data-variant/size on Button, data-metric-tile on all tile variants,
  data-activity-feed, data-alert); MetricTile.workday now honors icon +
  importance (it silently dropped both — every KPI row rendered flat);
  Alert/Banner read var(--color-*-100/200/800) with fallbacks instead of
  hardcoded Tailwind-blue hexes ('info' added to the emitted scale).
- **Anti-tell schema rules**: no fabricated deltas, no mechanical
  singularization ('Matche'), no repeated image seeds across pages, no
  double-header ActivityFeed-in-Card, chart-type variety (donut no longer
  always second).
- **right-rail shell chrome**: navigation can now sit on the RIGHT side
  (flex-row-reverse WideRail) — placement itself varies per app.

Live proof — four apps, four languages, four spatial arrangements:
LexFlow=broadsheet print-ledger (left wide rail) · IronLog=gridwork
neo-brutalist dark (floating rail) · VitalChart=meadow pastel (left light
rail) · WillowNook=manuscript document (RIGHT rail; full re-derive proved the
input fix: consumer-warm, warm amber, brand-named from seed). All verified
in-browser, zero console errors. Tests: +4 skin suite (deterministic seeded
picks, register authority, engine scoping, same-domain divergence);
`tests/services` sweep **24 failures = pristine baseline − 1, zero new**.

### 31.5 NAV IDENTITY — per-skin navigation grammars + dock chrome (2026-07-27)
Placement varied (6 chromes incl. right-rail) but every rail still LISTED
items the same way: icon + label rows. Now each skin carries its own
navigation GRAMMAR, emitted by `to_nav_css()` (marker `/* tentoro:nav */`),
scoped under `[data-skin]` + `[data-shell-nav]` with template hooks
(data-nav-item/icon/label/group-label) and a tiny runtime active-tracker
(follows pushState soft navs):
- broadsheet → **numbered index**: CSS-counter `01/02/…` two-digit indices,
  icons hidden, italic serif group labels — a typeset table of contents.
- manuscript → **document outline**: text-only lowercase items indented
  under dotted guides, italic lowercase groups.
- gridwork → **compartments**: every destination a bordered uppercase cell;
  active cell inverts; hover lifts with the offset-shadow signature.
- meadow → **pill chips** with tinted icon discs, springy translate hover.
- aurora → **glass capsules**: active wears a gradient hairline + glow.
- monoline → **dense instrument list**: 28px rows, right-aligned mono
  keycap index chips, instant (0ms) state changes, inset accent bar.
- signal → **bold blocks**: icons hidden, active is a solid accent block.
- inkwell → **quiet floating**: shadow-card active, small-caps labels.
Plus a NEW **dock** chrome (floating bottom-centre bar, content full-bleed —
consumer-warm/education/fitness draws) and per-skin motion signatures.
Live: LexFlow=numbered index · WillowNook=outline (right rail) ·
IronLog=compartments · VitalChart=pills. Tests +1 (nav grammar uniqueness +
pattern content); sweep **24 = baseline − 1, zero new**.

### 31.6 COMPOSITIONAL DESIGN ENGINE — a language per app, not a skin from a list (2026-07-27)
Ten named skins is a ceiling: generate 30 apps and the 30th repeats. The
language is now COMPOSED per app (`backend/services/design_language.py`).

**Axes** (each value = tags + a CSS emitter): navShape 20 · activeMark 12 ·
headerStyle 11 · kpiAnatomy 12 · cardTreatment 9 · radiusRegime 6 ·
typeClass 8 · density 5. Raw permutations run to the hundreds of millions.

**Taste model** — what keeps it premium rather than random:
- *coherence tags* (sharp/soft/technical/editorial/playful/luxe/organic/
  dense/airy): >=2 shared across nav/kpi/card/type or the draw is rejected;
  antonym pairs (sharp↔organic, dense↔airy, luxe↔playful) are excluded.
- *structural rules*: a bottom dock cannot carry a left edge-bar; a rounded
  floating rail cannot full-bleed-invert; right-bar needs a right wall;
  underline/overline are horizontal-only. Geometry, not taste — hard.
- *forbidden pairs* (~35, research-verified): glass+hard-offset,
  chamfer+soft-shadow, mono+pillowy, tint-block+tint-fill, …
- *one-loud cap*: at most ONE attention move (hard shadow / glass / colour
  bars / chamfer / tinted band) per app. This is what stops the circus.
- *archetype affinity*: legal weights editorial+luxe, devtools
  technical+dense, consumer soft+playful — domain-appropriate, never random.

**Distinctness**: `design_signature` = (navShape, kpiAnatomy, cardTreatment,
radiusRegime, typeClass). Simulation: **120 apps → 118 unique languages
(98%)**, all 20 nav shapes / 12 KPI anatomies / 9 card treatments / 12 marks
/ 11 headers / 7 chromes exercised. Fully deterministic per project id.

**Research-verified fixes shipped with it** (font binaries + contrast math):
- Fraunces and Oswald have NO tabular figures and proportional digits — as
  numeral faces they break every ruled KPI column. Swapped to Newsreader /
  Archivo Narrow (verified uniform-width). `tabular-nums` now always emitted.
- emerald-600 `#059669` measures 3.77:1 on white and FAILS AA as a delta
  colour; replaced with `#047857` (5.48:1) plus dark-mode variants.

The named SKINS remain as presets for back-compat; `to_component_css` /
`to_nav_css` delegate to the composed language when one is present.
Tests: +3 (spread >=50/60, taste model holds over 80 draws, register and
chrome follow the language). Sweep **24 = pristine baseline − 1, zero new**.

**Anti-slop pass** (research named the recurring generated-UI tells; two were
in our own engine): "hairline border + wide diffuse shadow" is *the* signature
of generated UI — every premium reference (Linear, Vercel, Ramp, Datadog,
PostHog, Raycast, Notion, Airtable, Mercury) forbids shadows on cards and
reserves them for popovers. That pair is now a forbidden combination, and a
new `surface-step` treatment supplies depth by TONE instead. A coloured
edge-tab on a card — "the single most recognisable tell of AI-generated UI" —
is banned outright. Radius >= 16px is kept away from data-dense ledger
anatomies (>= 16 reads consumer-marketing, not premium dashboard). Result:
only 22% of composed apps use any card shadow, matching the reference set.
Pinned by `test_no_ai_slop_signatures` over 120 draws.

**Ninth axis — PAGE SURFACE** (2026-07-27). Nothing in the engine varied the
ground the app sits on: every app was a flat fill. Eleven surfaces now
compose alongside the rest — plain, grid-paper, blueprint, dot-grid, grain
(feTurbulence data-URI), crosshatch, linen, wash, mesh, hairline-h, diagonal.
All pure CSS, no network, no images. This is the widest-reaching axis in the
engine: a blueprint grid, a paper grain and a flat fill read as three
different pieces of software before a single component renders. Surface joins
the coherence tags, the one-loud cap and the design signature. Its pair rules
are the strictest in the taste model — a patterned ground read through a
translucent or borderless card is mud, so glass/tint/rules-only cards forbid
every pattern.

**Modern corner geometry**: `corner-shape: squircle|bevel|scoop` (Chrome/Edge
139+, degrades to plain `border-radius` everywhere else) ships as progressive
enhancement, adding three regimes nothing else generates.

**Micro-craft layer**, emitted for every app: a WCAG 2.4.11 focus ring using
`outline` — NOT `box-shadow`, because box-shadow rings vanish entirely in
forced-colors mode while `outline` is preserved and now follows
`border-radius` in every current browser — plus a forced-colors fallback, an
explicit two-sided `::selection` pair (inheriting `color` is what produces
the unreadable selections on generated sites), app-keyed scrollbars, and
scope-wide `prefers-reduced-motion`.

**Fallback presets are search-derived, not hand-written.** The first
hand-written set silently violated the structural rules — 7 of 8 were
illegal, and one shipped a `rail-icon` nav with an `invert` mark. They are
now found by searching 7,262 fully-valid draws and greedily picking the eight
most mutually distinct (min 5 of 6 axes differ between any two), and
re-verified by `_assert_fallbacks_valid()` at import.

**Relaxation tiers replace the single fallback.** A shared conservative
default made 26 of 120 hard-to-satisfy apps identical — precisely the failure
this engine exists to fix. Constraints now relax in tiers: tier 1 drops the
surface to plain, tier 2 accepts looser mood coherence. The structural rules,
the forbidden pairs and **the one-loud cap are never relaxed**. Result:
**200 apps -> 185 unique languages (92%)**, worst collision 5, zero taste or
structural violations. +3 tests.

**SEED ENTROPY BUG — the one inflating every distinctness number above.**
`_byte(seed, salt)` was `seed[salt % len(seed)]`: every axis read a SINGLE
byte of a 32-byte digest, so two projects sharing the handful of bytes the
composer samples produced byte-identical languages however different the rest
of the seed was. Found by rendering eight real apps — a pet-grooming app and
a school portal drew the same signature in an 8-app sample, which is exactly
the sample size a user tests with. Hashing (seed, salt) spends the full
digest on every draw position. Measured after the fix:

| apps | unique | worst collision |
|---|---|---|
| 8   | 8   (100%)  | 1x |
| 50  | 50  (100%)  | 1x |
| 200 | 198 (99.0%) | 2x |
| 500 | 489 (97.8%) | 3x |

**Zero-gap KPI cells** (ledger / shared-strip / glass-ribbon separate cells
with rules or a shared fill rather than gutters) now carry inline padding —
without it one cell's delta butted straight against the next cell's label.
Caught by rendering, not by a test; a test now pins it.

Visual proof: `scratchpad/proof.html` renders N composed apps from their real
emitted CSS. Verified in-browser at 1440x900 — eight apps, eight distinctly
different shells, KPI anatomies, grounds and type systems, and the accounting
double rule closing the ledger app's table.

**GENERATION RELIABILITY — discovery cap was fatal, now trimmed (2026-07-28).**
`DiscoveryOutput.commonPitfalls` had `max_length=8`, which RAISES when the
domain LLM returns 10 — dead-ending the whole build at step one (hit live on
the 'invoice software' app; the per-field salvage branch re-raised because it
copied the over-length list verbatim). This module's contract is "degrade
gracefully, never dead-end discovery", so over-length list fields are now
TRIMMED to their schema cap (highest-signal-first) before validation via
`_clamp_capped_list_fields`, driven by the model's own field metadata so it
covers any future capped field. +2 regression tests.

**CHROME WAS AN ACCIDENT OF NAV-SHAPE COUNTS — now a first-class draw
(2026-07-28).** Chrome was inherited from whichever nav shape was picked, and
12 of the 20 nav shapes are left-rails, so ~60% of EVERY domain's apps came
out wide-rail and top-nav/dock/right almost never appeared. Live-observed on
real invoice generations (9 of 12 siblings were wide-rail, zero top-nav) —
"the sidebar looks the same every app". Chrome is now drawn as a first-class
7-family axis (wide/standard/icon/right/floating/topbar/dock) with an even
base weight plus a small affinity tilt, then a nav shape is drawn WITHIN the
chosen family. Result across 60 fintech-invoice apps: right 25% · standard
23% · wide 18% · icon 18% · topbar 10% · floating 5% (no chrome >27/60); and
across 120 mixed-domain apps ALL 7 chrome families appear, wide-rail down from
60% to 22%, uniqueness still 100%. Pinned by
`test_chrome_actually_varies_not_all_rails`.

**FIRST REAL GENERATION rendered end-to-end (invoice software → "LedgerFlow",
2026-07-28).** Composed `rail-right·ledger-leaders·hairline·square·mono·plain`
— a right-side rail, monospace ledger KPIs, teal fintech accent — and it
renders. Two bugs surfaced and were fixed on this first app: (1) a mixed
f-string/plain-string brace slip emitted `}} }` (a stray third `}`) in the
reduced-motion @media block, breaking the ENTIRE stylesheet with "Unexpected
}" so the app wouldn't boot — now every emitted stylesheet is brace-balance
tested across 200 apps; (2) `NEXTAUTH_URL` hardcoded to :3000 broke auth when
the app runs on any other port.

**KPI ANATOMY LAYOUTS WERE DEFEATED BY THE COMPONENT'S `flex-col`
(2026-07-28).** The MetricTile component ships a `flex-col` Tailwind class.
Anatomy CSS that set `display:flex` for a row (ledger-leaders, stat-column)
but never overrode `flex-direction` inherited that column direction, and
`justify-content:space-between` then blew the label and value to opposite ends
of the tile — the sparse, big-gap KPIs seen live on LedgerFlow. Every flex KPI
tile now declares its own `flex-direction`; the ledger/stat anatomies are a
tight label-over-value stack closed by a hairline rule (the Ramp / Modern
Treasury financial-statement look). Pinned by `test_flex_kpi_tiles_declare_
direction`. The same f-string/plain-string `}} ` brace slip recurred in the
value rule and was caught immediately by `test_emitted_css_is_brace_balanced_
every_app` — that test is now earning its keep.

**THE BIG KPI NUMBER WAS BEING SHRUNK TO LABEL SIZE — the real reason KPIs
looked un-premium (2026-07-28).** Root-caused live by inspecting LedgerFlow's
DOM: the register MetricTile variants (linear/workday/stripe/notion/figma)
nest the label inside a header row, so BOTH the label `<p>` and the value
`<p>` are `p:first-of-type` within their own parent. The emitter's KPI
selectors assumed flat siblings — `p:first-of-type` = label,
`p:nth-of-type(2)` = value — so the value selector matched NOTHING and the
label selector matched the value too, rendering a 24px JetBrains-Mono number
as 12px small-caps. Every register variant now carries explicit
`data-metric-label` / `data-metric-value` hooks (packages/library/src, all 6
variants) and the emitter targets those. Verified live: the value went 12px
IBM-Plex → **26px JetBrains Mono**, label correctly 12px small-caps. Pinned by
`test_kpi_targets_data_hooks_not_paragraph_positions` (asserts the fragile
`p:nth-of-type`/`p:first-of-type` selectors are gone). Lesson reinforced:
position-based selectors over a component you don't control are a trap —
component-owned data hooks are the contract. (Requires `npm run build
--workspace=packages/library` after pull; dist is gitignored.)

## §32 BUSINESS RULES — productionizing the feature (2026-07-28, component-fixes)

The Business Rules authoring feature (Power-Apps-style condition→action editor +
Drools/DMN decision-table editor + condition playground + the tree→FEEL compiler,
persisted as `ProjectRule` rows) was built but never hardened or wired into
generation. TRACK 1 hardens the authoring feature to production quality (the
pipeline wiring is Track 2). Verified against a 4-agent map of current code.

- **T1.1 decision-model prod-500 fixed.** `models/decision.py` (DecisionTable/
  Version/ExecutionLog — the `decision_table` rule type depends on them) was
  unregistered + unmigrated, so decisions endpoints 500'd in prod while passing
  tests via `create_all`. Registered in `models/__init__.py` + migration
  `b8d4e1f9a3c2`; platform DB brought to head; endpoint returns 401 not 500.
- **T1.2 FEEL Python↔TS conformance suite** (backend/tests/test_feel_conformance
  + frontend feel-conformance.test) — a shared fixture set asserted by both
  engines. Caught 3 real divergences where the playground disagreed with the
  server: absent-field null, numeric-string coercion, case-insensitivity. Fixed
  by conforming BOTH TS copies (playground + shipped runtime) to the Python
  reference (`_fuzzy_equal`). 42 fixtures green both sides.
- **T1.5 per-action save validation** — the save gate only checked the rule
  name, so incomplete actions / actionless rules persisted and no-op'd.
  Added a tested validator + inline error surfacing. Confirmed whenFeel is
  never stale (recompiles on edit / model switch / async type arrival).
- **T1.4 taxonomy pinned** — `VALID_RULE_TYPES` extracted to a named constant +
  a test, so `condition_action`/`decision_table` can't be silently dropped
  (that would 400 every editor save).
- **Live round-trip proven** — created a condition_action rule via the real API,
  read it back with config intact (source/whenFeel/actions), deleted it (204).

Not yet done (Track 2): runtime execution of the new rule shapes, converging the
two generated-app write paths, shipping DB rules into apps, UI-side enforcement.

### §32.1 BUSINESS RULES — wired into the generation pipeline (Track 2, 2026-07-28)

Authored rules now EXECUTE in generated apps — the half that was missing.

- **T2.1 runtime action dispatcher** (`templates/runtime/rules/engine.ts`):
  `evaluateRuleSet` / `evaluateFormRules` + `dispatchActions` for the 10 actions
  (set_field/set_default/clear_field → patches; show_error → reject; visibility/
  required/readonly/recommendation → form hints; trigger_workflow/send_notification
  → deferred side effects). Salience-ordered single pass, scope-filtered, formula
  via feel-lite. Tested against the real engine.
- **T2.2 both write paths fire rules.** data-engine create/update apply patches +
  reject (T2.2a); the workflow db_insert/db_update path resolves the TABLE name to
  a rule's MODEL (canon plural-tolerant) via `evaluateRuleSetForTable` and returns
  `{ error }` on reject — the engine already throws on that, so the form's onError
  surfaces it. No matching rule ⇒ true no-op (T2.2b).
- **T2.3 editor rules ship.** `_export_rules_to_filesystem` now reads the
  `project_rules` DB (sync psycopg2; rules_agent syncs AI rules there first, so the
  DB is the complete AI+manual source), falls back to registry. All three pipelines
  (relay/Figma/IR) pass `project_id`.
- **T2.4 UI-side enforcement.** New `/api/form-rules` route + a fail-safe
  `useFieldRules` hook in the library Form; a hidden field isn't rendered, required
  toggles reactively. Value patches stay server-side so it never fights computed
  fields. Fully additive — no rules / any error ⇒ form unchanged.

Chain, end to end: author in editor → project_rules DB → export → rules/index.json
→ engine loads → executes on write (both paths) + surfaces form hints on the UI.

Remaining (smaller / verification): a live end-to-end proof on a fresh generation;
Figma AI-rule authoring (editor rules already ship there); wiring the legacy dead
code (computeFields/canTransition — a separate concern from the editor feature).

## §33 CRITICAL FIX — generated apps had NO sidebar menu below 768px (2026-07-29)

**Symptom (hit investor demos):** intermittently "no menus in the sidebar",
"few menus missing", "no dashboard". Reported by the founder + engineering team;
suspected to be from the compositional chrome/UI work — correctly.

**Root cause (found by measuring the live DOM):** the custom chrome rails added
by the compositional engine — `WideRail`/`IconRail`, used by the **wide-rail,
icon-rail, right-rail, and floating-rail** chromes (≈4 of 7, so a large fraction
of apps) — are `hidden md:flex`. Below 768px they are `display:none` with **no
mobile navigation at all**. So on a non-maximized window, a projector, a smaller
laptop, or with browser zoom, those apps showed the content but **zero nav** —
the menu items were in the DOM at width:0/height:0. (The original `standard-rail`
SideNav has a mobile drawer; the new custom rails never got one.) Intermittent =
viewport-width × which chrome the app composed. A secondary "few missing": the
bottom **dock** capped the menu at `.slice(0, 8)`, dropping pages 9+.

**Fix:** new `MobileNav.tsx` — a mobile-only (`md:hidden`) top bar + slide-in
drawer with the COMPLETE menu — rendered for all four rail chromes (complements
the desktop rail, never touches it). Dock cap removed (`overflow-x-auto`, shows
every page). standard-rail already handled mobile; dock/topbar were already
visible on mobile.

**Verified live** on a real app at 386px: hamburger → drawer → all 14 items
visible → clicking navigates → drawer closes; at 1440px the desktop rail is
unchanged and the mobile bar is hidden. Pinned by `test_shell_nav_robustness.py`
(every rail chrome renders the mobile nav; the dock never slices). Ships to new
generations via the app-foundation template; existing apps get it on regenerate.

## §33.1 CRITICAL FIX pt.2 — "still not showing in some apps" (2026-07-31)

After §33 shipped, the team still hit "no menu" on **some** apps. §33 fixed the
**template**, so fresh gens into a NEW output dir are correct — but that wasn't
the whole failure surface. Investigation (audited every `output/*` app) found
**three more gaps**, each now closed:

**Gap A — reused output dirs kept the OLD layout.** The template floor copies
foundation files with `if not target.exists()` (`routers/generate.py`), so when
a project is **regenerated into an existing dir**, its `(dashboard)/layout.tsx`
is *never overwritten* — it keeps the pre-fix, no-mobile-nav version. The
template fix simply never reached it. **Fix:** `services/shell_nav_guard.py` —
`ensure_mobile_nav(output_dir)`, wired into `runtime_injector.inject_runtime()`
so it runs on **every** generation (fresh or reused). It idempotently ensures
`MobileNav.tsx` exists and patches the chrome-dispatch shells to render it. The
patch is **transactional**: it edits a layout only when it positively recognizes
the buggy `WideRail/IconRail` structure (anchored on `_WIDE_ICON_OLD`, which is
also where `const mobileNav` is defined) and otherwise leaves the file
**byte-for-byte untouched** — so it can never orphan an import or break a build
it doesn't understand (e.g. the older static-`<aside>` layout, or a
library-`SideNav` layout that already has its own mobile burger).

**Gap B — already-generated apps that won't be regenerated.** For apps that
exist on disk and won't be rebuilt, `backend/scripts/fix_shell_nav.py` is a
developer CLI that retrofits the fix in place: `python
backend/scripts/fix_shell_nav.py output` (all apps) or `… output/<id>` (one),
with `--dry-run`. Same transactional guard, so it is always safe to run, even
repeatedly. Reports `fixed / already ok / skipped (untouched)` per app.

**Gap C — the menu could be genuinely EMPTY (desktop, any width).** Independent
of viewport: `loadNavProps()` could return `{groups: []}` when shell.json had no
`SideNav` **and** nav-flow was missing/all-filtered — a blank rail on desktop
too ("no dashboard / no menus"). **Fix:** a last-resort `schemaRegistryItems()`
in the template layout derives a menu from the schema registry (`@/schemas/
registry`) — a Dashboard link + every top-level entity route — whenever the
normal paths yield zero items. Handles both registry key formats (route keys
like `/appointments` and the legacy `<entity>/list`). The rail is now **never
empty**.

**Coverage matrix (all 7 chromes, mobile-safe):** standard-rail → library
SideNav burger (ShellStateProvider wires `data-sidebar-toggle`); wide/icon/right/
floating-rail → `{mobileNav}`; dock → `fixed bottom` always visible; topbar →
horizontal scroll.

**Verified live** on a real app (VitalChart) at 386px: (1) normal path — burger
→ drawer → all 17 items visible; desktop rail correctly `display:none` on mobile.
(2) Forced empty-data path (shell.json without a SideNav + empty nav-flow) — the
registry fallback rendered a working 9-item menu (Dashboard + entity routes) and
the burger still worked. New template also typechecks clean (`tsc`, zero errors
in `layout.tsx`). Pinned by 9 tests in `test_shell_nav_robustness.py` (guard is
transactional + idempotent; unrecognized layouts left untouched; menu never
empty). **Delivery:** new gens → template; reused dirs → the guard in
`inject_runtime`; already-built apps → the developer CLI.

## §34 DO-OR-DIE SWEEP — business rules that actually execute + server-500 kill (2026-08-03, component-fixes)

Merged `forge-v3-smith-orchestrator-v2` (129 commits: Smith orchestrator,
computational archetype, field-interactions, planner contract, publish/deploy,
UAT sweeps) into `component-fixes` — conflicts resolved by taking the newer
superset for the 3 rules runtime files, keeping both in BLUEPRINT. Then a
root-caused sweep of the "business rules don't work / apps 500 / breaking
everywhere" reports (mapped by 3 investigation agents, every finding
re-verified against the code).

### §34.1 Business rules now EXECUTE end-to-end (Tasks 1 & 2)

**Root cause (the headline):** the AI **rules agent** (`agents/rules_agent.py`)
can only emit `validation / access / business / computed / state_machine /
trigger` — but the runtime write-path entrypoints (`evaluateRuleSet` /
`evaluateRuleSetForTable` / `evaluateFormRules` in
`templates/runtime/rules/engine.ts`) filtered `condition_action` ONLY. So on
any app without hand-authored editor rules, **every generated rule was a silent
no-op** — the exact "business rules integration doesn't work" symptom.

**Fixes (all in `templates/runtime/rules/engine.ts`, unit-tested in
`__tests__/rule-set.test.mts`):**
- `applyTypedRules()` runs the AI types through the same single entrypoint:
  `computed` → field patches, `validation` + failing `business` guards (with an
  explicit errorMessage) → rejection errors. Wired into `evaluateRuleSet`
  (server + workflow paths) and computed into `evaluateFormRules` (live form
  totals). Ordering is computed → validate, so validation sees derived fields.
- `entityNameForTable()` now registers models from EVERY active rule type (not
  just `condition_action`), so a validation/computed-only model resolves from
  its table on the **workflow** write path (Task 2).
- Robust table↔model matching (`nameKeys`/`namesMatch`) replaces the old
  single-`s` strip that never matched `addresses`→Address, `categories`→
  Category, `statuses`→Status (no over-strip), `companies`→Company.

**Pipeline fixes:**
- **Figma path never ran the rules agent** (`routers/generate.py`) → Figma apps
  had zero business rules. Added the `run_rules_agent` call before injection.
- **API-gate re-injection dropped manual rules:** the `_reinject` recovery call
  omitted `project_id`, so the rules re-export read registry-only and wiped
  every editor-authored (DB-only) rule. Now passes `project_id`.
- Rules runtime is re-copied (rmtree+copytree) on every `inject_runtime`, so the
  engine fix reaches fresh AND reused output dirs.

### §34.2 Business rules via Smith (Task 3)

Smith had **no** tool to author a business rule — `set_field_interaction` is a
separate subsystem (single-field reactive UI, not `project_rules`). Added:
- `create_business_rule` tool (`services/smith_tools.py`): resolves the project
  UUID from the app's `.env.local` (`FORGE_PROJECT_ID`), sync-inserts a
  `ProjectRule` via `runtime_injector.create_project_rule_sync`, then
  `_export_rules_to_filesystem` ships `rules/index.json` into the running app —
  no regeneration. Registered in the catalog, dispatch table, and
  `_MUTATING_TOOLS` (confirm/verify gate).
- System-prompt routing distinguishes a business rule (server-enforced DATA
  logic, model-wide) from a field interaction (one form field's UI) — the two
  are genuinely confusable.
- The rule it writes is exactly a type the §34.1 engine now executes, so
  "hey Smith, reject orders over $10k" → DB row → export → enforced on writes.
- Verified: E2E against live Postgres (row inserted + index.json exported);
  wiring + input-validation + env-parsing pinned in
  `tests/test_smith_business_rule_tool.py` (6 tests).

### §34.3 Server-component 500s + UI polish (Tasks 4 & 5)

**Server-500 root cause:** generated apps shipped NO route-segment `error.tsx`,
so any throw in the SERVER portion of a route (missing/corrupt
`src/schemas/<route>.json`, `auth()` failure) bubbled to `global-error.tsx`,
which renders its own `<html><body>` and replaces the WHOLE app with a
full-screen "Something went wrong" — the intermittent "500 sometimes".
- Added `(dashboard)/error.tsx`: a segment boundary that renders the error
  in-shell (sidebar/nav intact) with Retry + Dashboard, and reports to Forge.
  Ships to fresh + reused dirs via the template floor. **Verified live**: a
  simulated server throw at `/` renders the in-shell card with the full sidebar
  preserved (not a white-screen crash).
- Guarded `loadPageSchema`/`renderSchemaPage` (`src/lib/schema-page.tsx`): a
  missing/corrupt on-disk schema now returns null → `notFound()` (a clean 404)
  instead of an unguarded `fs.readFile`/`JSON.parse` throw → 500; `auth()`
  wrapped so a decrypt failure degrades to no-user, not a crash.
- Polish: `__APP_DESCRIPTION__` was never substituted (only `__APP_NAME__`
  was), so every app shipped the literal placeholder in its `<meta
  description>`. `_substitute_app_name` now resolves a real description.

### §34.4 Generation reliability — authoritative build gate (Task 6, D1)

The build-review loop decided pass/fail by **substring-matching the validator's
prose** ("build: pass", "failed to compile", …) and, after 5 cycles, silently
`break`ed and shipped whatever was there — a clean build phrased oddly wasted
cycles, and a genuinely broken app that didn't hit an error keyword shipped and
500'd. Replaced with an **authoritative gate** (`_real_build_ok` → the real
`npm run build` exit code) in BOTH pipeline copies: the keyword scan is now only
a hint; the real build decides, never breaks "clean" on a false pass, feeds the
coder the REAL errors when the heuristic was wrong, and on the final cycle
surfaces a loud `✗ Build STILL FAILING` with the actual errors instead of a
silent ship. The slow real build runs only when we think we're done or on the
last cycle (usually 1–2 builds, not 5). Verified: passes on a real app, fails
gracefully on a non-buildable dir, and the change itself builds a real app clean.

### §34.5 decision_table execution + serverless rules bundling

- **decision_table rules now execute** (`rules/engine.ts`
  `evaluateDecisionTables`): a DMN table (inputs bound to fields × rule rows →
  output patches) was accepted, stored, and exported but NEVER evaluated —
  authored tables did nothing. Now each input cell is matched as a DMN unary
  test (`> 1000`, `active`, `a,b`=OR, `-`=any) via feel-lite, output cells are
  literals or FEEL expressions, first-match-wins (Unique/First/Priority). Fires
  on both write paths. Unit-tested (tiered-discount table, incl. the workflow
  table path).
- **Serverless rules bundling** (Finding 7): `loadRules` read only
  `process.cwd()/rules`, which Next's output-file-tracing drops from the Vercel
  function bundle → `readdir` ENOENT → ALL rules silently disabled in production
  while working locally. Now: the exporter mirrors `rules/index.json` into
  `src/rules/`, `loadRules` tries both candidate dirs, and next.config's
  `outputFileTracingIncludes` names both so they ship in the serverless trace.
  Build-verified.

### §34.6 Honest status / remaining

Delivered + tested: §34.1 (unit), §34.2 (unit + live-DB E2E), §34.3 (live),
§34.4 (real-build verified), §34.5 (unit + build-verified). The business-rules
runtime is now complete — condition_action, validation, computed, business, AND
decision_table all execute on the data-engine and workflow write paths, ship
into the app, and survive a real production/serverless build.

Remaining (called out, not silently skipped):
- **D3 browser-validation-with-auth**: the pre-ship Playwright pass still boots
  `with_database=False` and doesn't log in, so authenticated dashboard RSC pages
  aren't exercised. This is a larger harness change (needs a seeded-DB boot +
  in-browser login), and its value is now largely subsumed by the graceful
  degradation shipped in §34.3 (server throws → in-shell error / 404, not a
  crash) plus the authoritative build gate (§34.4) catching the compile/module
  errors that make an app fail to boot. Left as a scoped follow-up rather than a
  rushed change to the generation harness.
- Deeper generated-UI "polish" is the ongoing compositional-design work (skins,
  builders, taste model — already extensive), not a single defect.
- Smith's live tool SELECTION depends on the model honoring the new routing
  (tool + DB + export path all proven).

## §35 Conversational flow, Smith, generation speed + progress (2026-08-04, component-fixes)

Five do-or-die platform-UX defects, each root-caused with a full frontend+backend
trace then fixed and tested. Delivered on `component-fixes`.

### §35.1 Chat conversational flow (Task 1)
The transcript mixed two incompatible ordering models (append-only client array
vs. a DB re-ordered by non-unique `func.now()` timestamps). Fixes:
- **Reorder-on-reload:** `conversations.created_at` = the transaction timestamp
  (identical for rows written together) + random uuid4 PKs = arbitrary restore
  order. Added a monotonic `seq` BIGINT identity (migration `cf3a91b2d7e4`,
  backfilled) and order the restore by it. Proven live: rows sharing a timestamp
  get distinct increasing seq.
- **Raw `[APPROVE_PLAN]` bubbles on reload:** control-signal user rows (hidden
  live) were persisted and resurfaced as text. `list_conversations` now filters
  them.
- **"Click Begin Quest 4-5 times":** the backend emitted `plan_ready` then ran a
  multi-second design-template LLM call while the stream stayed open, so Begin
  Quest appeared but was disabled (isGenerating) and early clicks dropped.
  Reordered all 4 sites to emit templates BEFORE `plan_ready` → the button is
  enabled the instant it appears.
- **Duplicates on reconnect:** the ChatPanel reconnect reader replayed from
  since=0 with no `_idx` dedup (unlike useSSE). Added it.

### §35.2 Smith reliability (Task 2)
- **Hangs ("stops responding"):** no timeout anywhere on the model boundary.
  Wrapped the turn in `asyncio.wait_for` (FORGE_SMITH_TIMEOUT_S=180) so the user
  always gets a response and the spinner clears.
- **"Doesn't do it":** `add_component` was advertised in the mutation guard +
  `_MUTATING_TOOLS` but had NO handler — the model was steered to a phantom
  tool. Removed it; "add a section" routes to `edit_page`.
- **Fabricated "Done!":** the anti-fabrication guard's verb list missed "get rid
  of", "take out", "turn X into Y", "convert", "switch", "eliminate", "toggle",
  "disable", "merge"… Expanded verbs + phrases + a turn/into rule (tested).
- **Truncated multi-step:** `max_iters` 10 → 16.
- **Masked errors:** the broad except now surfaces the error type as a hint.
- **Stale tests:** the result contract grew to 8 keys + adapter/router signatures
  changed; 6 stubs asserted the old shapes. Fixed — full Smith suite 401 pass / 0
  fail (was 7 failing).

### §35.3 Generation speed — Fast is actually fast (Task 3)
Fast vs Complete differed only in `narrative_expansion` (30-180s) while the real
10-20 min variance (planner revise/V2/critic re-streams @ 4-8 min each, the 5×
build-review loop) was profile-blind — so Fast could take LONGER than Complete.
The `Profile` now carries the speed levers (`review_cycles`, `planner_revise`,
`planner_v2_retry`, `planner_critic`): **Fast** = 2 build cycles + no planner
re-streams (keeps cheap validation) → ~12 min; **Complete** = 5 cycles + full
revise/V2/critic → ~30 min. Wired at the build loop + the V2/critic gate +
`run_planner_oneshot(allow_revise=…)`.

### §35.4 Progress % + ETA no longer freeze/mislead (Task 4)
Planning was 60s of a 455s baseline and its partial capped at the baseline, so
the ring shot to ~13% then FROZE for the whole multi-minute planning window.
Fixes: asymptotic partial fill (approaches but never caps → the bar always
creeps, never pins), planning baseline 60→180s, and the DiscoveryCard Fast/
Complete labels 15/40 → 12/30 to match the profile. New "never freezes"
regression test; 21 progress tests green.

### §35.5 Honest status / remaining
Delivered + tested (unit + live-DB where a DB was involved; migration verified on
the platform DB). Full-generation LIVE proof of the end-to-end speed numbers
needs API credits + a real run and is the one thing not exercised here — the
levers, gates, ordering, filters, timeout, and progress math are all unit-proven.
Lower-priority follow-ups called out, not silently skipped: restoring the
ephemeral theme-selection on project reload (RC-2.2), persisting live-only chat
events (RC-2.4), and verifying Smith's `understanding` against the applied diff
(RC-5).

## §36 LIVE-REPRODUCED chat/Smith/generation fixes (2026-08-07, component-fixes)

This round was done by RUNNING the platform live (browser + real generations),
not by unit tests — the gap that let the prior round "pass tests but fail for the
team". Merged origin/forge-v3-smith-orchestrator-v2 first (brought the new
`smith-arch` bootstrap orchestrator, which changed the discovery/planning path).

### §36.1 🔴 CRITICAL — seq-NULL 500 broke EVERY message write (root of "everything breaks")
The `seq` column added in §35.1 was `NOT NULL` with a DB sequence default, but the
ORM model declared it WITHOUT a server_default → SQLAlchemy sent an explicit
`seq=NULL` on every INSERT (the 10+ `Conversation(...)` sites never set it) →
Postgres rejected it → **POST /chat, Smith turns, and message-persistence during
generation all 500'd.** This alone explains the bulk of "everything breaks", "Smith
stops responding/breaks", and the "click Build Fast 4-5 times" (each click's
approve-signal write 500'd → the button silently re-enabled → click again). The
sqlite test harness (create_all, no sequence) could never reproduce it.
FIX: `server_default=nextval(...)` ON THE MODEL + migration e7f1a9c2b8d0 drops the
NOT NULL (crash-proof). VERIFIED LIVE: Smith answers; Build Fast registers on the
FIRST click; a real ORM insert auto-fills seq.

### §36.2 Signal-bubble leak on reload — real format is `[SIGNAL] {json}`
Signals are sent as `[APPROVE_DISCOVERY] {"mode":"fast"}`, but both the backend
restore filter and the frontend live-hide required the string to END with `]`, so
every JSON-payload signal rendered as a raw bubble on reload. FIXED both detectors
(regex allows the optional trailing object). VERIFIED LIVE: API returns no signal
row, 0 raw bubbles.

### §36.3 Smith works (Task 2) — VERIFIED LIVE
After the seq fix, asked Smith to "add a Vendors page"; it read the app's patterns
and correctly authored the page schema + TS types + Drizzle table + registry entry
+ nav-flow entry. The prior "Smith breaks/stops" was dominated by the seq-500.

### §36.4 Fast wasn't fast (Task 3) — profile never persisted + revise not gated
The NEW `smith-arch` bootstrap path is the one that actually runs, and it (a) never
called `persist_profile`, so generation-profile.json never existed and every reader
fell back to default, and (b) `orchestrate_planner` called `run_planner_oneshot`
WITHOUT the `allow_revise` gate, so a "fast" build ran the completeness-revise
(a 2nd full ~24K-token plan re-stream, +4-8 min). (Last round's fix was on the
bypassed `produce_plan` path.) FIXED: persist the profile in the smith-arch path;
`orchestrate_planner` loads the profile and passes allow_revise=profile.planner_revise.

### §36.5 🟠 Generation reliability — reproduced two "never builds" mechanisms
1. **`uvicorn --reload` kills generations.** A generation is a long in-process
   asyncio task; watchfiles detecting ANY file change mid-run restarts uvicorn,
   tears down the event loop ("Event loop is closed"), kills the planner task, drops
   the SSE → the app "never builds". FIXED: start-all.sh runs the backend WITHOUT
   --reload.
2. **Frontend reverts to the choice step while the backend keeps building.** The
   smith-arch planning stage emits `plan_ready`+`complete` only AFTER planning
   finishes (minutes of near-silence), so the SSE view is lost and the persisted
   discovery card's Fast/Complete buttons reappear — the user thinks it failed and
   clicks again (spawning duplicate builds). Root-caused; the durable fix (SSE
   heartbeats during long stages + not reverting on stream-close / reconnect via the
   generation buffer) is a scoped follow-up.

### §36.6 Honest status / remaining
DELIVERED + VERIFIED LIVE: §36.1 (seq — the big one), §36.2 (signals), §36.3 (Smith).
DELIVERED (correct root fix, at the right seam this time): §36.4 (Fast profile), §36.5.1
(--reload). STILL OPEN (root-caused, need dedicated work + slow gen cycles on the
freshly-merged smith-arch orchestrator): the SSE-revert UX (§36.5.2), planning speed
via decomposition of small apps, and progress %/ETA accuracy against the smith-arch
stage model. These are honestly NOT finished — the generation-completion path in the
new orchestrator needs a focused pass with repeated end-to-end runs.

## §37 CLOSING the §36.6 open items — planner crash, speed, progress (2026-08-07, component-fixes)

The focused end-to-end pass §36.6 asked for. Done by driving REAL generations
through the API (mint JWT → create project → discovery → `[APPROVE_DISCOVERY]
{"mode":"fast"}` → `[APPROVE_PLAN]`) and reading the SSE stream + backend
tracebacks. This is where the real blocker was hiding.

### §37.0 🔴🔴 THE actual "never builds" — `NameError` crashed EVERY fast plan
Live-reproduced an approve→plan run and read the backend traceback:
`agents/planner.py:3093 NameError: name 'logger' is not defined`, inside
`run_planner_oneshot`. That `logger.info(...)` sits in the FAST-build branch (the
completeness-revise skip taken when `allow_revise=False`) and was the ONLY
`logger.` reference in the whole 3.1k-line file — no module logger was ever
defined. So the instant a fast plan had any completeness gap (≈always — a real
run logged **154** gaps), planning raised NameError and died. BOTH planning routes
funnel through this function — the `smith-arch` orchestrator AND the classic
`produce_plan` fallback — so the crash took planning down entirely. THIS is the
dominant "never builds", above the §36.5 mechanisms. Unit tests never hit it (they
don't stream a real gap-bearing plan through the fast branch). FIX: define
`logger = logging.getLogger(__name__)` at module scope (commit d2314cfa).
VERIFIED LIVE: a fresh "contacts CRM" fast run now logs `[planner] fast build —
skipping completeness revise (154 gap(s) logged)` — the exact previously-crashing
line — and emits `plan_ready` with a real plan. NameError count across the run: 0.

### §37.1 Fast speed (Task 3) — skip decomposition, use the one-shot planner
`should_decompose(prompt)` estimates entities from the prompt and trips at a 20-
entity threshold; a simple 3-entity app got mis-classified "large" and routed into
the per-unit page-authoring path (many LLM calls) — a FAST build crawling at ~18%
after 4.5 min. Decomposition is the THOROUGH route; on small/medium apps a single
lean one-shot plan is faster + more predictable. FIX: Fast profile now sets
`decomposition=False`; `orchestrate_planner` honours it (commit fb6797e4).
VERIFIED LIVE: log shows `orchestrate_planner: profile=fast → one-shot (no
decompose)`; planning reached `plan_ready` in ~2 min (was crashing/crawling).

### §37.2 Progress %/ETA/label (Task 4) — authoritative planning progress
Root cause: `generate.py` emits ~75 `status` strings and ZERO `progress` events,
so the ring ALWAYS fell back to frontend interpolation. During planning
(`activeQuestIndex = -1`) that interpolation's `scale = elapsed/virtualDone` factor
BALLOONS the ETA once planning overruns its 180s baseline, and the label was stuck
on the unconditional "Classifying intent…". Reproduced as "18%, ~18 min, wrong
label". FIX (commit 43b1fbb5): during smith-arch planning (build path) emit real
`progress` events — phase "Planning your app", a bounded asymptotic percent
(2%→~18%, never freezes, never overstates) and a profile-anchored ETA
`max(build_floor, total_eta − elapsed)` that plateaus instead of ballooning; plus
an accurate "Planning your app…" status. Frontend hands off cleanly: when the first
real BUILD-phase status arrives it clears the (now-stale) planning `progress` so the
ring resumes per-phase interpolation. VERIFIED LIVE: a run emitted 139 `progress`
events — label "Planning your app", percent climbing 2.1→8.1%, ETA counting down
718→628s (anchored to the 12-min Fast profile, not the old 18-min mirage).

### §37.3 🔴 ENVIRONMENTAL — full disk + corrupted Postgres (a hidden "everything breaks")
The APFS data volume was 100% full (198Gi/228Gi, 130Mi free) — so Postgres
couldn't write, Docker's image metadata corrupted ("unexpected end of JSON input"),
generations failed mid-write, and even the shell couldn't capture command output
(ENOSPC). Recovery: freed 7.8G of REGENERABLE build caches under `output/` (58
generated apps' `node_modules`/`.next`; app source kept) → 10Gi free; restarted the
wedged Docker daemon; Postgres then failed with `FATAL: bogus data in lock file
"postmaster.pid": ""` (an empty/whitespace lock from the hard kill) — removed just
that stale lock (data intact: PG_VERSION=16, base/ present), and it recovered.
`alembic upgrade head` confirmed schema at e7f1a9c2b8d0 (the §36.1 seq fix). All
four services back to 200. LESSON: a full disk on the dev box presents exactly as
"everything randomly breaks" — worth ruling out first.

### §37.4 Honest status
VERIFIED LIVE end-to-end this round: §37.0 (planner NameError — the real blocker),
§37.1 (Fast → one-shot), §37.2 (progress events), §37.3 (env recovery). Planning now
runs clean to `plan_ready` with a real plan and honest live progress. NOT yet
run to a finished preview in THIS session: the full build pipeline after
`[APPROVE_PLAN]` (contracts→…→index, ~8-10 min) was launched but a green preview was
not re-confirmed here — the build path itself was unchanged by these fixes, and its
blocker (planning crash) is now removed. The §36.5.2 SSE-revert-on-stream-close UX
remains a scoped frontend follow-up (heartbeats now flow, which mitigates it).

## §38 Tester bug batch — 16 platform-UI bugs (2026-08-07, component-fixes)

QA filed 16 bugs (BUG-001..013, 015..017; there is no BUG-014). Each was driven
LIVE in the browser (logged in via a minted JWT, real projects), root-caused, fixed,
and re-verified in the running UI — not unit-tested. Parallel Explore agents mapped
the code first. Two findings mattered platform-wide:
- **Stale-build class**: BUG-004 (org counter "3 organization s") and BUG-017 (new
  page disappears) do NOT reproduce in current source — the counter is already
  `organization{n!==1?"s":""}` (verified rendering "1 organization"), and a created
  page survives a full editor reload (`/qa-persist-test` present). QA likely tested a
  stale `.next` build (ties to §37.3's wedged frontend). **Rebuild the frontend
  before QA** or old bugs reappear regardless of fixes.
- **Regression caught by live-testing**: my first NavigationEditor sync used a generic
  `useEffect([nodes])` write-back that oscillated the canvas to 0 nodes. Caught it
  live (GET returned 21 screens, canvas showed 0) and reworked to discrete-event sync.

### Org / onboarding (commit c67bd799)
- **BUG-001** dup close X on the welcome wizard: `OnboardingWizardDialog` rendered its
  own header X AND `DialogContent`'s built-in one. `showCloseButton={false}`. ✓ live.
- **BUG-002** org-card accent clipped: base `Card` `py-6` pushed the `h-1.5` gradient
  accent 24px below the top → square-cornered mid-card strip. `py-0` → flush + clipped
  by the card's rounded overflow. ✓ live (gap 24px→0).
- **BUG-003** footer floats mid-page: `main` was `display:block`; made it a flex column
  + footer `mt-auto`. ✓ live (space-below 186px→40px, no scroll).
- **BUG-005** completed onboarding step had `line-through` on the title beside the tick;
  removed it. ✓ no strikethrough renders.

### Project cards (commit 71ffdfa9)
- **BUG-006/008** status badge overlapped the ⋮ button (−15px) and the menu corner;
  moved the badge to the bottom row beside the date, freeing the corner for the ⋮. ✓ live.
- **BUG-007** duplicate naming "(Copy)(Copy)": `copy_project` unconditionally appended
  " (Copy)". `_unique_copy_name` strips existing "(Copy)"/"(Copy N)" and picks the first
  free suffix vs sibling names (no stack, no collision; tested). Added a **Rename**
  action (⋮ → dialog → `PUT /api/projects/{id}`). ✓ live (renamed a project, PUT 200).

### Data-model + shared dialog (commit 642cddb6)
- **BUG-013 (HIGH)** "Could not load app model — run indexer first": the Re-index
  button only re-ran the failing GET. Now POSTs `/refresh-index` (real indexer, SSE),
  drains it, re-fetches, and AUTO-triggers once on first error. ✓ endpoint returns 200 +
  streams from the browser; happy path renders the ERD (no regression). NOTE: only 1 of
  the built apps had `app-model.json` on disk — most rely on the endpoint's fallback
  candidates, so this recovery path matters broadly.
- **BUG-015/016** modal backdrop bleed-through: shared `DialogOverlay` was `bg-black/50`
  no blur. Now `bg-black/70 backdrop-blur-sm`. ✓ live (New Page dialog: editor behind is
  cleanly frosted).

### Pages & Nav (commit 0e875632) — both HIGH
- **BUG-011** "Add Screen" didn't appear until a tab switch: `NavigationEditor` seeded
  ReactFlow from props at mount only. Added a store→canvas reconcile on id-set change. ✓
  live (21→22 instantly).
- **BUG-012** Save didn't persist the screen: (a) canvas edits never reached the store
  Save serializes — now synced on discrete events (drop/connect/drag-end/delete), NOT a
  generic effect (which oscillated); (b) backend `_reconcile_nav_with_schemas` DROPPED
  any user-added screen with no matching schema — now preserves user screens + their
  edges while schema pages stay authoritative. ✓ live (add → Save → full reload → "New
  Screen" still present; server+canvas both 22).

### Visual editor (commit a4581c31)
- **BUG-009** Save button stayed black next to a green "Saved" indicator; now derives
  from `isDirty` — reads "Saved", fades (opacity-40) + disables when clean. ✓ live.
- **BUG-010** empty page showed a blank dotted grid; added a centered pointer-events-none
  empty-state ("This page is empty — drag a component…"). ✓ compiles/renders.

### Not changed (verified, honest)
- **BUG-004**, **BUG-017**: not reproducible in current source (see stale-build note).
  Left the working code untouched rather than risk a regression on code that's correct.

## §39 PRODUCTION QA GATE — independent re-verification of everything (2026-08-07, component-fixes)

A from-scratch production-readiness pass over BOTH batches (the 16 tester UI bugs
and the 5 do-or-die tasks). Pure verification — NO code changed (worktree stayed
clean). Method: code assertions → full backend suite → live browser/API → live
generation → production build. Five gates + three deep browser gates.

### Gate results
- **QA-0 code assertions**: 20/20 fixes present in committed code; stack healthy.
- **QA-1 full backend suite**: 5,739 passed. 118 failed + 51 errors are ALL
  PRE-EXISTING — proven by swapping my 5 changed backend files to their pre-batch
  baseline and re-running the suspect tests: they failed identically. **My changes
  introduce zero regressions.** (The failures are LLM/agent tests needing API keys,
  EAS/Figma/render externals, node-esm resolution, and a generated-app template
  `buildNavItems` assertion — none in my changed modules.)
- **QA-2 16 UI bugs, live**: all re-verified via DOM + API (e.g. BUG-002 gap 0,
  BUG-003 footer space 40/no-scroll, BUG-001 one close icon, BUG-009 Saved/disabled/
  0.4, BUG-012 "New Screen" persisted, BUG-013 refresh-index 200+streams, BUG-015/16
  backdrop blur(8px)+0.7, BUG-017 /qa-persist-test survives reload).
- **QA-4 production build**: `next build` SUCCEEDED (full route table, 0 hard
  errors); served with `next start` and browsed it — BUG-002/003/004 render correctly
  in the PRODUCTION bundle. This is the real deploy gate and closes the stale-build
  risk that explains most of "the team says it still breaks" (they tested stale
  `.next` bytes). **Rebuild the frontend before QA.**

### Do-or-die tasks, deep browser re-test (DOQA)
Drove a fresh app ("Recipe Box") through the real UI on the production build:
- **Task 1 chat flow — FULLY VERIFIED LIVE.** User msg posts once; correct sequence
  (describe → dossier → "Choose How To Build" Fast/Complete in place, NOT after a
  "Begin Quest"); **single click builds** (the "click 4-5×" bug is gone — 0 seq-NULL,
  0 chat-500s live); **navigate away→back restores** (transcript in order, live build
  reconnected 5.8%→9.2%, **0 leaked signal bubbles**).
- **Task 4 progress — VERIFIED LIVE in UI**: "Planning your app…" label, 5.8→9.2%
  bounded, ETA ~11m→~10m honest.
- **Task 3 speed — VERIFIED (log)**: `profile=fast → one-shot (no decompose)`.
- **Task 5 planner — VERIFIED (QA-3)**: completeness-skip runs, 0 NameErrors,
  plan_ready.
- **Task 2 Smith — comprehension VERIFIED** (accurate recipe-app dossier); live
  add/edit/delete NOT re-run this pass.

### Honest blockers (API)
Mid-pass the ANTHROPIC_API_KEY credits were exhausted (user will not recharge now).
Two items therefore remain to close once credits return: (1) a fresh full-build
**wall-clock** timing to completion (a full fast build DID complete earlier this
session — Contacts CRM, `Commit: d5b12a4`), and (2) a **live Smith edit/delete** op.
Everything else above was verified before/independent of the exhaustion.

---

## 32. Current State Audit (2026-08-26) — the smithv2 / a2ui rebuild

§27 (2026-07-21) was the last full audit; §28–§31 are dated addenda ending
2026-07-26. Since then the codebase moved onto branch **`smithv2`**, which is
not an increment — it is a re-architecture of how an application is generated,
edited, and verified. This section is the authoritative overlay for that work.
**When any earlier section (including §27) and §32 disagree, §32 wins.** It was
written from a direct read of the on-disk `smithv2` code on 2026-08-26.

Drift tags as in §27: 🆕 NEW · ⚠️ CORRECTS · ➕ EXTENDS · ✓ CONFIRMS.

### 32.0 The one-paragraph delta

The generator is no longer a hand-rolled relay of LLM agents that write files
and hope they compile. It is now three things standing on each other: a
**checkpointed LangGraph pipeline** (the spine), a **Living Application
Blueprint** that is the deterministic source of truth every artifact is
projected from, and an **A2UI composer** (an external MCP server, `agent2ui`)
that designs each page's *surface* while a deterministic binder attaches the
data and workflows. Editing is done by **Smith**, an Actor–Critic loop whose
answer is read from the git diff, not from the model's prose. Verification is a
**ship → heal** cycle that gives a build a blocking verdict and repairs it
deterministically. The through-line of the whole rebuild is *§116 of the PRD*:
**the model decides what an artifact should be; deterministic code decides
whether it is allowed in.**

### 32.1 Generation spine — a checkpointed LangGraph `StateGraph` 🆕 NEW

`services/pipeline_graph.py` is the default generation spine (opt out with
`FORGE_LANGGRAPH_PIPELINE=0` to fall back to the legacy `_run_relay_pipeline`
in `routers/generate.py`, which is retained for the LLM/IR and Figma paths).

Topology (declared as edges, not control flow):

```
bootstrap → maquettes → discovery → foundation → design → contracts
  → schema → workflows → rules → runtime → pages →[archetype?]→ pages_gate
  → finish → finish_gate → ship ⇄ heal
```

- **Resumable.** Every node completion is checkpointed to
  `data/pipeline_checkpoints.sqlite3`, keyed by the project slug (`thread_id`).
  A killed build relaunched with the same slug replays instantly through
  completed nodes and continues from the first unfinished one.
- **`maquettes`** — authors dashboard / collection / record *maquettes* (design
  mockups) after reading the montage "composition reference"
  (`services/plan_finalize.py::ensure_composition_reference`). These tell each
  screen kind what it must carry (KPIs, a primary chart, etc.) before A2UI draws it.
- **`design`** — the design-authority chain: per-app Design DNA (§31) →
  brief-canonical / design agent → brand auto-detect → token compile.
- **`pages`** — product brief → nav-flow → shell layout → the per-page schema
  pipeline (`services/schema_pipeline.py`) → auth page schemas → CTA / coverage gates.
- **`ship` ⇄ `heal`** — the agentic verify loop (see §32.5). Bounded by
  `FORGE_HEAL_ROUNDS` (default 1). *The LLM never chooses the topology* — only
  what gets repaired inside `heal`.
- **LangSmith tracing** with `LANGSMITH_TRACING=true` — one trace tree per build.
- **SSE bridge** — nodes push the same event dicts the legacy relay yielded into
  an `asyncio.Queue`; `run_pipeline_graph` drains it, so callers keep the
  unchanged `AsyncIterator[dict]` contract.

### 32.2 The Living Application Blueprint — deterministic source of truth 🆕 NEW

This is the architectural centre of the rebuild. `services/blueprint/` is a
24-module engine (`service.py`, `orchestrator.py`, `assembly.py`, `projection.py`,
`page_planner.py`, `api_derivation.py`, `completeness.py`, `functional_completeness.py`,
`verification.py`, `visual_verification.py`, `migration_ledger.py`, `references.py`,
`ids.py`, `approval.py`, `run_ledger.py`, `scoreboard.py`, `workflow_slots.py`,
`decision_memory.py`, `plan_forecast.py`, `figma_layout.py`, `agent_contract.py`,
`executors.py`, `migrations.py`, …). It implements a PRD whose sections the code
cites directly (§12–§120). The load-bearing rules:

- **The source-of-truth chain (PRD §115):** `Approved User Intent → Living
  Blueprint → Generated Implementation`. Per **§120**, anything that mutates
  application behaviour *without passing through the Blueprint is
  architecturally incorrect*. `services/blueprint/service.py` is the only
  supported way to change an app's definition.
- **Deterministic by design (§116):** every module in the package except
  `executors.py` makes *no* model call. `executors.py` is the single seam where
  a model interprets — it builds a prompt from the Blueprint, calls Claude, and
  returns an `AgentResult`; `apply_agent_result` then refuses any write outside
  that agent's declared §30 boundary regardless of what the model asked for.
- **The Blueprint is schema-constrained.** It validates against
  `contracts/blueprint.schema.json`, which is *generated* from the Zod source in
  `packages/schema/src/blueprint` — one definition, two languages.
- **Identity, versioning, history (§12/§91/§92/§93):** every artifact's ID comes
  from an `IdAllocator` (a re-run cannot renumber); an accepted change snapshots
  the prior version for rollback and records the request + RFC-6902 diff +
  touched artifacts.
- **Orchestration is a DAG, not a swarm (§28):** `orchestrator.py` resolves
  declared node dependencies into concurrency levels; illegal state transitions
  (§94) raise; impact analysis (§71) walks the Application Knowledge Graph (§19),
  which is *derived from artifact references* rather than stored separately.
- **Projections write the app; `assembly.py` makes it runnable.** Projections
  put schema modules, page schemas, workflow definitions, the route graph,
  tokens and seed rows on disk; assembly adds the Next.js scaffold and vendors
  the engine packages. It deliberately does **not** reuse `app_emitter`'s
  13-step LLM-repair cascade — deterministic projections don't need repairing.
- **Endpoint + migration:** `routers/blueprint_generate.py` is the
  Blueprint-driven build entry; `scripts/migrate_project_to_blueprint.py` +
  `services/blueprint_backfill.py` migrate legacy projects; `fleet/blueprints` +
  `fleet/blueprint-baselines.json` hold regression baselines. The system is in a
  managed migration — the relay spine and the Blueprint projection path coexist.

### 32.3 A2UI composition — `agent2ui` MCP designs the surface 🆕 NEW

Design is delegated to an external MCP server, the **`agent2ui`** repo
(`github.com/architect-moaaz/agent2ui`, cloned beside TentoroForge). It turns a
requirement + a design montage into a **validated A2UI surface** — declarative
JSON the composer must defend (generate → schema/structure/coverage/asset checks
→ retry). Tools: `generate_a2ui_surface`, `derive_ui_contract`,
`plan_pages_from_montage`, `extract_theme_from_montage`, `validate_a2ui_payload`,
`list_providers`. Catalogs: `plc` (21 components) and `forge` (93).

- **Forge launches it itself** at generation time via
  `services/a2ui_authority.py` (`compose_page_via_a2ui`,
  `compose_dashboard_via_a2ui`, `compose_pages_via_a2ui`) using
  `StdioServerParameters(command=sys.executable, args=[$A2UI_REPO/tools/a2ui-mcp/server.py])`.
  Wiring is one env var: **`A2UI_REPO`** must point at the agent2ui checkout
  (`availability()` reports it up front).
- **Whole-page-set context, one page per call**
  (`services/a2ui_ui_composition.py`): coherence (navigation, density, empty-state
  voice) is a property of the *set*, so every call carries the same shared page
  set + design system + UI registry — but the set is not crammed into one
  request (32 pages won't fit, and one call is all-or-nothing).
- **The composer designs; a deterministic binder decides behaviour.** A2UI says
  a page *has* a primary action and *where* it sits; which workflow that action
  dispatches is a Blueprint fact (`PageContract.dispatches`) attached afterward.
  `services/a2ui_to_forge.py` translates surface → Forge page schema: the
  composition (`updateComponents`) is kept; the invented sample data
  (`updateDataModel`) is **read and discarded** (importing it would ship fiction
  that every gate reads as perfect). Data-bearing props are pointers
  (`{"path":"/tasks/rows"}`) rewritten to live bindings (`"{{tasks}}"` + a real
  `dataSource`). KPI intent is recovered deterministically — a MetricTile label
  is matched against the entity's real enum values in the registry to emit the
  `filter` the label implies (fixing "three tiles all read 10").
- **⚠️ CORRECTS setup:** the a2ui server uses the **mcp 1.x** low-level `Server`
  API (`@app.list_tools()` / `@app.call_tool()` / `@app.list_resources()`).
  `mcp` 2.x renamed those, so `backend/requirements.txt` must pin **`mcp>=1.0,<2.0`**
  (1.29.1 verified) — 2.x makes the server crash on startup while
  `availability()` still falsely reports "ok" (it only checks that `mcp` imports).

### 32.4 Smith — the Actor–Critic app editor 🆕 NEW / ⚠️ CORRECTS §7

Smith replaces the old fix/patch agents as the conversational editor. It is not
one ReACT turn — `services/smith_orchestrator.py` wraps `run_smith_agent` in a
bounded Actor–Critic-with-guards loop:

1. invoke Smith with the ask + running corrective context;
2. if any file changed, run the guard suite;
3. green → commit, **synthesize the answer from the actual git diff**, return;
4. red → parse failures into the next-turn corrective prompt, loop;
5. turns exhausted → `git revert` every applied change, return an honest failure
   naming the residual guard failures.

Answer text comes from the diff, not Smith's prose — this kills the "believes he
did it" class of lie by construction (the orchestrator's `answer` is
authoritative; Smith's own is advisory). All boundaries (`smith_fn`, `guard_fn`,
`diff_fn`, `commit_fn`, `revert_fn`) are injectable seams, so the loop is
testable without the LLM, git, or disk. Smith's tool palette
(`services/smith_tools.py::TOOL_CATALOG`) reuses the fix-assistant's read-only
inspectors and adds `list_components_tool` (reads
`packages/registry/dist/component-contracts.json`) plus terminals `propose_fix`,
`answer`, `ask_user`. Supporting cast: ~30 `smith_*` services
(`smith_chat_v2`, `smith_plan_and_apply`, `smith_edit_tools`, `smith_decide`,
`smith_move_dispatcher`, `smith_blueprint`, `smith_grounding`, `smith_memory`,
`smith_find_source`, `smith_narrator`, `smith_session`, …). **Known live gap**
(`docs/SMITH-VERBS.md`, 2026-09-01): the catalog advertises far more verbs than
have write handlers, so Smith can read a brief correctly and still answer
"nothing to change" — expanding the write moves is an open workstream.

### 32.5 Ship → Heal — the self-verify + deterministic autofix cycle 🆕 NEW

Verification is a graph cycle, not a post-hoc script.

- **`ship`** (`services/ship_report.py::build_ship_report`) folds every
  verification artifact into `ship-report.json`, emits it over SSE
  (`ship_report`), and returns a **verdict** (`pass` / `block`). Under
  `FORGE_SHIP_GATE=strict` a blocking verdict fails the build.
- **`heal`** reads the report's critical/error findings, runs
  `services/platform_heals.py` + `services/repair_dispatcher.py` (the
  deterministic guard sweep) against them, clears the quarantine, and routes
  back through `finish_gate → ship` for a fresh verdict — up to
  `FORGE_HEAL_ROUNDS`. This is the observe→diagnose→repair→re-observe loop as a
  pre-built topology; the LLM only influences *what* is repaired, never the flow.
- **Runtime sidecar:** the Playwright **forge-verify** service (`docker/forge-verify`,
  port 6600, `/healthz` → `{"ok":true,"browsers_warm":true}`) runs the interaction
  + journey passes; `FORGE_AUTOFIX_V2` classifies faults into a taxonomy, runs
  deterministic handlers for known classes and dispatches the rest to Smith with
  a curated context slice, guarded by a git snapshot + auto-revert on regression.
- **Persistence:** new tables `verify_runs` and `fault_records` (see §32.7).

### 32.6 Workflow node catalog — one vocabulary for editor / agent / engine 🆕 NEW

The most recent smithv2 theme (git: *"Workflow nodes are the components: one node
catalog for editor, agent, projection and engine"*).
`services/workflow_node_contracts.py` auto-extracts the node/action/trigger
vocabulary from the runtime's own `templates/runtime/workflows/types.ts` unions +
the handler registrations (`registerActionHandler(...)`, inline
`actionType === "…"`), so the planner prompt (`format_node_catalog`) can only
propose nodes the engine actually executes — a drift guard test fails the build
if an emitted action has no handler or regresses to a stub (`KNOWN_STUBS` is
empty: every action must be functional). `services/node_config_specs.py` is the
paired secret-requirements registry (which provider key each action type needs)
driving `env_scaffold`, `integrations_scaffold`, and binding validation
(providers v1: `resend` email, `anthropic` AI, `s3` uploads; `twilio`/`stripe`
are shaped placeholders).

### 32.7 Platform surface — routers, tables, runtime ➕ EXTENDS §4/§6

- **Backend API: 48 routers** registered in `backend/main.py` (§27 counted 36).
  New/renamed since §27 include: `blueprint_generate`, `verify`, `pages`,
  `decisions`, `open_decisions`, `output_projects`, `field_interactions`,
  `plan_adjust`, `mobile_builds`, `platform_mcp_servers`, `runtime_exceptions`,
  `quality`, `app_actions`, `brand`, `usage`, `navigation`, `_debug_fidelity`.
- **Platform DB: 41 tables** (`appforge` on Postgres). New since the §4 set:
  `verify_runs` + `fault_records` (self-verify), `page_definitions` (Blueprint
  pages), `decision_tables` + `decision_table_versions` + `decision_execution_logs`
  (decision builder), `platform_mcp_servers` (user-facing MCP registry — separate
  from the built-in a2ui/figma MCP), `mobile_builds`, `runtime_exceptions`,
  `node_execution_logs`, `workflow_instances` + `task_instances`,
  `workflow_assignment_policies`, `app_access_policies` + `field_access_policies`,
  and the full org graph (`org_groups`, `org_group_members`, `org_people`,
  `org_roles`, `org_person_roles`).
- **⚠️ CORRECTS setup / run:**
  - Services: backend `:6500`, frontend/editor `:6501`, render-service `:6502`,
    render-scaffold `:6503`, **forge-verify `:6600`**. Launch with
    `PYTHON=<backend venv> bash start-all.sh` — `start-all.sh`'s default
    `PYTHON` is a non-existent 3.11 framework path, so the venv interpreter must
    be passed or it silently falls back to a system Python without the deps.
  - **Alembic migrations do not apply clean** on a fresh DB (`alembic upgrade
    head` → `KeyError` in a merge-migration DAG; single head `svst5_faults`).
    Fresh-DB bring-up: `CREATE SEQUENCE conversations_seq_seq;` (only a migration
    otherwise makes the `conversations.seq` server-default's sequence) → import
    `models` → `Base.metadata.create_all` → `alembic stamp head` (41 tables).
  - a2ui requires the `agent2ui` checkout on disk + `A2UI_REPO` set +
    `mcp>=1.0,<2.0` in the backend venv (§32.3).
  - **All workspace packages must be built, not just the engine/editor stacks.**
    The frontend editor imports `@forge/registry` (`packages/registry`, resolved
    via `main: dist/index.js`); if `registry` is unbuilt, opening any project
    dies with *"Module not found: Can't resolve '@forge/registry'"* on the visual
    editor route (`components/canvas/hooks/useDrop.ts`), blocking every build.
    The stock `npm run build` (a) is ordered wrong — it compiles `@tentoroforge/renderer`
    before its dependency `@forge/patches` (TS2307) — and (b) never builds
    `registry` or the aux packages at all. Build the full set in dependency order:
    `schema → registry → patches → library → renderer → engine → editor`, plus
    `ir`, `compiler`, `patterns`, `figma-parser` for the IR/Figma flows
    (`catalog` is data-only, no build). `registry`'s build additionally emits
    `dist/starter.json` + `dist/component-contracts.json` (the component catalog
    Smith and the a2ui binder read). Fixed 2026-08-26 (branch `component-fixes`).
  - **Fresh-DB `create_all` must import EVERY model module, not just those in
    `models/__init__.py`.** `create_all` only emits tables for classes registered
    on `Base.metadata`, and `models/__init__.py` does not re-export every model —
    `models/deployment.py` (`deployments`) and `models/smith_preference.py`
    (`smith_preferences`) were missed, so those 2 tables never got created. Effect:
    `GET /deployments/latest` 500s (`UndefinedTableError`) on every editor poll,
    and — worse — a **build stage that writes to a missing table throws inside the
    detached build task, which swallows the error, leaving the run hung at 0/22
    with no log**. Bring-up must import all `models/*.py` before `create_all`
    (imports all 42 model tables). Fixed 2026-09-06 (branch `component-fixes`).
  - **`anthropic` SDK ↔ httpx flavour.** `anthropic` 1.4.0+ vendors httpx as
    `httpx2` and its client REJECTS a plain `httpx.Timeout` (raises *"use
    httpx2.Timeout instead"*). `services/blueprint/executors.py::_anthropic()`
    built its client with `httpx.Timeout(...)`, so **every model call on the
    `requirements` node threw** — the node failed, all 21 downstream stages were
    skipped, and the run reported "complete" with `$0.00` usage and 0/22 built
    (the detached build task swallows the error; the real reason is in
    `output/<slug>/.forge/runs/*.jsonl`). Fix: import the flavour the installed
    SDK uses (`try: import httpx2 as httpx / except ImportError: import httpx`)
    so the granular Timeout (connect15/read300/write60/pool15, required for long
    streamed generations) is the type the client accepts. Fixed 2026-09-06 (branch `component-fixes`).

### 32.7.1 Workflow editor — bugs found + fixed (2026-09-06, brutal QA, branch `component-fixes`)

Live QA of the generated-app **Workflow editor** (the platform's visual workflow
builder, `frontend/src/components/workflow/*` + backend `routers/workflows.py` +
`runtime/engine.py`). Root-fixed so every future generated app benefits:

- **W1 — list always showed "0 steps".** `routers/workflows.py::workflow_list_item`
  computed `step_count=len(definition["steps"])`, but generated workflows store
  their graph in `definition.nodes`/`edges` and leave `steps` empty. Fixed: count
  the operational nodes (`nodes` minus triggers) when `steps` is absent. (Add a
  Pet now 5, Book an Appointment 13, …)
- **W2 — Simulator "Workflow definition '<id>' not found".** `runtime/engine.py::
  _load_definition` only looked in the legacy `<output_dir>/workflows/<id>.json`,
  but the Blueprint projection writes to
  `<output_dir>/app/src/lib/workflows/definitions/<id>.json` (what the list/editor
  resolve by via `_workflows_path`). Fixed: engine now prefers the projected dir,
  falls back to legacy. Simulate runs end-to-end again.
- **W3 — every node executed (and logged) twice.** `_find_start_nodes` added ANY
  `trigger`-typed node as an entry point even when it had an incoming edge, so a
  chained trigger (Start → "form submitted") entered the graph twice. Fixed: a
  start node is one with **no incoming edge**.

### 32.8 What still holds

§9A (schema / renderer contract), §13 (bindings — `{{expr}}` over a data engine),
§14 (rules / FEEL-lite / decision tables), §15 (workflow runtime), §17 (org-aware
generated-app auth), §22 (multi-tenancy / RBAC), and the per-app **Design DNA**
(§31) all remain accurate and are, if anything, more load-bearing now — the
Blueprint and the a2ui binder both read the registry, the rules, and the design
system these sections describe. The relay-pipeline narrative in §5.9 and §27.5
is now the *fallback* path (`FORGE_LANGGRAPH_PIPELINE=0`); the LangGraph spine in
§32.1 is the default.
