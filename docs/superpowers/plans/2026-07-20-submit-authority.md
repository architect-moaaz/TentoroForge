# Submit-Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every generated form has an explicit, planner-declared submit target (workflow or data API), and every workflow has an explicit dispatch source. Every workflow input has an explicit value source. No form ships without a target, no workflow ships as an orphan, no input can go unmapped.

**Architecture:** Planner becomes the single authority for the form ↔ workflow ↔ data-API binding graph. Plan schema is extended with three symmetric declarations: `page.submit`, `workflow.source`, and `workflow.inputs[].source`. Validators reject plans that violate the contract *before* codegen; post-generate guards catch anything that slipped through, and hard-fail the build rather than silently ship an orphan. Form scaffolder + workflow runtime read the declarations verbatim — no inference from entity/name coincidence.

**Tech Stack:** Python 3.11, FastAPI, TypeScript (runtime dispatcher), pytest, JSON Schema.

**Branch:** `forge-v3-smith-orchestrator-v2` (or new branch `forge-v3-submit-authority`)

---

## Motivation

Live-observed on `output/xoiz4i97`:

- `FeedbackFormPage` (`/feedback/new`) declared `entity: Feedback`, 8 fields, no submit target
- `SubmitFeedbackWorkflow` declared `trigger: manual`, `entity: null`, 9 inputs, no `submitted_by`
- Nothing in the app can dispatch the workflow. The form silently POSTs to `/api/data/feedback` (inferred from `entity`). The workflow ships as decoration.
- Even if we wired them by name-matching, one input (`applicationId`) has no form field — the dispatch would misfire silently at runtime.

Root cause: **authority leaks to inference**. Planner emits pages and workflows as independent islands; downstream generators guess the wiring; post-generate passes patch orphans on best-effort; the runtime discovers gaps too late.

## Non-goals

- Rewriting the deterministic form scaffolder (only its input source changes — from entity metadata to workflow declarations)
- Replacing the existing `workflow_launch_forms.py` pass — it becomes a **backstop** (skip-conditions removed), not the primary path
- Cron / webhook / event workflow sources — spec them but implement only "form" and "button" sources in v1; the rest as future slices
- Migration of existing generated apps — new invariant applies to newly generated plans; existing apps unaffected until re-planned

## Contract

### `plan.pages[].submit` (new — required for form-typed pages)

```json
{
  "submit": {
    "kind": "workflow" | "data_api" | "custom",
    "target": "<workflow name>" | "<entity name>" | "<custom_endpoint>",
    "field_map": { "<form_field>": "<target_input>" }
  }
}
```

- `kind=data_api`: submits to the data engine — `target` names an entity, POST /api/data/<entity>
- `kind=workflow`: dispatches a workflow — `target` names a workflow
- `kind=custom`: custom endpoint — `target` names the route + method (rare, for auth flows etc.)
- `field_map` is **optional** when field names match 1:1 (validator auto-derives identity map)

### `plan.workflows[].source` (new — required for every workflow)

```json
{
  "source": {
    "kind": "form" | "button" | "event" | "timer" | "webhook" | "cron",
    "page":  "<page name>",       // required when kind=form|button
    "event": "<event name>",      // required when kind=event
    "schedule": "<cron_expr>"     // required when kind=timer|cron
  }
}
```

For v1 we implement `form` and `button` only; the other kinds pass validation but generate a placeholder launcher.

### `plan.workflows[].inputs[].source` (new — required for every input)

```json
{
  "inputs": [
    {
      "name": "interviewSlotId",
      "type": "uuid",
      "required": true,
      "source": {
        "kind": "form_field",     // "route" | "auth" | "static" | "computed"
        "field": "interviewSlotId"
      }
    },
    {
      "name": "applicationId",
      "type": "uuid",
      "required": true,
      "source": { "kind": "route", "param": "applicationId" }
    },
    {
      "name": "recordedBy",
      "type": "uuid",
      "required": true,
      "source": { "kind": "auth", "claim": "user.id" }
    },
    {
      "name": "submittedAt",
      "type": "timestamp",
      "required": true,
      "source": { "kind": "static", "value": "{{now}}" }
    }
  ]
}
```

- `form_field`: value comes from the dispatching page's form
- `route`: value comes from a URL param on the dispatching page's route
- `auth`: value comes from the auth context (current user id, tenant, roles)
- `static`: hardcoded value or built-in template (`{{now}}`, `{{uuid}}`)
- `computed`: FEEL-lite expression over other sources (v2 — validator accepts but codegen defers)

