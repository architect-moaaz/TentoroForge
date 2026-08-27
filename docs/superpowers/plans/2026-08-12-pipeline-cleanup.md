# Pipeline Cleanup + Rich Decisions — Consolidated Plan

**Date:** 2026-08-12
**Author:** Claude (with Moaaz)
**Status:** Draft — ready to execute
**Related:** `scratchpad/pipeline-audit.html`,
`services/plan_finalize.py` (partial extract already shipped),
prior discussions summarised throughout this doc.

---

## The one-sentence goal

Ship an app generator that produces **reliably working apps that look meaningfully
different from each other**, in less time, at lower cost, with a pipeline you can
actually reason about and extend.

## The two-sentence goal

1. Collapse today's **72 phases + 60+ guards + 2 near-duplicate entry points**
   into a single spine with **≤35 phases + ≤15 assertion guards + 1 entry point**.
2. Split each artifact into **decisions (LLM) + assembly (composer)** so LLM
   creativity lives in a rich decisions/moments layer, and schema JSON is
   assembled contract-bound.

---

## The architectural spine

### One writer per artifact — but not the way it first sounds

The trap is "deterministic composers vs LLM." That's a false binary. The real
split is:

| Layer | What it decides | Who owns it |
|---|---|---|
| **Discovery** | actors, entities, journeys, tone | LLM |
| **Plan** | pages, workflows, relationships | LLM |
| **Design brief** | palette, personality, type pairing | LLM |
| **Per-page decisions + moments** | KPIs, layout, hero framing, empty-state tone, signature moves, ornament, density, row treatment | **LLM (rich, unbounded)** |
| **Schema assembly** | component tree, bindings, wrappers, validation | **Composer (deterministic, contract-bound)** |
| **Copy & microcopy** | headlines, empty-state text, button labels | LLM |
| **Novel / bespoke pages** (1–2 per app) | everything | LLM writes schema directly, validated only |

LLM is authority everywhere it has judgment. Composers are authority for the
places where LLM keeps drifting from contracts (references to real entities /
workflows / registry names / component types).

### Three page types, not six

Every page collapses to one of:

- **Dashboard** — many entities, aggregated. KPIs + charts + activity + hero.
- **Collection** — many rows of one entity. Table / Kanban / Calendar / Card grid.
- **Record** — one row of one entity, read or write. Modes: `view` / `edit` / `create`.

Plus a rare **bespoke** escape hatch (marketing landings, onboarding welcomes,
brand-defining hero moments) — 1–2 pages per app.

Today's "list / detail / form / archetype-specific / custom" collapse into
these three. Concretely:
- `scan` page = `Record(mode=create)` with `layout.controlHints: {photo: "camera"}`
- `tasks` inbox = `Collection(layout=table)` with archetype hint `task_inbox`
- `cart` page = `Collection(layout=table, footer=CheckoutSummary)`
- `integrations` = `Collection(layout=cards)`

No dedicated emitters. Rich hints do the differentiation work.

---

## Fixture set (regression bar for every phase)

Every phase merges only if `self_verify_pass` scores match or exceed baseline
across the fixture set. New fixture added for HR:

| Fixture | Domain | Archetype coverage | What it stresses |
|---|---|---|---|
| Yoga studio | Hospitality & Food | dashboard + booking + calendar | maquette richness, calendar collection, multi-actor sidebar |
| Recruitment | Human Resources | list + kanban + workflow + task | submit-authority, actor onboarding, workflow lifecycle |
| Leave management | Human Resources | dashboard + form + calendar + workflow + task inbox | balance rings, approval loop, role-scoped nav |
| Cart / commerce | Retail | catalog + checkout + workflow | deterministic composers, cart runtime |
| Visual product search | Retail | camera + agent-chat + list | archetype-as-hint (not emitter), MCP wiring |

Verification per phase:
- Regen all five.
- Run `self_verify_pass` in strict mode.
- Diff key metrics: broken-page count, empty-dashboard count, submit-failure
  rate, distinct-look score (two apps in same domain, side-by-side).
- Phase merges iff scores ≥ baseline. Baseline snapshot captured before Phase 0.

---

## Phases

Seven phases. 4–5 focused weeks. Each phase = its own PR, its own rollback path,
its own fixture-regen proof.

### Phase 0 — Dead code sweep

**Effort:** 1 day. **Risk:** low.

