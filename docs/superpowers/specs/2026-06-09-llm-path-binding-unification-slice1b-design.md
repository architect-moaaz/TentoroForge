# LLM-Path Binding Unification — Slice 1b

**Date:** 2026-06-09
**Status:** Design approved, pre-implementation
**Branch:** forge-v3
**Builds on:** Slice 1 (`2026-06-09-figma-plan-driven-binding-slice1-design.md`)

## Problem

The deterministic binding pass (`backend/services/schema_binding.py`) currently
runs only in the Figma pipeline (`_run_figma_relay_pipeline`). Prompt/LLM apps
(`_run_relay_pipeline`) never call it. LLM page schemas already carry **data**
binding (the page agent emits `dataSources` + `Repeat`/`bind` + `{{item.field}}`),
but their buttons carry only `label`/`navigate` — **no `workflow`/`args`**. So
clicking a prompt-app action button does nothing.

Two facts shape the fix:

1. **The intent isn't in the plan today.** `run_planner_oneshot` (the primary
   headless path) does not emit `api_strategy`/`workflow_actions`; that's only
   example prose in the planner prompt. So there is no declared button→workflow
   intent to apply on most prompt apps.
2. **The Slice-1 idempotency guard is all-or-nothing.** `apply_bindings` skips a
   whole page if it has any `dataSources`/`Repeat` — which every LLM page has —
   so it would no-op even where buttons need wiring.

## Decision

**Bindings come from planning** (consistent with Slice 1). The planner declares
per-page button→workflow intent in a machine-readable shape; a deterministic
adapter applies it via the existing binding pass, now reachable from the LLM
pipeline with per-concern idempotency.

## Architecture (4 parts)

### A. Planner declares per-page `actions[]`

Make `run_planner_oneshot` emit, for each page, an `actions[]` array using the
**same shape Layer A produces for Figma** so the plan is unified across paths:

```
"pages": [
  { "route": "/leave-requests", "type": "list", "entity": "LeaveRequest",
    "actions": [
      { "label": "Approve", "workflow": "LeaveApprovalWorkflow", "kind": "row_action" },
      { "label": "Reject",  "workflow": "LeaveApprovalWorkflow", "kind": "row_action" }
    ] }
]
```

- `label` — the exact button text the page will render.
- `workflow` — a workflow name the planner also declares in top-level `workflows[]`.
- `kind` — `row_action` (button repeated per list row → acts on that row) or
  `page_action` (a page-level / detail button).

This is a prompt-contract change to the planner: add `actions[]` to the page
output schema + instruct the model to populate it from the workflows it defines
and only with `kind ∈ {row_action, page_action}`. Pages with no actions get `[]`.

### B. LLM-plan → page_intent adapter

New `backend/services/llm_plan_binding_adapter.py`:

```
build_page_intent(page: dict, plan: dict) -> dict
  # returns {file, entity, actions:[{label, workflow, kind}]}
```

- `entity` = `page.get("entity")`.
- `file` = `page.get("file")` (or derived `src/schemas/<slug>.json`).
- `actions` = validated `page["actions"]` when present; else derived from
  `plan["api_strategy"][entity]["workflow_actions"]` if that exists
  (`trigger:"button:X"` → `label:"X"`; `ui_location:"list_page"` → `row_action`,
  else `page_action`). Drops actions whose `workflow` isn't in `plan["workflows"]`
  and whose `kind` isn't in the allowed set. Returns `actions: []` when neither
  source is present (graceful no-op).

The adapter is the path-specific glue; the binding primitives stay shared.

### C. Per-concern idempotency in `apply_bindings`

Replace the all-or-nothing `already_bound` short-circuit with independent gates
so button wiring runs even when data binding already exists:

- **List binding** is skipped when the page already has `dataSources` **or** any
  `Repeat` node (i.e., the data layer is already wired — Figma re-runs and LLM
  schemas alike). Implemented inside the list path; `apply_list_binding` returns
  a "skipped" info.
- **Button binding** is independently idempotent **per button**:
  `apply_button_bindings` already skips a button that has `props.workflow` and
  wires the rest. It also already walks both the `children` (array) and `root`
  (object) schema shapes.

`apply_bindings` therefore always attempts both, each self-gating. The report
gains `list_skipped: bool` alongside `list_bound`/`buttons_bound`. Slice-1 Figma
behavior is preserved: a fully-unbound Figma page still binds list + buttons; a
re-run binds nothing new.

### D. Hook in the LLM pipeline

Run the pass per page in the LLM schema pipeline, after each page schema is
written and before app emit. Hook in `backend/services/schema_pipeline.py`
(where `run_page_schema_agent` writes each schema, ~line 131) or as a dedicated
loop in `_run_relay_pipeline` after `run_schema_frontend_pipeline`. For each
page: load schema → `build_page_intent(page, plan)` → `apply_bindings` →
write back. Aggregate a `binding-report.json` at the output root (same as Figma).
Wrapped so a failure only logs, never aborts generation.

## Out of scope (later)

- Detail-page action arg sourcing (a `detail_page` button should target the
  record's id, e.g. from the route param / `op:"get"` source, not `{{item.id}}`).
  Slice 1b emits `row_action` → `args:{id:"{{item.id}}"}` and `page_action` →
  `workflow` only (no args); detail-record arg binding is a follow-up.
- `visible_when` conditional button visibility.
- Forms (create/update submit) wiring.

## Testing

- Adapter: page with `actions[]` → passthrough (validated, bad workflows
  dropped); page with only `api_strategy` → derived correctly
  (`button:X`→label, ui_location→kind); neither present → `actions: []`;
  unknown-workflow action dropped.
- Guard refactor: an LLM-like schema (has `dataSources` + `Repeat`, button
  without workflow) → list stays as-is (`list_skipped`), the matching button
  gets `workflow` (+ `args:{id:"{{item.id}}"}` for row_action); re-run is a no-op.
  Existing Slice-1 Figma tests still pass (full-unbound page still binds both).
- Planner (Part A): given a deterministic/mocked planner output, assert each
  page carries a validated `actions[]` (shape + kinds), and actions reference
  declared workflows. Follow the existing planner test pattern.
- Pipeline hook: integration-style — a fixture LLM schema + plan with page
  actions → after the pass, the row button carries the workflow binding and a
  `binding-report.json` is written.

## Success criteria

A prompt-generated app whose plan declares page `actions[]` produces page schemas
where the named action buttons carry `props.workflow` (+ `args:{id:"{{item.id}}"}`
for row actions), without disturbing the page agent's existing `dataSources`/
`Repeat` data binding, and a `binding-report.json` records what was wired.