## File structure

**New files:**
- `backend/services/submit_authority.py` — pure helpers: extract submit target from page, resolve field_map, derive form fields from workflow inputs, validate all sources trace to real anchors
- `backend/services/tests/test_submit_authority.py` — unit tests for all helpers

**Modified files:**
- `backend/agents/planner.py` — prompt update + normalizer for the three new fields; REVISE loop for source-missing violations
- `backend/services/plan_validator.py` — three new validations (submit-target, workflow-source, input-source); add to the REVISE loop's fail list
- `backend/services/plan_field_lookup.py` — expose `page_submit_of(plan, page_name)` and `workflow_source_of(plan, workflow_name)` for downstream reads
- `backend/services/form_scaffold.py` — read the target workflow's `form_field` inputs instead of entity columns for workflow-submitting forms; entity-submitting forms unchanged
- `backend/services/deterministic_pages.py` — create/edit builders honor `page.submit.target` when wiring the submit button's action
- `backend/services/workflow_launch_forms.py` — remove skip conditions (`entity=null`, complex inputs); becomes the guarantor of last resort
- `backend/services/post_generate_fixes.py` — add `workflow_completeness_guard` + `form_target_guard` to the pass suite
- `backend/templates/runtime/workflows/engine.ts` — dispatcher reads input.source per input and assembles from form/route/auth/static
- `backend/services/register_selector.py` (or wherever plan schema is documented) — extend the plan spec JSON Schema

**Tests:**
- `backend/tests/services/test_plan_validator.py` — add cases for each new violation kind
- `backend/tests/services/test_form_scaffold.py` — verify workflow-driven field list overrides entity list
- `backend/tests/services/test_deterministic_pages.py` — verify submit-button action honors `page.submit.target`
- `backend/tests/services/test_workflow_completeness_guard.py` — new
- `backend/tests/services/test_submit_authority.py` — helper unit tests

---

## Tasks

### Task 1: submit_authority helpers (pure functions, TDD)

**Files:**
- Create: `backend/services/submit_authority.py`
- Test: `backend/tests/services/test_submit_authority.py`

- [ ] **Step 1: write the failing test for `resolve_page_submit(plan, page_name)`**

```python
# test_submit_authority.py
def test_resolve_page_submit_returns_declared_target():
    plan = {"pages": [{
        "name": "FeedbackFormPage", "type": "form",
        "submit": {"kind": "workflow", "target": "SubmitFeedbackWorkflow"}
    }]}
    from services.submit_authority import resolve_page_submit
    r = resolve_page_submit(plan, "FeedbackFormPage")
    assert r == {"kind": "workflow", "target": "SubmitFeedbackWorkflow", "field_map": {}}

def test_resolve_page_submit_returns_none_for_missing():
    plan = {"pages": [{"name": "OtherPage", "type": "list"}]}
    from services.submit_authority import resolve_page_submit
    assert resolve_page_submit(plan, "OtherPage") is None
```

Run: `pytest tests/services/test_submit_authority.py::test_resolve_page_submit_returns_declared_target -v`
Expected: FAIL (module not found)

- [ ] **Step 2: implement `resolve_page_submit`**

```python
# submit_authority.py
from typing import Optional

def resolve_page_submit(plan: dict, page_name: str) -> Optional[dict]:
    """Return the page's declared submit target, or None if not declared.

    Empty field_map is normalized to {} (means "identity map" for the
    caller to derive from field names)."""
    if not isinstance(plan, dict):
        return None
    for p in plan.get("pages") or []:
        if not isinstance(p, dict) or p.get("name") != page_name:
            continue
        submit = p.get("submit")
        if not isinstance(submit, dict) or not submit.get("target"):
            return None
        return {
            "kind": str(submit.get("kind") or "").strip() or "data_api",
            "target": str(submit["target"]).strip(),
            "field_map": dict(submit.get("field_map") or {}),
        }
    return None
```

- [ ] **Step 3: run and pass**

- [ ] **Step 4: write test for `resolve_workflow_source(plan, wf_name)`**

- [ ] **Step 5: implement it (mirror shape)**

- [ ] **Step 6: write test for `derive_form_fields_from_workflow(plan, wf_name)`**

