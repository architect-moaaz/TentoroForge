# Code Generation Pipelines

This document maps the two end-to-end pipelines that the backend runs when generating an app from `POST /api/projects/{project_id}/generate` (initial) or `POST /api/projects/{project_id}/chat` (plan approval). The two pipelines differ by input source:

1. **LLM-driven pipeline** — input is a plain-text description / plan. Implemented by `_run_relay_pipeline()` in `backend/routers/generate.py` (starts at line ~305).
2. **Figma-driven pipeline** — input includes a `figmaUrl` + `figmaToken`. Implemented by `_run_figma_relay_pipeline()` in `backend/routers/generate.py` (starts at line ~1356).

Both pipelines share a final tail (seed → QA → validator → indexer) and several deterministic services (runtime injection, app emitter, photo injector, nav-flow emitter, post-generate fixes, fidelity scoring). They diverge in **how page schemas are produced** and in whether they emit branding/design-spec from text or extract it from Figma.

Throughout the doc, "schema" is used in two senses:

- **DB schema** — Drizzle ORM files under `src/db/schema/` (relational tables). Produced by the Schema Agent.
- **Page schema** — `PageV2` JSON files under `src/schemas/*.json` describing the UI tree. Produced by the Schema-mode pipeline (`run_schema_frontend_pipeline`) or by the deterministic Figma mapper / Figma MCP block.

---

## Routing Decision

Entry points: `POST /api/projects/{project_id}/generate` (`generate_project()` at `backend/routers/generate.py:2428`) and the chat-approval branch (`chat_endpoint()` around line 2850).

```
                 ┌─────────────────────────────────────────┐
                 │  client request                         │
                 │  - figma_url + figma_token?             │
                 │  - description?                         │
                 │  - plan? (from previous /generate call) │
                 └────────────────────┬────────────────────┘
                                      │
                          is_figma = bool(figma_url AND figma_token)
                                      │
              ┌───────────────────────┼──────────────────────────┐
              ▼                       ▼                          ▼
   is_figma and not plan      not is_figma and not plan      plan is set
              │                       │                          │
   build_plan_from_figma()      run_planner LLM         already have a plan
   → _figma_driven=True        → emits plan_ready       (came from /generate)
              │                  → user re-confirms             │
              └────────┐                │                       │
                       │                │ (re-enters /chat)     │
                       ▼                ▼                       ▼
                       └──── plan in DB; user approves ─────────┘
                                          │
                            chat_endpoint approval branch
                                          │
                  is_figma_project = bool(figma_url AND figma_token
                                          in plan_metadata)
                                          │
                ┌─────────────────────────┼─────────────────────────┐
                ▼                                                   ▼
       _run_figma_relay_pipeline()                       _run_relay_pipeline()
       (Figma path — file_key fetched                    (description path —
        deterministic mapper + LLM)                       LLM design agent first)
```

Concretely (see `generate.py:2887-2971`):

- **At `/generate`**: if `req.figma_url` is supplied, `build_plan_from_figma()` populates `plan.pages` from the actual frames (one page per top-level FRAME) and marks `plan._figma_driven = True`. If no plan and no Figma, `run_planner` produces a draft plan (intent `PLAN`) and the request returns without generating code — the client re-submits after approval.
- **At `/chat` approval**: a *previous* PLAN is loaded from the DB. If the plan's `metadata.figma_url` is non-empty (and `metadata.figma_token` is present), the pipeline rebuilds the plan from Figma so `plan.pages` truly come from the Figma file, then dispatches `_run_figma_relay_pipeline()`. Otherwise it dispatches `_run_relay_pipeline()`.

There is **no path** that runs both pipelines for the same project — the request fans out at exactly one point.

---

## LLM-Driven Pipeline

`_run_relay_pipeline(output_dir, plan, description, figma_context=None, project_id=...)` at `backend/routers/generate.py:305`.

High-level order:

```
design-spec  →  contracts  →  schema (DB + config)  →
parallel(API, BusinessLogic)  →  rules  →  runtime injection  →
nav-flow + shell layout  →  per-page schemas (page_schema_agent)  →
post-emit photos + nav-flow.json refresh + app-emitter  →
seed  →  completeness check  →  QA  →
coder↔reviewer loop (validator + page-fix)  →
visual review  →  flow validation  →  browser validation  →
indexer  →  final verify  →  fidelity scoring
```

### Step 0: Domain discovery + copy foundation templates

- **Source**: `agents/domain_agent.py::run_domain_discovery()` (Layer 1) + `shutil.copy2` calls at `generate.py:329-359`
- **What it does**:
  - **Discovery agent** — runs the Sonnet-backed research agent (with the `web_search_20250305` tool attached) on the user's description + plan to produce a structured `DiscoveryOutput` dossier: domain label, personas per agent role, design patterns with citations, visual language tendencies, entity suggestions, compliance regimes, common pitfalls, uncertain areas. Persisted to `<output>/src/contracts/discovery.json` via `persist_discovery()`. The dossier is the `domain_context` dict passed to every downstream agent.
  - **Chat-approval pause** — if invoked from the `/chat` endpoint, the dossier is saved to `<output>/.pending_discovery.json` (see `_save_pending_discovery` in `routers/generate.py`) and the pipeline pauses. The frontend renders a `DiscoveryCard` letting the user edit `domain` and `complianceNotes` (whitelist enforced by `_parse_discovery_edits`). On `[APPROVE_DISCOVERY]` the edits are merged via `_apply_discovery_edits` and the pipeline resumes.
  - **Template copy** — copies `backend/templates/app-foundation/` (Next.js + auth + middleware + shared UI) into the output dir except files that already exist.
- **Inputs**: `description`, `plan`. Pre-approved `domain_context` (when resuming from chat approval) skips inline discovery.
- **Outputs**:
  - `<output>/src/contracts/discovery.json` — full dossier
  - `<output>/.pending_discovery.json` — pause sentinel (cleared on approval)
  - `<output>/src/auth.ts`, `<output>/src/middleware.ts`, `<output>/src/app/api/auth/[...nextauth]/route.ts`, etc.
- **SSE events**: `discovery_started`, `discovery_complete`, `discovery_approval_needed`, `discovery_approved`, plus `log` ("Copied N foundation files…")
- **Notable behavior**:
  - `services/domain_context.py::detect_domain()` (the old keyword classifier) remains as a fallback for pre-pipeline planner calls that need a cheap label without paying for the discovery LLM round-trip.
  - Replaces the deleted `backend/knowledge/` folder — agents no longer read static curated KB files. Each agent's system prompt now includes a role-tailored `[DOMAIN PROFILE]` block built by `services/domain_context.py::build_domain_profile(domain_ctx, role)` from the in-memory dossier.
  - Template copy is skipped when `figma_context` is truthy (Figma flow brings its own pages). The auth files are pre-tested and never LLM-generated — agents customize on top.

### Step 1: Initialize the Contract Registry

- **Source**: `services/registry.py::create_registry` + `save_registry` (`generate.py:362-367`)
- **What it does**: Builds an in-memory `registry.json` skeleton from the plan — initial entries are seeded from `plan.data_models` (entities) and `plan.api_routes`. Also clears stale `src/schemas/*.json` from any prior run (`_clean_schemas_dir`).
- **Outputs**: `<output>/registry.json`
- **SSE event**: `log` — "[Registry] Initialized: N entities, M routes"
- **Notable behavior**: The registry is the single source of truth that downstream agents read (entities, routes, components, pages) and validate against. Every later phase merges new sections into it via `merge_section()`.

### Step 2: Design Agent (Phase 0)

- **Source**: `agents/design_agent.py::run_design_agent` (`generate.py:399-419`)
- **What it does**: Researches a UI/UX brief for the app — colour palette, typography, density, navigation pattern, per-entity UI archetype recommendation, imagery requirements. Streams its output text; the helper `extract_design_spec()` then parses the trailing `\`\`\`design-spec` fenced JSON.
- **Inputs**: `plan`, `domain_context`, optional `reference*.png` screenshots (Figma context if any).
- **Outputs**:
  - `<output>/src/contracts/design-spec.json` (via `save_design_spec`, which also rewrites `src/app/globals.css` palette CSS vars and Google-Fonts imports based on the chosen typography register)
- **SSE event**: `status` ("Researching UI/UX design..."), `log` ("[Design] …")
- **Notable behavior**:
  - Always runs even for text projects (no Figma).
  - Uses Sonnet (`claude-sonnet-4-20250514`).
  - Streamed `log`/`message` text is accumulated into `collected_design_text` so `extract_design_spec` can mine the JSON from agent chatter.

### Step 3: Brand auto-detect from URL

- **Source**: `services/url_brand_scraper.py::scrape_brand_from_url` (`generate.py:429-455`)
- **What it does**: Looks for any HTTP URL inside `description` or `plan.description` and scrapes that site's `og:image` to k-means-cluster a brand palette (primary, secondary, accent, etc.). The result overrides the LLM-extracted palette inside `design_spec.brand.derived`.
- **Outputs**: Mutates `design_spec.brand.derived = { primary, secondary, ... }` before save.
- **SSE event**: `log` — "[Brand] Auto-detecting palette from …", "[Brand] Extracted primary #… from …"
- **Notable behavior**: Silent failure — if no URL, scrape fails, or `og:image` missing, this step is a no-op and design-spec colours stay LLM/industry-derived.

### Step 4: Design spec save (with industry fallback)

- **Source**: `agents/design_agent.py::save_design_spec` + `services/industry_design.py::generate_design_spec_from_industry` (`generate.py:458-472`)
- **What it does**: Persists the design spec. If `extract_design_spec` couldn't parse one (LLM bailed early), falls back to `generate_design_spec_from_industry(domain_label, description, plan)` so the file is never missing. Always passes `brand_derived` through so a scraped URL palette takes precedence.
- **Outputs**: `<output>/src/contracts/design-spec.json` (final), plus side-effect rewrite of `src/app/globals.css` palette + typography blocks.

### Step 5: Register classification

- **Source**: `agents/planner.py::classify_register_llm` + `services/cta_defaults.py::defaults_for_register` (`generate.py:481-490`)
- **What it does**: Picks one of six visual "registers" (e.g. `"workday"`, `"saas-marketing"`, `"prosumer-tool"`, …) that pin CTA hierarchy and density. LLM-driven with a rule-based fallback. Writes back into `design_spec.register` + `design_spec.cta_hierarchy` and re-saves the spec.
- **Outputs**: Updated `design-spec.json`.
- **SSE event**: `log` — "[Design] Register: …"

### Step 6: Tokens compile (FIDELITY_MODE_ENABLED)

