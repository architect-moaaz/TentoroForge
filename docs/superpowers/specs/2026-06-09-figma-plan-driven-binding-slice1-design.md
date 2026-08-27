# Figma Plan-Driven Binding — Slice 1 (Lists + Buttons)

**Date:** 2026-06-09
**Status:** Design approved, pre-implementation
**Branch:** forge-v3

## Problem

Figma-generated apps are visually faithful but **inert**: lists show static
designer-drawn rows instead of real database records, and buttons do nothing.
The deterministic runtime plumbing to make them live already exists and is
verified:

- `packages/renderer/src/runtime/dispatch.tsx:62` deep-interpolates every
  node's `props` against the active scope (so nested `args` resolve).
- `packages/renderer/src/nodes/data/Repeat.tsx` renders one child subtree per
  row with `data: { ...ctx.data, [as]: item }` in scope (default `as: "item"`).
- `packages/library/src/components/Button/Button.tsx` reads top-level
  `props.workflow` (string) + `props.args` (object) and dispatches through
  `WorkflowDispatcherContext` (the engine dispatcher wired in
  `packages/engine/src/Engine.tsx`).
- Page `dataSources[]` are fetched by the engine and exposed as `ctx.data`.

What is missing is **schema-level bindings**: `dataSources` on the page, `bind`
on the repeater, `{{item.field}}` in row cells, and `workflow`+`args` on
buttons. Today nothing produces them for the Figma path.

## Root cause (why "infer from schema" is the wrong frame)

Binding intent belongs in the **plan**, not reverse-engineered from a rendered
schema. The LLM-path planner (`backend/agents/planner.py`) already emits it:

- `plan.pages[].entity` — each screen's focal entity.
- `plan.api_strategy[Entity].workflow_actions[]` —
  `{action, workflow, trigger:"button:Approve", ui_location, visible_when, on_success}`.
- `plan.api_strategy[Entity].crud.create.triggers_workflow` — form → workflow.

The **Figma-path plan** (`backend/services/figma_plan_builder.build_plan_from_figma`)
is scope-only: pages carry `route`/`name`/`figma_node_id`/`type` but
`entity: None`, no `data_models`, no `workflows`, no `api_strategy`. So the
Figma plan never declared the bindings the LLM plan does.

## Architecture: plan-driven binding (3 layers)

1. **Layer A — Plan binding intent.** Make the Figma plan carry the same
   structured, machine-readable binding fields the LLM planner emits. Surfaced
   at plan-approval so the user can review/correct before the build. Source of
   truth = the approved plan.
2. **Layer B — Deterministic applier.** A pure-Python pass that maps declared
   plan intent onto generated page schemas (the `what` comes from the plan, the
   `where` from the schema structure).
3. **Layer C — LLM fallback.** For nodes the plan didn't pin / that are
   ambiguous, a targeted LLM call resolves only the residue. Low confidence →
   leave unbound + report.

This unifies both pipelines on one principle. **Slice 1 builds A + B for the
Figma path, lists + buttons only.** C and the other coverage areas are later
slices (see Out of Scope).

## Slice 1 scope

In:
- Figma path only.
- List/table data binding (show real rows).
- Row-action and page-action buttons → workflows.

Out (later slices):
- Forms (create/update submit wiring) — slice 2.
- Detail views (`op:"get"`) + stat/metric aggregates — slice 3.
- Layer C LLM fallback for leftovers — slice 4.
- LLM-path unification (point Layer B at the already-present LLM plan intent) —
  folds in once B is proven.

## Layer A — Figma plan binding enrichment

Extend the Figma DESIGN_ANALYSIS so the emitted plan adds (field names aligned
with the LLM planner so Layer B is path-agnostic):

- Top-level `data_models[]` — entities the screens imply (name + fields with
  types). These flow into the registry so the schema agent builds matching
  tables, and Layer B uses their field names for `{{item.field}}`.
- Top-level `workflows[]` — workflows the screen actions imply (name + brief
  description). Names must be stable; Layer B references them.
- Per page:
  - `entity: string | null` — the primary entity the screen lists/shows.
  - `actions[]` — `{ label: string, workflow: string, kind: "row_action" | "page_action" }`.

Derivation: the analysis LLM step reads the Figma frames (frame names, visible
text/labels, detected button-like nodes) plus any domain discovery and proposes
the above. Output is structured JSON fields (not prose).

Boundary: Layer A only adds fields to the plan dict. It does not touch schema
files. If the analysis cannot propose an entity for a page, `entity` is `null`
and the page is left unbound by Layer B.

## Layer B — Deterministic binding applier

