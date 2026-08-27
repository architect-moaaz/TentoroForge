# Tentoro Forge — Development Plan

**Last updated**: 2026-04-10
**Status**: Post-MVP roadmap

---

## 1. Current State (What's Already Built)

### ✅ Core Generation Pipeline
- **Chat-driven planning** with multi-agent orchestration (Claude Agent SDK)
- **Figma import** with styles.json extraction, image download, Figma MCP integration
- **AHTML system** (`packages/ahtml`) — annotated HTML as design-layer IR
- **IR compiler** (`packages/compiler`) — JSON IR → TSX with deterministic output
- **Pattern library** (`packages/patterns`) — 9 fragment types (table, form, detail, kanban, etc.)
- **Registry + validator** — tracks entities, routes, components across agents
- **Domain detection** with industry-specific theme defaults
- **Git versioning** — every agent edit is committed, full history tracked

### ✅ Editors (All Functional)
- **Visual Editor** (blueprint-aligned) — live iframe + bridge.js + AST edits + `code_editor` agent for AI-mediated changes
- **AHTML Editor** (GrapeJS) — component palette, data binding, workflow binding, page flow, annotation panel
- **Data Model Editor** — ERD via React Flow, DB browser, SQL console, seed data
- **Workflow Editor** — 15+ node types (triggers, actions, AI nodes, human-in-loop, conditions)
- **Rules Editor** — field-level access policies, FEEL-lite expression engine
- **Navigation Editor** — React Flow page graph, sidebar/topbar link config
- **Code Editor** — Monaco, read-only with AI edits

### ✅ Platform Features
- **Multi-tenancy** — orgs with roles, teams, departments, groups, CSV import
- **Auth** — JWT access/refresh, rate limiting, account lockout
- **Live preview** — Next.js dev server per project on dynamic ports, HMR-aware
- **Export** — Dockerfile, docker-compose, README, git push to remote
- **Templates** — gallery infrastructure (content still empty)
- **Observability** — Sentry, structured logs, Prometheus metrics
- **SSE streaming** — real-time agent progress to frontend
- **Office visualization** — agent pipeline visualized as a virtual office

### ⚠️ Partial / Needs Work
- **Figma fidelity** — works via Figma MCP but still loses some detail; needs Phase 1 vision improvements
- **AHTML ↔ Visual Editor bridge** — two parallel editors, not unified
- **Observability dashboards** — metrics exist but no UI to view them
- **Test coverage** — backend has tests, generated apps have none
- **Templates** — infrastructure only, no actual template content

### ❌ Not Built
- **Deployment automation** (Vercel, AWS, Railway, etc.)
- **Messaging / real-time collaboration** in generated apps
- **Mobile app generation** (React Native, Expo, Capacitor)
- **MFA, OAuth/SSO** (router exists, minimal)
- **Password reset, email verification**

---

## 2. New Feature Specifications

### Feature A: One-Click Deployment

**Goal**: User clicks "Deploy" on a generated project → app is live on a public URL within 60 seconds.

#### A.1 Supported Targets
| Target | Why | Complexity |
|--------|-----|------------|
| **Vercel** | Best Next.js host, zero config | Low |
| **Railway** | Full stack + DB in one place | Medium |
| **Cloudflare Pages** | Global edge, free tier | Low |
| **Self-hosted Docker** | For enterprise users | Medium |
| **AWS Amplify** (later) | For AWS-native orgs | High |

#### A.2 Architecture
```
┌─────────────────────────────────────────────────────┐
│  Project Workspace → "Deploy" button                │
│       │                                             │
│       ▼                                             │
│  DeploymentDialog                                   │
│  - Pick target (Vercel / Railway / Cloudflare)      │
│  - Connect account (OAuth)                          │
│  - Environment variables                            │
│  - Database provisioning (if needed)                │
│  - Custom domain (optional)                         │
└─────────────┬───────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  Backend: deployment_router                          │
│  - POST /api/projects/:id/deploy                    │
│  - SSE stream of deployment progress                │
│  - Per-target adapter (vercel_adapter, railway_...)  │
│  - Secrets storage (env vars encrypted)             │
└─────────────┬───────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│  Deployment Adapter                                  │
│  - Validates build locally (`npm run build`)        │
│  - Uploads artifact or pushes to deploy branch       │
│  - Calls target's API to create deployment          │
│  - Polls status until live                          │
│  - Returns public URL                               │
└─────────────────────────────────────────────────────┘
```

#### A.3 Implementation Tasks
| # | Task | Files | Estimate |
|---|------|-------|----------|
| A1 | Build validation service (runs `npm run build`, reports errors) | `backend/services/build_validator.py` | 1d |
| A2 | Secrets vault (encrypted env var storage) | `backend/models/project_secret.py`, `services/secrets_vault.py` | 2d |
| A3 | Vercel adapter — OAuth connect + deploy via REST API | `backend/services/deploy/vercel_adapter.py` | 2d |
| A4 | Railway adapter — CLI or GraphQL API | `backend/services/deploy/railway_adapter.py` | 2d |
| A5 | Cloudflare Pages adapter | `backend/services/deploy/cloudflare_adapter.py` | 2d |
| A6 | Deployment router + SSE progress | `backend/routers/deployments.py` | 1d |
| A7 | DeploymentDialog UI with target picker, env var editor, progress | `frontend/src/components/projects/DeploymentDialog.tsx` | 3d |
| A8 | Deployment history view | `frontend/src/components/projects/DeploymentHistory.tsx` | 1d |
| A9 | Custom domain config (CNAME instructions) | `frontend/src/components/projects/DomainConfig.tsx` | 1d |
| A10 | Post-deploy health check + preview URL | `backend/services/deploy/health_check.py` | 1d |

**Total**: ~16 days (~3 weeks for 1 engineer)

#### A.4 Blueprint Alignment
Fits naturally into the existing export system (`backend/routers/export.py`). The Dockerfile/docker-compose generators stay for self-hosted; new adapters for managed platforms.

---

### Feature B: Messaging (In-App and Real-Time)

**Goal**: Enable real-time messaging/chat in both:
1. The **Tentoro platform itself** (team collaboration on projects)
2. **Generated apps** (as a first-class feature users can add to their apps)

#### B.1 Two Distinct Scopes

**B.1.1 Platform Messaging** — Tentoro team collaboration
- Team members can comment on specific elements in the Visual Editor
- Chat threads per project, per page, per element
- Mentions (`@user`), resolving comments
- Real-time presence ("Moaaz is editing the login page")
- Activity feed (who did what when)

**B.1.2 Generated App Messaging** — as a feature users can add
- Drop-in messaging component library for generated apps
- User-to-user chat, group chat, channels
- Read receipts, typing indicators, file attachments
- Backed by WebSocket + Redis pub/sub
- Optional: end-to-end encryption (Phase 2)