- **Source**: `services/design_compiler.py::compile_to_file` (`generate.py:500-515`)
- **What it does**: Deterministically compiles `design-spec.json` → `src/theme/tokens.custom.json` (the Tailwind-token shape the renderer reads at runtime).
- **Inputs**: `design-spec.json`
- **Outputs**: `<output>/src/theme/tokens.custom.json`
- **Notable behavior**: Gated by `FIDELITY_MODE_ENABLED` env flag (default `true`). When disabled, downstream agents read a stale or library-default token file.

### Step 7: Contract Agent (Phase 1)

- **Source**: `agents/contract_agent.py::run_contract_agent` (`generate.py:518-524`)
- **What it does**: Writes the five "contracts" that downstream agents read as a typed interface:
  1. `src/contracts/api-client.ts` — typed fetch functions per entity (CRUD + stats)
  2. `src/contracts/design-system.tsx` — page-shell components
  3. `src/contracts/services.ts` — workflow interfaces
  4. `src/contracts/app-model.json` — dependency graph (entities + pages)
  5. `contracts/seed-plan.json` — topologically-sorted seed plan
- **Inputs**: `plan`, `domain_context`. LLM model: Sonnet.
- **Outputs**: Above five files under `src/contracts/` + `contracts/`.
- **SSE event**: `status` ("Generating contracts..."), `office` agent_start/agent_complete for `contract_writer`.

### Step 8: Contract Gate

- **Source**: `services/phase_gates.py::check_contract_completeness` (`generate.py:527-539`)
- **What it does**: Verifies `api-client.ts` and `app-model.json` reference every plan entity + at least the canonical page set (list/detail/new per entity). If gaps are found, re-invokes `run_contract_agent` once.
- **Inputs**: `output_dir`, `plan`
- **Outputs**: same as Step 7 (overwrites).
- **SSE event**: `log` — "[Contract Gate] N gaps found …" or "[Contract Gate] ✓ All contracts complete"
- **Notable behavior**: Single retry attempt; failure on retry is logged but non-fatal.

### Step 9: Schema Agent (Phase 2)

- **Source**: `agents/schema_agent.py::run_schema_agent` (`generate.py:545-552`)
- **What it does**: Writes ALL project-level config + DB schema + types + runs `npm install`:
  - `package.json`, `tsconfig.json`, `next.config.ts`, `postcss.config.mjs`, `docker-compose.yml`, `.env.local.example`, `drizzle.config.ts`
  - `src/db/index.ts`, `src/db/schema/<entity>.ts` (one per entity), `src/db/schema/index.ts`
  - `src/types/<entity>.ts` per entity + `src/types/index.ts`
  - `src/lib/utils.ts`
  - Runs `npm install`
- **Inputs**: `plan`, `domain_context`, `project_short_id` (becomes the per-project DB name so multiple projects coexist).
- **Outputs**: Above files. Uses Haiku 4.5.
- **SSE event**: `status` ("Building foundation..."), `office` start/complete.

### Step 10: Registry merge — entities

- **Source**: `services/registry_extractor.py::extract_entities_from_schema` + `services/registry.py::merge_section` (`generate.py:555-559`)
- **What it does**: Parses every emitted `src/db/schema/*.ts` to extract actual entity definitions (names, columns, foreign keys) and merges them into `registry.json` under `entities`.
- **Outputs**: Updated `<output>/registry.json`
- **SSE event**: `log` — "[Registry] Updated entities from schema: N extracted"

### Step 11: Parallel — API Agent + Business Logic Agent (Phase 3)

- **Source**: `agents/api_agent.py::run_api_agent` + `agents/business_logic_agent.py::run_business_logic_agent` orchestrated by `services/parallel_runner.py::run_parallel_agents` (`generate.py:564-596`)
- **What it does**:
  - **API Agent** (Haiku): writes 3 route files per entity — `src/app/api/<slug>/route.ts` (list+create), `<slug>/[id]/route.ts` (get/put/delete), `<slug>/stats/route.ts`. Plus any custom routes in `plan.api_routes`.
  - **Business Logic Agent** (Haiku, only if `plan.workflows` is non-empty): writes service implementations under `src/lib/services/` AND fills `workflows/*.json` definitions.
- **Inputs**: `plan`, `domain_context`. API agent additionally reads the registry-injected entity context.
- **Outputs**:
  - `src/app/api/**/route.ts`
  - `src/lib/services/*.ts`
  - `workflows/*.json` (partial — gets a fallback fill later in step 24)
- **SSE event**: `status`, `office` parallel_start_event + per-agent start/complete.
- **Notable behavior**: BusinessLogic is added to the parallel list ONLY when `plan.workflows` is non-empty.

| Agent          | Module                                  | Model  | Conditional        |
|----------------|-----------------------------------------|--------|---------------------|
| API            | `agents/api_agent.py`                   | Haiku  | always              |
| Business Logic | `agents/business_logic_agent.py`        | Haiku  | iff `plan.workflows`|

### Step 12: Registry merge — API routes + validation

- **Source**: `services/registry_extractor.py::extract_routes_from_files` + `services/registry_validator.py::validate_registry` (`generate.py:599-610`)
- **What it does**: Scans `src/app/api/**/route.ts` to extract real HTTP routes and merges into `registry.api_routes`. Runs the 11-check validator (entity↔route↔component cross-references) and emits an SSE `registry_validation` event with the error list when there are mismatches.
- **Outputs**: Updated `registry.json`
- **SSE event**: `registry_validation` (`{phase: "post_api", errors: [...]}`)

### Step 13: Rules Agent

- **Source**: `agents/rules_agent.py::run_rules_agent` (`generate.py:620-630`)
- **What it does**: Converts the planner's prose business rules into structured ProjectRules. Validates each rule against the registry's entities/fields. When `project_id` is supplied, also syncs the rules to the `project_rules` DB table so the editor's RulesPanel picks them up.
- **Inputs**: `output_dir`, `plan`, `domain_context`, `project_id`
- **Outputs**: Returns a list of rule dicts (later exported to `rules/index.json` by `runtime_injector`).
- **SSE event**: `status` ("Generating business rules..."), `log` ("[Rules] Generated N rule(s) …")
- **Notable behavior**: Failure is non-fatal — pipeline continues with no rules.

### Step 14: Auth Gate

- **Source**: `services/phase_gates.py::check_auth_completeness` (`generate.py:633-656`)
- **What it does**: Verifies `src/auth.ts`, `src/middleware.ts`, `src/app/api/auth/[...nextauth]/route.ts`, `src/app/api/auth/signup/route.ts` all exist. If anything is missing, re-copies from `backend/templates/app-foundation/`.
- **Notable behavior**: This phase is exclusively template-based — no LLM call. Auth code is never LLM-generated.

### Step 15: Runtime Injection

- **Source**: `services/runtime_injector.py::inject_runtime` (`generate.py:660-674`)
- **What it does**: Always-on. Copies the embedded runtime stack into `<output>/src/lib/`:
  - `src/lib/feel-lite/` (expression engine)
  - `src/lib/workflows/` (workflow runtime)
  - `src/lib/rules/` (rules runtime)
  - `src/lib/runtime-loader.ts`
  - `src/lib/data-engine.ts` + `src/lib/data-engine/` (aggregations, saved-views)
  - `src/lib/event-registry.ts`
- And generates:
  - `src/app/api/data/[...path]/route.ts` (catch-all Data API)
  - `src/app/api/workflows/[id]/execute/route.ts` + `workflows/event/[event]/route.ts`
  - `src/app/api/workflows/route.ts` + `[id]/route.ts` + `tasks/route.ts`
  - `src/components/WorkflowTriggerButton.tsx`
  - `rules/index.json` (rules exported from DB)
  - `start.sh`
  - `.env.local` if missing
- **SSE event**: `log` — "[Runtime] Injected Data Engine + Workflow Engine: N files copied"

### Step 16: API Gate

- **Source**: `services/phase_gates.py::check_api_completeness` (`generate.py:677-695`)
- **What it does**: Verifies every entity has CRUD + stats routes. On failure, re-invokes `run_api_agent`, then re-extracts routes back into the registry.

### Step 17: Frontend dispatch — schema mode vs IR mode vs LLM mode

- **Source**: `services/schema_pipeline.py::SCHEMA_MODE_ENABLED` / `services/ir_pipeline.py::IR_FRONTEND_ENABLED` (`generate.py:698-907`)
- **What it does**: Branches on env flags:

| Mode        | Flag                                                 | Default | Output type             |
|-------------|------------------------------------------------------|---------|-------------------------|
| Schema      | `SCHEMA_MODE_ENABLED=true`                           | true    | `src/schemas/*.json`    |
| IR          | `SCHEMA_MODE_ENABLED=false`, `IR_FRONTEND_ENABLED=true`| false   | TSX via IR compiler     |
| LLM (legacy)| both flags off                                       | n/a     | TSX via component+page agents |

Steps 18-22 below describe the default (Schema mode) path. The LLM-mode tail (Components + Pages agents) is documented further down.

### Step 18: nav-flow synthesis from plan

- **Source**: `services/nav_flow_from_plan.py::nav_flow_from_plan` + `write_nav_flow` (`generate.py:710-718`)
- **What it does**: Deterministic — synthesises `src/contracts/nav-flow.json` from `plan.pages`. Each page gets an `id` (slug from route), `title`, `route`, `schemaFile` (e.g. `src/schemas/login.json`), and a `shell` flag (`false` when `page.type == "auth"`, true otherwise). Auth routes are aggregated under `nav_flow.auth_routes`; first non-auth route becomes `post_login_redirect`.
- **Outputs**: `<output>/src/contracts/nav-flow.json`
- **SSE event**: `log` — "[NavFlow] ✓ N pages → nav-flow.json"

### Step 19: Shell Layout Agent

- **Source**: `agents/shell_layout_agent.py::generate_shell_to_file` (`generate.py:722-758`)
- **What it does**: ONLY runs when `nav-flow.json` has any `shell: true` pages (skipped for auth-only projects). Asks Sonnet for an `ir-shell` JSON block (top bar + sidebar + main outlet), extracts it, validates with `services/shell_validator.py::validate_shell`, normalises Button variants via `services/schema_normalizer.py::normalize_v2_schema`, applies `apply_page_shell_layout_to_schema` (sticky sidebar + scrollable main + viewport fill), writes `<output>/src/schemas/shell.json`. If the heuristic transformed the schema, also appends `.sidebar-scroll` / `.main-scroll` CSS rules to `src/app/globals.css`.
- **Inputs**: `plan`, `nav_flow`, brand info from design_spec.
- **Outputs**: `<output>/src/schemas/shell.json` + CSS append.
- **SSE event**: `log` — "[ShellLayout] ✓ shell.json written (N nodes)"

### Step 20: Schema Frontend Pipeline (Phase 4 — per-page emission)

