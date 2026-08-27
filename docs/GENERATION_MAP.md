# Tentoroforge Generation Map

Complete pipeline trace from `POST /api/projects/{id}/generate` to a runnable Next.js project on disk. Reflects code state as of commit `7f500e3` (2026-05-15).

The pipeline has two branches:
- **Description path** (`_run_relay_pipeline`) — user supplied prose; LLM does everything.
- **Figma path** (`_run_figma_relay_pipeline`) — user supplied a Figma URL + token; deterministic mapper handles UI, LLM handles backend.

Both share phases 0–3 (planning + backend) and 6+ (post-emission); they diverge only in phases 4–5 (frontend generation).

---

## High-level Flow

```
                       POST /api/projects/{id}/generate
                                     │
                                     ▼
                   ┌─────────────────────────────────────┐
                   │ routers/generate.py:generate_project │
                   │   • strip whitespace from token/url │
                   │   • set project.status = generating │
                   │   • detect_domain(description)      │
                   └─────────────────────────────────────┘
                                     │
                            is_figma = bool(figma_url AND figma_token)
                                     │
                ┌────────────────────┴────────────────────┐
                │                                         │
                ▼                                         ▼
    _run_relay_pipeline                       _run_figma_relay_pipeline
    (description-driven)                      (figma-driven)
                │                                         │
                └─────────────── share ───────────────────┘
                                     │
                                     ▼
                            phases 0 – 3 (backend)
                                     │
                                     ▼
                           phase 4–5 (frontend)
                                     │
                       ┌─────────────┴─────────────┐
                       │                           │
              description path                figma path
              run_schema_frontend_pipeline   FigmaDeterministic
              (LLM emits schemas)            (mapper emits schemas)
                                                  │
                                            if not complete:
                                                  │
                                            run_schema_frontend_pipeline
                                            (LLM fills the rest)
                       │                           │
                       └─────────────┬─────────────┘
                                     │
                                     ▼
                            phase 6 (post-emission)
                                     │
                                     ▼
                            phase 7 (verification)
```

---

## Phase 0 — Plan + Domain Detection

| Step | Code | Output |
|---|---|---|
| Receive request | `routers/generate.py:generate_project` (line 1980) | — |
| Sanitise inputs | `req.figma_token.strip()`, `req.figma_url.strip()` | — |
| Detect domain | `services.domain_context.detect_domain(description)` | `domain_ctx` (e.g. "hr", "fintech") |
| Init contract registry | `services.registry.create_registry(plan)` | `output/<short_id>/contracts/registry.json` |

If no `plan` and no `figma_url`: pipeline enters **planning mode** (LLM generates a plan from the description). Otherwise proceeds to phase 1.

---

## Phase 1 — Contracts (both paths)

LLM-driven; ~15–30 s per agent. Same in both pipelines.

| # | Agent | Reads | Writes |
|---|---|---|---|
| 1.1 | `run_contract_agent` | `plan`, `domain_ctx` | `src/contracts/*.ts` |
| 1.2 | **GATE:** `check_contract_completeness` | contracts vs plan.entities | log warnings, may re-run 1.1 |
| 1.3 | `run_design_agent` (description path only) | `plan`, brand info | `src/contracts/design-spec.json`, `src/theme/tokens.custom.json`, `src/app/globals.css` |

`design_agent` also calls `services.photo_picker.pick_photo_for(entity, domain, project_seed=<short_id>)` to populate `spec["entityPhotos"]` — per-project photo rotation (commit `33f5370`).

The figma path **skips** `run_design_agent` here; design comes from the deterministic mapper in phase 4.

---

## Phase 2 — Schemas + Entity Extraction

| Step | Code | Writes |
|---|---|---|
| `run_schema_agent` | LLM | `src/db/schema/<entity>.ts` (Drizzle), `src/contracts/app-model.json` |
| `extract_entities_from_schema` | walks Drizzle | merges into `contracts/registry.json` |

---

## Phase 3 — API + Auth + Business Logic (parallel)

`services.parallel_runner.run_parallel_agents` fires three agents simultaneously:

| Agent | Writes |
|---|---|
| `run_api_agent` | `src/app/api/<resource>/route.ts` |
| `run_auth_agent` | NextAuth config + middleware |
| `run_business_logic_agent` | `src/lib/business-logic/*.ts` |

