# Wire Form ↔ Workflow Implementation Plan (Slice C)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deterministic seam `wire_form_to_workflow(page_route, workflow_name, field_map?, event?)` + Smith tool that surgically wires an existing form to an existing workflow. Immediately useful for retrofitting the ~11 orphan workflows on `4ct3h8z2` and any future orphans without waiting for the SUBMIT-AUTHORITY foundation.

**Architecture:** Pure Python seam that reads two artifacts (page schema + workflow definition), decides the wiring (submit button vs event vs button-action), writes updates to both, and rebuilds the plan.pages[].submit + plan.workflows[].source declarations to keep the plan authoritative. No LLM, no inference — the seam only wires; the CALLER decides intent.

**Tech Stack:** Python 3.11, pytest, no runtime changes.

**Branch:** `forge-v3-smith-orchestrator-v2` (or new `forge-v3-wire-form-workflow`)

**Depends on:** none (this ships first)

**Blocks:** Slice B's `plan_and_apply` uses this seam under the hood

---

## Contract

```python
def wire_form_to_workflow(
    output_dir: str,
    *,
    page_route: str,                           # e.g. "/candidates/new"
    workflow_name: str,                        # e.g. "ParseCvWorkflow"
    field_map: dict[str, str] | None = None,   # form_field -> workflow_input
                                               # None → identity map from matching names
    event: str | None = None,                  # for event-driven wiring (v2)
    trigger: str = "submit",                   # "submit" | "button:<label>"
) -> WireResult
```

`WireResult`:
```python
class WireResult(TypedDict):
    applied:      bool
    page_updated: str            # path to modified page schema
    wf_updated:   str            # path to modified workflow file
    plan_updated: bool           # whether plan.json was rewritten
    changes:      list[dict]     # per-file diff summary
    error:        str | None
```

