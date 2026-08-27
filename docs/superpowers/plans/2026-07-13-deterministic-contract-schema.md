# Deterministic Contract + Schema (Lever A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Replace the two agentic LLM phases `contract` (Haiku, 20 turns) and `schema` (Haiku, 20 turns + LLM-driven `npm install`) with deterministic `plan → files` builders, keeping the LLM agents as fallbacks — cutting ~5 min off generation while making the planner's decisions expand faithfully (no drift/miscount).

**Architecture:** The planner remains the sole decider of app contents. These two phases only *expand* the plan into files, which is mechanical. We build `services/app_model_builder.py` + `services/schema_builder.py`, finish the already-existing `services/contract_generator.py`, and wire all three as **deterministic-primary with LLM fallback** — the exact pattern of `build_shell_deterministic` (SP4). Config files already ship via the `standalone-app`/`app-foundation` templates, so the schema builder only emits per-entity Drizzle tables + types.

**Tech Stack:** Python 3.11, FastAPI pipeline in `backend/routers/generate.py`, pytest from `backend/` via `/usr/local/bin/python3 -m pytest`.

**Key facts from investigation (2026-07-13):**
- `generate_contracts()` in `services/contract_generator.py` exists but was **never wired** (0 call sites in git history). It emits 4/7 contract files; missing `app-model.json` (the blocker), `design-system.tsx`, `services.ts`.
- `services.ts` is **obsolete** — only `contract_agent` references it; no consumer reads it (workflow-JSON replaced TS services). Do not emit it.
- `navigation-flow.json` is superseded by the authoritative `nav-flow.json` (`nav_flow_emitter`), but is still read by `flow_validator`/`verify_pipeline`/QA — keep emitting it (generator already does).
- `app-model.json` has two variants: **contract** (`src/contracts/app-model.json`, dependency graph + page manifest — what we build) and **root** (`app-model.json`, already built deterministically by `verify_pipeline._generate_app_model()` via filesystem scan, and it merges the contract one).
- The **only** strict programmatic reader of contract `app-model.json` is `services/phase_gates.py`, which reads `.pages` (list of `{route|path}` dicts, or a dict keyed by route) and checks each entity has a `/{slug}` list route. Six other consumers (`qa`, `explainer`, `refiner`, `scaffolder`, `code_editor`, `planner`) read it as LLM prose (shape-tolerant). The registry system is independent of it.
- Planner emits `data_models` (LIST), `relations`, `pages` (with `archetype`+`features`), `api_routes`, `workflows`, `user_journeys`, `api_strategy`, `domain`, `name`. `contract_generator` currently reads stale `plan.entities` in `_generate_event_bindings` + `_generate_seed_plan` — bug to fix.

**Contract `app-model.json` target shape** (from `contract_agent.py` spec):
```json
{
  "name": "App Name",
  "entities": {
    "Order": {
      "table": "orders", "schema": "src/db/schema/orders.ts", "type": "src/types/orders.ts",
      "api": ["src/app/api/orders/route.ts", "src/app/api/orders/[id]/route.ts"],
      "components": ["src/components/orders/OrderTable.tsx", "src/components/orders/OrderForm.tsx"],
      "pages": ["src/app/orders/page.tsx", "src/app/orders/[id]/page.tsx"],
      "depends_on": ["User"], "used_by": ["Invoice"]
    }
  },
  "pages": [{"route": "/orders", "component": "OrdersListPage", "description": "..."}, ...],
  "routes": [{"method": "GET", "path": "/api/orders", "description": "..."}, ...]
}
```
Field derivations: `table`←pluralize(name) (`contract_generator._to_table`); path fields←conventional templates from slug; `depends_on`/`used_by`←FK graph from `plan.relations`; `pages`←manifest of list/detail/create per entity + dashboard/login/signup/error, each with `route` = `/{slug}` etc.; `routes`←per-entity REST (mirror `_generate_api_client`).

---

### Task 0: Per-phase timing instrumentation (measure before/after)

**Files:**
- Modify: `backend/routers/generate.py` (the `_stream_phase` helper in both `_run_relay_pipeline` and `_run_figma_relay_pipeline`)

