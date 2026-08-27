# Generation Pipeline Remediation — Multi-Phase Plan

**Started:** 2026-08-04
**Owner:** picks up in a fresh Claude session per phase (see "How to run" below).
**Source of truth:** commit `7a9edd88` = Phase 1 landed; this doc = the plan for Phases 0, 2, 3, 4, 5.

---

## Origin

End-to-end debug of the visual-product-search app (`output/nni3wjf6`) surfaced
19 platform-level issues + 6 planner-overreach root causes (see conversation
that produced this plan for the full inventory).

The user's ask: make future generations produce sensible, bounded,
domain-aware apps where every button works, every page shows data, no
phantom entities. Fixes must live in the generation pipeline, not per-app.

---

## The architecture we're moving toward

Current model: **generate freely → 30+ post-hoc guards fix symptoms**.
Failure mode: LLM re-invents the same class of problem each generation;
guards fix each symptom silently and drift over time.

Target model: **contracts before generation, proofs after, human gates in between**.
Failure mode: violations REJECT the LLM output; user sees ship-blocker chips.

Six layers:

1. **Requirement → Locked Spec** — deterministic + narrow LLM extractors
   produce a JSON spec (entities, actors, features, external deps) that
   downstream generators only READ. User confirms before generation.
2. **Spec → Page Manifest** — deterministic mapping. `managed` entities get
   CRUD, `event` entities get list+detail only, `role`/`derived` get no
   pages. User sees scope card, can prune/rename, then it becomes hard contract.
3. **Per-Page Generation** — LLM authors each page under 3 hard contracts
   (component / binding / action). Violations retry once, then fail the page.
4. **Post-Generation Proofs** — assertion pass. Orphan buttons, dangling
   bindings, unreachable pages, missing empty-states → ship-blocker chip
   (not silent repair).
5. **Runtime-Informed Verify Loop** — sandbox boot + Playwright golden path
   per feature × actor. Errors flow back to plan → LLM proposes fix → re-verify.
6. **Domain Archetype Library** — curated archetypes (visual-product-search,
   hr-recruitment, booking, crm, helpdesk, dashboard-only) bias the planner
   with sensible defaults. User confirms archetype before Layer 1 runs.

---

## Phase inventory

| Phase | Status | Time | What it delivers |
|---|---|---|---|
| 1 | ✅ done (commit `7a9edd88`) | 4h | 7 sharp platform fixes — see below |
| 0 | 🟡 core done (commit `a505d9bd`) | 8h | Locked spec + scope card + archetype library skeleton |
| 2 | 🟡 core done (commit `91ad337e`) | 4h | Planner recipes read locked spec (no re-derivation) |
| 3 | 🟡 core done (commit `91ad337e`) | 0-4h | Layer 3 contract validators |
| 4 | 📋 | 2h | Nice-to-haves (Drizzle migration bug, Firecrawl URL smarts) |
| 5 | 🟡 core done (commit `91ad337e`) | 6h | Layer 4 proof pass + Layer 5 verify loop wired |

**Total remaining:** ~10-14 hours (mostly pipeline wire-in + archetype
library expansion + Phase 4 + Phase 5 verify loop). All the deterministic
Python modules are landed, tested (76 tests green), and ready to be
consumed from `_run_relay_pipeline` behind an env flag.

### What "core done" means for Phases 0/2/3/5

Each phase's pure-Python module is written + tested (76 tests total).
Nothing wired into the generation pipeline yet — the wire-in is
deferred so each layer can ship + get exercised in isolation before
turning it on for real generations. The remaining pipeline-integration
work (2-3h) is:

1. In `backend/routers/generate.py::_run_relay_pipeline`, after the plan
   is produced, when `os.getenv("FORGE_LOCKED_SPEC") == "true"`:
   - Call `services.locked_spec.build_locked_spec(prompt)` → persist
   - Call `services.scope_card.build_and_persist_from_spec(output_dir)`
2. After workflow generation completes, unconditionally:
   - Call `services.workflow_validator.validate_output_dir(output_dir)`
     → persist via `persist_report`
3. After page schema generation completes, when the manifest is present:
   - Call `services.contract_validator.validate_output_dir(output_dir)`
     → persist via `persist_report`