- **Source**: `services/schema_pipeline.py::run_schema_frontend_pipeline` → `_emit_per_page` → `agents/page_schema_agent.py::run_page_schema_agent` (`generate.py:761-770`)
- **What it does**: Iterates `plan.pages` and, for each page, calls Sonnet through `run_page_schema_agent`:
  1. Slugs the route (`slugify_route("/users/[id]")` → `"users-detail"`).
  2. Builds a per-page brief including `page_type` (drives `page_type_templates.template_for(...)` injection).
  3. Builds a schema prompt with: registry context, design-spec, domain context, focal entity binding context, dashboard entity summary (when entity-free), shell-aware "content-only" instruction (when `shell.json` exists AND page is non-auth).
  4. LLM call → expects fenced JSON.
  5. `_validate_schema_json` runs Zod-style validation.
  6. Two-pass retry: failed pages get a second attempt with fresh state.
  7. Visual enrichment post-pass (`services/schema_visual_enricher.py::enrich_schema_visuals`) fills blank `photoUrl`/`backgroundImage`/`icon` from design_spec pools.
  8. Illustration asset bundler copies referenced SVG illustrations into the output dir.
  9. `_fill_missing_with_stubs` — for any plan.page whose schema file is still missing (silent LLM failure), writes a deterministic template via `page_template_generator.generate_template_schema`.
  10. `_regenerate_route_registry` — rewrites `src/schemas/registry.ts` as a dynamic-import map keyed by route.
- **Outputs**:
  - `<output>/src/schemas/<slug>.json` per page
  - `<output>/src/schemas/registry.ts`
- **SSE event**: `status` per route, `log` ("[Schema] ✓ /route" / "[Schema] ⚠ /route failed (TypeError): …")
- **Notable behavior**: Includes a `skip_routes` param — used by the Figma pipeline (always empty for LLM-only) so already-emitted Figma pages aren't overwritten.

### Step 21: Post-emit gates (CTA, Progressive Disclosure, Coverage)

- **Source**: `services/phase_gates.py::check_cta_hierarchy`, `check_progressive_disclosure`, `check_pages_coverage` (`generate.py:772-813`)
- **What it does**: Detect-only (no retry yet). CTA gate flags pages where the CTA hierarchy doesn't match `design_spec.cta_hierarchy`. Progressive disclosure flags forms with no grouped reveal. Coverage gate verifies every `plan.pages` route has a schema on disk.

### Step 22: Photo injection

- **Source**: `services/post_emit_photo_injector.py::inject_photos_into_dir` (`generate.py:819-830`)
- **What it does**: Walks every emitted `src/schemas/*.json` and fills in `photoUrl` on Avatar/Card nodes + `backgroundImage` on Hero nodes from `design_spec.entityPhotos`. Idempotent — preserves any existing values.
- **Outputs**: In-place mutation of every page schema.
- **SSE event**: `log` — "[Photos] Injected photo URLs into N page schema(s)"

### Step 23: nav-flow refresh + standalone app emit