- [ ] **Step 1: Wrap `_stream_phase` with `time.perf_counter()`**, accumulate `{phase_name: elapsed_seconds}` into a dict on the pipeline, and emit a `sse_event("log", {"text": f"[Timing] {name}: {elapsed:.1f}s"})` when each phase ends. At pipeline end, write `output/<slug>/generation-timing.json` with the full map + total.
- [ ] **Step 2:** Run one baseline generation via the API (`POST` the generate endpoint with a small 2-entity prompt) and record `generation-timing.json` as the **BEFORE** baseline. Commit the baseline numbers in the commit message.
- [ ] **Step 3: Commit.** `feat(pipeline): per-phase timing instrumentation + baseline`

---

### Task A1: `app_model_builder.py` — deterministic contract app-model (TDD)

**Files:**
- Create: `backend/services/app_model_builder.py`
- Test: `backend/tests/test_app_model_builder.py`

- [ ] **Step 1: Write failing tests** covering: (a) each `data_model` becomes an `entities[Name]` with correct `table` (pluralized), `schema`/`type`/`api`/`pages`/`components` conventional paths; (b) `depends_on`/`used_by` derived from `plan.relations` FK graph (bidirectional); (c) `pages[]` includes list+detail+create per entity + dashboard/login/signup/error, each with a `route`; (d) `routes[]` has the 5 REST routes per entity; (e) empty/missing `relations` → empty dependency edges, no crash; (f) `plan.data_models` as list (canonical) AND legacy dict both accepted.
- [ ] **Step 2:** Run tests, verify they fail.
- [ ] **Step 3: Implement `build_app_model(plan: dict) -> dict`** reusing `contract_generator._to_table/_to_slug/_to_camel`. Pure function, no I/O. Add `write_app_model(output_dir, plan)` that writes `src/contracts/app-model.json`.
- [ ] **Step 4:** Run tests, verify pass. **Step 5: Commit.**

---

### Task A2: Fix staleness + finish `generate_contracts()`

**Files:**
- Modify: `backend/services/contract_generator.py`
- Test: `backend/tests/test_contract_generator.py`

- [ ] **Step 1: Failing test** that a plan with `data_models` (and NO `entities` key) still produces non-empty `event-bindings.json` bindings and a non-empty `seed-plan.json`. (Reproduces the `plan.entities` staleness bug.)
- [ ] **Step 2:** Change `_generate_event_bindings` + `_generate_seed_plan` + `ensure_approval_bindings` to read `plan.get("data_models") or plan.get("entities") or []`. Add a `_normalize_models` helper mirroring the planner's list/dict handling.
- [ ] **Step 3:** In `generate_contracts()`, add app-model emission via `app_model_builder.write_app_model(...)` (append `src/contracts/app-model.json` to `generated`). Do NOT emit `services.ts` (obsolete).
- [ ] **Step 4:** Run tests green. **Step 5: Commit.**

---

### Task A3: Wire contracts deterministic-primary + LLM fallback

**Files:**
- Modify: `backend/routers/generate.py` (Contract phase in BOTH `_run_relay_pipeline` ~line 299 and `_run_figma_relay_pipeline`)
- Modify: `backend/agents/contract_agent.py` (drop `services.ts` from prompt)

- [ ] **Step 1:** Before the `_stream_phase("Contract", ...)` call, run `generate_contracts(output_dir, plan)`. Log generated/errors.
- [ ] **Step 2:** Run the deterministic phase-gate check (reuse `phase_gates`) on the emitted contracts. If it PASSES (all files present, every entity has pages/api), **skip** the LLM `contract_agent` entirely. If it reports gaps, run the LLM `contract_agent` as a **fallback** to fill them (existing behavior). This mirrors `build_shell_deterministic` → LLM fallback.
- [ ] **Step 3:** Remove the `services.ts` generation instruction from `contract_agent.py`'s prompt (it's obsolete).
- [ ] **Step 4: Verify** on a saved plan fixture that the deterministic path produces contracts that pass `phase_gates` (so the LLM is skipped). **Step 5: Commit.**