Followed by:
- `extract_routes_from_files(output_dir)` → merges API route list into registry.
- Optional: `run_rules_agent` → applies plan-level rules across the codebase.

**Gate:** if `validate_all` finds missing routes referenced by the plan → re-run `run_api_agent` once.

---

## Phase 4–5 — Frontend (the divergence)

This is where the two pipelines do something different.

### 4a — Description path (`_run_relay_pipeline:666–950`)

```
SCHEMA_MODE_ENABLED = True (default)
    ↓
run_schema_frontend_pipeline(output_dir, plan, description, domain_context=domain_ctx)
    ├── emits src/schemas/<page>.json    (one PageV2 per route)
    ├── emits src/contracts/nav-flow.json
    └── invokes design-tile + component-spec agents internally
    ↓
extract_components_from_files + extract_pages_from_files
    ↓
GATE: check_cta_hierarchy
GATE: check_progressive_disclosure
```

When `SCHEMA_MODE_ENABLED = False` (legacy path): runs `run_component_agent` + `run_page_agent` instead, which emit TSX directly.

### 4b — Figma path (`_run_figma_relay_pipeline:1492 onwards`)

```
[FigmaDeterministic] block — added in commit 1759947 + 66c0e87
    ↓
parse_figma_url(figma_url)
    ↓
fetch_figma_node(file_key, node_id, token)        ← services.figma_client
    ↓
build_page_schema(doc)                            ← services.figma_to_schema
    ├── walk_and_flatten(doc)                     ← services.figma_node_walker
    │      • collapses passthrough containers
    │      • surfaces _layoutMode / _padding / _itemSpacing
    ├── extract_tokens(walked)                    ← services.figma_style_extractor
    │      • Button-weighted primary candidates
    │      • color_theory.derive_scale(primary_500) → 11 steps
    │      • surface defaults + node_to_utility_classes
    ├── extract_typography(walked)                ← services.figma_typography_extractor
    │      • heading vs body voting via name regex
    │      • fontSize → Tailwind scale snap
    │      • lineHeight ratio + letterSpacing em
    └── classify(name, type) per node             ← services.figma_name_classifier
           + refine_container_type for Stack/Row/Grid
    ↓
Writes:
    src/schemas/<slug>.json                       (PageV2 from Figma)
    src/theme/tokens.custom.json                  (color + typography)
    ↓
deterministic_pages: list[str]
    ↓
if len(deterministic_pages) >= len(plan.pages):
    [Pipeline] Skipping LLM schema pipeline       ← saves $0.20-0.50 + 30-60s
else:
    run_schema_frontend_pipeline(...)             ← LLM fills the rest
```

The deterministic block is wrapped in try/except — on Figma 403 / network error / classifier panic, it logs `[FigmaDeterministic] skipped: ...` and falls through to the LLM pipeline gracefully.

---

## Phase 6 — Post-emission (both paths converge again)

Runs after frontend generation regardless of which path produced the schemas.

| Step | Code | Action |
|---|---|---|
| 6.1 Photo injection | `services.post_emit_photo_injector.inject_photos_into_dir` | Reads `entityPhotos` from design-spec, writes `Hero.backgroundImage` + `Avatar.photoUrl` into page schemas |
| 6.2 Nav-flow emit | `services.nav_flow_emitter.emit_nav_flow` | Walks emitted schemas, extracts `Button.navigate` / `Link.navigate` / `Hero.cta.action.to`, writes `src/contracts/nav-flow.json` with `pages[]` + `transitions[]` |
| 6.3 App emitter | `services.app_emitter.emit_standalone_app` | Writes Next.js scaffold (`src/app/p/[projectId]/[...slug]/page.tsx`, `next.config.ts`, etc.) — idempotent |
| 6.4 Seed generator (description path only) | `run_seed_generator` | LLM writes `src/db/seed.ts` for the schema |

---

## Phase 7 — Verification

| Step | Code | Failure handling |
|---|---|---|
| 7.1 QA | `run_qa_agent` | Re-runs failing agent up to 2× |
| 7.2 Validator | `run_validator` | TypeScript + ESLint + Next.js build |
| 7.3 Fidelity scoring | `_stream_fidelity_scoring` | Compares rendered scaffold output to reference bank; logs score |
| 7.4 Indexer | `run_indexer` | Writes `src/knowledge/index.json` for the AI edit feature |