Delete unreachable code with zero behaviour change:

- `services/profile_scope_caps.py` (Fast profile caps at 0/0, dead lever)
- `FORGE_LOCKED_SPEC` branch in `_run_relay_pipeline` (~40 lines, never on)
- `FORGE_BINDING_GATE=strict` branch (never enabled)
- `FORGE_MAQUETTE` env — auto-derive from profile only, remove env override
- Any other flag-gated dead paths surfaced during the sweep

**Verify:** Fixtures regen byte-identical. Line count down ~500. Tests green.

---

### Phase 1 — Collapse the two pipelines into one spine

**Effort:** 3–5 days. **Risk:** medium (ordering fragility).

- Extract shared spine from `_run_relay_pipeline` and `_run_figma_relay_pipeline`.
- One `_run_pipeline(*, plan, source: PlanSource, profile, ...)` where
  `PlanSource(kind: text | figma, figma_url?, figma_context?)`.
- Figma-specific steps become named functions (`_figma_deterministic_map`,
  `_figma_prune_covered_routes`) called from the spine when `source.kind == "figma"`.
- Delete `_run_figma_relay_pipeline`. Update all 5 entry-point callers.

**Verify:** All fixtures regen identically (this is a refactor, not a behaviour
change). Integration tests drive `_run_pipeline` with each `PlanSource.kind`.
Line count net −600.

**Status (2026-08-12 checkpoint — Phase 1a + 1b complete, safe to continue):**

*Phase 1a foundation — DONE:*
- `services/pipeline/source.py` — `PlanSource` dataclass (frozen, invariant-checked, `text()`/`figma()` factories) + 11 tests
- `services/pipeline/state.py` — `PipelineState` dataclass bundling `total_cost`/`total_turns`/`total_duration_ms`/`phase_timings`/progress buffer with `stream_phase()`, `write_timing()`, `drain_progress()` methods. Byte-for-byte lift of `_stream_phase` (Figma bug on exception not propagated). + 12 tests
- `services/pipeline/__init__.py` — package entry