4. As the final pipeline step:
   - Call `services.proof_pass.run_proof_pass(output_dir)` → persist
     via `persist_report`. Emit SSE `proof_result` event with the
     report. When `FORGE_PROOF_STRICT=true` and report.passed is False,
     mark generation as failed.
5. Frontend: consume `proof_result` SSE + render chip on project card.

---

## Phase 1 — done (2026-08-04, commit `7a9edd88`)

Seven isolated fixes.

| # | Task | File(s) touched | What it does |
|---|---|---|---|
| O3 | Runtime throws on unregistered actionType | `backend/templates/runtime/workflows/engine.ts:1020-1040` | Was silently skipping (LLM `set_variable` no-ops shipped as `completed`). Now throws; `FORGE_RUNTIME_STRICT=false` restores old behavior. |
| G4 | Commerce injection gated by plan flag | `backend/services/runtime_injector.py:569` (helper) + `:691` (gate) | `forge_cart` schema + `/api/cart` routes only copied when plan has an entity with `commerce: true` (already set by `services/commerce_flag.py`). |
| G5 | CRUD scaffold skips auth entities | `backend/services/crud_page_coverage.py:19-40` (helper) + `:130` (call) | Detects users/user table or `password*` columns; skips synthesizing `/users/new` + `/users/[id]/edit`. |
| O2 | Catch-all router consults registry | `backend/templates/standalone-app/src/app/[...slug]/page.tsx` | Now reads `schemas` from `@/schemas/registry` first, fs.access as backup. Fixes registry-declared routes with unusual file paths. |
| O1 | Auto-sync integrations to org projects | `backend/routers/platform_integrations.py:191-260` | On PUT/clear, iterates every project in the org with an `output_dir` and rewrites `.env.local`. No more manual sync click. |
| O11 | Fk-labels env opt-out | `backend/templates/runtime/data-engine.ts:45-50` | `FORGE_FK_LABELS=false` skips `<fkProp>Label` bloat. |
| O13 | Dev-warn on `bind` misuse | `packages/renderer/src/runtime/dispatch.tsx:132-152` | Console.warn (once per type:bind) when `bind` is set on a non-iterator. |

**Smoke-tested:** commerce vocab classification, auth-entity detection,
commerce helper import path.

**Not yet done for Phase 1** (deferred to later phases or explicitly out of
scope):
- Fresh live regeneration to prove the fixes fire end-to-end. Belongs in
  Phase 5's verify-loop harness.
- Renderer dist rebuild + revendoring (the `dispatch.tsx` edit lives in the
  package source; existing generated apps won't see the warning until
  `pnpm --filter @forge/renderer build` runs and generated apps are re-vendored).

---

## Phase 0 landing spots (commit `a505d9bd`)

Two pure-Python modules + 25 tests. Not wired to pipeline yet.

- `backend/services/locked_spec.py` — extract actors/entities/features/
  externals from a prompt via curated-vocab heuristics. Event nouns
  (Scan) survive verb-form disambiguation. `build_locked_spec(prompt)`
  returns `LockedSpec`; `persist_locked_spec(spec, output_dir)` writes
  `contracts/locked_spec.json`; `load_locked_spec(output_dir)` reads back.
- `backend/services/scope_card.py` — deterministic manifest derivation
  from the spec. `build_manifest(spec)` returns `Manifest`;
  `build_and_persist_from_spec(output_dir)` composes read-derive-write.
  Rules: entity → full CRUD, event → list+detail only, role/external
  → nothing, derived → list only. Custom features get `/verb` pages.