#### B.2 Architecture
```
┌──────────────────────────────────────────────────────┐
│  Platform Messaging (Tentoro)                        │
│                                                      │
│  ┌──────────────┐   ┌──────────────┐                │
│  │ Comment on   │   │ Project chat │                │
│  │ element      │   │ (team)       │                │
│  └──────┬───────┘   └──────┬───────┘                │
│         │                  │                        │
│         ▼                  ▼                        │
│  WebSocket + message queue (Redis)                   │
│         │                                            │
│         ▼                                            │
│  PostgreSQL (messages, threads, reactions)           │
└──────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────┐
│  Generated App Messaging (drop-in library)           │
│                                                      │
│  @tentoro/messaging package                          │
│    - <ChatWindow />                                  │
│    - <MessageList />                                 │
│    - <MessageInput />                                │
│    - <UserPresence />                                │
│    - useChatChannel() hook                           │
│                                                      │
│  Backed by:                                          │
│    - WebSocket server (embedded in generated app)    │
│    - Or: hosted service (Tentoro Messaging as SaaS)  │
└──────────────────────────────────────────────────────┘
```

#### B.3 Implementation Tasks (Platform Messaging — B.1.1)
| # | Task | Files | Estimate |
|---|------|-------|----------|
| B1 | WebSocket server with auth (JWT on connection) | `backend/services/websocket_server.py`, `backend/routers/ws.py` | 2d |
| B2 | Comment model + thread model | `backend/models/comment.py`, `backend/models/thread.py` | 1d |
| B3 | Comment API (CRUD, reactions, resolve) | `backend/routers/comments.py` | 1d |
| B4 | Presence tracking (who's online per project/element) | `backend/services/presence.py` | 1d |
| B5 | Comment anchors (attach to element via xpath/data-intent) | `backend/services/comment_anchor.py` | 1d |
| B6 | Frontend: CommentPopover on selected element in Visual Editor | `frontend/src/components/visual-editor/CommentPopover.tsx` | 2d |
| B7 | Frontend: Project chat panel | `frontend/src/components/chat/ProjectChatPanel.tsx` | 2d |
| B8 | Frontend: Presence avatars in toolbar | `frontend/src/components/presence/` | 1d |
| B9 | Activity feed | `frontend/src/components/activity/ActivityFeed.tsx` | 1d |
| B10 | Notification system (badge count, desktop notifs) | `frontend/src/components/notifications/` | 1d |

**Platform messaging total**: ~13 days

#### B.4 Implementation Tasks (Generated App Messaging — B.1.2)
| # | Task | Files | Estimate |
|---|------|-------|----------|
| B11 | Design `@tentoro/messaging` package structure | `packages/messaging/` | 1d |
| B12 | WebSocket server template (Socket.IO-based) | `packages/messaging/src/server/` | 2d |
| B13 | React components: ChatWindow, MessageList, MessageInput | `packages/messaging/src/client/` | 3d |
| B14 | Hooks: useChatChannel, useTyping, usePresence | `packages/messaging/src/hooks/` | 2d |
| B15 | Drizzle schema for messages, channels, members | `packages/messaging/src/schema/` | 1d |
| B16 | Integration template for generated apps (code_generator injects messaging setup) | `backend/agents/code_generator.py` changes | 1d |
| B17 | Demo: generate an app with messaging feature | — | 1d |

**Generated app messaging total**: ~11 days

**Feature B total**: ~24 days (~5 weeks for 1 engineer)

#### B.5 Blueprint Alignment
Platform messaging fits the blueprint's Section 18.2 (multi-user collaboration, deferred to post-MVP). Generated app messaging is a new feature library.

---

### Feature C: Mobile App Development

**Goal**: Generate **mobile apps** alongside web apps from the same plan. Target iOS/Android via React Native + Expo.

#### C.1 Approach Options

**Option 1: React Native + Expo (Recommended)**
- Same TSX-like code as Next.js
- Shared data models, API routes, types
- Expo makes it instant to preview on phone
- Native feel, camera/sensors/push notifications

**Option 2: PWA with Capacitor**
- Wraps the web app in a native shell
- Reuses 100% of the Next.js codebase
- Faster to implement but feels less native
- Good for internal tools

**Option 3: Flutter**
- Would require an entirely new codegen pipeline
- High complexity, rejected

**Recommendation**: Start with Capacitor (low effort, reuses existing code), add React Native as Phase 2.

#### C.2 Architecture
```
┌──────────────────────────────────────────────────────┐
│  User prompt: "Build a CRM with mobile app"          │
│       │                                              │
│       ▼                                              │
│  Planner agent produces plan with `platforms: [web, mobile]`│
│       │                                              │
│       ▼                                              │
│  Code Generator:                                     │
│    - Web: existing Next.js pipeline (unchanged)      │
│    - Mobile: new React Native/Expo pipeline          │
│       │                                              │
│       ▼                                              │
│  Output:                                             │
│    /output/{project}/                                │
│      ├── web/    (Next.js app)                       │
│      ├── mobile/ (Expo app)                          │
│      └── shared/ (types, API client, constants)      │
│       │                                              │
│       ▼                                              │
│  Preview:                                            │
│    - Web: browser iframe (existing)                  │
│    - Mobile: Expo QR code + iOS simulator / Android  │
└──────────────────────────────────────────────────────┘
```

#### C.3 Shared Layer (Critical)
The key to making this work is sharing code between web and mobile:

```
shared/
├── types/          # Entity TypeScript types (generated from schema)
├── api-client/     # Typed fetch wrappers for API routes
├── hooks/          # Platform-agnostic data hooks (useQuery wrappers)
├── validation/     # Zod schemas
└── theme/          # Design tokens (used by both Tailwind and RN-StyleSheet)
```

#### C.4 Implementation Tasks
| # | Task | Files | Estimate |
|---|------|-------|----------|
| C1 | Plan schema: add `platforms` field (web, mobile) | `backend/schemas/plan.py` | 0.5d |
| C2 | Design token system that works for both CSS and RN StyleSheet | `packages/theme/` | 3d |
| C3 | Shared types + API client generator (shared layer) | `packages/shared-gen/` | 3d |
| C4 | Expo project template (app.json, metro.config, babel) | `templates/expo/` | 1d |
| C5 | React Native component library matching shadcn/ui primitives | `packages/rn-ui/` (Button, Input, Card, etc.) | 5d |
| C6 | Mobile page generator — converts AppIR pages to RN screens | `packages/mobile-compiler/` | 5d |
| C7 | React Navigation setup (stack + tabs based on plan navigation) | `templates/expo/src/navigation/` | 2d |
| C8 | Mobile-specific IR nodes (BottomTabs, StackHeader, SafeArea) | `packages/ir/src/types.ts` additions | 2d |
| C9 | Auth flow for mobile (secure storage, biometric) | `templates/expo/src/auth/` | 2d |
| C10 | Backend: mobile generation pipeline phase | `backend/services/mobile_pipeline.py` | 3d |
| C11 | Preview: Expo dev server management | `backend/services/mobile_preview.py` | 2d |
| C12 | Frontend: Mobile preview tab with QR code + device selector | `frontend/src/components/mobile-preview/` | 2d |
| C13 | Build pipeline: EAS Build integration for .ipa/.apk | `backend/services/eas_build.py` | 3d |
| C14 | One-click deploy to TestFlight / Google Play Internal | `backend/services/deploy/app_stores.py` | 3d |

**Feature C total**: ~36 days (~7-8 weeks for 1 engineer)

#### C.5 Blueprint Alignment
The blueprint doesn't explicitly cover mobile, but the plan→IR→code architecture extends naturally. The IR just gets a new target compiler (mobile alongside web).

---

## 3. Phased Roadmap

### Phase 0: Foundation Hardening (2 weeks)
Before adding new features, stabilize what's built.

**Goals:**
- Fix the parallel agent timeout issues (already done today)
- Add proper vision for AI agents (screenshots to code_editor)
- Add approval gate for AI edits (diff preview before commit)
- Add intent annotations (`data-intent="locked"` etc.)
- Improve Figma fidelity (we did this today)
- Write generated-app test templates

**Deliverables:**
- Visual Editor with vision-enabled agent
- Diff preview UI
- Intent annotation schema
- Test templates shipped with every generated app

### Phase 1: One-Click Deployment (3 weeks)
Ship deployment to Vercel + Railway + Cloudflare.

**Milestones:**
- Week 1: Vercel adapter + secrets vault + deployment UI
- Week 2: Railway + Cloudflare adapters
- Week 3: Custom domains, health checks, deployment history

**Success metric**: User can go from "new project" to "live URL" in under 5 minutes.

### Phase 2: Platform Messaging (3 weeks)
Team collaboration inside Tentoro.

**Milestones:**
- Week 1: WebSocket server + comment anchors
- Week 2: Comment UI in Visual Editor, presence indicators
- Week 3: Project chat, activity feed, notifications

**Success metric**: Two users can comment on the same element simultaneously with real-time updates.

### Phase 3: Mobile App Generation (6-8 weeks)
The big one. Start with Capacitor for Phase 3a, React Native for Phase 3b.

**Phase 3a: Capacitor Wrapper (2 weeks)**
- Wrap generated Next.js apps as native shells
- iOS/Android builds via Capacitor CLI
- One-click export to mobile

**Phase 3b: React Native Generation (6 weeks)**
- Shared types/API client layer
- RN component library (rn-ui package)
- Mobile IR compiler
- Expo preview integration
- EAS Build → TestFlight/Play Store deploy

**Success metric**: Same plan generates web + mobile apps, both functional with shared data layer.

### Phase 4: Generated App Messaging (3 weeks)
Messaging as a library users can add to their generated apps.

**Milestones:**
- Week 1: `@tentoro/messaging` package with WebSocket server template
- Week 2: React components, hooks, Drizzle schema
- Week 3: Plan schema changes, code generator integration, demo app

**Success metric**: Users can say "add team chat to this app" and get a working messaging feature.

### Phase 5: Platform Polish (2 weeks)
- OAuth/SSO (GitHub, Google, Microsoft)
- MFA (TOTP)
- Password reset + email verification
- Template content (10+ starter templates)
- Observability dashboards

---

## 4. Total Timeline

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 0: Foundation | 2 weeks | 2 weeks |
| Phase 1: Deployment | 3 weeks | 5 weeks |
| Phase 2: Platform Messaging | 3 weeks | 8 weeks |
| Phase 3: Mobile (Capacitor + RN) | 8 weeks | 16 weeks |
| Phase 4: App Messaging | 3 weeks | 19 weeks |
| Phase 5: Polish | 2 weeks | 21 weeks |

**Total**: ~21 weeks (~5 months) for 1 engineer. With 2 engineers in parallel on Phase 1/2 and Phase 3, this compresses to **~14 weeks** (~3.5 months).

---

## 5. Dependencies & Risks

### Cross-Feature Dependencies
- **Deployment ← Build validation**: Can't deploy broken code. Build validator from Phase 0.
- **Mobile ← Shared types**: RN app needs the same types as web. Shared-gen package must come first.
- **App messaging ← WebSocket infra**: Platform messaging (Phase 2) builds the WebSocket infrastructure that app messaging (Phase 4) reuses.

### Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Figma fidelity still low after vision | High | Phase 0 focused investment; fallback to manual refinement |
| Vercel/Railway API changes | Medium | Abstract behind adapter interface; easy to swap |
| RN ecosystem fragmentation (Expo vs bare) | Medium | Start with Expo managed, bare as escape hatch |
| Real-time collab conflicts | High | Use CRDTs (Yjs) or OT for concurrent edits — add to Phase 2 |
| Mobile preview UX on Tentoro platform | Medium | Start with QR code (simple), native simulator (complex) later |
| App messaging quality bar | Medium | Start with basic chat; match Slack-level polish is multi-quarter effort |

---

## 6. Success Metrics

### Phase 0
- Figma import produces AHTML with >90% visual fidelity (measured by screenshot diff)
- AI edits preserve user customizations 100% of the time (via intent annotations)

### Phase 1
- Time from "generate" to "live URL": <5 minutes
- Deployment success rate: >95%
- Number of supported targets: 3 (Vercel, Railway, Cloudflare)

### Phase 2
- 2+ concurrent users can collaborate on the same project without conflicts
- Comment-to-notification latency: <500ms

### Phase 3
- Generated mobile app builds on both iOS and Android without manual intervention
- Shared code between web and mobile: >60%
- Preview QR code works on physical device

### Phase 4
- Messaging feature can be added to any generated app with 1 command
- Message latency: <200ms in same region

### Phase 5
- OAuth login works for all major providers
- 10+ production-ready templates

---

## 7. Out of Scope (Explicitly Deferred)

- **Desktop apps** (Electron, Tauri)
- **Browser extensions**
- **Voice/video calling** (use third-party SDKs like Daily.co)
- **Payment processing** (integrate Stripe via template, don't build from scratch)
- **Advanced AI features** (RAG, embeddings, fine-tuning) — use existing infra
- **White-labeling Tentoro itself**
- **On-premise enterprise deployment** of Tentoro platform
- **Backup & disaster recovery automation** beyond what's in blueprint

---

## 8. Resource Requirements

### Team
- **Minimum**: 1 full-stack engineer (fulfills all phases sequentially in ~5 months)
- **Optimal**: 2 engineers + 1 designer
  - Engineer A: Phase 0 → Phase 1 → Phase 5
  - Engineer B: Phase 2 → Phase 3 → Phase 4
  - Designer: UX for DeploymentDialog, ChatPanel, MobilePreview

### Infrastructure
- Vercel/Railway/Cloudflare accounts for testing deployment adapters
- Redis instance for WebSocket pub/sub (Phase 2+)
- Apple Developer account + Google Play console (Phase 3)
- Sentry (already have), DataDog or similar for deeper observability (Phase 5)

### Third-Party Services
- **Vercel API** (Phase 1)
- **Railway GraphQL API** (Phase 1)
- **Cloudflare Pages API** (Phase 1)
- **Expo EAS** (Phase 3)
- **Apple/Google store APIs** (Phase 3)
- **Yjs** for CRDT-based real-time collab (Phase 2, if going beyond basic messaging)

---

## 9. Key Decisions to Make Before Starting

1. **Deployment pricing model**: Free deployments only, or metered billing?
2. **Mobile approach**: Capacitor-first or RN-first?
3. **Messaging: SaaS or self-hosted**: Host a Tentoro Messaging service or embed in each generated app?
4. **Real-time collab level**: Comments/presence only, or full CRDT co-editing?
5. **Target persona**: Internal tools (fewer mobile needs) vs consumer apps (mobile critical)?

---

## 10. Immediate Next Steps

If approved, the concrete next actions are:

1. **This week**: Finalize Phase 0 scope and assign
2. **Week 1**: Implement vision for code_editor agent (pass screenshots)
3. **Week 2**: Add diff preview UI + intent annotations
4. **Week 3**: Start Phase 1 (Vercel adapter)

All feature branches should merge to `main` behind feature flags so the platform stays shippable throughout.

---

## 11. Additional Feature Specifications

These areas have significant existing investment but need hardening for production use.

---

### Feature D: Generated App Runtime Engine

**Current state**: Dev-mode only. `preview_manager.py` spawns `npx next dev` per project on ports 3200-3299, with docker-compose PostgreSQL, health checks (30s polling), and auto-restart (3 attempts with exponential backoff).

#### D.1 What's Missing
- **Production mode** — only `next dev`, no `next build && next start`
- **Log capture** — stdout/stderr routed to `/dev/null`, not persisted
- **Resource limits** — no memory/CPU caps per project
- **Log aggregation** — no central log viewing
- **Process isolation** — all projects run as same user
- **Horizontal scaling** — one preview per project, no load balancing
- **Graceful degradation** — if preview dies, user sees raw iframe error

#### D.2 Architecture
```
┌────────────────────────────────────────────────────┐
│  Runtime Manager (new service)                     │
│                                                    │
│  - Process supervisor (like PM2 for Next.js)       │
│  - Dev mode for editing, prod mode for preview     │
│  - Log stream capture → DB + tail to frontend      │
│  - Resource caps via ulimit/cgroups                │
│  - Container option (Docker run per project)       │
│  - Port pool management with heartbeat             │
└─────────────────┬──────────────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────────────┐
│  Log Streaming                                     │
│  - Bridge captures console.log in generated app    │
│  - WebSocket relay to frontend logs panel          │
│  - Persistent to DB for historical viewing         │
│  - Search + filter by level, timestamp             │
└────────────────────────────────────────────────────┘
```

#### D.3 Implementation Tasks
| # | Task | Files | Estimate |
|---|------|-------|----------|
| D1 | Process supervisor (replace simple spawn with supervised runtime) | `backend/services/runtime_manager.py` | 3d |
| D2 | Log capture: tee stdout/stderr to files + stream to frontend | `backend/services/log_streamer.py` | 2d |
| D3 | Production mode toggle (dev vs prod with `next build`) | `backend/services/preview_manager.py` updates | 2d |
| D4 | Resource limits via ulimit/cgroups | `backend/services/runtime_manager.py` | 1d |
| D5 | Docker runtime option (isolated container per project) | `backend/services/docker_runtime.py` | 3d |
| D6 | Frontend: Logs panel with live tail, search, filters | `frontend/src/components/logs/LogsPanel.tsx` | 3d |
| D7 | Frontend: Runtime status indicator (CPU, memory, uptime) | `frontend/src/components/runtime/RuntimeStatus.tsx` | 1d |
| D8 | Crash reporting: automatic error capture → Sentry-like UI | `backend/services/runtime_monitor.py` | 2d |
| D9 | Multi-port pool with reservation and cleanup | `backend/services/port_manager.py` | 1d |

**Feature D total**: ~18 days (~3.5 weeks)

#### D.4 Blueprint Alignment
Extends the existing `preview_manager.py` — not a rewrite. The runtime manager becomes the foundation for future multi-tenant hosting.

---

### Feature E: Database Creation & Migration Management

**Current state**: Each project gets Docker PostgreSQL via `docker-compose.yml`. `drizzle-kit push` runs on schema changes. Local only.

#### E.1 What's Missing
- **Managed DB providers** (Neon, Supabase, PlanetScale, RDS)
- **Migration versioning** (no rollback, history tracked in git only)
- **Schema diff preview** before applying changes
- **CSV/JSON data import** (only AI-generated seed data)
- **Backup/restore** tooling
- **Multi-database support** (only PostgreSQL — no MySQL, SQLite)
- **Database connection pooling** config per env

#### E.2 Architecture
```
┌────────────────────────────────────────────────────┐
│  Database Manager                                  │
│                                                    │
│  ┌──────────────┐  ┌──────────────┐               │
│  │ Local Docker │  │ Neon/Supabase│               │
│  │ PostgreSQL   │  │ (managed)    │               │
│  └──────────────┘  └──────────────┘               │
│         │                  │                       │
│         └────────┬─────────┘                       │
│                  │                                 │
│                  ▼                                 │
│  Migration Layer (per-project)                     │
│  - Drizzle migrations with version log             │
│  - Schema diff preview before apply                │
│  - Rollback to previous migration                  │
│  - Seed data replay after migration                │
└────────────────────────────────────────────────────┘
```

#### E.3 Implementation Tasks
| # | Task | Files | Estimate |
|---|------|-------|----------|
| E1 | Migration versioning (replace `drizzle-kit push` with versioned migrations) | `backend/services/migration_manager.py` | 3d |
| E2 | Schema diff preview — AST-based before/after comparison | `backend/services/schema_differ.py` | 2d |
| E3 | Rollback mechanism for applied migrations | `backend/services/migration_manager.py` | 2d |
| E4 | Neon adapter — create DB, run migrations via their API | `backend/services/db_providers/neon_adapter.py` | 2d |
| E5 | Supabase adapter | `backend/services/db_providers/supabase_adapter.py` | 2d |
| E6 | PlanetScale adapter | `backend/services/db_providers/planetscale_adapter.py` | 2d |
| E7 | RDS adapter (via AWS SDK) | `backend/services/db_providers/rds_adapter.py` | 3d |
| E8 | CSV/JSON seed import — bulk insert with FK validation | `backend/services/bulk_importer.py` | 2d |
| E9 | Backup to S3/local file | `backend/services/db_backup.py` | 2d |
| E10 | Frontend: Migration history UI with diff preview | `frontend/src/components/data-model/MigrationHistory.tsx` | 2d |
| E11 | Frontend: DB provider connect dialog | `frontend/src/components/data-model/DBProviderDialog.tsx` | 2d |
| E12 | Frontend: CSV/JSON import dialog | `frontend/src/components/data-model/ImportDialog.tsx` | 2d |
| E13 | Multi-DB support: SQLite + MySQL adapters | `backend/services/db_providers/sqlite.py`, `mysql.py` | 3d |

**Feature E total**: ~29 days (~6 weeks)

#### E.4 Blueprint Alignment
Builds on existing `data_model.py` router and schema change pipeline. The `schema_agent` continues producing Drizzle schemas; migration manager wraps them.

---

### Feature F: Seed Data System (Hardened)

**Current state**: `seed_generator.py` agent produces domain-aware fake data. Runs after `drizzle-kit push`. AI-generated only, no UI editor.

#### F.1 What's Missing
- **Seed data UI editor** — currently only editable via JSON file
- **CSV/JSON import** — no way to bulk-load real data
- **Seed versioning** — can't replay a specific seed state
- **Clear/reset endpoint** — have to manually truncate
- **Seed data validation** — no pre-insert constraint checks
- **Realistic data generators** — date ranges, geographies, names by locale

#### F.2 Implementation Tasks
| # | Task | Files | Estimate |
|---|------|-------|----------|
| F1 | Seed data UI editor (table-based per entity, inline edit) | `frontend/src/components/data-model/SeedDataEditor.tsx` | 3d |
| F2 | CSV/JSON import with field mapping wizard | `frontend/src/components/data-model/ImportWizard.tsx`, `backend/services/seed_importer.py` | 3d |
| F3 | Seed snapshot + restore (save current DB state as named snapshot) | `backend/services/seed_snapshots.py` | 2d |
| F4 | Clear/reset endpoint with confirmation | `backend/routers/data_model.py` additions | 1d |
| F5 | Locale-aware fake data (Faker.js integration) | `backend/agents/seed_generator.py` updates | 1d |
| F6 | Seed data templates (e-commerce, CRM, healthcare, etc.) | `backend/templates/seed_data/` | 3d |
| F7 | Pre-insert validation (check FK, uniqueness, CHECK constraints) | `backend/services/seed_validator.py` | 2d |
| F8 | Seed data diff view (what will change if I re-seed?) | `frontend/src/components/data-model/SeedDiff.tsx` | 2d |

**Feature F total**: ~17 days (~3.5 weeks)

#### F.3 Blueprint Alignment
Extends the existing `seed_generator` agent. Adds the UI layer that was missing.

---

### Feature G: Organisation Management (Enterprise Hardening)

**Current state**: Full org CRUD, 3-tier roles, departments, teams, groups, custom roles, manager hierarchies, invite system (no email sending yet), CSV bulk import (limited error handling).

#### G.1 What's Missing
- **Billing** — no `BillingPlan`, no subscription tiers, no usage metering
- **Resource quotas** — no project limit, API rate limit, storage cap per org
- **Audit logging** — `AuditLog` table exists but not wired into org endpoints
- **Email sending** — invite system generates tokens but doesn't send emails
- **SSO/SAML** — only manual invite-based
- **Resource access enforcement** — department/team scoping modeled but not enforced in APIs
- **Org settings** — beyond slug/name/logo
- **Data isolation verification** — no tests proving org A can't see org B's data

#### G.2 Implementation Tasks
| # | Task | Files | Estimate |
|---|------|-------|----------|
| G1 | BillingPlan model + subscription tiers (Free, Pro, Enterprise) | `backend/models/billing.py` | 2d |
| G2 | Usage metering service (projects, API calls, storage, agent cost) | `backend/services/usage_meter.py` | 3d |
| G3 | Quota enforcement middleware (reject if over limit) | `backend/middleware/quota_enforcement.py` | 2d |
| G4 | Stripe integration for subscription management | `backend/services/billing/stripe_adapter.py` | 3d |
| G5 | Audit log middleware (capture all write operations) | `backend/middleware/audit_logger.py` | 2d |
| G6 | Audit log UI with search, filter, export | `frontend/src/components/audit/AuditLogView.tsx` | 3d |
| G7 | Email service (SendGrid/Postmark) with templates | `backend/services/email_service.py` | 2d |
| G8 | Invite email flow (send, resend, expire) | `backend/routers/orgs.py` updates | 2d |
| G9 | SAML SSO integration (python3-saml) | `backend/services/sso/saml_provider.py` | 5d |
| G10 | OAuth providers (Google, Microsoft, GitHub) | `backend/services/sso/oauth_providers.py` | 3d |
| G11 | Department/Team data scoping enforcement in API queries | `backend/services/access_scoping.py` | 3d |
| G12 | Org settings page (branding, locale, timezone, security) | `frontend/src/components/org/OrgSettings.tsx` | 2d |
| G13 | Tenant isolation tests (prove org A can't see org B) | `backend/tests/test_tenant_isolation.py` | 2d |
| G14 | Resource usage dashboard per org | `frontend/src/components/org/UsageDashboard.tsx` | 2d |

**Feature G total**: ~36 days (~7 weeks)

#### G.3 Blueprint Alignment
The existing `org.py` model is solid. This adds the enterprise features: billing, quotas, audit, SSO, scoping enforcement.

---

### Feature H: Rules Engine (Runtime & Intelligence)

**Current state**: 10 rule types supported (validation, access, business, computed, state_machine, trigger, content_moderation, similarity_check, ai_validation, ai_enrichment). FEEL-lite expression engine (frontend + backend). Visual condition builder. Rules created manually or via code_editor agent. Rules applied via code injection, not middleware.

#### H.1 What's Missing
- **Runtime rule engine** — rules applied by regenerating code, not evaluated at request time
- **Rule testing/playground** — no dry-run, no simulate-on-data environment
- **Conflict detection** — can't detect if rule A contradicts rule B
- **Impact analysis** — "what breaks if I delete this rule?"
- **Rule versioning** — can't roll back rule changes independently
- **AI rule suggestions** — no "suggest rules based on domain" feature
- **Rule templates** — no library of common patterns (age verification, email uniqueness, etc.)
- **Rule performance monitoring** — no tracking of how long rules take to evaluate
- **Nested function composition** in FEEL-lite
- **Conditional activation** (enable/disable rule at runtime without regeneration)

#### H.2 Architecture
```
┌────────────────────────────────────────────────────┐
│  Rule Engine (new runtime layer)                   │
│                                                    │
│  Generated apps include a rules runtime that       │
│  reads rules at request time (vs code injection)   │
│                                                    │
│  Benefits:                                         │
│  - Change rules without regenerating code          │
│  - A/B test rules on traffic                       │
│  - Performance monitoring per rule                 │
│  - Conditional activation via feature flags        │
└────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────┐
│  Rule Playground (in Tentoro editor)               │
│                                                    │
│  - Pick an entity and rule                         │
│  - Input test data                                 │
│  - See evaluation trace (FEEL-lite step-by-step)   │
│  - Compare against existing data in DB             │
│  - "What-if" mode for breaking changes             │
└────────────────────────────────────────────────────┘
```

#### H.3 Implementation Tasks
| # | Task | Files | Estimate |
|---|------|-------|----------|
| H1 | Runtime rule engine package for generated apps | `packages/rules-runtime/` | 5d |
| H2 | Generated app middleware that applies rules at request time | `packages/rules-runtime/src/middleware.ts` | 2d |
| H3 | Rule playground UI — test data input + evaluation trace | `frontend/src/components/rules/RulePlayground.tsx` | 4d |
| H4 | FEEL-lite debugger — step-through evaluation view | `frontend/src/lib/feel-lite/debugger.ts` | 3d |
| H5 | Conflict detection algorithm (SAT solver for rule pairs) | `backend/services/rules/conflict_detector.py` | 4d |
| H6 | Impact analysis (which endpoints/pages use this rule?) | `backend/services/rules/impact_analyzer.py` | 2d |
| H7 | Rule versioning with per-rule rollback | `backend/models/rules.py` + `backend/services/rule_versioning.py` | 2d |
| H8 | AI rule suggester (analyzes schema + domain → suggests rules) | `backend/agents/rule_suggester.py` | 3d |
| H9 | Rule template library (20+ common patterns) | `backend/templates/rules/` | 3d |
| H10 | Performance monitoring (rule evaluation time tracking) | `packages/rules-runtime/src/metrics.ts` | 2d |
| H11 | Conditional activation via feature flags | `backend/services/rules/feature_flags.py` | 2d |
| H12 | FEEL-lite enhancements: nested composition, type coercion | `frontend/src/lib/feel-lite/` + `backend/services/feel_lite_eval.py` | 3d |
| H13 | Rule documentation UI (comments, examples) | `frontend/src/components/rules/RuleDocs.tsx` | 2d |

**Feature H total**: ~37 days (~7.5 weeks)

#### H.4 Blueprint Alignment
The existing rule infrastructure is strong. This adds the runtime layer, testing tools, and intelligence features.

---

## 12. Updated Phased Roadmap

Incorporating all features (A–H) with parallel workstreams:

### Track 1: Core Platform (Engineer A)
| Phase | Duration | Feature |
|-------|----------|---------|
| 0 | 2 wks | Foundation Hardening (vision, diff preview, intent) |
| 1 | 3 wks | Deployment (Vercel, Railway, Cloudflare) |
| 2 | 3 wks | Platform Messaging (comments, presence, chat) |
| 5 | 2 wks | Polish (OAuth, MFA, templates, dashboards) |
| **Total** | **10 wks** | |

### Track 2: Generation & Data (Engineer B)
| Phase | Duration | Feature |
|-------|----------|---------|
| D | 3.5 wks | Runtime Engine (logs, prod mode, supervision) |
| E | 6 wks | Database System (providers, migrations, import) |
| F | 3.5 wks | Seed Data System (UI, import, templates) |
| H | 7.5 wks | Rules Engine (runtime, playground, AI, versioning) |
| **Total** | **20.5 wks** | |

### Track 3: Mobile & Enterprise (Engineer C)
| Phase | Duration | Feature |
|-------|----------|---------|
| 3 | 8 wks | Mobile (Capacitor + RN + Expo) |
| 4 | 3 wks | Generated App Messaging |
| G | 7 wks | Organisation Hardening (billing, SSO, audit, quotas) |
| **Total** | **18 wks** | |

### Timeline Summary
- **Solo engineer (sequential)**: ~48 weeks (~11 months)
- **2 engineers**: ~25 weeks (~6 months)
- **3 engineers (optimal)**: ~20 weeks (~5 months) with buffer for integration

### Critical Path
These items block others and should be front-loaded:
1. **Feature D (Runtime)** — blocks production deployments, log capture, crash debugging
2. **Feature E migration system** — blocks Feature A (one-click deploy)
3. **Feature H runtime engine** — blocks conditional rule activation and A/B testing
4. **Feature G billing** — blocks commercial launch

---

## 13. Updated Success Metrics (All Features)

### Feature D (Runtime)
- Generated apps survive >24 hours without manual intervention
- Log search returns results in <500ms
- Zero data loss on runtime crashes

### Feature E (Database)
- DB provisioning time: <30s for local, <2m for managed providers
- Zero-downtime migrations for schema changes
- CSV import throughput: >10k rows/sec

### Feature F (Seed Data)
- User can edit seed data in UI without code changes
- Import success rate: >99% for valid CSV/JSON
- Domain-specific templates cover 10+ industries

### Feature G (Org Management)
- Tenant isolation: 100% test coverage
- Audit log captures 100% of write operations
- Billing reconciliation accuracy: 99.99%
- SAML login works for 5+ major IdPs

### Feature H (Rules)
- Rule playground test coverage: 100% of rule types
- Conflict detection precision: >95%
- Runtime rule evaluation: <5ms P99
- AI rule suggester acceptance rate: >40%

---

## 14. Resource Requirements (Updated)

### Team Options
- **Solo**: ~48 weeks (~11 months) sequentially
- **2 engineers**: ~25 weeks (~6 months)
- **3 engineers + 1 designer**: ~20 weeks (~5 months) optimal

### Infrastructure Additions
- **For Feature E**: Neon/Supabase/PlanetScale test accounts
- **For Feature G**: Stripe test account, SendGrid/Postmark, SAML test IdP
- **For Feature D**: Log storage (S3 or similar), cgroups-capable host

### Third-Party Services (Full List)
- Deployment (A): Vercel, Railway, Cloudflare Pages APIs
- DB providers (E): Neon, Supabase, PlanetScale, AWS RDS
- Org (G): Stripe, SendGrid/Postmark, SAML IdP (Okta, Auth0)
- Mobile (C): Expo EAS, Apple Developer, Google Play Console
- Messaging (B): Redis Cloud, optional
- Runtime (D): Sentry for crash reports


---

## Feature I: Editor Unification, Data Binding, Workflow-Form Connection & Binding Inspector

**Last updated**: 2026-04-19
**Priority**: High — directly affects quality of the no-code editing experience
**Depends on**: IR system (already built), AHTML system (already built), Workflow editor (already built), Rules editor (already built)

---

### I.1 Overview

Four interconnected problems need to be solved together because they share a common solution: **the IR node needs to know about data, rules, and workflows at editing time**.

| Problem | Current State | Target State |
|---|---|---|
| Visual Editor + Design Editor are separate | Two parallel editors, no handoff | One editing loop: structure in Design Editor, polish in Visual Editor |
| Form fields have no entity binding | Forms generated statically, no live link to schema | Each form field declares which entity/field it binds to |
| Workflows not connected to forms | Workflow panel and form generation are independent | Form submit can trigger a workflow; workflow step can render a form |
| No unified place to configure bindings | Spread across 5 different tabs | Properties panel on any IR node shows data + rules + workflow sub-tabs |

---

### I.2 Feature I-A: Design Editor → Visual Editor Handoff

**Goal**: Compile in Design Editor, continue polishing in Visual Editor — without losing context.

#### Architecture

```
Design Editor (GrapeJS AHTML)
  └── "Compile & Preview" button
        ↓  POST /api/projects/:id/ahtml/compile
      TSX files written to output_dir
        ↓  Next.js HMR picks up file changes
      Live preview server reloads
        ↓
  Visual Editor renders the updated page
  └── "Edit structure" button → jumps back to Design Editor on that page
```

The two editors share **page identity** via the `pageId` / route string. Both panels already exist in the workspace; this is a coordination problem.

#### Implementation Tasks

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| I-A1 | Emit a `design:compiled` event from the compile endpoint with the page route | `backend/routers/design.py` | 0.5d |
| I-A2 | Visual Editor listens for `design:compiled` SSE event and refreshes its iframe to the affected route | `frontend/src/components/visual-editor/VisualEditor.tsx` | 0.5d |
| I-A3 | Design Editor toolbar: add "Preview in Visual Editor" button that switches workspace tab to Visual Editor and passes the active page route | `frontend/src/components/design-editor/DesignEditor.tsx`, `frontend/src/app/org/[orgId]/projects/[projectId]/page.tsx` | 1d |
| I-A4 | Visual Editor element action popover: add "Edit structure" button that switches to Design Editor and highlights the corresponding GrapeJS block by its `data-block-id` | `frontend/src/components/visual-editor/VisualEditor.tsx` | 1d |
| I-A5 | Shared `activePageRoute` state in workspace so both editors stay on the same page when user switches tabs | `frontend/src/app/org/[orgId]/projects/[projectId]/page.tsx` | 0.5d |

**Subtotal**: ~3.5 days

---

### I.3 Feature I-B: Form ↔ Entity Binding

**Goal**: Every form field in the IR declares which entity and field it maps to. This drives auto-typing, validation inheritance, and submit/prefill wiring.

#### Data Model

Add to the IR `Form` node and each `FormField` node:

```ts
// On the Form node
entityBinding?: {
  entity: string           // e.g. "User"
  mode: "create" | "edit"
  submitRoute: string      // e.g. "POST /api/users"
  prefillRoute?: string    // e.g. "GET /api/users/:id" (for edit mode)
  onSuccess: Action        // navigate / toast / invalidate
}

// On each FormField node
fieldBinding?: {
  entity: string           // same entity as parent form
  field: string            // e.g. "email"
  // inherits: type, required, maxLength from schema
}
```

#### How Auto-wiring Works

When a user picks an entity in the "Bind to Entity" dropdown on a Form node:
1. Read all fields from the registry for that entity
2. Match existing form fields by name (fuzzy) or create new fields for unmatched schema fields
3. Set `submitRoute` to the `POST /api/{entity}` route from the registry
4. Set `prefillRoute` to `GET /api/{entity}/:id` if mode is `edit`
5. Apply DB-level constraints (required, maxLength, unique) as validation rules on each field

#### Implementation Tasks

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| I-B1 | Extend IR types: add `entityBinding` to `Form` node and `fieldBinding` to `FormField` node | `packages/ir/src/types.ts` | 0.5d |
| I-B2 | IR validator: warn if `entityBinding.submitRoute` is not in the registry | `packages/ir/src/validate.ts` | 0.5d |
| I-B3 | Backend endpoint: `GET /api/projects/:id/registry/entities` — returns entity list with fields + API routes | `backend/routers/generate.py` or new `routers/registry.py` | 0.5d |
| I-B4 | IR Editor Properties panel: "Data" sub-tab on Form node — entity picker dropdown, mode toggle (create/edit), submit route display, prefill route display | `frontend/src/components/ir-editor/PropertiesPanel.tsx` | 2d |
| I-B5 | Auto-wiring logic: on entity selection, diff existing fields against schema fields, generate `fieldBinding` entries | `frontend/src/components/ir-editor/PropertiesPanel.tsx` (or a hook) | 1.5d |
| I-B6 | FormField row in IR tree: show bound entity/field chip next to field name | `frontend/src/components/ir-editor/ComponentTree.tsx` | 0.5d |
| I-B7 | IR → TSX compiler: emit bound `onSubmit` handlers and `useQuery` prefill from `entityBinding` | `packages/compiler/src/emitters/form.ts` | 2d |
| I-B8 | Component agent: when generating forms, set `entityBinding` from the registry automatically | `backend/agents/component_agent.py` | 1d |

**Subtotal**: ~8.5 days

---

### I.4 Feature I-C: Workflow ↔ Form Connection

**Goal**: Two binding directions — a form can trigger a workflow on submit; a workflow step can designate a form as its human task UI.

#### Two Binding Directions

**Direction 1 — Form triggers Workflow (on submit):**
```
User fills form → submits → API mutation succeeds → workflow "EmployeeOnboarding" starts
                                                      with { employeeId, formData } as input
```

Add to the Form node's `entityBinding`:
```ts
onSuccessWorkflow?: {
  workflowId: string         // e.g. "EmployeeOnboarding"
  inputMapping: Record<string, string>  // workflow input field → form field or response field
}
```

**Direction 2 — Workflow step renders Form (human task):**
```
Workflow reaches "ManagerApproval" step
→ creates a task assigned to a manager
→ task renders the "ApprovalForm" component
→ manager submits → workflow continues
```

Add to the Workflow step node:
```ts
humanTaskForm?: {
  formComponent: string     // IR component path or name
  assignee: string          // role or user expression
  dueInHours?: number
}
```

#### Implementation Tasks

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| I-C1 | Extend IR Form node: add `onSuccessWorkflow` to `entityBinding` | `packages/ir/src/types.ts` | 0.5d |
| I-C2 | IR Editor: "Workflow" sub-tab on Form node — workflow picker, input mapping table | `frontend/src/components/ir-editor/PropertiesPanel.tsx` | 2d |
| I-C3 | Workflow Panel: "Form" property on human-task step nodes — component picker from registry | `frontend/src/components/workflow/WorkflowPanel.tsx` | 1.5d |
| I-C4 | IR → TSX compiler: emit workflow trigger call after mutation success | `packages/compiler/src/emitters/form.ts` | 1d |
| I-C5 | Workflow Panel: cross-reference display — show which forms trigger or are used by each workflow | `frontend/src/components/workflow/WorkflowPanel.tsx` | 1d |
| I-C6 | Page agent: when generating pages, wire `onSuccessWorkflow` if a workflow triggers on entity create | `backend/agents/page_agent.py` | 1d |

**Subtotal**: ~7 days

---

### I.5 Feature I-D: Unified Binding Inspector

**Goal**: Wherever you select a structural node (Form, DataTable, Repeater, Card linked to entity), a single panel shows Data + Rules + Workflow bindings — no need to switch tabs.

#### UI Design

The IR Editor's right Properties panel gets three new sub-tabs for composite nodes:

```
┌────────────────────────────────────────┐
│ Properties  │  Data  │  Rules  │  Flow │
├────────────────────────────────────────┤
│ [Data tab — for Form node]             │
│                                        │
│  Entity:     [User ▾]                  │
│  Mode:       ● Create  ○ Edit          │
│  Submit:     POST /api/users           │
│  Prefill:    — (create mode)           │
│                                        │
│  Fields (4 bound / 1 unbound):         │
│  ✅ email    → User.email              │
│  ✅ name     → User.name               │
│  ✅ role     → User.role               │
│  ⚠️  notes   (not bound)               │
└────────────────────────────────────────┘

┌────────────────────────────────────────┐
│ [Rules tab — for Form node]            │
│                                        │
│  Active rules (from Rules panel):      │
│  ✅ email format validation            │
│  ✅ role: only admin can set           │
│  ⚠️  name: no rules applied            │
│                                        │
│  [+ Add rule for this entity]          │
└────────────────────────────────────────┘

┌────────────────────────────────────────┐
│ [Flow tab — for Form node]             │
│                                        │
│  On submit success:                    │
│  ○ Navigate to /users                  │
│  ○ Show toast                          │
│  ● Trigger workflow: [EmployeeOnboarding ▾] │
│                                        │
│  Input mapping:                        │
│  employeeId  ←  response.id            │
│  department  ←  form.department        │
└────────────────────────────────────────┘
```

#### Context-sensitive tabs by node type

| Node type | Data tab | Rules tab | Flow tab |
|---|---|---|---|
| `Form` | Entity binding, field mapping | Validation + access rules for entity | Workflow trigger on submit |
| `DataTable` | Entity binding, visible columns | Access rules (who can see rows) | Row click action, bulk actions |
| `Repeater` | Data source (API route + params) | — | Item click action |
| `Card` (entity-linked) | Entity + field display mapping | — | Click action |
| `TextInput` / `Select` | Field binding (entity.field) | Per-field validation rules | onChange side effect |

#### Implementation Tasks

| # | Task | File(s) | Effort |
|---|------|---------|--------|
| I-D1 | Add `Data / Rules / Flow` sub-tabs to IR Editor Properties panel, shown only for composite nodes | `frontend/src/components/ir-editor/PropertiesPanel.tsx` | 1d |
| I-D2 | Data tab for `DataTable` node: entity picker, column selector (checkboxes), row click action | `frontend/src/components/ir-editor/PropertiesPanel.tsx` | 1.5d |
| I-D3 | Rules tab: query Rules panel API for rules matching the bound entity, display as read-only list with "edit" link that opens the Rules tab | `frontend/src/components/ir-editor/PropertiesPanel.tsx` | 1d |
| I-D4 | Rules tab: inline "Add validation rule" shortcut (opens a mini rule editor without leaving IR Editor) | `frontend/src/components/ir-editor/panels/InlineRuleEditor.tsx` | 2d |
| I-D5 | Flow tab: for Form nodes, render the `onSuccessWorkflow` UI (from I-C2) | `frontend/src/components/ir-editor/PropertiesPanel.tsx` | 0.5d (reuse I-C2 work) |
| I-D6 | Data Model panel: "Used by" column on each entity — shows linked form components and workflow nodes | `frontend/src/components/data-model/DataModelPanel.tsx` | 1.5d |
| I-D7 | Workflow panel: "Bound forms" indicator on human-task nodes | `frontend/src/components/workflow/WorkflowPanel.tsx` | 0.5d (reuse I-C3 work) |

**Subtotal**: ~8 days

---

### I.6 Sequencing & Dependencies

```
I-A (Editor Handoff)          ← can start immediately, no blockers
    │
    └── unblocks: smoother testing of I-B and I-C changes

I-B (Form ↔ Entity Binding)   ← start with types (I-B1), then backend (I-B3), then UI
    │
    └── unblocks: I-C (needs entityBinding on Form before wiring workflow)
                  I-D Data tab (needs binding model to display)

I-C (Workflow ↔ Form)         ← depends on I-B being done for Form trigger direction
    │                            human-task direction (I-C3) can start earlier
    └── unblocks: I-D Flow tab

I-D (Binding Inspector)       ← mostly depends on I-B + I-C; Rules tab (I-D3/4) is independent
```

**Recommended order**: I-A → I-B1 through I-B6 → I-C1 through I-C3 → I-D → I-B7 + I-C4 + I-C6 (compiler changes last)

---

### I.7 Total Estimates

| Feature | Effort |
|---|---|
| I-A: Editor Handoff | 3.5 days |
| I-B: Form ↔ Entity Binding | 8.5 days |
| I-C: Workflow ↔ Form | 7 days |
| I-D: Binding Inspector | 8 days |
| **Total** | **~27 days (~5–6 weeks for 1 engineer)** |

With 2 engineers running I-A + I-B in parallel with I-C + I-D: **~3 weeks**.

---

### I.8 Success Metrics

- A user can bind a form to an entity in under 10 seconds from the IR Editor
- Changes compiled in Design Editor appear in Visual Editor within 2 seconds (HMR)
- 100% of forms generated by agents have a valid `entityBinding` set
- A workflow can be triggered from any form without writing code
- The binding inspector surfaces all three concerns (data, rules, workflow) without leaving the IR Editor tab