*Phase 1b extractions — DONE (9 phases):*
- `services/pipeline/binding_gate.py::stream_binding_gate` + `binding_gate_is_strict` — extracted AND wired (both call sites in `generate.py`) ✓
- `services/pipeline/phases.py::phase_contract` — text 2029-2078, deterministic+LLM+gate+repair
- `services/pipeline/phases.py::phase_seed` — text 2965-2983 / figma 4828-4846 (identical)
- `services/pipeline/phases.py::phase_qa` — text 3043-3053 / figma 4855-4867 (identical)
- `services/pipeline/phases.py::phase_post_generate` — 1-liner wrapper
- `services/pipeline/phases.py::phase_indexing` — text 3262-3271 / figma 5017-5026 (identical)
- `services/pipeline/phases.py::phase_journey_gate` — text 3286-3308 / figma 5033-5045 (`include_hints` param toggles the divergence)
- `services/pipeline/phases.py::phase_fidelity_score` — text 3310-3315 / figma 5027-5032 (wraps generate.py's `_stream_fidelity_scoring` passed in)
- `services/pipeline/phases.py::phase_app_agent_install` — text 3342-3379 / figma 5052-5087 (identical)

All extracts are IMPORTABLE (verified) but not yet WIRED into the legacy pipelines — wiring happens in Phase 1e when we write the new single spine that constructs `PipelineState.create(...)` at the top.

*Phase 1c extractions — DONE (2 phases):*
- `services/pipeline/phases.py::phase_parallel_agents` — text 2138-2183 / figma 4402-4441. Branches internally on `state.source` (text: BusinessLogic only + `_deterministic_workflows()` gate; Figma: always API + optional BusinessLogic). Also carries the `_deterministic_workflows()` helper as a module-local mirror.
- `services/pipeline/phases.py::phase_figma_crud_route_fill` — figma 4448-4454. Figma-only, called immediately after parallel-agents on the Figma path.

*Phase 1d contracts — DONE (6 contracts locked; code motion deferred to 1e):*
- `services/pipeline/phase_frontend.py` — two functions with detailed signatures + closure-var thread list + line-range map:
  - `phase_frontend_text` — will lift text 2463-3055 (~590 lines, 3 branches + 5 post-gates)
  - `phase_frontend_figma` — will lift figma 4650-4918 (~270 lines, 2 branches, intentionally omits text-pipeline post-gates per A-strict policy)
- `services/pipeline/phase_figma_pre.py` — four Figma-only pre-phase contracts:
  - `phase_figma_deterministic_map` — figma 3722-4011 (~290 lines)
  - `phase_figma_schema_refine` — figma 4013-4067 (~55 lines)
  - `phase_figma_mcp` — figma 4069-4186 (~118 lines)
  - `phase_figma_binding_pass` — figma 4188-4253 (~65 lines)
- 11 new contract tests pin function shape + kw-only args + NotImplementedError with source-range references

*Why contract-only for 1d, not byte-for-byte lift:* the frontend blocks total ~1400 lines with many closure vars (registry, chat_flavor, project_short_id, project_id, deterministic_pages, plan mutations) across three branches. Duplicating that here would leave 1400 dead-but-critical lines in the tree until Phase 1e wires the extractions. Safer to lock the contract + defer the code motion to Phase 1e where it lands as ONE atomic edit (out of `generate.py`, into the new modules, wired from the new spine, delete originals).

*Phase 1e wrapper — DONE (Phase 1 goal delivered):*
- `services/pipeline/spine.py` — `run_pipeline(*, source: PlanSource, output_dir, plan, description, project_id, domain_context, ...)` dispatches internally to the legacy pipeline functions based on `source.kind`. Absorbs extra kwargs (`figma_context`, `figma_url`, `figma_token`) so `orchestrate_generation`'s kwarg-forwarding pattern still works. Source's own fields always win over loose kwargs.
- Exported from `services.pipeline` as top-level `run_pipeline`.
- 7 new spine tests (dispatch, arg forwarding, source-wins-over-loose-kwargs, extras-absorbed, package export) — **58/58 tests green**.
- All 3 pipeline call sites in `routers/generate.py` updated: `pipeline_fn=_run_relay_pipeline` / `pipeline_fn=_run_figma_relay_pipeline` → `pipeline_fn=run_pipeline, source=PlanSource.text()` (or `PlanSource.figma(url=..., token=...)`). Zero remaining `pipeline_fn=_run_` references in generate.py.

*Phase 1e deferred to a follow-up (Phase 1e.2 — dedicated session with fixture snapshots):*
- Delete `_run_relay_pipeline` + `_run_figma_relay_pipeline` from `routers.generate` and lift the ~1400 lines of frontend bodies into `phase_frontend.py` + `phase_figma_pre.py` (contracts already locked in Phase 1d). The wrapper currently keeps both legacy functions as internal implementations; they remain callable through `run_pipeline`. This is a ~2000-line atomic edit that needs a dedicated session with baseline fixture snapshots (task #607).

*Not extracted (belongs inline in the new spine when 1e.2 happens):*
- `phase_schema` — mutates the `registry` Python var; belongs inline in the spine so the reconciled registry is visible to subsequent phases.
- Registry-mutating tail after parallel (`extract_routes` → `merge_section` → `validate_registry`) — mutates the spine's `registry` var; stays inline right after `phase_parallel_agents`.

*Next: Phase 1e — write the new spine.* Copy `_run_relay_pipeline`'s body into `run_pipeline(*, plan, source: PlanSource, ...)`. Rewrite the top to construct `PipelineState.create(...)`. Swap in the 9 extracted phase calls. Handle the divergent blocks (Figma deterministic mapper, refiner, MCP, binding pass) with `if source.is_figma:` guards. Delete `_run_figma_relay_pipeline`. Update the 5 entry-point callers.

---

### Phase 2 — Rich decisions + moments layer

**Effort:** 5–7 days. **Risk:** medium (this is the variety mechanism — if it's
thin, apps look same, no matter what phases 3–5 do).

The decisions LLM authors today are shallow. Extend them to carry real
per-app design intent. Composer accepts these as first-class input.

**Decision object per page type:**

```
DashboardDecisions {
  kpis: [{label, aggregation, entity, emphasis, visualization}],
  primary_widget: { kind: "chart" | "balance-rings" | "heatmap" | ...
                    layout_hint, dataSource, series_op },
  activity: { kind, entity, empty_state },
  hero: { kind: "kpi-strip" | "personalised-greeting" | "editorial-quote" | ...
          copy, ornament },
  section_rhythm: "tight" | "cozy" | "generous",
  signature_moves: [id, id, ...],   // from catalog
}

CollectionDecisions {
  layout: "table" | "kanban" | "calendar" | "cards" | "timeline",
  columns: [...],
  row_treatment: "compact" | "photo-forward" | "status-led" | ...,
  filter_presets: [...],
  empty_state: { illustration, headline, cta },
  hero: {...},
  signature_moves: [...],
  footer: null | {...},
}

RecordDecisions {
  mode: "view" | "edit" | "create",
  section_grouping: [...],
  field_ordering: [...],
  control_hints: { fieldName: hint, ... },
  hero: {...},
  signature_moves: [...],
}
```

**Wire in the variety mechanisms (all already partially built):**

- **Signature-moves catalog** (Angle E — already exists, extend to ~50 curated
  moments) — LLM picks 1–3 per page from the catalog.
- **Variance seed** (Angle H — already exists) — deterministic per-brief salt so
  two same-domain apps diverge.
- **21st.dev references** (already wired) — LLM sees 3 domain-matched components,
  extracts composition intent (not raw JSX) into decisions.
- **Design brief propagation** (SPEC-A already ships brief → CSS, extend to
  decisions layer) — brief keywords shape moments.

**Composer contract:**

Each composer exposes named slots that must be honoured:
`hero`, `empty_state`, `signature_moves`, `ornament`, `section_rhythm`, `footer`.
Composer's job: assemble schema from structure + drop moments into slots.

**Verify:**
- Two generations of the yoga fixture produce measurably different pages
  (moment-diversity metric: <50% overlap in chosen moments).
- Leave-management dashboard shows balance rings (not KPI tiles) because
  decisions layer picks the domain-appropriate widget.
- Recruitment inbox has inline decisions (from advanced UX patterns), not
  navigate-away flow.

---

### Phase 3 — Dashboard authority (proof of pattern)

**Effort:** 3–5 days. **Risk:** medium (highest-visibility artifact).

Prove the "one writer per artifact" pattern on dashboards first.

- **Sole writer:** `apply_dashboard_maquette` composer.
- **LLM page-schema agent:** skips `type=dashboard` pages entirely.
- **Fallback:** if maquette authoring fails, composer falls back to recipe
  library (today's `dashboard_completeness` top-up path).
- **Guards demoted to assertions on dashboards:**
  - `dashboard_completeness` (assert, don't rewrite)
  - `surface_wrap_guard` (assert on dashboards)
  - `widget_data_source_guard` (assert)
  - `chart_data_source_guard` (assert)

**Verify:**
- Yoga dashboard: ≥3 KPIs, primary chart with real dataSource, activity feed.
- Recruitment dashboard: role-scoped variants (admin ≠ recruiter).
- Leave-management dashboards: balance rings + upcoming leaves + HR heatmap
  (three actor variants).
- `self_verify_pass` dashboard-completeness journey passes.

---

### Phase 4 — Renderer↔schema contract unification

**Effort:** 3–5 days. **Risk:** medium (renderer changes touch every app).

Fix the "author writes, renderer ignores" class of bug.

**Discovery pass:** grep every field the generator writes into `shell.json` /
page schemas, cross-reference against renderer reads. Known offenders:
- `shell.json.frame` (sidebar/topbar/rail) — renderer ignores
- `shell.json.layout.navigation` — renderer ignores
- (Full list per discovery pass)

**Per offender, one of:**
- Renderer honours it (update `AppShell.tsx` etc.).
- Generator stops writing it (remove from deterministic authors).

**Install a contract-drift test** that asserts every field written by the
generator has a corresponding reader in the renderer.

**Verify:**
- Multi-actor apps render sidebar as intended (yoga fixture — 3 actors → sidebar).
- Contract-drift test green.

---

### Phase 5 — Naming authority collapse

**Effort:** 3–5 days. **Risk:** low (extract-then-adapt).

Fold 7–8 overlapping registry modules into canonical `resource_registry`:

- `services/registry.py`
- `services/registry_validator.py`
- `services/registry_extractor.py`
- `services/registry_repair.py`
- `services/plan_field_lookup.py` → thin adapter over `resource_registry`
- `services/canonical_registry.py` (if separate)
- Overlap in `services/entity_completeness.py`

**Migration:** extract-then-adapt — keep legacy alive, port callers one at a
time, delete legacy when caller-count hits zero.

**Verify:** Fixtures regen identically. `resource_registry.build_canonical_registry(plan)`
produces same downstream state as today's chain.

---

### Phase 6 — Collection + Record + Shell authority

**Effort:** 5–7 days. **Risk:** medium (pattern repeats Phase 3's shape but
across more page types).

Apply the Phase-3 pattern to the remaining page types + shell.

**6a. Collection authority (2 days).**
- **Sole writer:** `build_collection_page` (extended from today's `build_list_page`).
- Layout picker: `table | kanban | calendar | cards | timeline` driven by
  decisions layer.
- Absorbs today's list emitters + tasks inbox + cart page + integrations
  settings emitters. Delete those dedicated emitters.
- Guards demoted: `list_data_source_guard`, `surface_wrap_guard` (on
  collections), `table_row_nav`, `ensure_create/edit_routes`.

**6b. Record authority (2 days).**
- **Sole writer:** `build_record_page(mode)` — one builder for view / edit / create.
- Absorbs today's `build_form_page`, `build_create_page`, `build_edit_page`,
  detail-view emitters, and the scan-page emitter.
- Mode picker driven by route (`/new` = create, `/[id]/edit` = edit, `/[id]` = view).
- Guards demoted: `form_scaffold`, `workflow_launch_forms` (backstop only),
  `form_target_guard`, `neutralize_event_only_buttons`, `singleton_page_reconciler`.

**6c. Shell authority (1 day).**
- **Sole writer:** `build_shell_deterministic` reading `nav-flow.json`.
- LLM `shell_agent` deleted (or reduced to content-hint only, not schema writer).
- `shell_menu_sync` folds into deterministic writer.
- `_dedupe_by_label` becomes dead code.

**6d. Purge the "custom" escape (½ day).**
- LLM `page_schema_agent` accepts only the 3 types + explicit `bespoke: true`
  from plan.
- Anything else fails validation → REVISE loop.
- Bespoke pages skip composer entirely, run through validator only. Reserved
  for 1–2 pages per app (landing, onboarding welcome, hero moments).

**Verify:**
- All 5 fixtures pass self-verify.
- Leave-management: forms have FK-Selects (not free text), calendar renders
  Calendar (not Table), approval inbox has inline-decision pattern.
- Every fixture: shell menu items match nav-flow.json exactly. Role-scoped
  visibility works.

---

### Phase 7 — Post-gen consolidation

**Effort:** 2–3 days. **Risk:** low (mostly bookkeeping).

- `apply_post_generate_fixes` called exactly once, at pipeline tail.
- Declare `PostGenPhase` enum + explicit order in `services/post_generate_fixes.py`.
- Every guard runs exactly once per generation (dev-mode counter to assert).
- Remaining ~15 guards are assertions only.

**Verify:** Fixtures regen identically. Guard-once counter green.

---

## Expected outcome (concrete)

### Generating a leave management system today vs after

| Feature | Today | After |
|---|---|---|
| Login/signup work | ✅ | ✅ |
| Employee dashboard | Sparse: "Balance: 0", one KPI, no chart | Balance rings per leave type + upcoming leaves + personalised greeting |
| Request-leave form | 30% crash rate; FK is free text; dates are Textareas | Works first time. Type is Select, dates are DatePickers, live "days requested" calc |
| Approval inbox | Empty table (no seed) | Real workflow tasks seeded, inline Approve/Reject with `useOptimistic` |
| Team calendar | LLM emits Table | Calendar component with color-coded leave-type entries |
| Balance overview | Hardcoded 0s | Real `SUM(leaveDays) GROUP BY type` aggregation, progress rings |
| HR admin dashboard | Same as employee dashboard | Team-wide KPIs + heatmap of team availability + coverage view |
| Sidebar per actor | Same menu for everyone | Employee sees My Requests, manager sees Approvals + badge, HR sees Balances |
| Workflow lifecycle end-to-end | Often broken (orphan, missing task, double-book) | Submit → task → decide → notify → balance — atomic + idempotent |
| Second HR app in same session looks | Identical | Distinct (variance seed + different signature moves + brief-driven moments) |

### Rollup metrics

| Metric | Today | After | Delta |
|---|---|---|---|
| Pipeline entry points | 2 | 1 | −1 |
| Phases in `generate.py` | 72 | ~35 | −37 |
| Post-gen guards | 60+ | ≤15 assertions | −45 |
| Writers per artifact (avg) | 4–9 | 1 | −5 avg |
| `generate.py` + `services/` lines | ~15k | ~13k | −2k |
| Broken pages per app | 1–3 | 0 | full |
| Working out-of-box | ~60% | ~95% | +35pp |
| Distinct-look score (same domain) | 2/10 | 7/10 | +5 |
| Generation time | 6–12 min | 4–7 min | −40% |
| Cost per generation | $3–6 | $2–4 | −40% |
| Smith iterations to presentable | 3–5 | 0–1 | −4 |
| Time to add a new vertical | 2 weeks | 3 days | −80% |

### Honest limits (what this doesn't buy)

- **Not Apple-caliber design.** Ceiling is the moments catalog + composer
  vocabulary. Curate 50 signature moves → 50 possible flavours per page type.
  Much better than 1, not infinite.
- **Not "one-shot Linear."** Genuinely category-defining marketing pages need
  hand-crafted work. Bespoke escape hatch helps but doesn't close the gap.
- **Domain gaps persist** for domains the catalog doesn't know (genomics,
  air-traffic control). Fix = curate more archetype hints; not something
  cleanup itself solves.
- **Sub-domain nuance** (e.g. "leave management for pilots with FAA duty
  rules") still needs brief-completeness discipline. Not a pipeline problem.
- **Fine-tuning postponed.** The pipeline needs to be coherent first
  (referring back to earlier discussion). After Phase 7, revisit fine-tuning
  the decisions/moments layer specifically.

---

## Sequencing

Recommended order — each phase unblocks the next:

```
0. Dead-code sweep (1d)
   ↓
1. Pipeline spine collapse (3–5d)
   ↓
2. Rich decisions + moments layer (5–7d)   ← variety mechanism, before authority
   ↓
3. Dashboard authority (3–5d)              ← proof-of-pattern
   ↓
4. Renderer↔schema contract (3–5d)         ← unblocks visible fixes
   ↓
5. Naming authority collapse (3–5d)        ← can run in parallel with 4
   ↓
6. Collection + Record + Shell authority (5–7d)
   ↓
7. Post-gen consolidation (2–3d)
```

Phase 2 sits before Phase 3 deliberately: authority collapses without a rich
decisions layer produce competent-but-generic apps. The moments layer is what
makes composer-authored apps not look same.

Total: **26–39 working days = 5–8 weeks calendar** at focused pace.

---

## Success criteria (must all be true to declare done)

- [ ] `_run_figma_relay_pipeline` deleted. One entry point.
- [ ] Guard count ≤ 15, remaining guards are assertions only.
- [ ] Every artifact has exactly one declared writer.
- [ ] LLM emits decisions/moments objects, not schema JSON (except bespoke).
- [ ] Signature moves catalog has ≥ 50 curated entries.
- [ ] Renderer contract-drift test installed and green.
- [ ] All 5 fixtures regen and score ≥ baseline on `self_verify_pass`.
- [ ] Two same-domain fixtures diverge measurably (moment-diversity metric).
- [ ] `generate.py` + `services/` line count down ≥ 2000.
- [ ] All existing tests still pass.
- [ ] Leave-management fixture ships with role-scoped nav, working approval
      workflow, real balance calc, calendar view, balance rings.

---

## Open questions (resolve before Phase 2)

- [ ] **Recipe library fate** — used by ~1 guard today. Keep as Phase-3
      fallback, or delete once maquette author is proven? Recommend: keep as
      fallback until Phase 6 ships, then evaluate.
- [ ] **Schema version bump for Phase 4** — do we bump to gate old-app
      compatibility, or trust re-generation? Recommend: don't bump; older
      apps re-generate on next user action anyway.
- [ ] **Rollout mode** — trunk-based per-phase or `FORGE_PIPELINE_V2` flag
      with dual-path until Phase 7? Recommend: trunk-based. Fixture-regen
      gate catches regressions; dual-path doubles maintenance cost during
      the 5–8 weeks.

---

## Not in scope

- Fine-tuning a model. Wait until Phase 7 lands.
- Renderer rewrite / `schemaVersion:3`. Phase 4 is additive.
- Smith / editor refactor. Different surface, different owners.
- Deployment / preview pipeline. Out of scope.
- New archetypes (dispatch-console, ATC-tower, etc.). Add after cleanup.