- 25 tests in `backend/tests/services/test_locked_spec.py` +
  `test_scope_card.py`. Pin the visual-product-search prompt to ~14
  pages max, no /scans/new, no /users/*, no /firecrawls, no /admins.

**Not done for Phase 0** (deferred to fresh session):
- 0.3 archetype library (`backend/services/archetypes/` package +
  `archetype_detector.py`)
- 0.4 pipeline wire-in behind `FORGE_LOCKED_SPEC=true` flag

---

## Phase 2 landing spots (commit `91ad337e`)

One pure-Python module + 12 tests. Not wired to pipeline yet.

- `backend/services/workflow_validator.py` — sweeps
  `<output_dir>/workflows/*.json` and flags:
  - `undefined-ref` (error): `{{root.x}}` where `root` isn't a declared
    node id / trigger / input / event / context / process variable.
  - `sql-literal-in-value` (error): "CURRENT_TIMESTAMP", "NOW()" etc
    as value strings — runtime doesn't substitute these.
  - `event-status-not-written` (warning): a workflow writes to an
    event entity's table but never sets .status — event rows stay
    stuck on default forever (nni3wjf6 symptom).
- Signatures: `validate_workflow(wf, filename, spec=None) -> [Finding]`
  and `validate_output_dir(output_dir) -> [Finding]` (loads LockedSpec
  automatically if present).
- `persist_report(findings, output_dir)` writes
  `contracts/workflow_validation.json`.

**Not done for Phase 2** (deferred):
- 2.1 Planner recipe(s) reading locked spec (needs planner-recipe seam
  exploration in a fresh session).
- 2.2 Rules-engine gate against fabricated fields.

---

## Phase 3 landing spots (commit `91ad337e`)

One pure-Python module + 11 tests. Not wired to pipeline yet.

- `backend/services/contract_validator.py` — sweeps
  `<output_dir>/src/schemas/**/*.json` and flags:
  - `route-not-in-manifest` (error): page's `route` isn't declared in
    the manifest. Kills the 27-phantom-pages class.
  - `orphan-navigate` (error): Button navigate target isn't in
    manifest. Dynamic route segments (uuids, ints) auto-normalize to
    `[id]` for lookup so `/scans/<uuid>` finds `/scans/[id]`.
  - `orphan-workflow` (warning): Button workflow name isn't in
    manifest. Runtime primitives (Login/Register/Logout/Checkout) are
    always allowed.
  - `orphan-binding` (warning): `{{root.x}}` where `root` isn't a
    dataSource on the page, a Repeat's `as` scope, or a well-known
    scope (user/item/row/scope/index/i).

---

## Phase 5 landing spots (commit `91ad337e`)

One pure-Python module + 11 tests. Not wired to pipeline yet.

- `backend/services/proof_pass.py` — post-generation aggregator.
  `run_proof_pass(output_dir)` returns a `ProofReport` with:
  - Every finding from `workflow_validator` and `contract_validator`.
  - Plus four page-quality checks: `empty-page` (chrome-only),
    `list-without-repeat`, `repeat-without-source` (error),
    `duplicate-route` (error).
  - `passed: bool = (error_count == 0)`, plus counts.
- `persist_report(report, output_dir)` writes
  `contracts/proof_report.json`.

**Not done for Phase 5** (deferred):
- 5.2 Verify loop wired to Playwright + Smith fix cycle. Reuses
  SV-1..SV-10 infra; needs pipeline exploration.

---

## Phase 0 — Locked Spec + Scope Card + Archetype Library (~8h)

**Why first (after Phase 1):** everything else reads the locked spec. Without
this layer, the recipe hardening in Phase 2 has nothing authoritative to read.

### Deliverables

**0.1 `backend/services/locked_spec.py`** — new module.

Types (dataclass or pydantic):
```
Actor        = { role: str, permissions_hint: list[str] }
EntityKind   = Literal["entity", "role", "event", "external", "derived"]
Entity       = { name: str, kind: EntityKind, cardinality: Literal["one","many"] }
Feature      = { name: str, actor: str, verb: str, target_entity: str|None }
ExternalDep  = { type: Literal["mcp","api","webhook"], provider: str }
LockedSpec   = { actors: [Actor], entities: [Entity], features: [Feature], externals: [ExternalDep] }
```

Functions:
- `extract_entities(prompt: str) -> list[Entity]` — LLM call with STRICT
  enum output. Prompt: "Extract nouns and classify each as entity/role/event/external/derived." Return raw list, dedup case-insensitively.
- `extract_actors(prompt: str) -> list[Actor]` — LLM call. Prompt: "Extract user roles/personas mentioned." Return unique.
- `extract_features(prompt: str, entities, actors) -> list[Feature]` —
  LLM call biased by entities+actors context. Prompt: "Extract each user
  action; map to actor and target entity if any."
- `extract_externals(prompt: str) -> list[ExternalDep]` — LLM. Look for
  MCP/API mentions, closed provider list.
- `build_locked_spec(prompt: str, archetype_hint: str|None) -> LockedSpec` —
  orchestrates the 4 extractors, dedups, returns.

Tests (`backend/tests/services/test_locked_spec.py`):
- Given the exact visual-product-search prompt, extract must return:
  entities=[Scan(event), PriceResult(event), Retailer(entity), User(role)],
  actors=[user, admin], features=[scan, upload, view-history, view-comparison, admin-manage-retailers], externals=[Firecrawl MCP].
- Given a simple TODO prompt, entities=[Task(entity)], actors=[user], features=[add, complete, delete].

**0.2 `backend/services/scope_card.py`** — new module.

Derives from locked spec → **PageManifest**:
```
Page   = { path: str, kind: Literal["list","detail","create","edit","custom"], entity: str|None, feature: str|None, actor: str|None }
Manifest = { pages: [Page], entities_with_tables: [str], workflows: [str] }
```

Rules:
- Each `kind==entity` gets: list + detail + create + edit
- Each `kind==event` gets: list + detail ONLY (no create/edit)
- Each `kind==role` / `kind==derived` gets: no pages (no table either)
- Each `kind==external` gets: no pages (no table)
- Each feature that doesn't map to an entity CRUD → custom page
- Auth features (login, register) → 2 pages always if any actor exists

Return the manifest as JSON. Persist to `contracts/manifest.json`.

Tests: given the visual-product-search locked spec, manifest must produce
exactly the 6 pages expected (see conversation).

**0.3 Scope card UI (`frontend/`)** — user confirmation gate.

Not required for pipeline correctness — plan can proceed without it initially.
For the MVP: emit `scope_card_pending` SSE event with the manifest before
generation runs, wait for `scope_card_confirmed` or `scope_card_edited`
event. If auto-accept env (`FORGE_SKIP_SCOPE_CARD=true`) is set, proceed
without waiting.

Wire the wait point in `backend/routers/generate.py` `_run_relay_pipeline`
right after locked-spec extraction, before any downstream agent runs.

**0.4 `backend/services/archetypes/`** — new package.

One file per archetype:
- `visual_product_search.py`
- `hr_recruitment.py`
- `booking.py`
- `crm.py`
- `helpdesk.py`
- `dashboard_only.py`

Each exports:
```
NAME = "visual-product-search"
KEYWORDS = ["scan", "product", "image", "camera", "price", "comparison"]
DEFAULT_ENTITIES = [...]   # sensible list this archetype tends to need
DEFAULT_WORKFLOWS = [...]
DEFAULT_COMPONENTS = ["Camera", "FileUpload", "ProductCard", "Table"]
ANTI_ENTITIES = ["cart", "checkout"]   # things NOT to include
```

`backend/services/archetype_detector.py` — new module.
- `detect_archetype(prompt: str) -> str|None` — LLM classifier over the
  known archetypes; returns name or None if freeform.
- Injected into locked-spec extraction as hint (biases entity/feature
  extractors).

Wire into `_run_relay_pipeline` right before locked-spec extraction.

### Acceptance for Phase 0

- `pytest backend/tests/services/test_locked_spec.py` passes with the
  visual-product-search fixture producing exactly the expected spec.
- `pytest backend/tests/services/test_scope_card.py` passes: given the spec,
  manifest = 6 pages, 3 entities-with-tables, 1 workflow.
- `_run_relay_pipeline` writes `contracts/locked_spec.json` +
  `contracts/manifest.json` before any downstream agent runs.

### Kickoff prompt for Phase 0's fresh session

```
Read docs/superpowers/plans/2026-08-04-generation-pipeline-remediation.md
in full. Then implement Phase 0 as spec'd there. Ship as 3-4 focused
commits: (0.1) locked_spec module + tests, (0.2) scope_card module + tests,
(0.3) archetype library skeleton with visual-product-search filled in
(others as stubs), (0.4) wire into _run_relay_pipeline behind a
FORGE_LOCKED_SPEC=true flag (default false so existing pipeline unchanged).
```

---

## Phase 2 — Planner Recipes Read the Locked Spec (~4h)

**Depends on Phase 0.** Recipes stop re-deriving entities/features and just
read from `contracts/locked_spec.json`.

### Deliverables

**2.1 Planner recipe(s)** — refactor to read the locked spec:
- `backend/services/planner_recipes/visual_product_search.py` (create if
  doesn't exist by then) — reads locked_spec, emits plan.json's `entities`,
  `workflows`, `pages` deterministically where the spec pins them.
- The planner LLM call is now confined to page contents and workflow
  step logic — never structural decisions (which entities exist).

**2.2 Workflow-authoring correctness (Phase 2 items O4/O5/O6/O8/O9/O12):**

Modify `backend/services/workflow_generator.py` (or wherever the workflow
JSON is emitted) so:
- O8: visual-product-search recipe emits `actionType: "ai_extract"` for
  identify_product (not `set_variable`).
- O9: recipe emits a `db_query` node that looks up retailerId by name
  before save_price_result nodes.
- O12: recipe emits db_update writing status="completed" at terminal.
- O4/O5: post-planner validator flags `{{<undefined_ref>}}` in workflow
  values. Add to `backend/services/workflow_validator.py`.
- O6: same validator flags string literals like `"CURRENT_TIMESTAMP"`,
  `"NOW()"` — these should be a runtime sentinel like `"$now"`.

Runtime `_coerceValue` should recognize `$now` → `new Date()`.

**2.3 Rules-engine gate** — the rules that blocked scan inserts in nni3wjf6
were auto-generated from the LLM's plan. Add a validator that any rule
referencing a field must reference a field that actually exists in the
locked_spec entity. Reject the rule pre-commit if it's fabricated.

### Acceptance

- Regenerating visual-product-search produces a workflow JSON with real
  `ai_extract`, real retailerId lookup, real status write.
- `pytest backend/tests/services/test_workflow_validator.py` catches
  undefined-ref, CURRENT_TIMESTAMP, and fabricated-rule cases.

### Kickoff for Phase 2

```
Phase 1 (commit 7a9edd88) and Phase 0 (commit <TBD>) are landed.
Read docs/superpowers/plans/2026-08-04-generation-pipeline-remediation.md
sections "Phase 2" and "Origin" for context. Implement Phase 2.
```

---

## Phase 3 — Layer 3 Contract Validators (~0-4h, mostly absorbed)

**If Phase 0's spec-locking works well, Phase 3 is minimal — the contracts
are the spec.** But three surface-level guards worth keeping/hardening:

- **Component contract** (already exists as post-hoc guards; keep them but
  add a pre-flight registry check that rejects LLM output referencing
  unknown component types → retry once with the violation as context).
- **Binding contract** (Phase 2 covers workflow bindings; page bindings
  need the same treatment — validate every `{{x.y}}` walks to a real
  entity + column at plan time).
- **Action contract** (every button `navigate`/`workflow` must target
  something in the manifest — already partially covered by nav-target guard).

Reuse Phase 0's manifest as the authority for what's in-scope.

### Kickoff for Phase 3

```
Phases 0, 1, 2 landed. Check whether pending contract violations remain
after Phase 2 by regenerating a test app and reviewing the plan JSON
against the manifest. Only fill gaps that Phase 2 didn't cover.
```

---

## Phase 4 — Nice-to-Have (~2h)

**4.1 O10 Drizzle migration bug** — investigate why `doublePrecision`
becomes `integer` in generated migrations. Likely in
`backend/services/schema_builder.py` or in the drizzle-kit generation path.
Fix so the migration matches the schema.

**4.2 O7 Firecrawl per-retailer URL smarts** — visual-product-search
recipe currently sends a search URL (e.g. amazon.com/s?k=...) to
`firecrawl_extract`. Target's search page LLM extraction fails ~50% of
the time. Two-step: first `firecrawl_search` to find the product URL,
then `firecrawl_extract` on the product page. Update the recipe.

### Kickoff for Phase 4

```
Phases 0-3 landed. Implement Phase 4's two items.
```

---

## Phase 5 — Proof Pass + Verify Loop (~6h)

**5.1 Post-generation proof pass** — new module
`backend/services/proof_pass.py`. Run after `post_generate_fixes`. For each
generated page, assert:

- Every button's `navigate`/`workflow` target exists (in manifest / workflow files)
- Every `{{binding}}` resolves to a real column
- No page consists solely of Heading+Row (bare-container check exists —
  reuse it, escalate from warning to blocker)
- Every list has `isLoading` skeleton + empty-state
- Every list dataSource has a matching `bind` on a Repeat
- Every workflow output is consumed (or the workflow node output is unused)

Failures written to `contracts/proof_report.json` and streamed as SSE
`proof_result` events. Ship-blocker if any assertion fails at severity
`error`; warnings for severity `warn`.

Frontend: render the report in a chip on the project card ("3 proofs
failed — click to auto-repair or open editor").

**5.2 Verify loop** — reuse SV-1..SV-10 infrastructure (Playwright runner,
fault classifier, Smith wiring). Add a golden-path test per
`feature × actor` from the locked spec. Wire into pipeline so an app that
fails golden path gets one auto-fix attempt via Smith, then either
converges or ships with a red chip.

### Kickoff for Phase 5

```
Phases 0-4 landed. Implement Phase 5's proof pass first (deterministic,
faster ROI), then wire the verify loop on top.
```

---

## How to run each fresh session

1. Open a new Claude session at `/Users/m/Work/code/poc/design2ui-forge-v3`.
2. Paste this doc's path plus the phase-specific kickoff prompt.
3. Let Claude read the full doc first (it's the source of truth for
   architecture + Phase 1 landing spots).
4. Claude implements the phase, tests, and commits.
5. When done, Claude updates the phase's row in the inventory table at the
   top of this doc to `✅ done (commit <sha>)` and appends a short "Phase X
   landing spots" section like Phase 1's above.

## Common context every fresh session needs

- Backend: FastAPI on `:6500` (`backend/`).
- Frontend: Next.js on `:6501` (`frontend/`).
- Generated apps live in `output/<short_id>/`.
- Platform DB: Postgres on `:5432` (db `tentoroforge`).
- Generated app DBs: per-app Postgres on `:5439+` (varies).
- Test framework: `pytest` for backend, `vitest` for TS packages.
- Never commit `.env` files. Never bypass hooks.
- Template files (in `backend/templates/`) are copied into generated apps
  at gen time. Edits to template files land in newly-generated apps only;
  existing apps need re-vendoring.
- Fix at platform, never per-app (see user memory
  `feedback_bug_fixes_platform_only`).

## Key files this plan touches or creates

**Existing (touched in Phase 1):**
- `backend/templates/runtime/workflows/engine.ts` — strict actionType handler
- `backend/services/runtime_injector.py` — commerce gate helper
- `backend/services/crud_page_coverage.py` — auth-entity skip
- `backend/templates/standalone-app/src/app/[...slug]/page.tsx` — registry-first routing
- `backend/routers/platform_integrations.py` — auto-sync
- `backend/templates/runtime/data-engine.ts` — labels opt-out
- `packages/renderer/src/runtime/dispatch.tsx` — bind warn

**New (Phase 0):**
- `backend/services/locked_spec.py`
- `backend/services/scope_card.py`
- `backend/services/archetype_detector.py`
- `backend/services/archetypes/` (package with per-archetype modules)

**Modified (Phase 2):**
- `backend/services/planner_recipes/visual_product_search.py` (create if missing)
- `backend/services/workflow_generator.py`
- `backend/services/workflow_validator.py`

**Modified (Phase 5):**
- `backend/services/proof_pass.py` (new)
- Reuse `backend/services/verify/*` (SV-1..SV-10 infra)

## Known unknowns

- Whether existing planner code already writes `contracts/plan.json` at a
  known location — Phase 1's G4 helper assumes `contracts/plan.json` or
  `plan.json` at project root. Verify path when Phase 0 starts.
- Whether `services/planner_recipes/` exists as a package or planner recipes
  are inlined in `planner_agent.py`. Phase 2's kickoff needs to grep for
  where visual-product-search-specific logic lives today.
- Whether SV-1..SV-10 infrastructure is production-ready or still shadow
  mode. Phase 5's verify loop depends on it being at least callable.