```python
def test_derive_form_fields_from_workflow():
    plan = {"workflows": [{
        "name": "W", "inputs": [
            {"name": "a", "type": "uuid",   "source": {"kind": "form_field", "field": "a"}},
            {"name": "b", "type": "integer","source": {"kind": "form_field", "field": "b"}},
            {"name": "c", "type": "uuid",   "source": {"kind": "route",      "param": "id"}},
        ]
    }]}
    from services.submit_authority import derive_form_fields_from_workflow
    fields = derive_form_fields_from_workflow(plan, "W")
    assert [f["name"] for f in fields] == ["a", "b"]   # only form_field inputs
```

- [ ] **Step 7: implement — filter inputs by `source.kind == form_field`**

- [ ] **Step 8: write test for `validate_input_sources(workflow, page, route)` — checks every input has a resolvable source**

- [ ] **Step 9: implement — return list of unresolved-input errors**

- [ ] **Step 10: commit — `git add … && git commit -m "feat(submit-authority): pure helpers for page.submit + workflow.source"`**

### Task 2: extend planner prompt + normalizer

**Files:**
- Modify: `backend/agents/planner.py:_ONESHOT_SYSTEM_PROMPT` (add submit-authority section)
- Modify: `backend/agents/planner.py:_normalize_oneshot_plan` (defaults for missing declarations)
- Test: `backend/tests/test_planner_submit_authority.py` (new)

- [ ] **Step 1: write test — canned planner-shape plan without `submit` is normalized to add identity submit when a matching workflow exists**

- [ ] **Step 2: extend prompt with the SUBMIT-AUTHORITY contract**

Add a new section to `_ONESHOT_SYSTEM_PROMPT` (verbatim block):

```
=== SUBMIT AUTHORITY (REQUIRED) ===

Every form-typed page MUST declare page.submit. Every workflow MUST
declare workflow.source. Every workflow input MUST declare source.

Page submit shapes:
  {"kind":"data_api","target":"<EntityName>"}       # POST to data engine
  {"kind":"workflow","target":"<WorkflowName>",
   "field_map":{"<form_field>":"<workflow_input>"}}  # dispatch a workflow

Workflow source shapes (v1: form|button; others accepted but placeholder):
  {"kind":"form","page":"<PageName>"}
  {"kind":"button","page":"<PageName>"}

Input source shapes:
  {"kind":"form_field","field":"<field name on the dispatching form>"}
  {"kind":"route","param":"<url param on the dispatching page's route>"}
  {"kind":"auth","claim":"user.id"}                 # current user
  {"kind":"static","value":"<literal or template>"} # e.g. "{{now}}"

RULES:
- A workflow with source.kind=form MUST be the target of that page's submit
- Every input.source.kind=form_field MUST name a field the source page has
- Every input.source.kind=route MUST name a param the page's route declares
- NO orphan workflows. NO forms without submit. NO inputs without source.
```

- [ ] **Step 3: extend `_normalize_oneshot_plan` — for backward-compat, when a plan omits `submit` on a form page WITH a matching entity, insert `{"kind":"data_api","target":entity}` (identity fallback so old plans still validate)**

- [ ] **Step 4: run test — pass**

- [ ] **Step 5: commit**

### Task 3: plan validator — three new checks

**Files:**
- Modify: `backend/services/plan_validator.py` (add rules)
- Modify: `backend/tests/services/test_plan_validator.py`

- [ ] **Step 1: write failing test — plan with a form page missing `submit` returns a validation error**

- [ ] **Step 2: implement `_rule_forms_have_submit` (return list of errors, empty on success)**

- [ ] **Step 3: write failing test — plan with a workflow missing `source` returns error**

- [ ] **Step 4: implement `_rule_workflows_have_source`**

- [ ] **Step 5: write failing test — workflow input with `source.kind=form_field` naming a field the source page doesn't have → error**

- [ ] **Step 6: implement `_rule_input_sources_resolve` (uses `submit_authority` helpers)**

- [ ] **Step 7: wire all three rules into `validate_plan_completeness(plan)`**

- [ ] **Step 8: verify REVISE loop picks these up — add integration test that a plan with violations triggers the retry once**

- [ ] **Step 9: commit — `feat(plan-validator): enforce submit-authority contract`**

### Task 4: form scaffolder reads workflow instead of entity

**Files:**
- Modify: `backend/services/form_scaffold.py`
- Test: `backend/tests/services/test_form_scaffold.py`

- [ ] **Step 1: write failing test — a form page with `submit.kind=workflow` derives its fields from the target workflow's `form_field` inputs, ignoring `page.entity`**

