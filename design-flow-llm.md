# `_run_relay_pipeline` — Design Flow

Source: `backend/routers/generate.py:305-1380`
Triggered by: `/chat` approval when `plan._figma_driven` is **not** set.
Entry signature: `_run_relay_pipeline(output_dir, plan, description, *, domain_context, design_spec, project_short_id)`

> "Relay" because each agent hands off an artifact to the next, like a relay race. The Contract Registry (`registry.json`) is the shared baton — every agent reads + merges into it so cross-references stay consistent.

---

## 0. Mental model

The pipeline is split into **3 layers**:

```
┌────────────────────────────────────────────────────────────────┐
│  Layer 1 — Foundation         (deterministic, fast)            │
│    domain detect → templates copy → registry init              │
├────────────────────────────────────────────────────────────────┤
│  Layer 2 — Generation         (LLM agents, sequential + parallel)│
│    design → contract → schema → ⟨API ∥ BizLogic⟩ → rules        │
│    → nav-flow → shell → per-page schemas                       │
├────────────────────────────────────────────────────────────────┤
│  Layer 3 — Hardening          (gates, validators, retries)     │
│    contract gate, auth gate, API gate, CTA / PD / coverage     │
│    gates, photo injection, emitter, fidelity scoring           │
└────────────────────────────────────────────────────────────────┘
```

After Layer 3, the pipeline **returns early in schema mode** (`SCHEMA_MODE_ENABLED=true`, the default). The legacy LLM-TSX tail (Component → Page → QA → Coder↔Reviewer → Visual review) only runs when schema mode is off.

---

## 1. Pipeline flowchart

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                          _run_relay_pipeline                             │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Layer 1 — Foundation                                                    │
│                                                                          │
│   run_domain_discovery(description, plan)     (agents/domain_agent.py)   │
│        │  Sonnet + web_search → DiscoveryOutput dossier                  │
│        │  (persona per role, designPatterns, complianceNotes,            │
│        │   entitySuggestions, visualLanguage, commonPitfalls)            │
│        │  → src/contracts/discovery.json                                 │
│        │                                                                 │
│        ▼                                                                 │
│   [Chat-approval pause] when invoked from /chat                          │
│        │  Save .pending_discovery.json, emit discovery_approval_needed   │
│        │  Frontend renders DiscoveryCard for review/edit                 │
│        │  Resume on [APPROVE_DISCOVERY] (with optional edits)            │
│        ▼                                                                 │
│   copy_foundation_templates()                                            │
│        │                                                                 │
│        ▼                                                                 │
│   _clear_schemas_dir()                                                   │
│        │                                                                 │
│        ▼                                                                 │
│   create_registry(output_dir)                 → src/contracts/registry.json
└──────────────────────────────────────────────────────────────────────────┘