---

## Critical-Path Files Produced

For project `output/<short_id>/`:

```
src/
├── contracts/
│   ├── registry.json           ← shared by all agents (phase 0 → end)
│   ├── design-spec.json        ← description path | figma deterministic
│   ├── nav-flow.json           ← phase 6
│   └── app-model.json          ← phase 2
├── theme/
│   └── tokens.custom.json      ← description: design_agent
│                                  figma: figma_style_extractor + figma_typography_extractor
├── db/
│   ├── schema/<entity>.ts      ← schema_agent
│   └── seed.ts                 ← seed_generator
├── app/
│   ├── globals.css             ← design_agent (description) | unchanged (figma)
│   ├── api/<resource>/route.ts ← api_agent
│   └── p/[projectId]/...       ← app_emitter scaffold
└── schemas/
    └── <page>.json             ← description: schema_frontend_pipeline
                                  figma: figma_to_schema OR fallback to LLM
```

---

## Where the Editor + Preview Read From

The visual editor and the preview both render the same artifacts on disk:

| Surface | Reads | Renders via |
|---|---|---|
| Editor canvas (`/editor/<id>`) | `src/schemas/<page>.json`, `src/contracts/nav-flow.json`, `src/contracts/design-spec.json`, `src/theme/tokens.custom.json` | `<EngineProvider>` + `<Engine>` from `@tentoroforge/engine` |
| Preview (`http://localhost:6503/p/<id>/<slug>`) | same files via `loadSchema` / `loadTokens` / `loadNavFlow` in `apps/render-scaffold/src/app/p/.../page.tsx` | `<PreviewShell>` + `<SchemaRendererWrapper>` (which itself wraps `<EngineProvider>` + `<Engine>`) |
| AI edit modal (`/editor/<id>` → sparkle icon) | Reads current artifacts from disk, POSTs to `_debug/project-ai-edit/<short_id>` | `peer_patcher` LLM agent → `replaceArtifacts` action |

All three flow through `EngineProvider` which:
1. Walks `tokens` → emits 144+ CSS custom properties on the wrapper.
2. Maps tokens to shadcn-style semantic vars (`--foreground`, `--card`, `--primary`, …) so the library themes per-project.

---

## Cost / Latency Per Phase (rough order-of-magnitude)

| Phase | Description path | Figma path (deterministic complete) |
|---|---|---|
| 0 Plan | $0.02 / 5–15 s | $0.02 / 5–15 s |
| 1 Contracts | $0.10–0.30 / 30–60 s | same |
| 2 Schemas | $0.05–0.15 / 15–30 s | same |
| 3 API + Auth + BL | $0.30–0.80 / 60–120 s | same (parallel) |
| **4–5 Frontend** | **$0.20–0.50 / 30–90 s** | **$0.00 / 1–3 s** ← saved |
| 6 Post-emission | $0.05 (seed only) / 10–20 s | $0.00 (no seed) / 5 s |
| 7 Verification | $0.05–0.10 / 20–40 s | same |
| **Total** | **~$0.80–1.95 / 3–6 min** | **~$0.55–1.40 / 2–4 min** |

When the Figma deterministic mapper is partially incomplete, the LLM frontend pipeline fires for the missing pages only — cost lands somewhere between the two columns.

---

## Open Follow-ups Not Yet Wired

1. **Multi-page Figma** — `plan.figma_node_ids: dict[slug, node_id]` so a single Figma file maps many frames to many pages.
2. **Typography → semantic vars** — `EngineProvider.tokensToSemanticVars` doesn't yet map `typography.font.heading` to a `--font-heading` var that the library could read.
3. **Pages & Nav tab edges** — `_derive_edges_from_schemas` returns 0 for db17s1zl because the generated schemas reference invalid routes (e.g. `/items` instead of `/requests`). Schema-side cleanup pending.
4. **Stack-style fidelity** — `_run_relay_pipeline` runs QA + Validator + Indexer; the figma pipeline currently skips Seed but otherwise mirrors the same post-emission steps. A future audit may want to also skip QA/Validator for figma-only projects since the deterministic output is already structurally validated by `figma_to_schema`'s tests.
