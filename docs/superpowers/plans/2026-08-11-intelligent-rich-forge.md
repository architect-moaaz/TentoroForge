# Intelligent + rich Forge — implementation plan

**Status**: proposed, not started.
**Owner**: joint (pipeline + Smith + design-quality workstreams).
**Spec**: `docs/superpowers/specs/2026-08-11-intelligent-rich-forge.md`
(read first — this plan assumes that spec's terminology + decisions).

**Goal in one sentence.** Ship the substrate so that every generated
app is *architecturally correct on first try* (no manual patches
needed) and *visually distinctive by domain* (no generic-shadcn
look), across the small/large × single/multi-module × in-scope/
extension/out-of-scope matrix defined in the spec.

**Ship discipline.** Pipeline is upgraded in place — no
`FORGE_INTELLIGENT_GENERATION` toggle, no legacy-mode alongside
new-mode. Every PR lands with snapshot regression coverage on 8
canonical apps. If a merge escapes review, revert the commit —
same as any other platform change. Old generated apps (in
`output/`) are untouched; Smith computes `app_shape`/etc. lazily
when it edits them.

**Timeline.** 14 weeks, 3 engineers running in parallel. Each
milestone ships independently and unblocks the next.

---

## Sequencing rationale

The plan sequences four dependencies:

1. **Data model + vocabularies first**, because nothing downstream
   can read what isn't yet on `plan.py`.
2. **Planner authors the axes before consumers read them**, because
   an empty `app_shape` on `plan.json` breaks every reader.
3. **App-global stages before per-page stages**, because
   `resolve_shape(plan, route)` requires the outer profile to exist.
4. **P1 (topology) before P2 (intelligence) before P3 (richness)**,
   because the intelligence loop reads the four axes, and richness
   readers key off capability primitives that P1 authors.

Anything violating this ordering must justify why.

---

## Milestone map

| M | Weeks | Deliverable |
|---|---|---|
| **M0** | 1 | Foundations: data model, vocabularies, `industry` rename |
| **M1** | 2-3 | Planner authors all four axes + coverage verdict |
| **M2** | 4 | Coverage-verdict gate + out-of-scope refusal card |
| **M3** | 5-6 | App-global stages read `plan.app_shape` + `runtime_context` |
| **M4** | 7-8 | Per-page stages read `resolve_shape(plan, route)`; multi-module apps work |
| **M5** | 9-10 | Intelligence loop (`SessionContext` + plan→act→verify→recover) |
| **M6** | 11-12 | Rich by construction (aesthetic profiles + signatures + surface pass + critic enforcement) |
| **M7** | 13-14 | Acceptance suite + quality dashboard + recipe/reference-app library seeding + live cutover |

---

## M0 — Foundations (Week 1)

**Deliverable.** `plan.py` has all four axis fields; vocabulary
JSON files exist; `industry` rename is landed; no downstream
consumer reads any of it yet. Regenerating any existing app is
byte-identical modulo the rename.

**Owner.** Engineer A (systems).
**Effort.** 5 days.

### Tasks

- **IRF-M0-T1** — `services/tools/rename_domain_industry.py`
  codemod. `sed` over ~20 Python files + JSON keys in `plan.py`,
  `domain_context.py`, `industry_design.py`, `page_type_templates.py`,
  agent prompts, snapshot fixtures. Full `pytest` sweep green.
- **IRF-M0-T2** — Author `backend/shapes/vocabulary.json` with the
  12 shape primitives + closed value sets from the spec.
- **IRF-M0-T3** — Author `backend/archetypes/capability_vocabulary.json`
  with the 5 capability slices from the spec.
- **IRF-M0-T4** — Author `backend/runtime/context_vocabulary.json`
  with the 15 runtime capabilities from the spec.
- **IRF-M0-T5** — Seed `backend/shapes/reference_apps.json` with
  10 reference apps (Snap2App, Spotify, Instagram, Uber, Workday,
  Shopify, Robinhood, Gusto, Swiggy, tip calc) as authored in the
  spec's planner-prompt section.
- **IRF-M0-T6** — Seed `backend/archetypes/recipes.json` with 15
  recipes: `visual_product_search`, `catalog`, `crud`, `directory`,
  `dashboard`, `kanban`, `approval_queue`, `wizard`, `checkout`,
  `cart`, `chat`, `feed`, `player`, `chart_analysis`, `map_pins`.
  Each declares its resolved capability primitives + workflow
  template + component set + recipe-specific signatures.
- **IRF-M0-T7** — Seed `backend/archetypes/signature_moves.json`
  keyed by capability primitive value (10 triggers as listed in
  the spec).
- **IRF-M0-T8** — Seed `backend/runtime/context_bundles/` — one
  folder per capability with permission strings + native import +
  provider template + integration key requirements. Start with 6
  most common (`geo`, `camera`, `push_notifications`,
  `biometric_auth`, `photo_library`, `deep_linking`); rest deferred
  to M7.
- **IRF-M0-T9** — Extend `plan.py` types: `ShapeProfile`,
  `LayoutSlice`, `AuthSlice`, `NavSlice`, `WorkflowSlice`,
  `DataSlice`, `IdentitySlice`, `ShapeProfileOverride`,
  `Capabilities`, `ReadSlice`, `WriteSlice`, `PresSlice`,
  `StateSlice`, `ArchetypeInstance`, `CoverageVerdict`. Add the 5
  new fields to `Plan` (`app_shape`, `archetypes`, renamed
  `industry`, `runtime_context`, `coverage_verdict`). All types
  optional-with-defaults for M0 (unblocks pipeline; planner starts
  populating them in M1).
- **IRF-M0-T10** — Snapshot-generation baseline: regenerate 3
  existing apps (whatever's in `output/` from recent gens), commit
  their `plan.json`s as fixtures. These are the "M0-clean" starting
  point every subsequent PR compares against.

### Acceptance

1. `pytest` full sweep green after codemod.
2. `plan.py` type-checks with the new fields; existing generations
   still work because fields are optional.
3. 3 baseline snapshots committed.

---

## M1 — Planner authors four axes + coverage verdict (Weeks 2-3)

**Deliverable.** Every fresh `plan.json` has all four axes and
the coverage verdict populated by the LLM (not defaults). Fallback
detectors exist as safety nets. Snapshot tests on 5 canonical
apps prove the planner composes correctly.

**Owner.** Engineer A + Engineer C (Smith/context).
**Effort.** 10 days.

### Tasks

- **IRF-M1-T1** — Planner prompt extension: append the four-axes +
  coverage-verdict prompt blocks from the spec. Reference apps
  section renders from `reference_apps.json`. Structured output
  schema updated to require the new fields.
- **IRF-M1-T2** — `services/plan_validators/shape_profile.py` —
  validate every primitive value against
  `shapes/vocabulary.json`. Bad value → per-field fallback via
  `shape_profile_detector.py`. Emit findings.
- **IRF-M1-T3** — `services/plan_validators/archetypes.py` — for
  each `ArchetypeInstance`, validate: `recipe` name exists in
  `recipes.json` (if set); `capabilities` values in
  `capability_vocabulary.json` (if set); at least one is set.
- **IRF-M1-T4** — `services/plan_validators/runtime_context.py` —
  validate every declared capability exists in
  `context_vocabulary.json`. Reject unknown values (LLM
  hallucination) — no fallback (empty list is a valid answer).
- **IRF-M1-T5** — `services/plan_validators/coverage_verdict.py` —
  validate `status` in enum; `nearest_supported` populated when
  status != in_scope; `missing_dimensions` populated when
  extension_needed.
- **IRF-M1-T6** — `services/shape_profile_detector.py` — keyword
  scorer safety net (per the fallback ladder in the spec). Fills
  per-field; conservative defaults when no signal.
- **IRF-M1-T7** — `services/archetype_recipe_detector.py` — keyword
  scorer safety net that picks a recipe when the LLM's output is
  invalid.
- **IRF-M1-T8** — `LLM_UNAVAILABLE` finding class + persistence.
  When any detector fires, generation is tagged
  `produced_under_degraded_conditions=true`; quality dashboard
  (M7) surfaces the rate.
- **IRF-M1-T9** — `services/plan_coherence.py` — the cross-field
  coherence check from the spec. Suspicious combos
  (`consumer-utility`-like shape + workspace archetype;
  `on-load` gating + `single-session` identity; fire-and-forget
  workflow + single-record read; etc.) → `plan_completeness`
  finding, REVISE loop once.
- **IRF-M1-T10** — Planner REVISE loop wiring: on validator
  finding severity >= warning, one retry with the specific finding
  in-prompt (existing Slice 7 pattern).
- **IRF-M1-T11** — Live regen 5 canonical apps (Snap2App-shaped,
  Linear-shaped, Instagram-shaped, Uber-shaped, Workday-shaped)
  → assert each `plan.json` matches expected axis composition
  (fixtures committed as `snapshots/plan/`).
- **IRF-M1-T12** — Live regen 2 stress-test briefs (multiplayer
  game, video editor) → assert `coverage_verdict.status ==
  "out_of_scope"` and `nearest_supported` populated. No downstream
  generation performed (gate lands in M2; for now, verify the
  verdict, then abort manually).

### Acceptance

1. 5 canonical apps produce expected axis compositions.
2. 2 out-of-scope briefs produce correct verdicts.
3. Kill-switch simulation (no `ANTHROPIC_API_KEY`) — detectors
   fill everything, `LLM_UNAVAILABLE` finding recorded.
4. Full `pytest` green including 12 new validator/coherence tests.

---

## M2 — Coverage-verdict gate + refusal path (Week 4)

**Deliverable.** `out_of_scope` verdict halts generation before
tokens are spent; frontend shows a structured refusal card;
`extension_needed` verdicts land in `substrate_gap_log.jsonl`.

**Owner.** Engineer A + Engineer C (frontend surface).
**Effort.** 5 days.

### Tasks

- **IRF-M2-T1** — `services/coverage_verdict_gate.py` — runs FIRST
  in `_run_relay_pipeline` (before any generation stage). Reads
  `plan.coverage_verdict`. Three code paths per spec (in_scope /
  extension_needed / out_of_scope).
- **IRF-M2-T2** — `services/substrate_gap_log.py` — append-only
  JSONL writer at `backend/telemetry/substrate_gap_log.jsonl`.
  One entry per `extension_needed` verdict with brief summary +
  gap fields + timestamp.
- **IRF-M2-T3** — SSE event: `coverage_verdict` message-type,
  emitted on halt. Payload is the full `CoverageVerdict` object.
- **IRF-M2-T4** — Frontend `OutOfScopeCard` component. Displays
  the refusal reason, `nearest_supported`, three action buttons
  (Generate nearest / Refine brief / Cancel). "Generate nearest"
  reissues the brief with an `overrides.suggested_reframe` block
  targeting the nearest-supported shape.
- **IRF-M2-T5** — Backend `POST /api/projects/{id}/reframe` —
  accepts the user's override choice and reissues the plan step.
- **IRF-M2-T6** — Gap-log review page (dev-only for now):
  `localhost:6501/dev/substrate-gaps` — lists gaps grouped by
  dimension, count per week. Manual "promote to vocabulary" is
  intentionally NOT a button — vocabulary edits stay human-authored
  via PR.
- **IRF-M2-T7** — Live E2E: 2 out-of-scope briefs → refusal card
  appears in chat; 2 extension-needed briefs → gap log rows
  appear; 5 in-scope briefs → normal generation.

### Acceptance

1. Out-of-scope brief spends <5s of tokens (planner only) and
   halts.
2. `substrate_gap_log.jsonl` accumulates rows for
   extension-needed generations.
3. In-scope generations unaffected (baseline snapshots hold).

---

## M3 — App-global stages read axes (Weeks 5-6)

**Deliverable.** Every stage in the downstream integration table
that reads app-global state pulls from `plan.app_shape` /
`plan.industry` / `plan.runtime_context`. Snap2App-style consumer
apps regenerate as consumer-utility (no dashboard shell, no
`/login` route, `<Toaster />` at root). Small consumer apps stop
requiring manual patches.

**Owner.** Engineer A + Engineer B (library/frontend).
**Effort.** 10 days.

### Tasks

- **IRF-M3-T1** — `services/shape_profile_derived.py` — derived
  functions (`needs_root_toaster`, `form_submit_pattern`,
  `should_generate_login_route`, plus `_merge`, `_find_owning_module`).
  Unit-tested; the ONE place cross-primitive logic lives.
- **IRF-M3-T2** — `select_frame` (SP4-2) reads
  `plan.app_shape.layout.shell`. Switch on the 6 values; each
  renders the corresponding frame. `none` → no shell wrapper.
- **IRF-M3-T3** — `derive_actor_onboarding` reads
  `plan.app_shape.auth` + `should_generate_login_route(app_shape)`.
  `route` → existing `/login`+`/signup`. `modal` →
  `<LoginModal>` + `useRequireAuth`. `none` → skip.
- **IRF-M3-T4** — `shell_menu_sync` reads
  `plan.app_shape.nav.menu` + `plan.archetypes`. `none` skips
  synthesis; `bottom-tabs` renders bottom tabs; `sidebar-links`
  keeps existing behavior; `header-links` renders header nav;
  `drawer` renders drawer; `command-palette` renders cmd-k.
- **IRF-M3-T5** — `root_layout_template` reads
  `needs_root_toaster(app_shape)` → mounts `<Toaster />` when
  derivation says so. Fixes AC10-copy "no toaster on _figmaDerived"
  class permanently.
- **IRF-M3-T6** — `schema_builder` reads
  `plan.app_shape.data.denormalization`. `aggressive` → emit
  `*Name` denorm columns per FK. Fixes AC10-copy `retailer_name`
  column need without hand-editing.
- **IRF-M3-T7** — `design_agent` reads `plan.app_shape.layout.hero`
  + `layout.density` + `plan.industry` → passes to
  `aesthetic_profile_picker` (stubbed in M3, real in M6).
- **IRF-M3-T8** — NEW `services/runtime_context_wire.py` —
  post-gen pass. For each `plan.runtime_context` capability, reads
  the corresponding `context_bundles/<name>/` folder and emits
  permission block, native import, provider wrap in root layout,
  env vars. Idempotent.
- **IRF-M3-T9** — Existing `MOBILE-A` (Expo scaffolding) reads
  `plan.runtime_context` instead of guessing per-recipe.
- **IRF-M3-T10** — Existing `platform_integrations` provider
  matching reads `plan.runtime_context` — providers that need
  server keys (FCM/APNs for `push_notifications`, geocoding for
  `geo`) auto-appear in `/settings/integrations`.
- **IRF-M3-T11** — Snapshot regression: regen Snap2App-shaped +
  Linear-shaped + Instagram-shaped apps. Zero-manual-patches
  target hits for Snap2App-shaped (AC10 baseline).

### Acceptance

1. Snap2App-shaped fresh generation renders end-to-end (hero page,
   modal auth, toaster works, retailer_name column emitted,
   scan-then-navigate flow) without any hand editing.
2. Linear-shaped fresh generation still renders with sidebar (no
   regression on the workspace class).
3. Instagram-shaped fresh generation renders with bottom-tabs shell
   (new class works).
4. Baseline snapshots for the 3 canonical apps updated once,
   locked as the new floor.

---

## M4 — Per-page stages + multi-module resolution (Weeks 7-8)

**Deliverable.** Every per-page stage reads
`resolve_shape(plan, route)`. Multi-module apps (Uber, Workday,
Swiggy) generate correctly — the `/pay` route flips to form-mode
over the map shell; the `/checkout` route strips the shell during
wizard; the `/order-tracking` route flips to `map-canvas` on top
of the bottom-tabs shell.

**Owner.** Engineer A + Engineer B.
**Effort.** 10 days.

### Tasks

- **IRF-M4-T1** — `page_schema_agent` reads `resolve_shape(plan,
  route)` + owning `ArchetypeInstance` + `plan.runtime_context`
  as system context. Prompt injected via
  `services/session_context.py` (stub M4; real in M5).
- **IRF-M4-T2** — `build_form_page` reads
  `form_submit_pattern(resolve_shape(plan, route))` + owning
  archetype. Submit pattern from effective shape (fire-and-forget
  / await-with-spinner / in-place-progress); field layout from
  archetype.
- **IRF-M4-T3** — `translate_workflow` reads
  `resolve_shape(plan, workflow.owning_route).workflows.executionMode`.
  Fire-and-forget → emit `submit.mode: fire-and-forget` (fixes
  AC10-copy Form-await-blocks class); streaming → emit polling +
  navigate-on-complete; await-with-progress → existing.
- **IRF-M4-T4** — Engine-level `continueOnError: true` on
  workflow nodes. Fixes the "scan stays pending forever" AC10-copy
  class — one failing `extract_N` doesn't kill `mark_completed`.
- **IRF-M4-T5** — `post_generate_fixes` refactor — every guard now
  takes `plan` + `route` (not just `plan`). Runs derived
  functions over effective shape. Guards that only depend on
  app-global state (border/next.config) unchanged.
- **IRF-M4-T6** — `signature_moves_guard.py` — reads
  `plan.archetypes`, computes expected signatures per instance
  from resolved capabilities via
  `services/signature_move_resolver.py`, verifies presence per
  route. Missing → inject template (M4; M6 upgrades to REVISE
  loop).
- **IRF-M4-T7** — Snapshot regression: regen Uber-shaped +
  Shopify-shaped + Workday-shaped + Swiggy-shaped. Assert
  per-route shapes differ where local overrides declare so.

### Acceptance

1. Uber-shaped: `/` renders map-canvas; `/pay` renders form-modal
   over map; `/history` renders header + list; `/chat` renders
   three-pane. Snapshot committed.
2. Shopify-shaped: `/` renders header + hero + card-grid;
   `/checkout` renders wizard with no header. Snapshot committed.
3. Workday-shaped: 8 modules generate; org-chart module uses tree
   layout with pan/zoom; kanban module uses board layout with
   drop-zone glow; wizard modules strip nav.menu during flow.
4. Swiggy-shaped: bottom-tabs shell; `/order-tracking` flips to
   map-canvas; `runtime_context_wire` emits `geo` +
   `push_notifications` permissions.

---

## M5 — Intelligence loop (Weeks 9-10)

**Deliverable.** Every generation stage AND every Smith turn
follow the same context → plan → act → verify → recover cycle.
`SessionContext` is the shared substrate. Verify runs after
every mutation, not only at the end.

**Owner.** Engineer C (Smith/intelligence).
**Effort.** 10 days.

### Tasks

- **IRF-M5-T1** — `services/session_context.py` — `SessionContext`
  Pydantic model with 7 fields per spec. Loaders read
  `plan.json` + `registry.json` + shape/archetype/industry
  profiles + edit history + verify history. In-process cache
  keyed by (project_id, plan-mtime).
- **IRF-M5-T2** — Every pipeline stage's entry signature accepts
  a `SessionContext` argument. Old signatures accept it as
  optional; new callers pass it. Migration one stage per commit.
- **IRF-M5-T3** — `smith_memory` becomes a view onto
  `SessionContext`. `build_app_map` + `smith_memory._VERBATIM_CLIP`
  wiring stays; underlying data source unified.
- **IRF-M5-T4** — `Stage.plan(context) → StagePlan` interface on
  every generation stage. `StagePlan = {intent, files_to_touch,
  files_to_read, expected_bindings, expected_workflows}`.
  Deterministic where possible; LLM-authored otherwise. First 3
  stages migrated (planner, page_schema_agent, workflow author);
  rest deferred to M5 tail if time.
- **IRF-M5-T5** — `services/verify_stack.py` — 5-check verify
  stack per spec (static / structural / domain-conformance /
  design-conformance / runtime). Each stage declares which checks
  it needs. Cheap checks (<5s) always run; expensive ones opt-in.
- **IRF-M5-T6** — `services/recover_ladder.py` — 3-attempt
  ladder per spec (LLM-authored → LLM+validator-error → template
  fallback → escalate). Wraps every stage output and every Smith
  tool call.
- **IRF-M5-T7** — Domain-conformance check: for each generated
  page, verify effective shape's constraints are honored (no
  `<Sidebar>` on shell:none pages; auth modal declared on
  auth.surface:modal apps; etc.). Findings feed the recover
  ladder.
- **IRF-M5-T8** — Multi-perspective critic personas: `design`
  (aesthetic conformance), `ux` (invariant conformance),
  `correctness` (binding/data conformance). Runs after page
  generation. REVISE loop if any fail hard threshold. M5 wires
  the plumbing; M6 tunes rubrics.
- **IRF-M5-T9** — `read_last_verify_run` extended to include
  verify-stack results; Smith reads it before mutations to know
  current health.
- **IRF-M5-T10** — Live E2E: refire the AC10-copy "Scan now
  clicked, nothing happens" symptom via Smith. Recover ladder
  hits template fallback for the workflow-node case; scan
  completes; verify-loop confirms redirect works. Zero user
  intervention.

### Acceptance

1. Every stage output logs a `VerifyReport` in
   `session_context.verify_history`.
2. Every Smith turn logs a plan → act → verify record.
3. Simulated failure (delete a required binding mid-turn) → recover
   ladder walks 3 attempts and either fixes or escalates with
   structured "here's what I tried."
4. Workflow with continueOnError node → mark_completed still runs
   even when an extract step fails.

---

## M6 — Rich by construction (Weeks 11-12)

**Deliverable.** Every generated app is visually distinctive by
composition — no default-shadcn look. Aesthetic profile picked
from primitives, signature moves injected per-module, surface
treatment applied deterministically, design critic in
enforcement mode for consumer-facing shapes.

**Owner.** Engineer B (library/design).
**Effort.** 10 days.

### Tasks

- **IRF-M6-T1** — Author 6 aesthetic profile JSON fragments in
  `backend/design/aesthetic_profiles/` (glass-dark, carbon,
  polaris, material-3, fluent-2, clean-editorial). Each = tokens
  (color, type, radius, shadow, spacing) that merge into
  design-spec.
- **IRF-M6-T2** — Author the 6 corresponding library component
  variants (`Button.glass`, `Card.carbon`, `Input.polaris`, etc.).
  Library dist rebuild. Revendor into `standalone-app` template.
- **IRF-M6-T3** — `services/aesthetic_profile_picker.py` per
  spec. Derived from `plan.app_shape` primitives + `industry` +
  user override.
- **IRF-M6-T4** — `services/surface_treatment_pass.py` per spec.
  Post-gen, deterministic: root Stack → gradient background on
  hero pages; Container role:card → variant from profile; Button
  role:primary → variant from profile; Loader → aesthetic
  animation. Zero LLM.
- **IRF-M6-T5** — Author 10 form patterns in
  `backend/forms/patterns/` (single-column-progressive,
  wizard-3-step, checkout-express, settings-tabbed, filter-drawer,
  onboarding-carousel, inline-editable-grid, modal-quick-add,
  master-detail-edit, multi-step-approval).
- **IRF-M6-T6** — `services/form_ux_invariants.py` — ~30 NN/g
  invariants as deterministic guards (required marker,
  blur-validation, in-flight-disable, error-describes-fix,
  numeric inputMode, etc.). Auto-fix where mechanical; surface as
  finding where intentional.
- **IRF-M6-T7** — Interpolator formatters (`percent`, `currency`,
  `relative`). Fixes AC10-copy "0.87%" class permanently.
  Renderer + library changes; unit-tested.
- **IRF-M6-T8** — Design critic promoted from shadow → enforcement.
  Trigger: effective shape has `identity.usageMode in
  (single-session, public-anonymous)` OR `layout.hero != none`.
  REVISE loop up to 2 revisions before falling to
  surface-treatment-pass fix.
- **IRF-M6-T9** — Design-critic rubric implementation: palette
  diversity ≥4 non-neutral, class-diversity vs shadcn baseline
  ≥40%, signature-moves-presence-per-instance ≥80%, shape
  topology conformance 100% (hard), aesthetic profile conformance
  ≥75%.
- **IRF-M6-T10** — Live regen 5 canonical apps → design-critic
  score computed + logged. Target: consumer-utility ≥85, workspace
  ≥70, none <50.

### Acceptance

1. Snap2App-shaped app renders visually equivalent to AC10 copy
   (radial dark gradient + glass cards + gradient-glow CTA) with
   zero hand-patching.
2. Workspace app renders in Carbon-adjacent aesthetic (sharp,
   dense, monochrome+accent) — clearly a different family from
   Snap2App.
3. Healthcare-adjacent workspace renders with Polaris-adjacent
   aesthetic tuned by healthcare palette — distinctive from the
   CRM.
4. Design critic blocks generation when score <50; auto-REVISE
   when 50-74; passes ≥75.

---

## M7 — Acceptance suite + rollout (Weeks 13-14)

**Deliverable.** 8-app snapshot suite runs on every PR to the
substrate area. Quality dashboard live. Recipe library seeded
to 20+ entries. Reference-app library seeded to 20+ entries.
Substrate-gap log has a review cadence. Substrate declared
complete; A/B/C/D/E spec workstreams start landing on top.

**Owner.** Engineer A + Engineer B + Engineer C.
**Effort.** 10 days.

### Tasks

- **IRF-M7-T1** — Snapshot-test infra: `tests/snapshots/` +
  fixture generator + snapshot updater CLI + diff renderer. CI
  gate: any diff in the 8-app snapshot suite fails the PR unless
  explicitly `snapshot: intentional` in the PR body.
- **IRF-M7-T2** — Snapshot fixtures for all 8 acceptance apps
  from the spec: (1) Snap2App capture utility, (2) tip
  calculator, (3) Instagram feed+capture, (4) Linear workspace,
  (5) Workday HCM, (6) Uber rider, (7) Shopify storefront, (8)
  Swiggy delivery.
- **IRF-M7-T3** — Quality dashboard at
  `localhost:6501/quality` — reads generation telemetry, shows
  weekly rolling: manual-patches per gen, post-gen guards fired,
  verify-findings survived, time-to-first-render, design-critic
  score by shape, Smith turn success rate,
  produced-under-degraded-conditions rate, out-of-scope rate,
  extension-needed rate.
- **IRF-M7-T4** — Grow `reference_apps.json` from 10 → 25 (add
  cover for finance-personal, health-fitness, education-learning,
  logistics-tracking, hospitality-booking, media-streaming,
  productivity-notes, community-social, government-forms,
  telecom-selfservice, ecommerce-admin, workspace-analytics,
  workspace-communication, consumer-photo, consumer-music). One
  afternoon of authoring.
- **IRF-M7-T5** — Grow `recipes.json` from 15 → 25 (add:
  `wizard-multi-step`, `chat-with-agent`, `livestream`,
  `booking-calendar`, `subscription-plan`, `settings-tabbed`,
  `search-with-filters`, `notification-inbox`, `onboarding-tour`,
  `document-viewer`).
- **IRF-M7-T6** — Complete `context_bundles/` for the 9
  remaining runtime capabilities (started 6 in M0). Full 15
  covered.
- **IRF-M7-T7** — Gap-log review workflow doc:
  `docs/superpowers/patterns/substrate-gap-review.md`. Weekly
  cadence, promotion rules (≥3 briefs across ≥2 weeks →
  vocabulary edit), template for the resulting PR.
- **IRF-M7-T8** — Companion authoring guides (per spec's
  "Companion documents to write" section):
  - `docs/superpowers/patterns/app-shape-shape-profile.md`
  - `docs/superpowers/patterns/aesthetic-profile.md`
  - `docs/superpowers/patterns/signature-move.md`
  - `docs/superpowers/patterns/recipe.md`
  - `docs/superpowers/patterns/runtime-context-bundle.md`
- **IRF-M7-T9** — Final acceptance: regen all 8 canonical apps
  fresh, no manual patches, all design-critic scores meet
  targets, quality dashboard shows the metrics live.
- **IRF-M7-T10** — Substrate-complete announcement: internal doc
  declaring the substrate stable; A/B/C/D/E specs may now depend
  on it; existing generated apps not migrated (Smith handles
  on-demand).

### Acceptance (matches the spec's Success Criteria)

For all 8 canonical apps:

1. **Zero manual patches** to reach usability equivalent to AC10
   copy (small apps) or reference-product module coverage (large
   apps).
2. **Every stage** logs `SessionContext` + `VerifyReport`;
   `resolve_shape` exercised on multi-module apps;
   `runtime_context_wire` exercised on apps declaring
   capabilities.
3. **Every Smith turn** logs plan → act → verify record; failures
   trigger recover ladder without user intervention.
4. **Design critic score** ≥75 unhand-tuned, ≥85 with one REVISE;
   multi-module apps scored per-module and app-average.

---

## Staffing

| Engineer | Owns | Milestones |
|---|---|---|
| **A — systems** | plan/pipeline data model, wiring, guards, telemetry | M0, M1 (with C), M2 (with C), M3 (with B), M4 (with B), M7 (with all) |
| **B — library + design** | library variants, aesthetic profiles, surface treatment, forms, design critic | M3 (with A), M4 (with A), M6, M7 (with all) |
| **C — Smith + intelligence** | context substrate, verify loop, recover ladder, multi-perspective critique | M1 (with A), M2 (with A), M5, M7 (with all) |

Every milestone has an owner; cross-milestone work is explicit.
Weekly cadence:
- **Monday** — milestone standup + demo (regenerate 1 canonical
  app, walk the delta).
- **Wednesday** — quality-dashboard review (once M7 lands; before
  M7, walk snapshot diffs).
- **Friday** — risks/blockers surface + next-week planning.

---

## Milestone gates

Each milestone requires **all three** to advance:
1. All acceptance tests green.
2. Canonical-app snapshot regressions triaged (either accepted as
   intentional or fixed).
3. Quality-dashboard metrics (once M7 lands) show monotonic
   improvement week-over-week or held steady with reason.

---

## Companion workstreams (parallel to milestones)

Two workstreams run in parallel to engineering; they don't gate
milestones but they gate ship quality.

**Content-A: recipe + reference-app library authoring.** Not
engineering — needs a design lens. Ongoing from M0; target 25
recipes + 25 reference apps by end of M7. One engineer half-day
per week is enough if disciplined.

**Content-B: acceptance app brief authoring.** Write the 8
canonical acceptance briefs as fixture inputs during M0. These
inputs are what M1-M7 snapshot against; getting them right early
saves rework.

---

## Risks + mitigations

Copied from the spec's "Risks + how we catch them" section; here's
what changes per milestone:

- **M0**: `industry` rename hitting hidden call sites — codemod
  in one commit + full pytest sweep + snapshot regen on 3
  baseline apps. Red CI = red merge.
- **M1**: LLM emits invalid axis values — validators reject +
  detector fallback + `LLM_UNAVAILABLE` finding. Not a runtime
  crash.
- **M2**: Refusal-card UX confuses users — copy tested with 3
  real users before ship. Refined based on feedback.
- **M3**: App-global stage refactor breaks existing generations
  — every stage change gated by the 3 baseline snapshots from
  M0-T10.
- **M4**: `resolve_shape` fanout increases planner-agent context
  size — cap `SessionContext` size at 8k tokens per Smith
  invocation; use a summary view for large apps.
- **M5**: Verify loop adds >30s per gen — CI budget check on
  wall-clock; over budget = revert. Design cheap-vs-expensive
  verify split accordingly.
- **M6**: Design critic in enforcement blocks legitimate designs
  — two tiers per spec; opt-out per gen via UI checkbox.
- **M7**: Quality dashboard shows regressions we can't fix in
  time — extend M7 by 1 week rather than ship with metrics
  regressed.

Every merged PR is atomic; a bad merge gets reverted, same as
any platform change. No rollback plan needed beyond
`git revert`.

---

## What "done" looks like on 2026-11-17

- Every generated app has the four axes populated by the LLM.
- Snap2App-clone briefs regenerate to visually AC10-quality
  output with zero hand-patching.
- Workday-clone briefs regenerate as 8 coherent modules under
  one sidebar shell, each with its own signature moves.
- Uber-clone briefs regenerate with map shell + form-mode `/pay`
  + list-mode `/history` — same app, three per-route shapes.
- Game / video-editor briefs get a structured refusal card, not
  a broken app.
- Smith edits pass the same verify loop the pipeline runs,
  auto-recover on failure, and log plan → act → verify per turn.
- Quality dashboard shows manual-patches-per-gen trending toward
  zero, design-critic score trending toward 85, Smith
  turn-success trending toward 95%.
- The substrate is stable; A/B/C/D/E spec workstreams start
  landing features on top of it.

That's when the substrate is done and the next quarter's
roadmap becomes about what to build on top, not what to fix
underneath.