The discovery dossier is the `domain_context` dict threaded into every
downstream agent. Each agent's system prompt picks up a role-tailored
`[DOMAIN PROFILE]` block via `services.domain_context.build_domain_profile
(domain_ctx, role)`. This replaces the deleted `backend/knowledge/` folder
and the hardcoded personas that used to live in `domain_context.py`.
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Layer 2A — Design + Contracts                                           │
│                                                                          │
│   run_design_agent(plan, domain_ctx)          (LLM — claude-sonnet-4)    │
│        │  emits design rationale + colorPalette + tokens                 │
│        ▼                                                                 │
│   extract_design_spec()                                                  │
│        │                                                                 │
│        ▼                                                                 │
│   [optional] auto_brand_from_url(plan.brandUrl)                          │
│   save_design_spec()  ──→  src/contracts/design-spec.json                │
│        │                                                                 │
│        ▼                                                                 │
│   classify_register(design_spec)              → 'default'/'corporate'/   │
│   save_register()                                'editorial'/'playful'   │
│        │                                                                 │
│        ▼                                                                 │
│   [FIDELITY_MODE_ENABLED] compile_tokens()    → src/theme/tokens.custom.json
│        │                                                                 │
│        ▼                                                                 │
│   run_contract_agent(plan, domain_ctx)        (LLM — Haiku 4.5)          │
│        │  reads registry + plan                                          │
│        │  writes src/contracts/contracts.json, src/contracts/types.ts    │
│        ▼                                                                 │
│   check_contract_gate(output_dir)                                        │
│   ┌── gap_count > 0 ──→ run_contract_agent (Contract-Fix)                │
│   │                                                                      │
│   └── ✓ All contracts complete                                           │
│        │                                                                 │
│        ▼                                                                 │
│   run_schema_agent(plan, domain_ctx)          (LLM — Haiku 4.5)          │
│        │  writes prisma/schema.prisma                                    │
│        ▼                                                                 │
│   extract_entities_from_prisma()                                         │
│   merge_into_registry(entities=...)           → registry.entities       │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Layer 2B — Parallel: Auth + API + BusinessLogic                         │
│                                                                          │
│     ┌──────────────────┬───────────────────┬────────────────────┐        │
│     ▼                  ▼                   ▼                    │        │
│  run_auth_agent    run_api_agent      run_business_logic_agent │        │
│  (Haiku 4.5)       (Haiku 4.5)        (Sonnet 4)                │        │
│     │                  │                   │                    │        │
│     ▼                  ▼                   ▼                    │        │
│  src/app/api/auth/  src/app/api/*    services/workflows.ts      │        │
│  app/(auth)/        + routes.json                               │        │
│     └──────────────────┴───────────────────┘                    │        │
│                       │                                                  │
│                       ▼                                                  │
│   extract_api_routes()                                                   │
│   merge_into_registry(api_routes=..., validation=...)                    │
│        │                                                                 │
│        ▼                                                                 │
│   validate_registry(phase=post_api)                                      │
│        │ emits `registry_validation` SSE event                           │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Layer 2C — Rules + Gates                                                │
│                                                                          │
│   run_rules_agent()    (LLM — Sonnet 4, optional)                        │
│        │  src/contracts/rules.json (declarative business rules)          │
│        ▼                                                                 │
│   check_auth_gate()                                                      │
│   ┌── issues > 0 ──→ run_auth_agent (Auth-Fix)                          │
│   └── ✓                                                                  │
│        │                                                                 │
│        ▼                                                                 │
│   inject_runtime_helpers()  (rules engine + fixtures wired)              │
│        │                                                                 │
│        ▼                                                                 │
│   check_api_gate()                                                       │
│   ┌── missing entities ──→ run_api_agent (API-Fix)                       │
│   └── ✓                                                                  │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Layer 2D — Frontend dispatch (3-way fork)                               │
│                                                                          │
│         SCHEMA_MODE_ENABLED ?                                            │
│        ┌────true (default)────┐    ┌──IR_FRONTEND_ENABLED──┐  ┌──else──┐ │
│        ▼                       ▼                            ▼          ▼ │
│  ── SCHEMA MODE ──            ── IR MODE ──            ── LLM-TSX MODE──│
│  nav-flow build                ir_compiler              run_component_  │
│   ↓                            ↓                        agent +          │
│  shell_layout_agent            tsx compile from IR     run_page_agent   │
│   ↓                                                     (legacy path)    │
│  schema_frontend_pipeline                                                │
│   (per-page schema agent)                                                │
│   ↓                                                                      │
│  post-emit gates                                                         │
│   ↓                                                                      │
│  photo injection + emit + fidelity                                       │
│   ↓                                                                      │
│  RETURN (success event)                                                  │
└──────────────────────────────────────────────────────────────────────────┘
```

The schema-mode branch (default) is what I'll walk through in detail. The other two branches are documented at the end.

---

## 2. Schema-mode frontend (the default branch)

```text
┌──────────────────────────────────────────────────────────────────────────┐
│  Step A — nav-flow synthesis                                             │
│    build_nav_flow_from_plan(plan, registry)                              │
│      → src/contracts/nav-flow.json                                       │
│      pages[]: {id, route, title, schemaFile, shell, guard, params}      │
│      transitions[]: {trigger, from, to, params}                          │
│      guards[]: {name, condition, redirect}                               │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Step B — Shell Layout Agent (when ≥1 page has shell:true)               │
│    run_shell_layout_agent(plan, nav_flow, brand, domain_ctx)             │
│      (LLM — Sonnet 4.5)                                                  │
│      → LLM emits Row{ sidebar Container, main Stack }                   │
│      → normalize_v2_schema()    (rewrite default→primary, content→root) │
│      → apply_page_shell_layout_to_schema()                              │
│           ↓ matches Row with min-h-screen + w-60 sidebar pattern         │
│           ↓ swaps to viewport-fill + sticky sidebar + scrollable main   │
│           ↓ marks shellRole=sidebar, spawns backdrop, tags hamburger   │
│      → _ensure_scrollbar_styles()                                       │
│           ↓ appends .sidebar-scroll / .main-scroll + drawer @media     │
│             rules to src/app/globals.css                                │
│      → src/schemas/shell.json                                            │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Step C — Schema Frontend Pipeline (per-page emission)                   │
│    schema_frontend_pipeline.run_schema_frontend_pipeline(plan, domain_ctx)│
│                                                                          │
│      for each page in plan.pages:                                        │
│        if page.route in skip_routes: continue                            │
│        ┌── page-type templates available? ──┐                            │
│        │   detail / form / list / overview  │                            │
│        │   → seed prompt with archetype     │                            │
│        └────────┬──────────────────────────┘                             │
│                 ▼                                                        │
│        run_page_schema_agent(page, plan, registry, design_spec)          │
│          (LLM — Haiku 4.5)                                               │
│          ↓ emits Page (PageV2 schema)                                    │
│          ↓ normalize_v2_schema()                                         │
│          ↓ apply_page_shell_layout_to_schema()  (per-page page-shell)   │
│          ↓ schema_visual_enricher (avatar URLs, hero bg, feature icons) │
│        → src/schemas/<slug>.json                                         │
│                                                                          │
│      check_pages_coverage(plan, output_dir)                              │
│        ↓ verifies every plan.pages route has a schema on disk            │
│        ↓ falls back to deterministic template_generator for any missing  │
│                                                                          │
│      build_schema_registry(output_dir)                                   │
│        → src/schemas/registry.ts (route → schema map)                    │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Step D — Post-emit gates                                                │
│    CTA Gate            (every page has a primary CTA)                    │
│    Progressive Disclosure Gate (forms don't dump all fields at once)     │
│    Coverage Gate       (every plan.pages route has a schema)             │
│    ↓ All non-blocking — warnings logged via SSE, generation continues    │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Step E — Photo + asset injection                                        │
│    schema_visual_enricher.inject_photo_urls()                            │
│      ↓ walks schemas, finds Avatar/Hero/FeatureCard nodes                │
│      ↓ fills photoUrl from design_spec.entityPhotos / unsplash_picker    │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Step F — nav-flow refresh + standalone app emit                         │
│    refresh_nav_flow(output_dir)                                          │
│    emit_standalone_next_app(output_dir)                                  │
│      ↓ writes the rest of the Next.js app skeleton (layout.tsx, etc.)   │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Step G — Fidelity scoring (advisory)                                    │
│    [FIDELITY_SCORING_ENABLED]                                            │
│      score_fidelity(output_dir, design_spec)                             │
│      ↓ visual reference comparison via fidelity_scorer                  │
│      ↓ logs per-page scores via `fidelity` SSE events                    │
│      ↓ does NOT gate — pure observability                                │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                          ┌────────────────────┐
                          │   build_success    │
                          │   agent_result     │
                          │      return        │
                          └────────────────────┘
```

---

## 3. The Contract Registry baton

Every agent in Layer 2 reads + merges into `registry.json`. This is the single source of truth that prevents cross-agent reference drift.

```text
                            registry.json
                                  │
       ┌────────────────┬─────────┴──────────┬───────────────┐
       ▼                ▼                    ▼               ▼
   entities[]      api_routes[]        components[]      pages[]
       │                │                    │               │
   schema_agent    api_agent            component_agent  page_agent
   merges from     merges from          merges from      merges from
   prisma          src/app/api/*        src/components   src/schemas
       │                │                    │               │
       └────────────────┴────────────────────┴───────────────┘
                                  │
                                  ▼
                         qa_agent reads ALL
                         validator validates cross-refs
                         registry_repair fixes deterministic mismatches
```

Validation phases:
- **post_api** — entities ↔ api_routes consistency (every entity has CRUD routes)
- **pre_qa** — pages ↔ components ↔ api_routes consistency (every page reference resolves)

Errors emit `registry_validation` SSE events with section + name + suggestion. Auto-repair runs before QA via `registry_repair.py` (rewrites import names, field refs).

---

## 4. Gate / retry pattern

Every gate follows the same shape:

```python
gate = check_<thing>_gate(output_dir, plan, ...)
if gate["needs_fix"]:
    yield sse_event("log", {"text": f"[X Gate] N issues — sending back"})
    yield sse_event("status", {"message": f"Fixing X ({n} issues)..."})
    try:
        async for evt in _stream_phase("X-Fix", run_<thing>_agent(
            output_dir, plan, domain_context=domain_ctx,
            fix_prompt=gate["retry_prompt"]
        )):
            yield evt
    except Exception as e:
        yield sse_event("log", {"text": f"[X Gate] Fix attempt failed: {e}"})
else:
    yield sse_event("log", {"text": "[X Gate] ✓ All X complete"})
```

Gates in the pipeline:

| Gate | When | Triggers retry of | What it checks |
|---|---|---|---|
| Contract Gate | after run_contract_agent | run_contract_agent | every plan.entity has fields + relations |
| Auth Gate | after parallel batch | run_auth_agent | session cookie + middleware + login route present |
| API Gate | after Auth Gate | run_api_agent | every entity has CRUD + auth guard |
| CTA Gate | after schema emit | none (advisory) | every page has a primary CTA |
| Progressive Disclosure Gate | after schema emit | none (advisory) | forms don't dump all fields |
| Coverage Gate | after schema emit | falls back to template_generator | every plan.pages route has a schema |
| Cross-Reference Gate | after page emit (LLM-TSX mode) | run_api_agent | page→API refs all resolve |
| UX Gate | after page emit (LLM-TSX mode) | run_page_agent | domain-specific UX patterns applied |
| Workflow Gate | after page emit (LLM-TSX mode) | run_business_logic_agent | workflows wired to triggers |

---

## 5. Parallelism map

The pipeline is mostly sequential because each step depends on the prior step's artifacts. Two opportunities for parallelism:

```text
                    contract_agent
                          │
                          ▼
                     schema_agent
                          │
                          ▼
                ┌─────────┼─────────┐
                ▼         ▼         ▼
            auth_agent  api_agent  business_logic_agent
                 │         │         │
                 └─────────┴─────────┘
                          │
                          ▼
                  (rejoin + gates)
```

Implementation: `services.parallel_runner.run_parallel_agents(output_dir, [(name, factory), ...])` — uses `asyncio.gather`. Each agent's subprocess gets `stream_with_idle_timeout(idle=90s, total=600s)` so a stuck agent doesn't hang the pipeline indefinitely.

---

## 6. The 3 frontend modes

| Mode | Flag | When active | What it emits |
|---|---|---|---|
| **Schema** | `SCHEMA_MODE_ENABLED=true` (default) | always (unless overridden) | `src/schemas/<page>.json` + `shell.json` + `nav-flow.json`. Runtime renders via `@tentoroforge/renderer` + `@tentoroforge/engine` |
| **IR** | `IR_FRONTEND_ENABLED=true` | experimental | Intermediate Representation tree → typed TSX via `ir_compiler` |
| **LLM-TSX** | `SCHEMA_MODE_ENABLED=false AND IR_FRONTEND_ENABLED=false` | legacy | `component_agent` writes `.tsx` files; `page_agent` writes page-level `.tsx`. Heavier pipeline tail (QA → validator → coder↔reviewer loop → visual review) |

**The schema mode path returns at Step G — the rest of the steps below only run in LLM-TSX mode.**

---

## 7. LLM-TSX mode tail (legacy, skipped in default)

Active only when `SCHEMA_MODE_ENABLED=false`. Documented for completeness:

```text
   run_component_agent (LLM — Sonnet 4)
        ↓ writes src/components/* (TSX)
        ↓ extract_components() → registry merge
        ↓ Component Gate → retry on issues

   run_page_agent (LLM — Sonnet 4)
        ↓ writes app/(routes)/* (TSX)
        ↓ extract_pages() → registry merge
        ↓ Page Gate + Cross-Ref Gate + UX Gate → retry chains

   workflow_fallback_fill()  (deterministic fill of empty workflow definitions)
   Workflow Gate → retry run_business_logic_agent

   run_seed_generator()
        ↓ writes seed data + fixtures

   [FIDELITY_LOOP_ENABLED] fidelity_loop()
        ↓ iterative visual refinement against design references

   completeness_validator()  → completeness_report

   run_qa_agent (LLM — Haiku 4.5)
        ↓ reads registry + completeness_report
        ↓ writes QA findings

   post_generate_fixes()  (deterministic regex repair)

   Coder ↔ Reviewer loop  (MAX_REVIEW_CYCLES iterations)
        run_validator() ──→ run_fix_agent() on errors
                                  │
                                  ▼
        run_validator() again ──→ exit if clean

   Visual review loop  (MAX_VISUAL_CYCLES iterations)
        capture_screenshots(scaffold)
        run_design_reviewer_agent()  (Vision)
        run_fixer_agent() on findings

   verify_pipeline()  (build, type-check, dead-code, link-check)

   run_indexer()  (writes generation-summary.md)

   build_success + agent_result + return
```

---

## 8. SSE event timeline

Frontend filters events on the `type` field. The pipeline emits these in order:

| Phase | SSE event types emitted |
|---|---|
| Foundation | `session`, `discovery_started`, `discovery_complete`, `discovery_approval_needed`, `discovery_approved`, `log` (Templates + Cleanup + Registry init) |
| Design | `status`, `log` (Design/Brand/Tokens), `office` (agent_start) |
| Contract | `status`, `log`, `office` (agent_start/complete/handoff) |
| Schema | `status`, `log`, `office`, `registry_validation` |
| Parallel batch | `parallel_start`, `office`, `log` |
| Gates | `log` (gate result), `status` (when retrying), `registry_validation` |
| Frontend dispatch | `status`, `log` |
| Per-page emit | `phase_start`, `phase_complete`, `phase_warning` |
| Fidelity | `fidelity` |
| Termination | `office` (build_success), `agent_result` |

Errors are reported as `log` events with `[<phase>] ⚠ <error>` text. Fatal errors raise; non-fatal emit a warning and continue.

---

## 9. Outputs on disk

What lives where when the pipeline returns:

```
output/<project_id>/
├── src/
│   ├── app/                          (Next.js routes — emitter)
│   │   ├── api/                      (api_agent + auth_agent)
│   │   │   ├── auth/
│   │   │   └── <entity>/route.ts
│   │   ├── (auth)/                   (auth_agent — login/signup pages)
│   │   ├── globals.css                (design_agent + shell scrollbar/drawer rules)
│   │   ├── layout.tsx
│   │   └── page.tsx
│   ├── components/                   (component_agent — LLM-TSX mode only)
│   ├── contracts/
│   │   ├── contracts.json             (contract_agent)
│   │   ├── design-spec.json           (design_agent)
│   │   ├── nav-flow.json              (nav_flow_emitter)
│   │   ├── registry.json              (every agent merges here)
│   │   ├── rules.json                 (rules_agent)
│   │   └── types.ts                   (contract_agent)
│   ├── schemas/                      (schema mode — page_schema_agent)
│   │   ├── <slug>.json                (one per page)
│   │   ├── shell.json                 (shell_layout_agent)
│   │   └── registry.ts                (build_schema_registry)
│   ├── services/                     (business_logic_agent)
│   │   └── workflows.ts
│   └── theme/
│       └── tokens.custom.json         (design_compiler, fidelity mode)
└── prisma/
    └── schema.prisma                  (schema_agent)
```

---

## 10. Failure modes + recovery

| Failure | Recovery |
|---|---|
| `contract_agent` produces partial contracts | Contract Gate detects gaps → Contract-Fix retry |
| `schema_agent` produces invalid Prisma | No explicit gate — failure surfaces at next-step entity extraction |
| `auth_agent` missing middleware | Auth Gate detects → Auth-Fix retry |
| `api_agent` missing routes for entity | API Gate detects → API-Fix retry |
| `page_schema_agent` produces empty schema | Coverage Gate detects → falls back to `template_generator` |
| `page_schema_agent` emits `content:` instead of `root:` | `normalize_v2_schema` rewrites at write time |
| `shell_layout_agent` emits `variant: "default"` | `normalize_v2_schema` rewrites to `"primary"` |
| `shell_layout_agent` produces non-shell-shaped output | `apply_page_shell_layout_to_schema` no-ops (idempotent) |
| Subprocess hang (no SSE event in 90s) | `stream_with_idle_timeout` raises; pipeline logs warning + continues |
| Total subprocess > 600s | Hard timeout raises BillingError-style; surfaced to user |

---

## 11. Knobs worth knowing

```bash
# Default-on (true)
SCHEMA_MODE_ENABLED=true        # schema mode (the default branch)

# Default-off
IR_FRONTEND_ENABLED=false       # IR compiler instead of schema mode
FIDELITY_MODE_ENABLED=false     # compile tokens.custom.json from design-spec
FIDELITY_LOOP_ENABLED=false     # iterative visual refinement (LLM-TSX mode)
FIDELITY_SCORING_ENABLED=false  # advisory per-page scoring at end
FIGMA_SHELL_EXTRACT=false       # structural-diff shell extraction (rolled back)
PEER_PATCHER_ENABLED=false      # AI edit feature (editor-side, not pipeline)

# Tuning
AGENT_TIMEOUT_SECONDS=600       # per-subprocess hard timeout
SCAFFOLD_BASE_URL=http://localhost:6503  # for visual review screenshots
```

---

## 12. TL;DR

`_run_relay_pipeline` orchestrates 15-20 LLM agents and ~10 deterministic services to turn a `plan` + `description` into a Next.js app on disk. It's a 3-layer pipeline (foundation → generation → hardening) with:

- **The Contract Registry as the cross-agent baton** so component/page/api references always resolve.
- **Auto-repair gates after every major step**, each capable of triggering ONE retry with a targeted fix-prompt.
- **3 frontend modes** (schema / IR / LLM-TSX) gated by env flags, with schema mode being the default + fastest.
- **Mostly sequential, with one parallel branch** for auth + api + business-logic.
- **A return-early in schema mode** so the legacy LLM-TSX tail (QA / validator / coder-reviewer / visual review) only runs when explicitly opted into.

The schema-mode path is what your LeaveHub / Ditans regens have been running through end-to-end.