**Fail modes** (all return `applied=False` with a specific error):
- Page not found → `page_not_found`
- Workflow not found → `workflow_not_found`
- Trigger element missing (button label doesn't exist on the page) → `trigger_not_found`
- field_map names a form field that doesn't exist → `unknown_field`
- field_map names a workflow input that doesn't exist → `unknown_input`
- Required workflow input has no source (form field + field_map + route params + auth claims don't cover it) → `unresolved_input:<name>`

## File structure

**New files:**
- `backend/services/wire_form_workflow.py` — the seam + WireResult typed dict
- `backend/tests/services/test_wire_form_workflow.py` — TDD tests

**Modified files:**
- `backend/services/smith_tools.py` — register `wire_form_to_workflow` in TOOL_CATALOG + handler
- `backend/agents/smith_agent.py` — routing rule for surgical wiring asks

**Read-only reads:**
- `src/schemas/{page}.json`
- `workflows/{workflow}.json`
- `src/contracts/plan.json` (for identity-map derivation)

**Reads + writes:**
- `src/schemas/{page}.json` — patches submit button's action
- `workflows/{workflow}.json` — sets `trigger` + `inputs[].source`
- `src/contracts/plan.json` — mirrors to `page.submit` + `workflow.source` + `workflow.inputs[].source`

---

## Tasks

### Task 1: Pure resolver — decide the wiring given the two artifacts (TDD)

**Files:**
- Create: `backend/services/wire_form_workflow.py`
- Test: `backend/tests/services/test_wire_form_workflow.py`

- [ ] **Step 1: write failing test — `_resolve_wiring(page_dict, workflow_dict, field_map=None)` returns (form_fields, input_sources, submit_action_patch, workflow_source_patch)**

```python
def test_resolve_wiring_identity_map():
    page = {"route": "/candidates/new", "root": {"children": [
        {"component": "Form", "props": {"submit": {"label": "Submit"}},
         "children": [{"component": "Input", "props": {"name": "cvUrl"}}]}
    ]}}
    wf = {"name": "ParseCvWorkflow", "inputs": [
        {"name": "cvUrl", "type": "string", "required": True}
    ]}
    from services.wire_form_workflow import _resolve_wiring
    r = _resolve_wiring(page, wf)
    assert r["field_map"] == {"cvUrl": "cvUrl"}
    assert r["input_sources"] == {
        "cvUrl": {"kind": "form_field", "field": "cvUrl"},
    }
    assert r["submit_action_patch"]["type"] == "dispatchWorkflow"
    assert r["submit_action_patch"]["workflow"] == "ParseCvWorkflow"
```

- [ ] **Step 2: implement `_resolve_wiring` — walk page for form fields, cross-reference workflow inputs, derive identity map, build patch payloads**

- [ ] **Step 3: write failing test — explicit field_map overrides identity derivation**

- [ ] **Step 4: implement + pass**

- [ ] **Step 5: write failing test — workflow input NOT covered by form fields returns `unresolved_input:<name>` error**

- [ ] **Step 6: implement + pass**

- [ ] **Step 7: write failing test — route-param input auto-resolved when page.route declares that param (e.g. `/candidates/[id]` + `input.name=id` → `source: route`)**

- [ ] **Step 8: implement + pass**

- [ ] **Step 9: commit — `feat(wire-form-workflow): pure resolver + input source derivation`**

### Task 2: File I/O + atomic write (TDD)

- [ ] **Step 1: write failing test — `wire_form_to_workflow(output_dir, page_route, workflow_name)` reads two files, patches, writes both atomically, returns WireResult(applied=True)**

- [ ] **Step 2: implement wire_form_to_workflow — use `atomic_apply.apply_bundle` for atomicity**

- [ ] **Step 3: write failing test — page not found returns applied=False, error="page_not_found:<route>"**

- [ ] **Step 4: implement + pass**

- [ ] **Step 5: write failing test — workflow not found returns applied=False, error="workflow_not_found:<name>"**

- [ ] **Step 6: implement + pass**

- [ ] **Step 7: verify no partial writes — if workflow write fails after page write succeeds, page must be rolled back**

- [ ] **Step 8: commit — `feat(wire-form-workflow): atomic file I/O + rollback`**

### Task 3: Plan.json mirroring (keep plan authoritative)

- [ ] **Step 1: write failing test — after `wire_form_to_workflow` runs, plan.json's `page.submit` reflects the wiring**

```python
def test_plan_json_mirrors_wiring():
    # setup: plan has FeedbackForm + ParseCvWorkflow, no submit declared
    # call: wire_form_to_workflow(...)
    # assert: reload plan.json → pages[FeedbackForm].submit = {kind:"workflow", target:"ParseCvWorkflow", field_map:{...}}
```

- [ ] **Step 2: implement `_mirror_to_plan(output_dir, page_route, workflow_name, field_map, input_sources)`**

- [ ] **Step 3: write failing test — plan.json's `workflow.source` reflects the wiring**

- [ ] **Step 4: implement + pass**

- [ ] **Step 5: write failing test — plan.json missing OR unreadable is a soft-fail (returns applied=True with a warning; plan is best-effort)**

- [ ] **Step 6: implement + pass**

- [ ] **Step 7: commit — `feat(wire-form-workflow): mirror wiring back to plan.json`**

### Task 4: Smith tool registration

**Files:**
- Modify: `backend/services/smith_tools.py`
- Modify: `backend/agents/smith_agent.py`
- Test: `backend/tests/test_smith_wire_tool.py`

- [ ] **Step 1: add `wire_form_to_workflow` to `TOOL_CATALOG` with description + input_schema**

```python
{
  "name": "wire_form_to_workflow",
  "description": (
    "Wire an existing form's submit to an existing workflow, so submitting "
    "the form dispatches the workflow. Use for retrofitting orphan workflows "
    "or connecting a manually-created page to a manually-created workflow. "
    "For NEW features that need both a form AND a workflow, use plan_and_apply."
  ),
  "input_schema": { "type": "object",
    "properties": {
      "page_route":    {"type": "string"},
      "workflow_name": {"type": "string"},
      "field_map":     {"type": "object"}
    },
    "required": ["page_route", "workflow_name"]
  }
}
```

- [ ] **Step 2: add handler `_smith_wire_form_to_workflow(output_dir, args)` in smith_tools.py**

- [ ] **Step 3: write failing test — Smith with a canned "wire ParseCvWorkflow to /candidates/new" ask picks this tool**

- [ ] **Step 4: update `agents/smith_agent.py::_ROUTING_RULES` — add row for surgical wiring asks**

```
Wire an EXISTING form to an          → wire_form_to_workflow(page_route,
  EXISTING workflow (retrofit an       workflow_name, field_map?)
  orphan workflow, connect a
  manually-authored form to a
  workflow)
```

- [ ] **Step 5: verify tool dispatches correctly with a mock LLM**

- [ ] **Step 6: commit — `feat(smith): wire_form_to_workflow tool`**

### Task 5: Live acceptance on 4ct3h8z2 orphans

- [ ] **Step 1: pick a live orphan — recommend `parsecvworkflow` (natural candidate: fire when CV uploaded on `/candidates/new`)**

- [ ] **Step 2: open Forge chat for `4ct3h8z2` (project 664bac9a-...)**

- [ ] **Step 3: send ask: `"wire parsecvworkflow to /candidates/new"`**

- [ ] **Step 4: verify Smith picks `wire_form_to_workflow` tool (not edit_page / add_workflow)**

- [ ] **Step 5: verify — reload `/candidates/new` in the running app on :3001 — submitting the form now dispatches parsecvworkflow. Check workflow run history.**

- [ ] **Step 6: verify — cd output/4ct3h8z2 && git diff HEAD~1 shows page schema submit-button change + workflow trigger declaration**

- [ ] **Step 7: verify — plan.json now has page.submit + workflow.source for this pair**

- [ ] **Step 8: commit acceptance notes + declare Slice C complete**

---

## Success criteria

1. `wire_form_to_workflow(...)` seam ships as a standalone Python module with 100% unit test coverage
2. Smith can call it via chat asks and correctly retrofit an orphan workflow
3. Both artifacts (page schema + workflow file) update atomically — no half-wired states
4. plan.json's SUBMIT-AUTHORITY declarations mirror the wiring
5. Live: at least 1 of the 10 orphans on 4ct3h8z2 is retrofitted end-to-end via Smith

## Rollout

- Ship additive — no existing behaviour changes
- Smith's routing prompt gets a new row; other rules unchanged
- No env flag needed — the tool is only invoked when Smith picks it

## Risk

- **Mis-wiring a form** — if the resolver misdetects the submit button or an input source, wiring may point at the wrong element. Mitigation: unit tests + a `dry_run: bool = True` flag on the seam that returns the patch payload without writing (later slice)
- **Overwriting user's manual customization** — the seam patches the submit button verbatim. If a user hand-edited the action, that edit is lost. Mitigation: seam preserves other button props; only rewrites `action`
- **Plan.json out of sync** — if plan write fails but file writes succeed, plan is stale. Mitigation: mirror runs LAST + soft-fails with a warning; next generation rebuilds plan.json from artifacts

## Open decisions

1. **What if the target form has NO submit button** (e.g. list page)? — Recommend: return `trigger_not_found`, don't auto-add a button.
2. **What if the workflow already has a trigger declared** (some other source)? — Recommend: OVERWRITE with the new source, log the previous one. User can pass an explicit `preserve_existing_source: True` flag later.
3. **`dry_run` flag in v1?** — Recommend: no, ship simple; add in a later iteration if UX demands it.
4. **Should `wire_form_to_workflow` also emit an event-emit action for event-driven wiring** (Task 3 spec mentions `event` param)? — Recommend: v1 handles `trigger=submit` only; event support ships in Slice B when we need it for whole-feature asks.