- [ ] **Step 2: read `submit_authority.resolve_page_submit(plan, page_name)` at the top of `build_form_page`**

- [ ] **Step 3: when `submit.kind == "workflow"`, call `derive_form_fields_from_workflow(plan, submit.target)` and use THAT as the field list**

- [ ] **Step 4: when `submit.kind == "data_api"`, fall through to existing entity-driven logic (backward-compat)**

- [ ] **Step 5: verify — existing entity-form tests still pass**

- [ ] **Step 6: commit — `feat(form-scaffold): workflow-driven field list when page.submit.kind=workflow`**

### Task 5: deterministic page builder wires submit action from `page.submit.target`

**Files:**
- Modify: `backend/services/deterministic_pages.py` (create + edit + form builders)
- Test: `backend/tests/services/test_deterministic_pages.py`

- [ ] **Step 1: write failing test — a form page with `submit.kind=workflow` renders its submit button with `action.type=dispatchWorkflow, action.workflow=<target>`**

- [ ] **Step 2: implement the wire — grep for existing submit-button emission, add a branch for the workflow case**

- [ ] **Step 3: write failing test — a form page with `submit.kind=data_api` renders with the existing data-engine POST action (unchanged)**

- [ ] **Step 4: verify existing tests pass**

- [ ] **Step 5: commit — `feat(det-pages): submit action honors page.submit.target`**

### Task 6: workflow_launch_forms becomes the backstop (no skips)

**Files:**
- Modify: `backend/services/workflow_launch_forms.py`

- [ ] **Step 1: remove skip conditions — the `entity=null` skip and the "too many inputs" skip. Every manual workflow without a declared source-page gets a synthesized launcher**

- [ ] **Step 2: when synthesizing, populate `plan.workflows[wf].source = {"kind":"form","page":"<GeneratedLauncherName>"}` in memory so downstream can see it**

- [ ] **Step 3: write test — a workflow with `entity=null` and 9 inputs gets a launcher generated (was skipped before)**

- [ ] **Step 4: commit — `refactor(workflow-launch-forms): remove skip conditions, always synthesize`**

### Task 7: workflow completeness guard (post-generate, hard fail)

**Files:**
- Create: `backend/services/workflow_completeness_guard.py`
- Modify: `backend/services/post_generate_fixes.py` (register in the pass suite)
- Test: `backend/tests/services/test_workflow_completeness_guard.py`

- [ ] **Step 1: write failing test — a generated app with a workflow whose source-page doesn't exist in `src/schemas/` returns an error**

- [ ] **Step 2: implement guard — walk `workflows/*.json`, for each read the plan's `workflow.source`, verify the source page schema exists and has a submit button targeting this workflow**

- [ ] **Step 3: on failure, three-tier response:**
  - Auto-wire: find a form whose fields match → patch the page's submit button
  - Auto-synthesize: call `workflow_launch_forms` for the workflow (single-workflow mode)
  - HARD FAIL: raise `WorkflowCompletenessError("<workflow> has no launcher and none could be synthesized")` — pipeline surfaces via SSE error event

- [ ] **Step 4: register in `apply_post_generate_fixes` after `workflow_launch_forms` runs**

- [ ] **Step 5: commit — `feat(post-gen): workflow-completeness guard hard-fails on orphaned workflows`**

### Task 8: form target guard (symmetric to Task 7)

**Files:**
- Create: `backend/services/form_target_guard.py`
- Modify: `backend/services/post_generate_fixes.py`
- Test: `backend/tests/services/test_form_target_guard.py`

- [ ] **Step 1: write failing test — a form-typed page schema with no submit action returns an error**

- [ ] **Step 2: implement — walk `src/schemas/*.json`, for each form page check the submit button's action wires to a real workflow or data endpoint**

- [ ] **Step 3: on failure — auto-wire from `page.submit` in plan.json → HARD FAIL if plan doesn't declare submit**

- [ ] **Step 4: register in `apply_post_generate_fixes` — runs before workflow_completeness_guard (form must have target before we check workflow has form)**

- [ ] **Step 5: commit — `feat(post-gen): form-target guard hard-fails on submit-less forms`**

### Task 9: runtime dispatcher assembles inputs from sources

**Files:**
- Modify: `backend/templates/runtime/workflows/engine.ts` (dispatcher)
- Modify: `backend/services/runtime_injector.py` (if the dispatcher signature changes)
- Test: manual smoke — verify a workflow dispatched from a form gets its route param + auth claim + form fields correctly assembled