- **Source**: `services/nav_flow_emitter.py::emit_nav_flow` + `services/app_emitter.py::emit_standalone_app` (`generate.py:833-848`)
- **What it does**:
  - `emit_nav_flow` re-walks the (now-final) page schemas to extract `Button.navigate` transitions, merges them with `plan.pages` to overwrite `nav-flow.json` with transitions populated.
  - `emit_standalone_app` copies the `backend/templates/standalone-app/` template into the output dir (renders `.tmpl` files with the project's short_id) and vendors the `@tentoroforge/*` packages into `<output>/vendor/@tentoroforge/<pkg>/` so the resulting tarball runs `npm install` standalone.
- **Outputs**:
  - `<output>/src/contracts/nav-flow.json` (rewritten)
  - `<output>/package.json`, `<output>/next.config.ts`, `<output>/src/app/layout.tsx`, etc.
  - `<output>/vendor/@tentoroforge/<engine|library|renderer|patches|registry>/`

### Step 24: Fidelity scoring (advisory)

- **Source**: `services/fidelity_runner.py::run_fidelity_scoring` (`generate.py:851-855`)
- **What it does**: Optional. Gated by `FIDELITY_SCORING_ENABLED` env var. Boots a preview, captures screenshots of every page, calls a vision LLM to score each page 0-10 against design-spec criteria.
- **SSE event**: `fidelity` per page, plus a `log` summary.

> **In Schema mode the pipeline returns here (`return` at `generate.py:862`).** Phase 6/7/8/9 (seed, QA, validator, indexer) only run on the legacy LLM-TSX path. The current default is Schema mode, so the steps below from Step 25 onward primarily document the legacy/LLM-mode tail, which still also runs in the Figma pipeline.

### Step 25 (LLM-TSX mode only): Component Agent

- **Source**: `agents/component_agent.py::run_component_agent` (`generate.py:911-924`)
- **What it does**: Generates the project's atomic + feature TSX components. Reads the registry for known entities + routes, reads the design-spec for styling, writes under `src/components/`.
- **Outputs**: `<output>/src/components/**/*.tsx`
- **SSE event**: `status` ("Creating UI components..."), `office` start/complete

### Step 26 (LLM-TSX mode only): Component Gate

- **Source**: `services/phase_gates.py::check_component_completeness`
- **What it does**: If any required component is missing, re-invokes `run_component_agent` once.

### Step 27 (LLM-TSX mode only): Page Agent

- **Source**: `agents/page_agent.py::run_page_agent` (`generate.py:949-961`)
- **What it does**: Generates Next.js App Router page files (`src/app/**/page.tsx`) using the components + contracts. Cross-checks against registry entities and API routes.
- **Outputs**: `<output>/src/app/**/page.tsx`

### Step 28: Page Gate + Cross-Reference Gate + UX Gate

- **Source**: `phase_gates.check_page_completeness`, `check_cross_references`, `check_ux_compliance` (`generate.py:974-1019`)
- **What they do**:
  - **Page Gate** — re-runs Page Agent with a `fix_prompt` if pages are incomplete.
  - **Cross-Reference Gate** — flags pages that call API routes that don't exist; sends a fix prompt back to `run_api_agent`.
  - **UX Gate** — domain-specific UX patterns (loaded via `domain_ux_specs.py`); sends a fix prompt back to `run_page_agent`.

### Step 29: Workflow fallback fill + Workflow Gate

- **Source**: `services/workflow_generator.py::generate_workflow_definitions` + `phase_gates.check_workflow_integration` (`generate.py:1021-1044`)
- **What it does**: For any `plan.workflows[i]` whose definition file is still empty (Business Logic Agent didn't fill it), writes a deterministic scaffold. Then verifies workflows are wired end-to-end (trigger → step → action). On failure, re-invokes BusinessLogic.

### Step 30: Seed Generator (Phase 6)

- **Source**: `agents/seed_generator.py::run_seed_generator` (`generate.py:1050-1056`)
- **What it does**: Writes `src/db/seed.ts` — reads the DB schema (per-entity or `schema.ts`), reads `contracts/seed-plan.json` for table order, writes ~10 rows per table with realistic values. Does NOT execute the seed.
- **Outputs**: `<output>/src/db/seed.ts`
- **SSE event**: `status` ("Generating seed data..."), `office` start/complete

### Step 31: Fidelity Loop (Phase 14)

- **Source**: `services/fidelity_loop.py::FidelityLoopRunner.run` (`generate.py:1059-1101`)
- **What it does**: Optional, gated by `FIDELITY_LOOP_ENABLED` (default true). Runs the vision-evaluator + patch-agent closed loop per page until score ≥ threshold or max iterations.
- **Outputs**: Patched page schemas; produces a `FidelityReport`.
- **SSE event**: `phase_start`/`phase_complete` with phase `"fidelity_loop"`. On exception emits `phase_warning` (never aborts the pipeline).

### Step 32: Completeness validator (Phase 6.5)

- **Source**: `services/completeness_validator.py::validate_completeness` + `format_issues_for_agent` (`generate.py:1107-1114`)
- **What it does**: Deterministic — finds gaps (missing routes, missing dashboard tiles, undefined entity refs) and produces a `completeness_report` string that becomes `extra_context` for QA.

### Step 33: QA Agent (Phase 7)

- **Source**: `agents/qa_agent.py::run_qa_agent` (`generate.py:1117-1123`)
- **What it does**: Cross-layer verification. Sonnet reads `app-model.json` + `Sidebar` + every page + matching API route + matching schema, then fixes mismatches. Receives the registry validation report as a "FIX THESE FIRST" block plus the completeness report.
- **Outputs**: Direct in-place edits to TSX/JSON files.
- **SSE event**: `status` ("Running QA verification..."), `office` start/complete.

### Step 34: Post-generate fixes (deterministic)

- **Source**: `services/post_generate_fixes.py::apply_post_generate_fixes` (`generate.py:1126`)
- **What it does**: Clears stale `.next/` build cache plus a few file-system patches (Tailwind v4 import line, missing `"use client"` heuristic). No LLM.

### Step 35: Coder ↔ Reviewer loop

- **Source**: `agents/validator.py::run_validator` ⇄ `agents/page_agent.py::run_page_agent` with `fix_prompt` (`generate.py:1129-1186`)
- **What it does**: Up to `MAX_REVIEW_CYCLES=5` iterations:
  - **Reviewer (Validator)**: runs `npm run build`, captures errors, runs a runtime-safety scan (missing `"use client"`, hard-coded API calls, etc.). Outputs PASS/FAIL.
  - **Coder (Page Agent re-invoke)** with `fix_prompt = validator_output[-3000:]`: reads each failing file, fixes, re-runs `npx tsc --noEmit`.
- **Exit conditions**: Build PASS with no errors → break. Hit `MAX_REVIEW_CYCLES` → break with warning.
- **SSE event**: per-cycle `status` + `log`.

### Step 36: Visual review loop

- **Source**: `screenshot.capture_key_pages` + `agent.run_design_reviewer_agent` + `agent.run_fixer_agent` (`generate.py:1190-1322`)
- **What it does**: Boots a project preview via `services/preview_manager.start_project_environment(short_id, output_dir, with_database=False)`, screenshots each page, asks a vision model whether the page is "APPROVED". For any not approved, invokes `run_fixer_agent` with the full issue list. Up to `MAX_VISUAL_CYCLES=3`. Stops preview after.
- **Outputs**: In-place edits to TSX / schema files.
- **SSE event**: `log` per cycle / page.

### Step 37: Flow snapshot validation (deterministic)

- **Source**: `services/flow_validator.py::validate_navigation_flow` (`generate.py:1253-1274`)
- **What it does**: Walks `nav-flow.json` transitions and verifies the target routes exist + the buttons referenced actually exist in the page schemas. On failure, sends a `fix_prompt` back to `run_page_agent`.

### Step 38: Browser validation

- **Source**: `services/browser_validator.py::run_browser_validation` (`generate.py:1277-1311`)
- **What it does**: Boots preview, runs a Playwright trace per page (console errors, network 4xx/5xx, hydration warnings). On failure, sends fix prompt back to `run_page_agent`, then re-runs.

### Step 39: Indexer (Phase 9)

- **Source**: `agents/indexer.py::run_indexer` (`generate.py:1317-1323`)
- **What it does**: Final pass — Haiku reads everything and writes the canonical `app-model.json` (merged with any contract-level `app-model.json` already on disk).
- **Outputs**: `<output>/app-model.json`

### Step 40: Verify pipeline

- **Source**: `services/verify_pipeline.py::run_verify_pipeline` (`generate.py:1327-1336`)
- **What it does**: Additional automated checks — CSS rules present, every page renders without throwing, etc. Surfaces issues as `log` events.

### Step 41: Final fidelity scoring

- **Source**: `services/fidelity_runner.py::run_fidelity_scoring` (`generate.py:1339-1343`)
- **What it does**: Same as Step 24, run at the end so it sees the post-QA / post-validator state. Gated by `FIDELITY_SCORING_ENABLED`.

### Step 42: build_success

- **Source**: `services/office_events.py::build_success_event` (`generate.py:1346-1353`)
- **What it does**: Emits the terminal `office` event, then a final `agent_result` carrying total cost / turns / duration.

---

### LLM Pipeline Diagram

```text
                            POST /api/projects/{id}/generate
                            (description, no figma_url)
                                       │
                          ┌────────────▼─────────────┐
                          │ run_planner (LLM)        │
                          │ → emits plan_ready       │
                          └────────────┬─────────────┘
                                       │ user approves
                                       │ via /chat
                                       ▼
                       ┌────────────────────────────────────┐
                       │ _run_relay_pipeline                │
                       │ (backend/routers/generate.py:305)  │
                       └────────────────┬───────────────────┘
                                        │
                ┌───────────────────────▼───────────────────────┐
                │ 0. run_domain_discovery (+ chat-approval pause)│
                │    + copy foundation templates                 │
                └───────────────────────┬───────────────────────┘
                                        ▼
                ┌─────────────────────────────────────────────────┐
                │ 1. create_registry (registry.json)              │
                └───────────────────────┬─────────────────────────┘
                                        ▼
                ┌─────────────────────────────────────────────────┐
                │ 2. Design Agent ──→ design-spec.json + globals  │
                └───────────────────────┬─────────────────────────┘
                                        ▼
                ┌─────────────────────────────────────────────────┐
                │ 3. brand auto-detect from URL (best effort)     │
                └───────────────────────┬─────────────────────────┘
                                        ▼
                ┌─────────────────────────────────────────────────┐
                │ 4. save_design_spec (industry fallback)         │
                ├─────────────────────────────────────────────────┤
                │ 5. classify_register_llm                        │
                ├─────────────────────────────────────────────────┤
                │ 6. design_compiler → tokens.custom.json         │
                │    (FIDELITY_MODE_ENABLED)                      │
                └───────────────────────┬─────────────────────────┘
                                        ▼
                ┌─────────────────────────────────────────────────┐
                │ 7. Contract Agent ──→ src/contracts/*           │
                │    (api-client.ts, app-model.json,              │
                │     design-system.tsx, services.ts,             │
                │     contracts/seed-plan.json)                   │
                └───────────────────────┬─────────────────────────┘
                                        ▼
                ┌─────────────────────────────────────────────────┐
                │ 8. Contract Gate (retry once on gaps)           │
                └───────────────────────┬─────────────────────────┘
                                        ▼
                ┌─────────────────────────────────────────────────┐
                │ 9. Schema Agent ──→ src/db/schema/* +           │
                │    package.json + drizzle.config + npm install  │
                └───────────────────────┬─────────────────────────┘
                                        ▼
                ┌─────────────────────────────────────────────────┐
                │ 10. extract_entities_from_schema → registry     │
                └───────────────────────┬─────────────────────────┘
                                        ▼
                ┌─────────────────────────────────────────────────┐
                │ 11. ┌─────────────────┐  ┌────────────────────┐ │
                │     │ API Agent       │  │ BusinessLogic      │ │
                │     │ src/app/api/**  │  │ src/lib/services/* │ │
                │     │ /route.ts       │  │ workflows/*.json   │ │
                │     └────────┬────────┘  └─────────┬──────────┘ │
                │              └────── parallel ─────┘            │
                └───────────────────────┬─────────────────────────┘
                                        ▼
                ┌─────────────────────────────────────────────────┐
                │ 12. extract_routes_from_files → registry        │
                │     + validate_registry (registry_validation)   │
                ├─────────────────────────────────────────────────┤
                │ 13. Rules Agent → rules/index.json + DB         │
                ├─────────────────────────────────────────────────┤
                │ 14. Auth Gate (re-copy templates)               │
                ├─────────────────────────────────────────────────┤
                │ 15. inject_runtime (Data + Workflow + Rules)    │
                │     → src/lib/{feel-lite,workflows,rules}/      │
                │     → src/app/api/{data,workflows,tasks}/       │
                ├─────────────────────────────────────────────────┤
                │ 16. API Gate (retry api_agent on gaps)          │
                └───────────────────────┬─────────────────────────┘
                                        ▼
                ┌────────────────── 17. frontend dispatch ────────────────────┐
                │                              │                              │
                │ SCHEMA_MODE_ENABLED          │  SCHEMA off,                 │
                │ (default)                    │  IR_FRONTEND_ENABLED=true    │
                │                              │                              │
                ▼                              ▼                              ▼
   ┌─────────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
   │ 18. nav_flow_from_plan  │    │ run_ir_frontend_     │    │ 25-27. LLM TSX path: │
   │     → nav-flow.json     │    │ pipeline → TSX +     │    │  Component + Page    │
   ├─────────────────────────┤    │ schema artifacts     │    │  agents → src/**.tsx │
   │ 19. ShellLayout Agent   │    │                      │    │                      │
   │     → schemas/shell.json│    │ (deterministic IR    │    │                      │
   │     + .sidebar-scroll css   │  compiler — rarely    │    │                      │
   ├─────────────────────────┤    │  enabled)            │    │                      │
   │ 20. run_schema_         │    │                      │    │                      │
   │     frontend_pipeline   │    │                      │    │                      │
   │     ─→ per-page LLM     │    │                      │    │                      │
   │     ─→ src/schemas/*.json   │                      │    │                      │
   │     ─→ stubs for misses │    │                      │    │                      │
   │     ─→ registry.ts      │    │                      │    │                      │
   ├─────────────────────────┤    │                      │    │                      │
   │ 21. CTA + PD + Coverage │    │                      │    │                      │
   │     gates (detect only) │    │                      │    │                      │
   ├─────────────────────────┤    │                      │    │                      │
   │ 22. post_emit_photo_    │    │                      │    │                      │
   │     injector            │    │                      │    │                      │
   ├─────────────────────────┤    │                      │    │                      │
   │ 23. nav_flow_emitter +  │    │                      │    │                      │
   │     emit_standalone_app │    │                      │    │                      │
   │     (vendors @tentoro-  │    │                      │    │                      │
   │      forge packages)    │    │                      │    │                      │
   ├─────────────────────────┤    │                      │    │                      │
   │ 24. fidelity scoring    │    │                      │    │                      │
   │     (advisory)          │    │                      │    │                      │
   │                         │    │                      │    │                      │
   │  ★ RETURN HERE in       │    │                      │    │                      │
   │    Schema mode          │    │                      │    │                      │
   └─────────────────────────┘    └──────────┬───────────┘    └──────────┬───────────┘
                                             │                            │
                                             │ ─────  joins ─────────  ─ ┤
                                             ▼                            ▼
                                ┌──────────────────────────────────────────────────┐
                                │ 28. Page Gate / X-Ref Gate / UX Gate             │
                                ├──────────────────────────────────────────────────┤
                                │ 29. workflow fallback fill + Workflow Gate       │
                                ├──────────────────────────────────────────────────┤
                                │ 30. Seed Generator → src/db/seed.ts              │
                                ├──────────────────────────────────────────────────┤
                                │ 31. Fidelity Loop (FIDELITY_LOOP_ENABLED)        │
                                ├──────────────────────────────────────────────────┤
                                │ 32. completeness_validator (deterministic)       │
                                ├──────────────────────────────────────────────────┤
                                │ 33. QA Agent (Sonnet — fixes cross-layer)        │
                                ├──────────────────────────────────────────────────┤
                                │ 34. apply_post_generate_fixes (clears .next/)    │
                                ├──────────────────────────────────────────────────┤
                                │ 35. Coder ↔ Reviewer loop (max 5 cycles)         │
                                │     validator → page_agent fix_prompt            │
                                ├──────────────────────────────────────────────────┤
                                │ 36. Visual review (Playwright + vision LLM)      │
                                │     up to 3 cycles                               │
                                ├──────────────────────────────────────────────────┤
                                │ 37. flow_validator (transitions / nav-flow)      │
                                ├──────────────────────────────────────────────────┤
                                │ 38. browser_validator (Playwright runtime)       │
                                ├──────────────────────────────────────────────────┤
                                │ 39. Indexer → app-model.json                     │
                                ├──────────────────────────────────────────────────┤
                                │ 40. verify_pipeline (CSS + pages checks)         │
                                ├──────────────────────────────────────────────────┤
                                │ 41. final fidelity scoring (FIDELITY_SCORING)    │
                                ├──────────────────────────────────────────────────┤
                                │ 42. build_success_event + agent_result           │
                                └──────────────────────────────────────────────────┘
```

---

## Figma-Driven Pipeline

`_run_figma_relay_pipeline(output_dir, plan, description, figma_url, figma_token)` at `backend/routers/generate.py:1356`.

This pipeline's signature design is that the **Figma deterministic mapper runs FIRST**, before any LLM phase. The intent (per comment at `generate.py:1405-1410`): backend LLM agents (Contract, Schema, API, BusinessLogic) sometimes wedge on subprocess timeouts; if we let them run first, a wedge would mean the user's Figma frames never land on disk. Running the deterministic mapper first guarantees `src/schemas/*.json` exists regardless of what happens downstream.

After the deterministic block, the pipeline goes through the same Contract → Schema → Parallel(API, BusinessLogic) → Runtime steps as the LLM pipeline, then dispatches to a Schema/IR/LLM frontend phase that **skips** routes the deterministic mapper already produced (via `skip_routes`), and finally runs the shared seed → QA → validator → indexer tail.

### Step 0: Domain discovery + registry init + figma_driven log

- **Source**: `agents/domain_agent.py::run_domain_discovery` + `services/registry.py` (`generate.py:1380-1397`)
- **What it does**: Same as LLM Step 0/1 — runs the discovery agent for a full domain dossier (or skips it when a pre-approved `domain_context` is passed in from chat-approval), builds the initial registry, clears stale schemas. Logs the inferred Figma scope ("[Figma Plan] Driven by Figma — N page(s): ['/login','/dashboard',...]") when `plan._figma_driven` is true.

### Step 1: Deterministic Figma mapper (the heart of this pipeline)

- **Source**: `services/figma_client.py::fetch_figma_node_batched` + `fetch_figma_image_urls` + `services/figma_to_schema.py::build_page_schema` + `services/figma_node_walker.py::walk_and_flatten` + `services/figma_style_extractor.py::extract_tokens` + `services/figma_typography_extractor.py::extract_typography` + `services/figma_name_classifier.py::classify` + `services/figma_asset_downloader.py::download_figma_assets` (`generate.py:1411-1662`)
- **What it does**:
  1. **Parse Figma URL** to extract `file_key`.
  2. Read `plan.pages` — every entry with `figma_node_id` is in scope (≤ 50 pages).
  3. **Batched node fetch**: `fetch_figma_node_batched(file_key, node_ids, figma_token)` pulls each frame's full document (semaphore-capped at 8 concurrent).
  4. **Walk + flatten** every fetched doc into a flat node list (`walk_and_flatten`). Container flattening collapses degenerate single-child wrappers.
  5. **SVG asset export**:
     - For every walked node that classifies as `Icon` / `Image` / `VECTOR` / `BOOLEAN_OPERATION` AND isn't a giant UI-screenshot FRAME (heuristic: image-classified FRAMEs with >4 walked children or bbox >600px in either axis are skipped UNLESS they're vector-only frames like multi-piece logos), call `fetch_figma_image_urls(file_key, exportable_ids, figma_token, format="svg")`.
     - Then `download_figma_assets(urls, output_dir, project_id=...)` downloads each CDN URL to `<output>/public/figma/` and returns `{cdn_url: /api/asset/<short_id>/figma/<file>}`. The map keyed by `fid → local_url_path` is held as `asset_paths` for the next step.
  6. **Per-frame schema build**: For each plan.page-with-figma_node_id:
     - `build_page_schema(doc, asset_paths=asset_paths)` — orchestrator that classifies every node by `(name, type)` to one of the library's schema types (Heading, Text, Input, Form, Button, Stack, Row, Card, Icon, Image, Dialog, Avatar, …) with `Box` as the safe fallback. Applies bbox-based layout inference (Container → Row from child positions), folds descendant text into leaf headlines, applies 7 polish heuristics, and auto-wires `Button.opensDialog` via name-similarity scoring against any Dialog nodes in the same page.
     - Writes `<output>/<page.file or "src/schemas/<slug>.json">`.
     - On `result.complete == False`, logs the count of Box-fallback nodes (still writes — partial schemas are better than none).
     - Tracks `deterministic_pages` set (used later to skip the LLM schema phase for these routes) + `deterministic_failures` for visibility.
  7. **Token extraction + merge**: `extract_tokens(all_walked_nodes)` and `extract_typography(all_walked_nodes)` together produce the merged color scales (`color_theory.derive_scale` builds 11-step palettes), font stacks, and spacing tokens. Written to `<output>/src/theme/tokens.custom.json` (shallow per-category merge with any existing).
  8. **(Disabled by default) Shell extraction**: gated by `FIGMA_SHELL_EXTRACT=1` env flag. When set, calls `services/figma_shell_extractor.py::extract_shell_by_structural_diff` then falls back to `extract_shell_from_pages`. Currently disabled because it was hoisting auth pages too aggressively.
- **Outputs**:
  - `<output>/src/schemas/*.json` — one per Figma frame
  - `<output>/public/figma/<icon|logo>.svg` and the `/api/asset/<short_id>/figma/...` URL convention
  - `<output>/src/theme/tokens.custom.json`
- **SSE event**: `status`, `log` ("[FigmaDeterministic] ✓ /login", "[FigmaAssets] Exporting N SVG asset(s)...", "[FigmaDeterministic] tokens merged from N walked node(s)")
- **Notable behavior**:
  - **Per-page failure isolation** — one frame's `build_page_schema` exception only fails that route (logged in `deterministic_failures`), the other pages still emit.
  - **SVG export polish** — vector-only multi-piece logos (e.g. "DITANS HEALTH" wordmark with 12+ child VECTORs) are exported as one SVG via `_is_vector_only_frame`.
  - **Always non-fatal** — the whole `try` is wrapped, so a Figma API outage degrades to "no pages emitted yet; LLM schema phase will fill them in".

### Step 2: Figma MCP overlay block

- **Source**: `agents/figma_mcp_agent.py::fetch_jsx_via_mcp` + `services/figma_mcp_pipeline.py::build_schema_from_jsx` (`generate.py:1664-1770`)
- **What it does**:
  1. **Reachability probe** — HTTP GET to `http://127.0.0.1:3845/mcp` with a 2s timeout. If unreachable, the entire MCP block is skipped (single log line).
  2. For each `plan.pages` entry with `figma_node_id`:
     - Builds a per-page URL `https://www.figma.com/design/<file_key>/frame?node-id=<node-id with : → ->`.
     - `fetch_jsx_via_mcp(page_url)` — wraps a Claude agent with one allowed tool (`mcp__figma-dev-mode-mcp-server__get_design_context`). Returns the raw JSX from Figma's Dev Mode server.
     - `build_schema_from_jsx(jsx, output_dir, project_id=str(project_id))`:
       - Extracts MCP asset URLs from the JSX.
       - `download_figma_assets` to cache them locally to `<output>/public/figma/`.
       - `transform_jsx_to_schema(jsx, asset_paths)` — JSX AST → PageV2 schema. Strips Figma absolute positioning.
       - Upserts the page into `nav-flow.json` via `_upsert_nav_flow`.
     - **Overwrites** the deterministic schema with the MCP-derived one for that page (same filename convention).
  3. Tasks for all pages are gathered in parallel with a semaphore of 3 concurrent MCP calls.
- **Outputs**: Overwrites `<output>/src/schemas/<slug>.json` per page when MCP succeeded.
- **SSE event**: `log` ("[FigmaMCP] MCP available — upgrading N page(s)…", "[FigmaMCP] ✓ /login (3 asset(s) cached)", "[FigmaMCP] ⚠ /dashboard: no JSX returned — keeping deterministic schema")
- **Notable behavior**:
  - **Per-page failure isolation** — keeps deterministic schema when MCP fails for a page.
  - **Whole-block failure non-fatal** — wrapped in outer try/except; pipeline continues with deterministic schemas intact.

### Step 3: Contract Agent (Phase 1)

- **Source**: same as LLM Step 7 (`generate.py:1797-1815`)
- **Notable difference**: No design-spec was produced by a Design Agent (Figma context replaces that role). However Figma context plus a separate `extract_figma_context()` call (in the entry point `generate_project`, before this pipeline starts) writes `src/contracts/figma-context.json` with extracted color/font/radius/spacing token sets. The Contract Agent reads this as part of its input.

### Step 4: Inject register + cta_hierarchy into design-spec

- **Source**: `agents/planner.py::classify_register_llm` + `agents/design_agent.py::save_design_spec` + `services/cta_defaults.py::defaults_for_register` (`generate.py:1820-1839`)
- **What it does**: Figma context doesn't include a `register` field, so the pipeline LLM-classifies the register (same call as LLM Step 5) and saves `design-spec.register` + `design-spec.cta_hierarchy` back to disk. Skipped silently if `design-spec.json` doesn't exist yet.

### Step 5: Tokens compile (FIDELITY_MODE_ENABLED)

- **Source**: `services/design_compiler.py::compile_to_file` (`generate.py:1845-1860`)
- **What it does**: Same as LLM Step 6. **Note**: in this pipeline `tokens.custom.json` already exists from the deterministic mapper. `compile_to_file` shallow-merges design-spec-derived tokens with the existing file, so Figma-extracted tokens are preserved.

### Step 6: Schema Agent (Phase 2)

- **Source**: same as LLM Step 9 (`generate.py:1863-1870`)
- **Outputs**: Same DB schema + config files as LLM pipeline.

### Step 7: Registry merge — entities (post-schema)

- Same as LLM Step 10 (`generate.py:1873-1877`).

### Step 8: Parallel — API Agent + Business Logic Agent (Phase 3)

- Same as LLM Step 11 (`generate.py:1882-1913`).

### Step 9: Registry merge — routes + validation

- Same as LLM Step 12 (`generate.py:1916-1927`).

### Step 10: Auth Gate (Figma pipeline)

- Same as LLM Step 14 (`generate.py:1932-1955`). The Figma pipeline does NOT have a Rules Agent step — there's no `run_rules_agent` call in `_run_figma_relay_pipeline`.

### Step 11: Runtime Injection

- Same as LLM Step 15 (`generate.py:1958-1963`).

### Step 12: Frontend dispatch with skip_routes (Phase 4+5)

- **Source**: `services/schema_pipeline.py::run_schema_frontend_pipeline(skip_routes=deterministic_pages)` (`generate.py:1972-2002`)
- **What it does**:
  - When `len(deterministic_pages) >= len(plan.pages)`, the LLM schema phase is **entirely skipped** — every requested page is already on disk.
  - Otherwise the pipeline runs `run_schema_frontend_pipeline` with `skip_routes=deterministic_pages` — the per-page emitter filters out any `plan.pages` entry whose `route` is in that set, and the LLM only fills the gaps (frames the mapper couldn't fetch or where MCP overwrote with a bad result).
- **Outputs**: For routes not in `skip_routes`: same as LLM Step 20 — `src/schemas/<slug>.json` + `registry.ts`.
- **SSE event**: `log` — "[Pipeline] Deterministic mapper covered N/M pages — LLM fills the rest" OR "[Pipeline] Deterministic mapper covered all M plan page(s) — skipping LLM schema pipeline".

### Step 13: CTA / Progressive Disclosure / Coverage Gates

- Same as LLM Step 21 (`generate.py:2004-2045`).

### Step 14: Photo injection

- Same as LLM Step 22 (`generate.py:2050-2062`).

### Step 15: nav-flow refresh + standalone app emit

- Same as LLM Step 23 (`generate.py:2064-2080`).

### Step 16: Fidelity scoring (advisory) + return in Schema mode

- Same as LLM Step 24 (`generate.py:2083-2094`).
- **In Schema mode, this pipeline also returns here** (`return` at `generate.py:2094`). The Figma+IR_FRONTEND_ENABLED variant continues, and the legacy LLM-mode tail of Component+Page+QA+Indexer is replaced by the FigmaUI Agent.

### Step 17 (IR mode only): IR Figma pipeline

- **Source**: `services/ir_figma_pipeline.py::run_figma_ir_pipeline` (`generate.py:2096-2126`)
- **What it does**: Calls `run_figma_ir_pipeline(output_dir, plan, description, figma_url, figma_token)` — the IR-compiler path that converts Figma → IR → TSX deterministically. Then extracts components + pages back into the registry.

### Step 18 (LLM-TSX mode only): Figma UI Agent

- **Source**: `agents/figma_ui_agent.py::run_figma_ui_agent` (`generate.py:2127-2161`)
- **What it does**: Replaces both Component Agent + Page Agent for Figma flows. Single agent reads the Figma file directly (via screenshots / styles.json / figma-context.json) and emits pixel-targeted TSX for both components and pages.
- **Outputs**: `<output>/src/components/**/*.tsx` + `<output>/src/app/**/page.tsx`

### Step 19: Seed Generator (Phase 6)

- Same as LLM Step 30 (`generate.py:2166-2173`).

### Step 20: Completeness validator + QA Agent

- Same as LLM Step 32+33 (`generate.py:2179-2195`).

### Step 21: Post-generate fixes

- Same as LLM Step 34 (`generate.py:2198`).

### Step 22: Coder ↔ Reviewer loop

- Same as LLM Step 35 (`generate.py:2200-2258`).
- **Notable difference**: The reviewer's CODER call invokes `run_page_agent` — even though pages came from the Figma UI Agent, fix prompts route through the Page Agent.

### Step 23: Visual review loop

- Same as LLM Step 36 (`generate.py:2261-2322`).

### Step 24: Indexer + final scoring + build_success

- Same as LLM Steps 39-42 (`generate.py:2324-2351`).
- **Notable difference**: The Figma pipeline does NOT run Step 37 (Flow validator) or Step 38 (browser validator) or Step 40 (verify_pipeline). It jumps straight from visual review → indexer → fidelity scoring → success.

---

### Figma Pipeline Diagram

```text
                                  POST /api/projects/{id}/generate
                                  (figma_url + figma_token supplied)
                                                │
                                                ▼
                                ┌────────────────────────────────────┐
                                │ build_plan_from_figma()            │
                                │ - parse fileKey                    │
                                │ - fetch_figma_file depth=2         │
                                │ - one plan.page per top FRAME      │
                                │ - sets _figma_driven = True        │
                                └────────────────┬───────────────────┘
                                                 │
                                                 ▼
                                ┌────────────────────────────────────┐
                                │ design_analyzer (LLM) builds a     │
                                │ design brief from screenshots —    │
                                │ emits plan_ready / DESIGN_ANALYSIS │
                                └────────────────┬───────────────────┘
                                                 │ user approves via /chat
                                                 │
                                                 ▼
                                ┌────────────────────────────────────┐
                                │ _run_figma_relay_pipeline          │
                                │ (generate.py:1356)                 │
                                └────────────────┬───────────────────┘
                                                 │
                ┌────────────────────────────────▼────────────────────────────────┐
                │ 0. detect_domain + create_registry + clean schemas              │
                └────────────────────────────────┬────────────────────────────────┘
                                                 ▼
                ┌─────────────────────────────────────────────────────────────────┐
                │ 1. DETERMINISTIC FIGMA MAPPER (runs FIRST — guarantees pages    │
                │    land even if LLM agents wedge)                               │
                │                                                                 │
                │   parse_figma_url → file_key                                    │
                │   plan.pages.filter(p.figma_node_id) → node_ids                 │
                │   fetch_figma_node_batched (sem=8)  ─────────┐                  │
                │                                              │                  │
                │   walk_and_flatten(doc) for all docs ────┐   │                  │
                │                                          │   │                  │
                │   ┌──────────────────────────────┐       │   │                  │
                │   │ SVG asset export             │       │   │                  │
                │   │  classify(name, type) →      │       │   │                  │
                │   │  Icon/Image/VECTOR/BOOL_OP   │       │   │                  │
                │   │  → fetch_figma_image_urls    │       │   │                  │
                │   │  → download_figma_assets     │       │   │                  │
                │   │  → {fid: /api/asset/.../svg} │       │   │                  │
                │   └──────────────┬───────────────┘       │   │                  │
                │                  │                       │   │                  │
                │   for page in plan.pages_with_node_id:   │   │                  │
                │     build_page_schema(doc, asset_paths)  │   │                  │
                │     → src/schemas/<slug>.json            │   │                  │
                │     → deterministic_pages.add(route)     │   │                  │
                │                                          │   │                  │
                │   extract_tokens + extract_typography ───┘   │                  │
                │     → src/theme/tokens.custom.json (merge)   │                  │
                │                                              │                  │
                │   IF env FIGMA_SHELL_EXTRACT=1:              │                  │
                │     extract_shell_by_structural_diff /       │                  │
                │     extract_shell_from_pages → shell.json   ─┘                  │
                └────────────────────────────────┬────────────────────────────────┘
                                                 ▼
                ┌─────────────────────────────────────────────────────────────────┐
                │ 2. FIGMA MCP OVERLAY                                            │
                │    probe http://127.0.0.1:3845/mcp; skip if unreachable         │
                │    for page in plan.pages_with_node_id (sem=3 concurrent):     │
                │      fetch_jsx_via_mcp(url) [Claude agent + MCP tool]           │
                │      → build_schema_from_jsx(jsx, asset_paths)                  │
                │      → extract MCP asset URLs                                   │
                │      → download_figma_assets to public/figma/                   │
                │      → transform_jsx_to_schema (strips abs positioning)         │
                │      → _upsert_nav_flow                                         │
                │      → OVERWRITES src/schemas/<slug>.json on success            │
                └────────────────────────────────┬────────────────────────────────┘
                                                 ▼
                ┌─────────────────────────────────────────────────────────────────┐
                │ 3. Contract Agent  (reads src/contracts/figma-context.json)     │
                ├─────────────────────────────────────────────────────────────────┤
                │ 4. Inject register + cta_hierarchy into design-spec.json        │
                ├─────────────────────────────────────────────────────────────────┤
                │ 5. design_compiler → tokens.custom.json (merges over Figma)     │
                ├─────────────────────────────────────────────────────────────────┤
                │ 6. Schema Agent (DB schema, config, npm install)                │
                ├─────────────────────────────────────────────────────────────────┤
                │ 7. extract_entities_from_schema → registry                      │
                ├─────────────────────────────────────────────────────────────────┤
                │ 8. ┌───────────────┐    ┌──────────────────────────┐            │
                │    │ API Agent     │ ∥  │ BusinessLogic (if wfs)   │            │
                │    └───────────────┘    └──────────────────────────┘            │
                ├─────────────────────────────────────────────────────────────────┤
                │ 9. extract_routes_from_files + validate_registry                │
                ├─────────────────────────────────────────────────────────────────┤
                │ 10. Auth Gate (template re-copy)                                │
                ├─────────────────────────────────────────────────────────────────┤
                │ 11. inject_runtime (Data + Workflow + Rules engines)            │
                └────────────────────────────────┬────────────────────────────────┘
                                                 ▼
                ┌────────────────── 12. frontend dispatch ────────────────────────┐
                │                              │                                  │
                │ SCHEMA_MODE_ENABLED          │  SCHEMA off,                     │
                │ (default)                    │  IR_FRONTEND_ENABLED=true        │
                │                              │                                  │
                ▼                              ▼                                  ▼
   ┌─────────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
   │ IF len(det_pages) >=    │    │ 17. run_figma_ir_    │    │ 18. Figma UI Agent  │
   │ len(plan.pages):        │    │ pipeline (Figma →    │    │  (single LLM call    │
   │   SKIP LLM schema phase │    │ IR → TSX compile)    │    │  → components +      │
   │ ELSE:                   │    │                      │    │  pages TSX)          │
   │   run_schema_frontend_  │    │                      │    │                      │
   │   pipeline(skip_routes= │    │                      │    │                      │
   │     deterministic_pages)│    │                      │    │                      │
   │   ─→ per-page LLM ONLY  │    │                      │    │                      │
   │     for gaps            │    │                      │    │                      │
   ├─────────────────────────┤    │                      │    │                      │
   │ 13. CTA + PD + Coverage │    │                      │    │                      │
   │     gates               │    │                      │    │                      │
   ├─────────────────────────┤    │                      │    │                      │
   │ 14. post_emit_photo_    │    │                      │    │                      │
   │     injector            │    │                      │    │                      │
   ├─────────────────────────┤    │                      │    │                      │
   │ 15. nav_flow_emitter +  │    │                      │    │                      │
   │     emit_standalone_app │    │                      │    │                      │
   ├─────────────────────────┤    │                      │    │                      │
   │ 16. fidelity scoring +  │    │                      │    │                      │
   │     RETURN              │    │                      │    │                      │
   └─────────────────────────┘    └──────────┬───────────┘    └──────────┬───────────┘
                                             │                           │
                                             │ ─── joins on next phase ──┤
                                             ▼                           ▼
                                ┌─────────────────────────────────────────────────┐
                                │ 19. Seed Generator → src/db/seed.ts             │
                                ├─────────────────────────────────────────────────┤
                                │ 20. completeness_validator + QA Agent           │
                                ├─────────────────────────────────────────────────┤
                                │ 21. apply_post_generate_fixes                   │
                                ├─────────────────────────────────────────────────┤
                                │ 22. Coder ↔ Reviewer loop (max 5)               │
                                │     validator → page_agent fix_prompt           │
                                ├─────────────────────────────────────────────────┤
                                │ 23. Visual review (Playwright + vision LLM)     │
                                ├─────────────────────────────────────────────────┤
                                │ 24. Indexer → app-model.json                    │
                                │     final fidelity scoring                      │
                                │     build_success_event + agent_result          │
                                └─────────────────────────────────────────────────┘
```

---

## Shared Services (both pipelines)

These modules are invoked by both `_run_relay_pipeline` and `_run_figma_relay_pipeline`. Most are deterministic — no LLM call — and exist precisely so the pipeline tail stays uniform regardless of where the page schemas came from.

| Service                                                    | Path                                                  | Phase                          | Role |
|------------------------------------------------------------|-------------------------------------------------------|--------------------------------|------|
| `services.registry`                                        | `backend/services/registry.py`                        | Phase 0 → throughout           | Single source of truth across agents (entities/routes/components/pages). |
| `services.registry_extractor`                              | `backend/services/registry_extractor.py`              | After Schema / API / Frontend  | Re-derives registry from actual emitted files. |
| `services.registry_validator`                              | `backend/services/registry_validator.py`              | post_api / pre_qa              | 11 cross-reference checks; emits `registry_validation` SSE. |
| `services.phase_gates`                                     | `backend/services/phase_gates.py`                     | After each agent               | Deterministic gates: `check_contract_completeness`, `check_auth_completeness`, `check_api_completeness`, `check_component_completeness`, `check_page_completeness`, `check_cross_references`, `check_ux_compliance`, `check_workflow_integration`, `check_cta_hierarchy`, `check_progressive_disclosure`, `check_pages_coverage`. |
| `services.runtime_injector`                                | `backend/services/runtime_injector.py`                | After parallel agents          | Copies Data Engine + Workflow Engine + Rules Engine; generates catch-all API routes. |
| `services.nav_flow_from_plan`                              | `backend/services/nav_flow_from_plan.py`              | Pre-shell agent                | First-pass nav-flow synthesis (no transitions). |
| `services.nav_flow_emitter`                                | `backend/services/nav_flow_emitter.py`                | After per-page emission        | Final nav-flow with transitions extracted from schemas. |
| `services.post_emit_photo_injector`                        | `backend/services/post_emit_photo_injector.py`        | After per-page emission        | Fills photoUrl / backgroundImage from design-spec.entityPhotos. |
| `services.app_emitter`                                     | `backend/services/app_emitter.py`                     | After per-page emission        | Standalone Next.js skeleton + `vendor/@tentoroforge/*` so the tarball is self-contained. |
| `services.schema_pipeline`                                 | `backend/services/schema_pipeline.py`                 | Phase 4                        | Per-page schema emission via `run_page_schema_agent`; honours `skip_routes`. |
| `services.schema_normalizer`                               | `backend/services/schema_normalizer.py`               | After schema emit / shell agent| `normalize_v2_schema` (rewrites legacy prop shapes), `apply_page_shell_layout_to_schema`. |
| `services.completeness_validator`                          | `backend/services/completeness_validator.py`          | Phase 6.5                      | Pre-QA gap finder; produces report fed to QA agent. |
| `services.post_generate_fixes`                             | `backend/services/post_generate_fixes.py`             | After QA                       | Clears `.next/` and a few file-system patches. |
| `services.flow_validator`                                  | `backend/services/flow_validator.py`                  | LLM pipeline only              | Validates `nav-flow.json` transitions against page schemas. |
| `services.browser_validator`                               | `backend/services/browser_validator.py`               | LLM pipeline only              | Playwright runtime trace per page. |
| `services.verify_pipeline`                                 | `backend/services/verify_pipeline.py`                 | LLM pipeline only              | CSS + page-render sanity checks. |
| `services.fidelity_runner` / `services.fidelity_loop`      | `backend/services/fidelity_runner.py`, `fidelity_loop.py` | Optional, both pipelines    | Advisory scoring + patch-agent closed loop. |
| `services.preview_manager`                                 | `backend/services/preview_manager.py`                 | Visual review / browser val.   | Boots / stops project preview env. |
| `services.parallel_runner`                                 | `backend/services/parallel_runner.py`                 | Phase 3                        | `run_parallel_agents`, `stream_with_idle_timeout`. |
| `services.figma_client`                                    | `backend/services/figma_client.py`                    | Figma only                     | `fetch_figma_file`, `fetch_figma_node_batched`, `fetch_figma_image_urls`. |
| `services.figma_plan_builder`                              | `backend/services/figma_plan_builder.py`              | Figma only (in `generate_project`) | One plan.page per top-level FRAME. |
| `services.figma_context`                                   | `backend/services/figma_context.py`                   | Figma only (in `generate_project`) | Extracts design tokens from `styles.json` to `src/contracts/figma-context.json`. |
| `services.figma_to_schema`                                 | `backend/services/figma_to_schema.py`                 | Figma only                     | Deterministic Figma → PageV2. |
| `services.figma_node_walker`                               | `backend/services/figma_node_walker.py`               | Figma only                     | Walks the Figma tree, flattens containers. |
| `services.figma_name_classifier`                           | `backend/services/figma_name_classifier.py`           | Figma only                     | `(name, type) → schema type`. |
| `services.figma_style_extractor`                           | `backend/services/figma_style_extractor.py`           | Figma only                     | Token extraction (color, radius, spacing). |
| `services.figma_typography_extractor`                      | `backend/services/figma_typography_extractor.py`      | Figma only                     | Font family + size scale extraction. |
| `services.figma_asset_downloader`                          | `backend/services/figma_asset_downloader.py`          | Figma only                     | Downloads CDN URLs into `public/figma/`. |
| `services.figma_shell_extractor`                           | `backend/services/figma_shell_extractor.py`           | Figma only (gated)             | Structural diff → shared shell. Gated by `FIGMA_SHELL_EXTRACT=1`. |
| `services.figma_mcp_pipeline`                              | `backend/services/figma_mcp_pipeline.py`              | Figma only                     | `build_schema_from_jsx` orchestrator (asset extract + download + transform + nav-flow upsert). |
| `services.design_compiler`                                 | `backend/services/design_compiler.py`                 | After design-spec save         | design-spec → tokens.custom.json. |
| `services.url_brand_scraper`                               | `backend/services/url_brand_scraper.py`               | LLM only (after Design Agent)  | Brand palette from URL og:image. |
| `services.industry_design`                                 | `backend/services/industry_design.py`                 | LLM only                       | Fallback design spec when extract fails. |
| `services.cta_defaults`                                    | `backend/services/cta_defaults.py`                    | Both                           | Maps register → CTA hierarchy. |
| `services.workflow_generator`                              | `backend/services/workflow_generator.py`              | LLM only                       | Fills empty workflow definitions deterministically. |
| `services.schema_visual_enricher`                          | `backend/services/schema_visual_enricher.py`          | Per-page emit post-pass        | Fills blank Avatar `photoUrl`, Hero `backgroundImage`, FeatureCard `icon`. |
| `services.illustration_bundler`                            | `backend/services/illustration_bundler.py`            | Per-page emit post-pass        | Bundles any referenced SVG illustrations into the output dir. |

---

## Shared Agents

| Agent                             | Path                                          | Both pipelines? | Notes |
|-----------------------------------|-----------------------------------------------|-----------------|-------|
| Planner                           | `agents/planner.py::run_planner`              | LLM only (Figma uses `figma_plan_builder`) | Also exposes `classify_register_llm` used by both. |
| Design Analyzer                   | `agents/design_analyzer.py`                   | Figma only      | Analyses Figma screenshots, produces plan-shaped output for user approval. |
| Design Agent                      | `agents/design_agent.py::run_design_agent`    | LLM only        | Writes `design-spec.json` + `globals.css`. |
| Contract Agent                    | `agents/contract_agent.py::run_contract_agent`| Both            | |
| Schema Agent                      | `agents/schema_agent.py::run_schema_agent`    | Both            | |
| API Agent                         | `agents/api_agent.py::run_api_agent`          | Both            | Parallel with BizLogic. |
| Business Logic Agent              | `agents/business_logic_agent.py`              | Both (iff `plan.workflows`) | Parallel with API. |
| Rules Agent                       | `agents/rules_agent.py`                       | LLM only        | |
| Shell Layout Agent                | `agents/shell_layout_agent.py`                | LLM only (Figma uses extractor when `FIGMA_SHELL_EXTRACT=1`) | Sonnet → `ir-shell` JSON block → `shell.json`. |
| Page Schema Agent (per page)      | `agents/page_schema_agent.py`                 | Both (Figma fills gaps) | Inside `run_schema_frontend_pipeline`. |
| Page Layout Agent                 | `agents/page_layout_agent.py`                 | LLM-TSX legacy only | |
| Component Agent (legacy)          | `agents/component_agent.py`                   | LLM-TSX legacy only | |
| Page Agent (legacy + retry)       | `agents/page_agent.py`                        | LLM-TSX legacy + Figma retry/fix prompts | |
| Figma UI Agent (legacy)           | `agents/figma_ui_agent.py`                    | Figma-LLM only  | |
| Figma MCP Agent                   | `agents/figma_mcp_agent.py`                   | Figma only      | Wraps MCP `get_design_context` tool call. |
| Feature Slice Schema Agent        | `agents/feature_slice_schema_agent.py`        | LLM only (legacy trio path) | Used when `plan.pages` is empty. |
| Seed Generator                    | `agents/seed_generator.py`                    | Both            | |
| QA Agent                          | `agents/qa_agent.py::run_qa_agent`            | Both            | |
| Validator                         | `agents/validator.py::run_validator`          | Both            | Coder↔Reviewer loop reviewer. |
| Indexer                           | `agents/indexer.py::run_indexer`              | Both            | Writes `app-model.json`. |
| Design Reviewer / Fixer (visual)  | `agent.run_design_reviewer_agent`, `run_fixer_agent` | Both | Visual review loop. |
| Peer Patcher (alt path)           | `agents/peer_patcher.py`                      | Opt-in `PEER_PATCHER_ENABLED` | Replaces the entire LLM pipeline with a single-shot artifact diff. |

---

## Environment Flags

| Env var                       | Default | Effect |
|-------------------------------|---------|--------|
| `SCHEMA_MODE_ENABLED`         | `true`  | When true (default), frontend is emitted as `src/schemas/*.json` (PageV2) and the QA/validator/indexer tail is skipped. When false, falls through to IR mode or legacy LLM TSX mode. |
| `IR_FRONTEND_ENABLED`         | `false` | When true AND `SCHEMA_MODE_ENABLED=false`, uses the deterministic IR compiler instead of the per-page Schema Agent (Figma → `run_figma_ir_pipeline`, text → `run_ir_frontend_pipeline`). |
| `FIDELITY_MODE_ENABLED`       | `true`  | Gates `design_compiler.compile_to_file` (design-spec → tokens.custom.json). When false, downstream agents see stale or library-default tokens. |
| `FIDELITY_LOOP_ENABLED`       | `true`  | Gates the Fidelity Loop phase (vision evaluator + patch agent closed loop). LLM pipeline only. |
| `FIDELITY_SCORING_ENABLED`    | unset   | Gates `_stream_fidelity_scoring` (the advisory final scoring pass). Both pipelines. |
| `SCAFFOLD_BASE_URL`           | `http://localhost:6503` | Render-scaffold URL used by fidelity scoring's screenshot capture. |
| `FIGMA_SHELL_EXTRACT`         | unset   | Figma pipeline only. When `"1"`, runs `extract_shell_by_structural_diff` → `extract_shell_from_pages` to hoist a shared shell.json. Currently disabled by default due to auth-page stripping. |
| `PEER_PATCHER_ENABLED`        | unset   | LLM pipeline only. When `"1"`, `"true"`, or `"yes"`, replaces the entire pipeline with `run_peer_patcher` (single-shot artifact diff). |
| `AGENT_TIMEOUT_SECONDS`       | (parallel_runner default) | Per-agent idle-timeout for the `stream_with_idle_timeout` wrapper that fails wedged agents fast instead of hanging. |
| `CLAUDECODE` / `CLAUDE_CODE_ENTRYPOINT` | env-set | Each agent pops these before invoking `claude_agent_sdk.query` to avoid Code-CLI-specific behaviors leaking into subprocesses. |

---

## Key Artifact Map

The single output directory `output/<short_id>/` ends up structured like this. Every file is written by either an agent or a deterministic service. The "by" column lists the primary writer.

| Path                                          | Written by                                                                 | When |
|-----------------------------------------------|----------------------------------------------------------------------------|------|
| `src/contracts/discovery.json`                | `agents.domain_agent.run_domain_discovery`                                 | Step 0 (LLM) — pre-pipeline domain research |
| `src/auth.ts`, `src/middleware.ts`, `src/app/api/auth/...` | Template copy (`backend/templates/app-foundation/`)                | Step 0 (LLM) / Step 10 (Figma) |
| `registry.json`                               | `services.registry`                                                        | Step 1, refreshed after every extraction |
| `src/contracts/design-spec.json`              | `agents.design_agent` (LLM) / `agents.design_analyzer` + Figma context (Figma) | Step 2-4 |
| `src/contracts/figma-context.json`            | `services.figma_context.extract_figma_context`                             | Figma — set up in `generate_project` before pipeline |
| `src/theme/tokens.custom.json`                | `services.design_compiler` (LLM) / `services.figma_style_extractor` + `figma_typography_extractor` (Figma) | Step 6 (LLM) / Step 1+5 (Figma) |
| `src/app/globals.css`                         | `agents.design_agent.save_design_spec` + `_inject_typography_into_globals` | Step 4, Step 19 appends sidebar/main scrollbar CSS |
| `src/contracts/api-client.ts`                 | Contract Agent                                                             | Step 7 / Step 3 (Figma) |
| `src/contracts/design-system.tsx`             | Contract Agent                                                             | "" |
| `src/contracts/services.ts`                   | Contract Agent                                                             | "" |
| `src/contracts/app-model.json`                | Contract Agent (initial) + Indexer (final merge)                           | Step 7 / Step 39 |
| `contracts/seed-plan.json`                    | Contract Agent                                                             | Step 7 |
| `src/db/schema/*.ts`                          | Schema Agent                                                               | Step 9 / Step 6 (Figma) |
| `src/db/index.ts`                             | Schema Agent                                                               | "" |
| `src/types/*.ts`                              | Schema Agent                                                               | "" |
| `src/lib/utils.ts`                            | Schema Agent                                                               | "" |
| `package.json`, `tsconfig.json`, `next.config.ts`, `drizzle.config.ts`, `docker-compose.yml`, `.env.local.example` | Schema Agent | "" |
| `src/app/api/<entity>/route.ts`, `<entity>/[id]/route.ts`, `<entity>/stats/route.ts` | API Agent | Step 11 / Step 8 (Figma) |
| `src/lib/services/*.ts`                       | Business Logic Agent                                                       | "" |
| `workflows/*.json`                            | Business Logic Agent + `services.workflow_generator` fallback             | Step 11 + Step 29 |
| `src/lib/feel-lite/*.ts`, `src/lib/workflows/*.ts`, `src/lib/rules/*.ts`, `src/lib/runtime-loader.ts`, `src/lib/data-engine.ts`, `src/lib/event-registry.ts` | `services.runtime_injector` | Step 15 / Step 11 (Figma) |
| `src/app/api/data/[...path]/route.ts`         | runtime_injector                                                           | "" |
| `src/app/api/workflows/[id]/execute/route.ts`, `workflows/event/[event]/route.ts`, `workflows/route.ts`, `tasks/route.ts` | runtime_injector | "" |
| `src/components/WorkflowTriggerButton.tsx`    | runtime_injector                                                           | "" |
| `rules/index.json`                            | runtime_injector (exports DB rules)                                        | "" |
| `start.sh`, `.env.local`                      | runtime_injector                                                           | "" |
| `src/contracts/nav-flow.json`                 | `services.nav_flow_from_plan` (first pass) → `services.nav_flow_emitter` (final pass with transitions) → also via `figma_mcp_pipeline._upsert_nav_flow` per Figma MCP page | Step 18 + Step 23 / Step 2 + Step 15 (Figma) |
| `src/schemas/shell.json`                      | `agents.shell_layout_agent` (LLM) / `services.figma_shell_extractor` (Figma, gated) | Step 19 / Step 1 (Figma, gated) |
| `src/schemas/<slug>.json`                     | `agents.page_schema_agent` per page (LLM) / `services.figma_to_schema.build_page_schema` (Figma deterministic) / `services.figma_mcp_pipeline.build_schema_from_jsx` (Figma MCP, overwrites) | Step 20 / Step 1 + Step 2 (Figma) |
| `src/schemas/registry.ts`                     | `schema_pipeline._regenerate_route_registry`                               | Step 20 |
| `public/figma/<asset>.svg`                    | `services.figma_asset_downloader`                                          | Figma Step 1 + Step 2 |
| `src/components/**/*.tsx`                     | Component Agent (LLM-TSX) / Figma UI Agent / runtime_injector              | Step 25 (LLM-TSX) / Step 18 (Figma-LLM) |
| `src/app/**/page.tsx`                         | Page Agent (LLM-TSX) / Figma UI Agent                                      | Step 27 (LLM-TSX) / Step 18 (Figma-LLM) |
| `src/db/seed.ts`                              | Seed Generator                                                             | Step 30 / Step 19 (Figma) |
| `app-model.json` (root)                       | Indexer                                                                    | Step 39 / Step 24 (Figma) |
| `vendor/@tentoroforge/<engine|library|renderer|patches|registry>/` | `services.app_emitter._vendor_engine_packages`               | Step 23 / Step 15 (Figma) |

---

## SSE Event Cheat Sheet

The pipeline emits SSE events via `sse_helpers.sse_event(type, data)`. Notable event types:

| Event type          | Emitter                                            | Payload key fields                                     |
|---------------------|----------------------------------------------------|--------------------------------------------------------|
| `intent`            | entry point                                        | `intent`: `"PLAN"`, `"DESIGN_ANALYSIS"`, `"GENERATE"`  |
| `status`            | every phase                                        | `message`                                              |
| `log`               | every phase                                        | `text`                                                 |
| `office`            | per phase                                          | One of `agent_start`, `agent_complete`, `agent_handoff`, `parallel_start`, `build_success` events from `services.office_events` |
| `message`           | agent text relay                                   | `text` (a chunk of streamed LLM text)                  |
| `agent_result`      | per-agent end                                      | `num_turns`, `cost_usd`, `duration_ms`                 |
| `registry_validation`| `validate_registry` after API / before QA         | `phase`: `"post_api"` or `"pre_qa"`, `errors[]`        |
| `plan_ready`        | entry point (planning)                             | `plan` (full dict)                                     |
| `phase_start` / `phase_complete` / `phase_warning` | Fidelity Loop                  | `phase`: e.g. `"fidelity_loop"`                        |
| `fidelity`          | `_stream_fidelity_scoring`                         | `type`: `score`/`skip`/`error`, `page`, `score_0_to_10`, `qualitative_notes` |
| `session`           | `buffered_event_stream`                            | `session_id`                                           |
| `complete`          | entry point end                                    | `project_id`, summary stats                            |
| `error`             | entry point error path                             | `message`                                              |

The buffering layer (`buffered_event_stream` / `generation_buffer.py`) wraps every pipeline run so a client that disconnects can replay events via `GET /api/projects/{id}/generation/{session_id}/events?since=N`.

---

## What Differs Between Pipelines — Quick Reference

| Concern                          | LLM Pipeline                                                  | Figma Pipeline                                                                            |
|----------------------------------|---------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| Plan source                      | LLM Planner (`run_planner`) — interactive                     | `services.figma_plan_builder.build_plan_from_figma` (one page per top-level FRAME)        |
| User-facing intent before pipeline | `intent: "PLAN"`                                            | `intent: "DESIGN_ANALYSIS"` (Design Analyzer runs against screenshots)                    |
| First step of pipeline           | Design Agent (LLM produces design-spec + globals.css)         | **Deterministic Figma mapper** (extracts schemas, tokens, SVGs) — runs FIRST              |
| Page schemas                     | Per-page `page_schema_agent` LLM call                         | (1) Deterministic `build_page_schema` per frame, (2) Figma MCP overlay overwrites, (3) LLM fills gaps via `run_schema_frontend_pipeline(skip_routes=...)` |
| Design tokens                    | `design_compiler.compile_to_file` from LLM-authored design-spec | `figma_style_extractor.extract_tokens` + `figma_typography_extractor.extract_typography` (real Figma styles), merged with any LLM-authored design-spec |
| Brand scrape from URL            | Runs (silent fallback)                                        | Not invoked                                                                               |
| Industry-default design fallback | Runs if Design Agent didn't emit                              | Not invoked                                                                               |
| Rules Agent                      | Runs (produces `rules/index.json`)                            | **Not invoked**                                                                           |
| Shell Layout Agent               | LLM call produces `shell.json` when nav has shell-pages       | Optional — `figma_shell_extractor` gated by `FIGMA_SHELL_EXTRACT=1`                       |
| Frontend dispatch                | Schema mode (default) → return; or IR / LLM-TSX               | Same three modes, with `skip_routes=deterministic_pages` to avoid overwriting Figma output |
| LLM-TSX fallback components+pages| Component Agent + Page Agent                                  | Single `figma_ui_agent` (one agent emits both)                                            |
| Flow validator + browser validator | Both run                                                    | **Skipped**                                                                               |
| `verify_pipeline`                | Runs                                                          | **Skipped**                                                                               |
| Visual review loop               | Runs                                                          | Runs                                                                                       |
| Seed + QA + Validator + Indexer  | Runs                                                          | Runs                                                                                       |
| Coder↔Reviewer fix prompt routes through | `run_page_agent` with `fix_prompt`                    | Same — `run_page_agent` is invoked even though pages came from Figma UI Agent             |

---

## Reading Order for New Contributors

If you need to learn the codebase by following one request end-to-end:

1. **Entry point**: `backend/routers/generate.py::generate_project` (line 2428) and the `/chat` approval branch (line 2850-3020).
2. **Routing decision**: `generate.py:2887-2971` — picks `_run_relay_pipeline` vs `_run_figma_relay_pipeline`.
3. **LLM pipeline body**: `generate.py:305-1353`.
4. **Figma pipeline body**: `generate.py:1356-2351`.
5. **Per-page LLM call**: `services/schema_pipeline.py::run_schema_frontend_pipeline` → `agents/page_schema_agent.py::run_page_schema_agent`.
6. **Per-page deterministic call** (Figma): `services/figma_to_schema.py::build_page_schema` + the supporting walker/classifier/extractor modules.
7. **Per-page MCP call** (Figma): `agents/figma_mcp_agent.py::fetch_jsx_via_mcp` + `services/figma_mcp_pipeline.py::build_schema_from_jsx`.
8. **The standalone-app skeleton**: `backend/templates/standalone-app/` + `services/app_emitter.py::emit_standalone_app`.
9. **What the runtime ends up running**: `backend/templates/runtime/` + `services/runtime_injector.py::inject_runtime`.
10. **Cross-cutting validation**: `services/registry.py`, `services/registry_extractor.py`, `services/registry_validator.py`, `services/phase_gates.py`, `services/completeness_validator.py`.
