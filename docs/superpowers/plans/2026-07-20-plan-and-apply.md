# Plan & Apply (Smith Composition) Implementation Plan (Slice B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Smith gets a `plan_and_apply(ask)` tool that turns a whole-feature ask into a scoped plan-fragment, dispatches the fragment through existing seams, and reports what was applied. Fragments carry SUBMIT-AUTHORITY declarations from Slice A, so composed artifacts arrive pre-wired — no orphans possible.

**Architecture:** Two-stage inside one Smith tool call:
1. **plan_scope(ask, output_dir)** — LLM emits a `Fragment` pydantic model: what pages/workflows/entities to add or edit, with `page.submit`, `workflow.source`, `workflow.inputs[].source` populated per SUBMIT-AUTHORITY.
2. **apply_scope(fragment, output_dir)** — pure dispatcher iterates fragment → calls `add_page`, `add_workflow`, `add_entity`, `edit_page`, `wire_form_to_workflow` (Slice C) in dependency order. Collects diff + files_touched.

Smith calls `plan_and_apply`, gets a structured result, formats a reply with the applied changes + assumptions + any unresolved items.

**Tech Stack:** Python 3.11, pydantic, pytest, Anthropic SDK for the scoped-planner LLM call, TypeScript untouched.

**Branch:** `forge-v3-smith-orchestrator-v2` (or new `forge-v3-plan-and-apply`)

**Depends on:**
- **Slice A** — SUBMIT-AUTHORITY contract must be stable (Fragment fields depend on it)
- **Slice C** — `wire_form_to_workflow` seam must exist (apply_scope calls it for cross-artifact wiring)

**Blocks:** Nothing — this is the top-of-stack for Smith's compositional authoring.

---

## Contract

### Fragment (pydantic model)

```python
class PageToAdd(BaseModel):
    route:     str
    archetype: str                        # from DETERMINISTIC_ARCHETYPES
    entity:    str
    title:     str | None = None
    fields:    list[dict] | None = None
    features:  list[str] | None = None
    submit:    dict | None = None         # SUBMIT-AUTHORITY (Slice A)

class PageToEdit(BaseModel):
    route:  str
    intent: str                            # free-text patch instruction
    submit: dict | None = None             # re-declare if wiring changes

class WorkflowToAdd(BaseModel):
    name:    str
    entity:  str | None
    op:      str                           # "create"|"update"|"custom"
    source:  dict                          # SUBMIT-AUTHORITY (required)
    inputs:  list[dict]                    # each has .source (Slice A)
    steps:   list[dict]

class WireOp(BaseModel):
    page_route:    str
    workflow_name: str
    field_map:     dict[str, str] | None = None

class EntityToAdd(BaseModel):
    name:   str
    fields: list[dict]
    table:  str | None = None

class MenuEntry(BaseModel):
    label: str
    route: str

class Fragment(BaseModel):
    pages_to_add:     list[PageToAdd]     = []
    pages_to_edit:    list[PageToEdit]    = []
    workflows_to_add: list[WorkflowToAdd] = []
    entities_to_add:  list[EntityToAdd]   = []
    wires:            list[WireOp]        = []
    menu_entries:     list[MenuEntry]     = []

class ScopedPlan(BaseModel):
    understanding: str
    fragment:      Fragment
    assumptions:   list[str] = []
    unresolvable:  list[str] = []
```

### plan_scope(ask, output_dir) — LLM call

Reads:
- App map skeleton
- Resource-registry slice for entities the grounding matches
- Archetype catalog (from `DETERMINISTIC_ARCHETYPES`)
- SUBMIT-AUTHORITY contract (from Slice A) — injected as required-shape instruction
- Seam contracts (`add_page` / `edit_page` / `add_workflow` / `add_entity` / `wire_form_to_workflow`)

Emits: JSON-schema-constrained `ScopedPlan`.
Retry: one on schema-validation failure, appending validator error.

### apply_scope(plan, output_dir) — dispatcher