---

### Task B1: `schema_builder.py` — deterministic Drizzle tables + types (TDD)

**Files:**
- Create: `backend/services/schema_builder.py`
- Test: `backend/tests/test_schema_builder.py`

- [ ] **Step 1: Failing tests**: (a) each `data_model` → `src/db/schema/<slug>.ts` with `pgTable("<table>", {...})`, correct column types mapped from field SQL types (reuse the field-type mapping already in `contract_generator._field_to_ts_type` / `semantic_field_types` conventions), PK `id serial primaryKey`, `createdAt/updatedAt timestamps`; (b) FK fields → `.references(() => other.id)` + a `relations()` block from `plan.relations`; (c) `src/db/schema/index.ts` barrel exports ALL tables; (d) `src/types/<slug>.ts` exports `type X = typeof x.$inferSelect` / `NewX = $inferInsert` + barrel; (e) enum columns honored if `enum_values` present.
- [ ] **Step 2:** Run, verify fail.
- [ ] **Step 3: Implement `build_schema_files(plan, output_dir)`** emitting only per-entity `src/db/schema/*.ts` + index and `src/types/*.ts` + index. Config files (package.json, next.config, tailwind, drizzle.config, `src/db/index.ts`, `src/lib/utils.ts`) come from the `standalone-app`/`app-foundation` templates — do NOT emit them here (verify they exist post-emitter; add any missing to the template, not the builder).
- [ ] **Step 4:** Run tests green. **Step 5: Commit.**

---

### Task B2: Deterministic `npm install` (off the LLM)

**Files:**
- Modify: `backend/routers/generate.py` (Schema phase)

- [ ] **Step 1:** After `build_schema_files` + `emit_standalone_app`, run `npm install` as a plain `asyncio.create_subprocess_exec` (with a timeout + logged output), NOT as an LLM turn. Investigate reusing a warm cache (pnpm store or a prebuilt template `node_modules`) to cut install time — if a shared `node_modules` for the fixed template deps is feasible, symlink/copy it and run `npm install` only for drift.
- [ ] **Step 2: Verify** deps resolve (`node_modules/next` exists) on a real emit. **Step 3: Commit.**

---

### Task B3: Wire schema deterministic-primary + LLM fallback

**Files:**
- Modify: `backend/routers/generate.py` (Schema phase, BOTH pipelines)

- [ ] **Step 1:** Before `_stream_phase("Schema", ...)`, run `build_schema_files(plan, output_dir)`. If every `data_model` produced a schema file + type file AND `npm install` succeeded, skip the LLM `schema_agent`. Otherwise run it as fallback.
- [ ] **Step 2: Verify** the deterministic path yields a schema that `drizzle-kit` / the existing `drizzle_check` guard accepts. **Step 3: Commit.**

---

### Task C1: End-to-end verification + measure the win

**Files:** none (verification task)

- [ ] **Step 1:** Run a full generation via the API on the same prompt as the Task 0 baseline. Confirm: deterministic contract + schema fire (LLM contract/schema skipped in logs), `phase_gates` passes, registry validator passes, the app builds and renders a page in the browser preview, and downstream LLM agents (component/page/qa) still consume the contracts without error.
- [ ] **Step 2:** Diff `generation-timing.json` vs the Task 0 baseline. Confirm ≥5 min saved (or report the actual delta). Record in the final commit.
- [ ] **Step 3: Final review** of the whole increment; then finish the branch.

---

## Risks / guardrails
- **Shape-compat:** the only hard contract is `phase_gates` reading `app-model.json.pages[].route`. Everything else is LLM-prose-tolerant or independent (registry). Keep `navigation-flow.json` (flow_validator still reads it).
- **Fallback keeps us safe:** every deterministic phase falls back to the existing LLM agent on incompleteness — a novel plan shape can't break generation.
- **Don't edit backend during a live generation** (uvicorn `--reload` is on; a save mid-gen restarts the server).
- **Figma pipeline:** the Contract + Schema phases run in `_run_figma_relay_pipeline` too — wire both.
