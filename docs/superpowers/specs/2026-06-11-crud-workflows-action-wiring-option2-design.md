# CRUD Workflows + Full Action Wiring (Option 2) — Design

**Date:** 2026-06-11
**Status:** Design approved (approach + sequencing), pre-implementation
**Branch:** forge-v3
**Builds on:** Slice 1 (figma binding), Slice 1b (LLM-path binding), the live E2E run that exposed the gap.

## Problem

Generated apps render action buttons (Approve, Reject, New, Edit, Delete, Save)
but most don't *do* anything real:
- The runtime's only button-action mechanism is **workflow dispatch**
  (`POST /api/workflows/{name}/execute`). There is no data-mutation primitive;
  every create/update/delete must be a **workflow** that runs `db_insert` /
  `db_update` / `db_delete` (handlers already exist in the generated runtime).
- The planner declares only **domain** workflows (e.g. one approval workflow).
  CRUD workflows are never generated, so create/edit/delete buttons have nothing
  to bind to — and the page agent hallucinated names (`createLeaveRequest`) with
  no backing definition.

## Goal

Every **navigation / create / update / delete / process** button (categories
1–5 of the button taxonomy) maps to a real backend: a `navigate` target or a
**generated, dispatchable workflow**. Categories 6 (UI state) and 7 (utility/
external) remain out of scope.

## Design stance

CRUD is mechanical: `(entity, page-type)` fully determines the standard actions,
so generate CRUD **deterministically** — no LLM guessing, eliminating the
hallucination class. The LLM/planner keeps owning only **domain process**
workflows (approve/reject/escalate). A final **LLM completeness guard** verifies
that every actionable button is tied to a real backend and proposes
deterministically-validated repairs for any that aren't.

## Parts

### A. Deterministic CRUD workflow generator

New `backend/services/crud_workflow_generator.py`. For each entity (from the
registry/plan, after entities+tables are known), emit up to three workflow JSON
files in the project's `workflows/` dir, each one action node:

- `Create<Entity>` → node `{actionType: "db_insert", table, values: {field: "{{field}}"}}`
- `Update<Entity>` → node `{actionType: "db_update", table, where: {id: "{{id}}"}, values: {...}}`
- `Delete<Entity>` → node `{actionType: "db_delete", table, where: {id: "{{id}}"}}`

Shape matches the existing workflow JSON (`{id, name, description,
processVariables, definition:{nodes, edges}}`) and the runtime `db_*` handler
config contract (`config.table` = SQL table name; `config.values`/`config.where`
= field→`{{var}}` maps). `processVariables` declares the inputs (id + writable
fields). Idempotent: never overwrite a workflow file that already has nodes
(domain workflows the bizlogic agent produced win). Hook into both pipelines
after the schema/registry entities exist.

### B. Deterministic CRUD action derivation + binding

New `backend/services/crud_actions.py`: `derive_crud_actions(page, entity, workflows_present)`
returns the standard actions for a page given its `type`:
- **list** → page-level `New` (kind `navigate`, target the form route) + per-row
  `Delete` (`row_action` → `Delete<Entity>`)
- **detail** → `Edit` (`navigate` to edit form) + `Delete` (`page_action` → `Delete<Entity>`)
- **form** → handled by Part C (submit), no extra buttons
Only emits an action whose target workflow actually exists (created in Part A) or
whose nav route exists. Merge these into the plan page's `actions[]` (alongside
any LLM process actions). The Slice-1b binding pass then wires them; extend its
adapter to understand a `navigate` action kind (sets `props.navigate`) in
addition to `row_action`/`page_action` (which set `workflow`+`args`). Wiring is
**fill-only-if-absent** (chosen): never overwrite a button the page agent already
wired.

### C. Form submit → create/update workflow wiring

`Form` already dispatches `props.workflow` on submit. A new binding step wires a
form on a `form`-type page for entity E:
- new/create form → `Form.workflow = Create<Entity>`
- edit/update form → `Form.workflow = Update<Entity>`
and maps the form's field names to the workflow's process variables (so submit
persists). Deterministic; fill-only-if-absent. Lives in the binding pass
(extend it to handle `Form` nodes, not just `Button`).

### D. LLM completeness guard

After A–C, a per-page LLM pass (`backend/agents/wiring_guard.py`) receives the
page's buttons/forms + the list of **real** backends (existing workflow names +
valid nav routes + dataSources) and returns, for each actionable node, a verdict:
already-wired / proposed-binding / intentionally-inert (UI/utility). Apply only
**deterministically-validated** repairs — a proposed `workflow` must be in the
real workflow set; a proposed `navigate` must be a real route — never invent.
Emit a `wiring-report.json` (per node: kind, bound-to, source: crud|process|nav|
guard|unbound). The guard is a safety net, not the primary mechanism; it runs
default-on but degrades to a no-op without an API key.

### E. Live E2E re-run

Re-run the prompt build (leave-request domain) and confirm: `Create/Update/
Delete<Entity>` workflow files exist; list/detail/form buttons carry real
`workflow`+`args` or `navigate`; `wiring-report.json` shows no actionable button
left unbound; (if a DB is available) clicking dispatches and mutates.

## Out of scope

- Categories 6 (UI-state: filter/sort/expand) and 7 (export/print/download).
- Auth/permission gating of actions (`visible_when`).
- A data-mutation button primitive in the runtime (deliberately avoided — CRUD
  goes through workflows).

## Testing

- A: per-entity create/update/delete JSON has correct `actionType`/`table`/
  `where`/`values`/`processVariables`; idempotent (won't clobber existing
  domain workflow); skips entities without a table.
- B: `derive_crud_actions` returns the right actions per page-type; only targets
  existing workflows/routes; binding sets `navigate` for nav kind and
  `workflow`+`args` for row/page actions; fill-only-if-absent.
- C: form-page form gets `workflow=Create/Update<Entity>` + field→var map; no
  overwrite when already set.
- D: guard applies only validated repairs (phantom workflow proposal rejected);
  emits report; no-op without API key (mock the LLM in tests).
- E: manual.

## Success criteria

A prompt-generated CRUD app where New/Edit navigate to forms, Save/Submit
dispatch `Create/Update<Entity>` (persisting via `db_insert`/`db_update`),
Delete dispatches `Delete<Entity>` (`db_delete`), and domain actions
(Approve/Reject) dispatch their process workflow — every category 1–5 button
tied to a real backend, verified by `wiring-report.json`.
