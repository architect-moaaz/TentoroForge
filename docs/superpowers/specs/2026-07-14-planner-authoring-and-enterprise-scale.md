# Planner-Authored Forms & Dashboards + Enterprise-Scale Generation — Spec

## The unifying idea
The canonical registry is the single substrate. The planner emits **only the judgment the registry cannot derive**, in a *structured* contract that deterministic builders consume as the top-priority source; each unit is built/authored against a **bounded registry slice**; the strict gate validates. This makes generation both **correct at the source** (Half 1) and **scalable to enterprise size** (Half 2) — and the two reinforce: a smaller, judgment-only planner output is both more correct (determinism handles structure) and fits smaller contexts.

Grounded findings this rests on:
- Planner emits pages as **prose**; deterministic builders (`deterministic_pages`, `semantic_field_types`, `form_scaffold`) ignore the prose and re-derive fields from the registry (`deterministic_pages.py:230-273,220-227`).
- Action `input_map` is column→column; the button's **target value** (`status="Cancelled"`) is nowhere in the plan — it's scraped from generated workflow node labels (`semantic_field_types.harvest_workflow_statuses:150-237`). This is the equipment-availability class.
- **No deterministic dashboard builder** — dashboards are always LLM-authored (`deterministic_pages.build_crud_page:445` returns None → `schema_pipeline.py:332`).
- Pages are already authored in **isolated, parallel** contexts (`schema_pipeline.py:318-360`), but each page prompt injects **whole-app** context (`resource_registry_context.build_resource_context:195-288`) → O(pages × app-size), the primary scale bottleneck. Three parallel context readers (plan dict, raw `.ts`, registry JSON) — divergence risk.
- No app-map/module decomposition; the whole plan is one LLM pass. Registry is per-entity-keyed and cheaply **sliceable** but currently a *secondary* source.

---

## Half 1 — Planner authors forms & dashboards correctly (prevention at the source)

**Principle:** planner supplies *judgment*; registry supplies *structural truth*; deterministic layer *backstops omissions*; gate *rejects* unresolved intent. The planner contract is intentionally MINIMAL — it does NOT re-specify what determinism already knows (control from SQL type, required from notNull, FK→Select). It emits only what the registry cannot know.

### A1 — Structured form-field intent (only the judgment bits)
Planner emits, per form, an optional `fieldSpecs` keyed by column — carrying ONLY:
- `semanticType` when non-obvious: `currency | percent | email | phone | url | multiline | code` (drives control + formatting; `currency` → plain number + `$`, no stepper). Omit when the registry type/name already implies it.
- `enumValues` for status/type/category columns (closes the enum-truth gap at the SOURCE instead of scraping workflows; also lets the schema emit a real `pgEnum`).
- `interaction`: computed formula / dependsOn / onChange (item 5 S2 — the planner declares `total = qty * rate`, `product dependsOn category`).
- `required` only to OVERRIDE the registry (rare) — registry `notNull` (post schema-reconcile) is the default truth.
Consumed as the **highest-priority source** in `deterministic_pages._input_for:230`, `semantic_field_types._decide:402`, and the enum union `:499-517` (the seam that currently scrapes workflows). Registry backstops every omission; gate validates each `semanticType`/`enum`/formula-var resolves.

### A2 — Action target values (the equipment-availability fix)
Extend planner `actions[]` from `{workflow, input_map}` to also carry `setValues: {column: literal}` — the concrete state a button sets (`{status:"Approved"}`, `{status:"Picked Up", pickedUpAt:"now"}`). The workflow generator writes these literals directly (no `{{self}}` self-refs, no label-scraping). `workflow_mutation_guard` demotes to a *pure safety net* — fires only when the planner omitted a value, and the strict gate **fails** a state-transition button whose target value is neither planner-supplied nor derivable. Only judgment knows "Approved" — so the planner MUST author it.

### A3 — Structured dashboard widgets + a deterministic dashboard builder
Planner emits, per dashboard page, `widgets[]`: `{type: stat|chart|table, entity, metric|groupBy|filter, title}` bound to real entities. A NEW `deterministic_pages.build_dashboard_page(widgets, registry)` renders them from the registry (aggregate/series/list dataSources) — replacing the always-LLM path at `build_crud_page:445`. LLM dashboards become the *fallback* for genuinely bespoke layouts, not the default. Kills the "dashboard guesses its own data" class.

### A4 — Gate
Extend the strict binding gate: every `semanticType`/`enumValues`/`setValues`/`widget` references a real registry column/entity; a state-transition action with no resolvable target value → error. Prevention, not repair.

---

## Half 2 — Enterprise scale with small context windows (registry-backed bounded contexts)

**Principle:** never hold the whole app in one context — only the *map* (tiny) and one *unit's slice* at a time. The registry is the shared key-space that makes independently-authored units consistent by construction.