Order (dependency-driven, not free-form):
1. `entities_to_add` → `fix_applier._apply_add_entity`
2. `pages_to_add` → `fix_applier._apply_add_page` (each PageToAdd.submit becomes the page's submit declaration)
3. `pages_to_edit` → `services.llm_edit.smart_edit_page` (intent as patch instruction)
4. `workflows_to_add` → `fix_applier._apply_add_workflow` (each carries source + inputs.source)
5. `wires` → `wire_form_to_workflow(...)` (Slice C)
6. `menu_entries` → `services.shell_menu_sync.sync_shell_menu`

Partial apply OK — each step try/except, records `ok:False` on failure, continues.

Returns:
```python
class ApplyResult(BaseModel):
    steps:         list[ApplyStep]
    edited_paths:  list[str]
    all_succeeded: bool
```

### plan_and_apply (Smith tool)

```python
{
  "name": "plan_and_apply",
  "description": (
    "Delegate a multi-artifact feature to the scoped planner. Use for "
    "asks that need coordinated pages + workflows + wiring — e.g. "
    "'add resume parsing that fires on CV upload', 'kanban board of "
    "candidates with drag-to-transition'. For SINGLE-ARTIFACT asks use "
    "add_page/add_workflow/edit_page directly."
  ),
  "input_schema": {
    "type": "object",
    "properties": {"ask": {"type": "string"}},
    "required": ["ask"]
  }
}
```

Handler `_smith_plan_and_apply(output_dir, args)`:
1. `plan = plan_scope(args["ask"], output_dir)`
2. `result = apply_scope(plan.fragment, output_dir)`
3. Return `{understanding, assumptions, unresolvable, steps, edited_paths, all_succeeded}`

Smith formats the reply with the understanding + assumptions + diff summary + any unresolvable items as a follow-up question.

## File structure

**New files:**
- `backend/services/plan_scope.py` — Fragment/ScopedPlan pydantic models + LLM call + JSON-schema-constrained output
- `backend/services/apply_scope.py` — dispatcher over the six existing seams
- `backend/tests/services/test_plan_scope.py`
- `backend/tests/services/test_apply_scope.py`

**Modified files:**
- `backend/services/smith_tools.py` — register `plan_and_apply` + handler
- `backend/agents/smith_agent.py` — routing rule for multi-artifact feature asks + reporting block

**Depends on (must exist first):**
- `backend/services/wire_form_workflow.py` — Slice C
- SUBMIT-AUTHORITY plan schema — Slice A

---

## Tasks

### Task 1: Fragment + ScopedPlan pydantic models (TDD)

**Files:**
- Create: `backend/services/plan_scope.py`
- Test: `backend/tests/services/test_plan_scope.py`

- [ ] **Step 1: write failing test — `Fragment.model_validate(dict)` accepts a canonical example with all six fields**

- [ ] **Step 2: implement all pydantic models**

- [ ] **Step 3: write failing test — WorkflowToAdd rejected when `source` missing (SUBMIT-AUTHORITY invariant)**

- [ ] **Step 4: add pydantic validator**

- [ ] **Step 5: write failing test — WorkflowToAdd rejected when any input lacks `source`**

- [ ] **Step 6: add validator + pass**

- [ ] **Step 7: commit — `feat(plan-scope): Fragment/ScopedPlan models with SUBMIT-AUTHORITY invariants`**

### Task 2: plan_scope LLM call + JSON-schema constraint

- [ ] **Step 1: write failing test — plan_scope with a mock LLM returning a valid ScopedPlan JSON returns the parsed model**

- [ ] **Step 2: implement `plan_scope(ask, output_dir, *, query_fn=None)` — build system prompt from app map + archetype catalog + seam contracts + SUBMIT-AUTHORITY instruction; call LLM; parse; validate**

- [ ] **Step 3: write failing test — LLM returns malformed JSON → single retry with validator-error-appended prompt**

- [ ] **Step 4: implement retry loop (max 1)**

- [ ] **Step 5: write failing test — retry also malformed → return empty fragment with `unresolvable=["planner_json_invalid:<err>"]`, don't raise**

- [ ] **Step 6: implement + pass**

- [ ] **Step 7: verify the prompt block includes DETERMINISTIC_ARCHETYPES dynamically (no hardcoded list)**

- [ ] **Step 8: commit — `feat(plan-scope): LLM call with retry + graceful degrade`**

### Task 3: apply_scope dispatcher (TDD, mock seams)

**Files:**
- Create: `backend/services/apply_scope.py`
- Test: `backend/tests/services/test_apply_scope.py`

- [ ] **Step 1: write failing test — fragment with 1 add_page + 1 add_workflow calls the two seams in order, both `ok=True`, `all_succeeded=True`**

- [ ] **Step 2: implement `apply_scope` — iterate fragment sections in fixed order, call each seam, capture ApplyStep**

- [ ] **Step 3: write failing test — add_page seam raises → step recorded `ok:False, error:<msg>`, dispatch continues to next section, `all_succeeded=False`**

- [ ] **Step 4: implement try/except per section + pass**

- [ ] **Step 5: write failing test — wires section calls `wire_form_to_workflow` (Slice C) with correct args**

- [ ] **Step 6: implement + pass**

- [ ] **Step 7: write failing test — empty fragment returns `ApplyResult(steps=[], all_succeeded=True, edited_paths=[])`**

- [ ] **Step 8: implement + pass**

- [ ] **Step 9: verify apply order: entities → pages_to_add → pages_to_edit → workflows_to_add → wires → menu_entries (dependency order)**

- [ ] **Step 10: commit — `feat(apply-scope): dispatcher over existing seams with partial-apply tolerance`**

### Task 4: plan_and_apply Smith tool + routing prompt

**Files:**
- Modify: `backend/services/smith_tools.py`
- Modify: `backend/agents/smith_agent.py`
- Test: `backend/tests/test_smith_plan_and_apply.py`

- [ ] **Step 1: register `plan_and_apply` in TOOL_CATALOG**

- [ ] **Step 2: implement `_smith_plan_and_apply(output_dir, args)` handler — call plan_scope + apply_scope, shape the return**

- [ ] **Step 3: write failing test — Smith with a canned multi-artifact ask picks `plan_and_apply` (not `add_page` alone)**

- [ ] **Step 4: update `_ROUTING_RULES` — add row for multi-artifact asks + REPORTING block**

Add above the `add_page` row:
```
Feature-add needing MULTIPLE artifacts    → plan_and_apply(ask=<verbatim>)
  (page + workflow + wiring;
  e.g. "kanban view of X with drag
  transitions", "add CV parsing that
  fires on upload")
Single new page (archetype + entity      → add_page(archetype, entity, route)
  already decided)
```

Add a REPORTING block:
```
When plan_and_apply returns, your `answer` MUST include:
  - What was applied (per-step summary)
  - The assumptions list VERBATIM (so user can correct any wrong defaults)
  - Any unresolvable items as a follow-up question
```

- [ ] **Step 5: verify routing test — mock LLM emits plan_and_apply call for "add resume parsing" ask**

- [ ] **Step 6: commit — `feat(smith): plan_and_apply tool + multi-artifact routing`**

### Task 5: Prompt engineering — SUBMIT-AUTHORITY compliance in scoped planner

- [ ] **Step 1: write failing test — plan_scope on a canned "add kanban board with drag transitions" ask returns a ScopedPlan whose WorkflowToAdd has `source.kind='button'` and `source.page` points at the new page**

- [ ] **Step 2: refine the plan_scope system prompt with 2-3 worked examples showing the required source declarations**

- [ ] **Step 3: verify — the mock LLM's canned response conforms to the model**

- [ ] **Step 4: commit — `feat(plan-scope): worked examples for SUBMIT-AUTHORITY compliance`**

### Task 6: Live E2E — the resume-parsing ask

- [ ] **Step 1: kill and restart backend + frontend so all three slices are live**

- [ ] **Step 2: open Forge chat on a project that has ATS shape (freshly generated recommended — with SUBMIT-AUTHORITY active on new generations)**

- [ ] **Step 3: send: `"add a resume parsing feature: when a candidate uploads their CV on the create form, extract personal info and prefill the profile fields"`**

- [ ] **Step 4: verify Smith picks `plan_and_apply`**

- [ ] **Step 5: watch the trace — plan_scope returns a ScopedPlan with:**
  - `workflows_to_add` — ParseCvWorkflow with `source={kind:"event",event:"cv.uploaded"}`, inputs mapped to form_field/route/auth
  - `pages_to_edit` — /candidates/new (emit cv.uploaded on upload, subscribe to workflow completion)
  - `wires` — one wire linking the workflow to the page event

- [ ] **Step 6: verify apply_scope executed all steps successfully**

- [ ] **Step 7: verify in the running generated app — upload a CV → workflow fires → fields prefill**

- [ ] **Step 8: verify Smith's reply includes understanding + assumptions + diff summary**

- [ ] **Step 9: commit acceptance notes + declare Slice B complete**

### Task 7: Kill unused paths (cleanup)

- [ ] **Step 1: any old placeholder tools removed (e.g. #223 S2-T3 plan_app / build_app if still stubbed)**

- [ ] **Step 2: verify no dead code paths remain**

- [ ] **Step 3: update memory: mark plan_and_apply live, retire earlier orchestrator experiment note if applicable**

- [ ] **Step 4: commit — `chore(smith): retire stubs superseded by plan_and_apply`**

---

## Success criteria

1. Fragment/ScopedPlan pydantic models reject any workflow without `source` or any input without `source` — SUBMIT-AUTHORITY invariant baked in
2. plan_scope produces a valid ScopedPlan for the resume-parsing ask on a fresh ATS
3. apply_scope dispatches to five existing seams (entities/pages/workflows/wires/menu) in dependency order with partial-apply tolerance
4. Smith picks plan_and_apply for multi-artifact asks, not add_page alone
5. Live E2E: resume parsing works end-to-end on a fresh ATS (upload → workflow fires → fields prefill)

## Rollout

- Additive tool — old direct-seam paths (add_page, add_workflow) remain
- Smith's routing prompt gives plan_and_apply priority for multi-artifact asks; single-artifact asks unchanged
- Behind no flag — Smith decides per turn which tool to use
- If plan_and_apply misbehaves, user can bypass via explicit direct-seam asks

## Risk

- **Scoped-planner hallucination** — LLM invents entities/pages/workflows that don't align with the app. Mitigation: pydantic validators + system prompt lists ONLY real entities/archetypes + one retry with validator errors
- **apply_scope partial success confusion** — some steps succeed, others fail, resulting in half-wired feature. Mitigation: `all_succeeded=False` surfaces the specific failures; Smith reports honestly
- **Chained seams cascade fail** — add_workflow succeeds but wire step fails → orphan created. Mitigation: run wires AFTER workflows so wires only fire on successful additions; also apply_scope reports which wires didn't run
- **Prompt drift** — Fragment schema grows over time. Mitigation: pydantic auto-generates JSON schema for the LLM prompt — one source of truth
- **Slice A/C not ready** — this plan hard-depends on both. Mitigation: sequence enforcement in the roadmap; skip live-E2E task (T6) until both are live

## Open decisions

1. **Concurrent seam dispatch** — apply_scope could parallelize add_page + add_workflow when they don't share files. **Recommend: no, ship sequential; parallelize later if apply times become painful**
2. **Retry policy for individual seams** — if add_page fails once, should apply_scope retry? **Recommend: no, one-shot per seam; the seam itself has retry logic where appropriate**
3. **Should Smith be able to preview a ScopedPlan before applying?** — a `dry_run` variant that returns the fragment without dispatching. **Recommend: yes, add as separate tool `preview_scope(ask)` in v2 once the base tool is proven**
4. **Chat UX for large fragments** — a 5-artifact fragment produces a long reply. **Recommend: render as a compact card in the frontend (grouped by artifact type), reuse the fix-chip pattern**