New module `backend/services/schema_binding.py`. Runs as a pipeline phase after
the schema refiner, iterating the generated page schemas. Inputs per page:
the plan page intent, `plan.data_models`, `plan.workflows`, and the page schema.

**Plan↔schema correlation:** each generated page schema carries `route` (and a
slugified `id`) copied from `plan.pages[].route`; Layer B joins a schema file to
its plan page on `route` (falling back to slugified `id`/filename). A schema
with no matching plan page is skipped (left unbound).

Units (each independently testable):

1. `detect_repeater(node) -> RepeaterMatch | None`
   Group a container's children by **structural signature** (node `type` +
   recursive child-type fingerprint, depth-bounded). The largest group of ≥2
   sibling subtrees with identical signature is the list. Returns the matched
   sibling group + their common parent. No confident group → `None`.

2. `map_cells_to_fields(template_row, entity_fields) -> dict[nodeId, field]`
   Within one template row, map text/value-bearing nodes to entity fields:
   header-row text match first, else positional order against declared field
   order. Unmapped cells are left as static text.

3. `apply_list_binding(schema, page_intent, entity_def) -> schema`
   Using 1 + 2: collapse the matched group to a single template row, ensure it
   is a `Repeat` (or set `bind` on a `Table`), append
   `dataSources += [{ name, entity, op: "list" }]`, set `bind: name` on the
   repeater, and rewrite mapped cell props to `{{item.<field>}}`.

4. `apply_button_bindings(schema, page_intent) -> schema`
   - Row-action buttons (inside the template row) matching a `row_action`
     label get `workflow` + `args: { id: "{{item.id}}" }`.
   - Page-action buttons (top-level) matching a `page_action` label get
     `workflow` (+ args from the page entity where applicable).
   Matching is by normalized label equality against `actions[].label`.

5. `apply_bindings(schema, page_intent, plan) -> (schema, BindingReport)`
   Orchestrates 1–4, returns the new schema + a per-page report.

## Safety, output, validation

- **Never guess blindly.** No confident repeater → leave the page's list
  unbound. A button matching no plan action → left inert. A faithful-but-inert
  node is always preferred over a wrong binding.
- **Report.** Emit `binding-report.json` at the output root:
  `{ route, bound: [...], unbound: [{ nodeId, kind, reason }] }` per page, so
  results are inspectable.
- **Idempotent.** Skip nodes that already carry `bind` / `workflow` (so re-runs
  and LLM-path schemas that already have bindings are untouched).
- **Validate-or-fallback.** After applying bindings, re-validate the page schema
  against the Zod page schema. `dataSources`, `bind`, `workflow`, and `args` are
  valid v2 fields and bridge nodes accept arbitrary props, so success is
  expected; on any validation failure, revert that page to its pre-binding
  schema (mirrors the refiner's validate-or-fallback).

## Pipeline placement

Run Layer B as a dedicated phase in `_run_figma_relay_pipeline`
(`backend/routers/generate.py`) **after the schema refiner block** (≈ line
1802). It consumes the plan (entities/workflows/actions) + the generated page
schemas already on disk. It does not depend on registry extraction because the
plan is the source of truth for entity field names and workflow names; both the
schema agent and Layer B derive from `plan.data_models` / `plan.workflows`, so
the interpolated field names match the generated columns.

Layer A changes live in the Figma DESIGN_ANALYSIS step that produces the plan
the user approves (before `_run_figma_relay_pipeline` build).

## Runtime changes

None. `dispatch.tsx` deep-interpolation, `Repeat` row scope, and Button
`workflow`/`args` are already present and verified.

## Testing

- `detect_repeater`: fixtures with N identical siblings (positive), mixed
  siblings (negative), nested lists, single-row (negative).
- `map_cells_to_fields`: header-match path, positional path, more-cells-than-
  fields, fewer-cells-than-fields.
- `apply_list_binding`: asserts `dataSources`, `bind`, collapsed-to-one-row,
  `{{item.field}}` rewrites; idempotency on re-run.
- `apply_button_bindings`: row_action → `args.id == "{{item.id}}"`,
  page_action → no item scope, unmatched button left inert.
- `apply_bindings`: end-to-end on a representative Cemex-like page fixture;
  validate-or-fallback on a deliberately invalid result; report contents.
- Layer A: given a synthetic Figma analysis input, asserts the plan gains
  `data_models`, `workflows`, per-page `entity` + `actions[]`.

## Success criteria

A regenerated Cemex (or comparable) Figma app where at least one list renders
real DB rows via `dataSources`/`bind`/`{{item.field}}`, and its row/page action
buttons dispatch the declared workflow with the correct row id — all driven by
binding intent visible in the approved plan, with a `binding-report.json`
enumerating what bound and what stayed unbound.
