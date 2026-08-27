# Resource-Binding Contract — Spec

## Problem
Generated apps intermittently ship UI that references resources the backend doesn't have — a form posting to a mis-cased table, a button dispatching a workflow with an input the schema rejects, a list bound to a dataSource name nothing resolves. Root cause: the **LLM page agent authors UI wiring from inference**, unconstrained by the real registries and unvalidated before shipping. It's non-reproducible (a different set of breaks each generation). We've been patching with post-hoc *repair* guards; the cure is to author bindings **against the real registries** and **validate before emission**.

## Principle (agreed with user)
It need NOT be fully deterministic. The requirement is two things:
1. **Author against the exact resources** — the page/schema agent is handed the CLOSED set of real registered resources (entity slugs the data engine serves, workflow ids the workflow engine runs, real column names/types per entity) and must bind only to them.
2. **Validate against those resources before use** — a hard gate checks every UI binding against the registries and FAILS the build on any unresolved/typed-wrong reference (not the user's click).

LLM keeps the *judgment* (which workflow a button means, page composition, which fields to surface). The system guarantees the *exact reference*.

## The registries (already exist — this is the source of truth)
- **Data-engine entities/slugs:** the `pgTable("<name>")` names in `src/db/schema/*.ts` = the `/api/data/<slug>` slugs (data engine `registerEntity(name,…,{slug:name})`). Also `registry.json` entities.
- **Workflow ids + trigger types + input contract:** `output/<slug>/workflows/*.json` (id, `trigger.type`, and each `db_insert/db_update` `values` = the columns it writes, i.e. the inputs it needs + their column types from the schema).
- **Columns + types per entity:** `src/db/schema/*.ts` (name, drizzle type → uuid/int/varchar/…, notNull).
- **event-bindings.json / api-client.ts** for completeness.

## Target architecture (3 slices)

### Slice 1 (THIS ONE) — the hard validation gate
A build-time validator `services/binding_validator.py::validate_bindings(output_dir) -> {ok, errors[], warnings[]}` that runs AFTER `apply_post_generate_fixes` (so the repair guards fix what they can first) and checks every UI binding in `src/schemas/**/*.json` against the registries:
- **Form submit target** — a form whose submit dispatches a workflow: that workflow id must exist; a form that writes to a data resource: that slug must be a registered entity.
- **Button `workflow` ref** — must be a real workflow id; if the workflow is event-driven and the button lacks record context → error (already partly handled by `workflow_trigger_button_guard` — the validator confirms none slipped through).
- **List/widget/Select `optionsFrom.source` / dataSource `source`/`table`** — must resolve to a registered entity slug.
- **Binding key `{{name}}`** used by a Table's `rows`/`items` — must match a dataSource `name` on that page.
- **Workflow input ↔ column type** — for a form that dispatches a workflow, each mapped field's value type must be compatible with the target column type (a uuid FK Select feeds a uuid column; a free-text Input must NOT feed a uuid column — this is the `uuid:"M"` class).
Return a structured report. Reuse the resolution helpers already in `list_data_source_guard`, `workflow_table_guard`, `workflow_trigger_button_guard`, `schema_references`, `semantic_field_types` — do NOT reinvent canonicalization.
Wire into `routers/generate.py` at pipeline end (both pipelines), behind flag `FORGE_BINDING_GATE` (default: WARN-and-log every error as an SSE log line; when the flag is set to "strict", treat unresolved references as a generation failure). Emit a clear per-error summary so the user sees exactly which binding is broken and why.

### Slice 2 (later) — constrain the page agent to the registries
Inject the CLOSED resource set (entity slugs, workflow ids + their input columns, per-entity columns+types) into `agents/page_schema_agent.py` / the schema-frontend prompt, with an explicit instruction: bind forms/buttons/lists ONLY to these ids; for a form that triggers a workflow, map fields to that workflow's declared input columns by name+type. Reduces the mismatch RATE the gate has to catch.

### Slice 3 (later) — planner authors an explicit action contract
Extend the planner/`binding_contract` so each page's `actions` carry `{button → workflow_id, input_map: {field→column}, requires_record}` validated against real workflows; generators emit buttons strictly from it. Then the repair guards become redundant (the gate stays as the safety net).

## Slice 1 tests
- A page with a form dispatching a non-existent workflow → error.
- A Select `optionsFrom.source` not a registered entity → error.
- A Table `rows: {{foo}}` with no `foo` dataSource → error.
- A form field (plain Input) mapped to a uuid workflow-input column → error (the uuid:"M" class).
- An all-valid app → `ok: True`, no errors.
- Warn (not error) for a genuinely-static widget with no binding.

## Out of scope for Slice 1
Slices 2 & 3 (LLM constraint + planner action contract). Do NOT modify the page agent or planner in Slice 1 — just the validator + its wiring.