### B1 — Bound per-page context to a registry slice (highest leverage, lowest risk)
Replace the whole-app `build_resource_context` injected per page with a **per-page slice**: focal entity + its FK-neighbor entities + ONLY the workflows its own interactions reference + its relationships. Source it from the canonical registry (already per-entity-keyed and sliceable) — making the registry the **single** context substrate and retiring the three-reader divergence (plan dict / raw `.ts` / registry). Kills the O(pages × app-size) bottleneck; each page prompt becomes O(focal-neighborhood), flat in app size. Page isolation + parallelism already exist (`schema_pipeline.py:318-360`).

### B2 — App-map (skeleton) planning stage for very large apps
Split planning into two passes:
1. **App-map pass** — emits only the skeleton: modules → entities (names + fields-summary) → pages (route + archetype + entity + the A1/A3 judgment stubs) → workflows (id + trigger + target entity + A2 setValues) → roles. Small, bounded, fits any context. Hooks in where `ensure_entity_reachability:44` already guarantees the page set.
2. **Per-unit detail pass** — each page/form/dashboard/workflow authored in its own bounded context (B1 slice). Deterministic units (CRUD, dashboards from A3 widgets) spend **zero** LLM. Consistency is free because every unit reads the one registry.
This removes the "whole plan in one LLM response" ceiling (`planner.py:1149-1163`) — the same chunking already applied to pages, applied to the plan itself.

### B3 — Shard the whole-app post-passes
`apply_semantic_field_types` / `form_scaffold` / `build_canonical_registry` are whole-app single-pass steps. Make them operate per-entity/per-page from the registry so an N-entity app is N bounded operations, not one O(N) sweep. (Lower priority — not a context-window limit, but a scale-cleanliness win.)

---

## Sequencing & why
- **B1 first** (bound per-page context to a registry slice) — biggest scale win, lowest risk, and it makes the registry the single substrate that A1–A4 also read. Foundational.
- **A2 + A4** (action target values + gate) — closes the highest-value correctness gap (dead/destructive buttons) at the source; makes `workflow_mutation_guard` a pure net.
- **A1 + A3** (field-intent + dashboard widgets/builder) — the bulk of "forms & dashboards authored correctly."
- **B2** (app-map decomposition) — only needed once apps exceed a single planning context; build after the above prove out on medium apps.

## Non-negotiables (from the prevention principle)
- Every planner-authored field is *validated* against the registry; the gate FAILS on unresolved intent (no silent repair).
- Deterministic layer + registry remain the source of *structural* truth; the planner adds *judgment* only.
- Guards (`workflow_mutation_guard`, `semantic_field_types` scraping, `harvest_workflow_statuses`) become safety nets that should ideally fire zero times once the planner authors the intent — a guard that keeps firing is a planner/generator bug to fix at the source.

## Scope decisions (locked with user, 2026-07-14)
1. **FULL per-field spec** — the planner authors a complete form/dashboard spec (every field's control, label, order, required, plus the judgment bits: semanticType/enum/setValues/interaction), rendered verbatim by the generators.
2. **B1 + B2 together** — per-page registry-slice context AND the app-map skeleton→per-unit decomposition, in one effort. True enterprise scale.

### How the two compose (the key architectural resolution)
The full per-field spec is authored **per unit, inside the decomposed flow** — not as one giant plan. In the B2 app-map→per-unit pipeline, each page's complete field/widget spec is written in its OWN bounded context (the B1 registry slice for that page's entity), and validated against that slice. So "full spec" does NOT reintroduce the scale problem (each unit's spec is bounded) nor unvalidated trust (the gate rejects any field referencing a non-real column / incompatible control / unresolved setValue). The registry remains the guarantor: the planner is the primary author, the registry + gate are the guarantee. Deterministic builders fill any field the planner omits (registry defaults) so a partial spec still yields a complete form.

### Build order (foundation-first; each phase independently green)
1. **B1** — registry slice reader + bound per-page context (the substrate everything else authors against). LOW risk, highest leverage.
2. **A2** — planner action `setValues` + workflow generator consumes literals + gate fails un-resolvable transitions (`workflow_mutation_guard` → pure net).
3. **A1** — full per-field form spec in the planner contract + deterministic builder renders it verbatim (registry backstop) + gate.
4. **A3** — dashboard `widgets[]` + new deterministic dashboard builder + gate.
5. **B2** — app-map skeleton pass + per-unit detail pass (the structural planner change; per-unit authoring uses B1 slices and emits A1/A2/A3 specs).
6. **A4** — gate extensions folded in as A1–A3 land.
This is a large multi-phase build (core planner + generation restructure). Live E2E verification is auth-gated (user-triggered); phases are unit-tested and artifact-verified between.