- [ ] **Step 1: extend dispatcher signature to accept the workflow definition alongside submitted form values**

- [ ] **Step 2: for each declared input, resolve its value:**
  - `form_field` → from submitted values
  - `route` → from `window.location` or the dispatch call site
  - `auth` → from the app's auth session
  - `static` → literal or template evaluated (support `{{now}}`, `{{uuid}}`)

- [ ] **Step 3: reject dispatch with a specific error message if any required input has no resolved value**

- [ ] **Step 4: rebuild vendored engine dist, revendor into a fresh generated app for smoke test**

- [ ] **Step 5: commit — `feat(runtime): dispatcher assembles inputs from declared sources`**

### Task 10: acceptance test — the ATS SubmitFeedbackWorkflow case

**Files:** No file changes. Live E2E.

- [ ] **Step 1: kill and restart backend + frontend**

- [ ] **Step 2: kick off a fresh recruitment-domain generation via chat**

- [ ] **Step 3: verify plan.json has `submit`, `workflow.source`, `input.source` on every relevant artifact**

- [ ] **Step 4: verify generated `src/schemas/feedback/new.json` has submit button wired to `SubmitFeedbackWorkflow`**

- [ ] **Step 5: verify workflow_launch_forms did NOT synthesize a duplicate launcher (the page was already there)**

- [ ] **Step 6: boot the generated app, navigate to /feedback/new, fill in fields, submit**

- [ ] **Step 7: verify the workflow actually fired (check workflow run history)**

- [ ] **Step 8: verify workflow received all 9 inputs, including `applicationId` from route + `recordedBy` from auth**

- [ ] **Step 9: report success or debug — commit acceptance notes**

---

## Success criteria

1. Plan validator rejects any generated plan lacking `submit` on a form page, `source` on a workflow, or `source` on any workflow input.
2. Every form-typed page in a generated app has a working submit action wired to either a workflow or the data engine.
3. Every workflow in a generated app has at least one triggering source in the UI (form submit, button click, or a scheduled/event source).
4. Every workflow input in every dispatched call receives a resolved value; no `null` gets sent to a required input.
5. Live E2E: `SubmitFeedbackWorkflow` in a freshly generated ATS is dispatched from `/feedback/new` and runs successfully.

## Rollout

- Ship behind no flag — additive. Existing generated apps unaffected until re-planned.
- New generated apps will fail the plan validator if the planner doesn't declare the new fields; that's the point — force adoption.
- If a specific app hits repeated validator failures despite REVISE retries, fall back to normalizer defaults (Task 2 Step 3) so we ship SOMETHING, but log a hard warning.
- Existing `apply_post_generate_fixes` order matters: `form_target_guard` must run before `workflow_completeness_guard` (form must have target before we check workflow has form).

## Risk

- **Planner regression**: adding required fields to the prompt increases the token budget and risks the planner missing them under pressure. Mitigation: normalizer defaults for backward-compat + one REVISE retry.
- **Form scaffolder breaking existing entity-driven forms**: covered by keeping the `data_api` branch byte-unchanged.
- **workflow_launch_forms doing too much when its skips are removed**: mitigation — only synthesize when `workflow.source.kind == form` AND no source page exists; treat everything else as an authored intent to respect.
- **Runtime dispatcher signature change breaking existing generated apps**: only affects newly generated ones. Existing apps that vendor an older engine dist keep working.

## Open decisions (want your call before Task 1 starts)

1. **Should `field_map` be REQUIRED even when field names match?** Explicit is safer (rename-proof); implicit is less prompt burden. **Recommend: optional; validator auto-derives identity map when omitted.**

2. **Should `computed` sources be supported in v1?** Would need FEEL-lite evaluator wired into the dispatcher. **Recommend: no. Validator accepts and stores, but generator errors if any input has `computed` source; ship in v2.**

3. **Should we support multi-source workflows (page A OR page B can dispatch)?** Some real workflows are (e.g. an "approve" action might fire from a list-row button OR a detail-page button). **Recommend: yes — `workflow.source` accepts a LIST of source declarations; v1 requires ≥1 form-source but tolerates additional button-sources.**

4. **What happens to `workflow_launch_forms.py` after Task 7?** Currently primary path. **Recommend: keep it as the backstop-synthesizer called BY the completeness guard, not as a top-level pass.**
