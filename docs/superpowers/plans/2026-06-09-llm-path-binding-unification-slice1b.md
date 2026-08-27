# LLM-Path Binding Unification — Slice 1b Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make the deterministic binding pass wire buttons→workflows for prompt/LLM-generated apps (not just Figma), driven by per-page `actions[]` the planner declares.

**Architecture:** Planner emits machine-readable per-page `actions[]` (Part A); a new adapter builds `page_intent` from the LLM plan (Part B); `apply_bindings` idempotency is split per-concern so buttons get wired even when the page already has data binding (Part C); a hook runs the pass in the LLM schema pipeline (Part D).

**Tech Stack:** Python 3, pytest. Reuses `backend/services/schema_binding.py` from Slice 1. Runtime unchanged.

**Spec:** `docs/superpowers/specs/2026-06-09-llm-path-binding-unification-slice1b-design.md`

**Reference shapes:**
- `page_intent` (consumed by `apply_bindings`): `{file, entity, actions:[{label, workflow, kind:"row_action"|"page_action"}]}`
- LLM plan page (after `_annotate_page_types`): `{route, name, type, entity, actions?:[...], file?}`
- LLM plan top-level: `{pages:[...], data_models:[{name, fields:[{name,...}]}], workflows:[{name,...}], api_strategy?:{<Entity>:{workflow_actions:[{action,workflow,trigger,ui_location}]}}}`
- LLM page schema: top-level `root` (object); buttons `{type:"Button", props:{label, navigate?}}`; lists already have `Repeat`/`bind`/`dataSources`.

**Test command (from `backend/`):** `python3 -m pytest tests/services/<file> -v`

---

### Task 1: Adapter `build_page_intent` (Part B)

**Files:**
- Create: `backend/services/llm_plan_binding_adapter.py`
- Test: `backend/tests/services/test_llm_plan_binding_adapter.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_llm_plan_binding_adapter.py
from services.llm_plan_binding_adapter import build_page_intent

_PLAN = {
    "data_models": [{"name": "LeaveRequest", "fields": [{"name": "id"}]}],
    "workflows": [{"name": "LeaveApprovalWorkflow"}],
}


def test_passthrough_validated_page_actions():
    page = {"route": "/leave-requests", "file": "src/schemas/leave-requests.json",
            "entity": "LeaveRequest", "actions": [
                {"label": "Approve", "workflow": "LeaveApprovalWorkflow", "kind": "row_action"},
                {"label": "Bad", "workflow": "GhostWorkflow", "kind": "row_action"},
                {"label": "WrongKind", "workflow": "LeaveApprovalWorkflow", "kind": "nope"},
            ]}
    intent = build_page_intent(page, _PLAN)
    assert intent["entity"] == "LeaveRequest"
    assert intent["file"] == "src/schemas/leave-requests.json"
    # bad workflow + bad kind dropped
    assert intent["actions"] == [
        {"label": "Approve", "workflow": "LeaveApprovalWorkflow", "kind": "row_action"}]


def test_derive_from_api_strategy_when_no_page_actions():
    page = {"route": "/leave-requests", "entity": "LeaveRequest"}
    plan = {**_PLAN, "api_strategy": {"LeaveRequest": {"workflow_actions": [
        {"trigger": "button:Approve", "workflow": "LeaveApprovalWorkflow", "ui_location": "list_page"},
        {"trigger": "button:Audit", "workflow": "LeaveApprovalWorkflow", "ui_location": "detail_page"},
    ]}}}
    intent = build_page_intent(page, plan)
    assert intent["actions"] == [
        {"label": "Approve", "workflow": "LeaveApprovalWorkflow", "kind": "row_action"},
        {"label": "Audit", "workflow": "LeaveApprovalWorkflow", "kind": "page_action"},
    ]


def test_empty_when_no_source():
    page = {"route": "/x", "entity": "LeaveRequest"}
    intent = build_page_intent(page, _PLAN)
    assert intent["actions"] == []
    assert intent["file"] == "src/schemas/x.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_llm_plan_binding_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/llm_plan_binding_adapter.py
"""Adapter: build a binding page_intent from an LLM/prompt plan.

The deterministic binding pass (services/schema_binding.apply_bindings) consumes
a page_intent of {file, entity, actions:[{label, workflow, kind}]}. For the LLM
path we source `actions` from the planner-declared `page["actions"]`, falling
back to `plan["api_strategy"][entity]["workflow_actions"]` when present.
"""
from __future__ import annotations

_ALLOWED_KINDS = ("row_action", "page_action")


def _slug(route: str) -> str:
    return (route or "/").strip("/").replace("/", "-") or "home"


def _known_workflows(plan: dict) -> set[str]:
    return {w["name"] for w in (plan.get("workflows") or [])
            if isinstance(w, dict) and w.get("name")}


def _from_page_actions(page: dict, known: set[str]) -> list[dict]:
    out: list[dict] = []
    for a in page.get("actions") or []:
        if (isinstance(a, dict) and a.get("label") and a.get("workflow") in known
                and a.get("kind") in _ALLOWED_KINDS):
            out.append({"label": a["label"], "workflow": a["workflow"], "kind": a["kind"]})
    return out


def _from_api_strategy(page: dict, plan: dict, known: set[str]) -> list[dict]:
    entity = page.get("entity")
    strat = ((plan.get("api_strategy") or {}).get(entity) or {}) if entity else {}
    out: list[dict] = []
    for wa in strat.get("workflow_actions") or []:
        if not isinstance(wa, dict):
            continue
        trig = wa.get("trigger") or ""
        label = trig.split("button:", 1)[1].strip() if "button:" in trig else None
        workflow = wa.get("workflow")
        if not label or workflow not in known:
            continue
        kind = "row_action" if wa.get("ui_location") == "list_page" else "page_action"
        out.append({"label": label, "workflow": workflow, "kind": kind})
    return out


def build_page_intent(page: dict, plan: dict) -> dict:
    """Return {file, entity, actions} for the binding pass. Prefers
    planner-declared page['actions']; else derives from api_strategy. Drops
    actions whose workflow isn't declared or whose kind is invalid."""
    known = _known_workflows(plan)
    actions = _from_page_actions(page, known)
    if not actions:
        actions = _from_api_strategy(page, plan, known)
    return {
        "file": page.get("file") or f"src/schemas/{_slug(page.get('route', ''))}.json",
        "entity": page.get("entity"),
        "actions": actions,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_llm_plan_binding_adapter.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/llm_plan_binding_adapter.py backend/tests/services/test_llm_plan_binding_adapter.py
git commit -m "feat(binding): LLM-plan -> page_intent adapter"
```

---

### Task 2: Per-concern idempotency in `apply_bindings` (Part C)

**Files:**
- Modify: `backend/services/schema_binding.py` (the `apply_bindings` function)
- Modify: `backend/tests/services/test_schema_binding.py` (update the idempotency test to new semantics; add an LLM-shaped test)

- [ ] **Step 1: Update the idempotency test + add an LLM-shaped test (these fail first)**

Replace the existing `test_apply_bindings_idempotent` body with the version below, and add the new `test_apply_bindings_wires_buttons_when_list_already_bound`:

```python
def test_apply_bindings_idempotent():
    once, _ = apply_bindings(_drivers_schema(), _page_intent(), _plan())
    twice, report = apply_bindings(copy.deepcopy(once), _page_intent(), _plan())
    assert twice == once                 # nothing changes on re-run
    assert report["list_skipped"] is True
    assert report["buttons_bound"] == 0


def test_apply_bindings_wires_buttons_when_list_already_bound():
    # LLM-shaped: page already has a dataSource + a Repeat (data bound by the
    # page agent), but the row button has no workflow yet.
    schema = {
        "schemaVersion": "2", "id": "drivers",
        "dataSources": [{"name": "driver", "entity": "Driver", "op": "list"}],
        "root": {"id": "r", "type": "Stack", "children": [
            {"id": "rep", "type": "Repeat", "bind": "driver", "children": [
                {"id": "row", "type": "Card", "children": [
                    {"id": "nm", "type": "Text", "props": {"content": "{{item.name}}"}},
                    {"id": "btn", "type": "Button", "props": {"label": "Approve"}},
                ]},
            ]},
        ]},
    }
    out, report = apply_bindings(schema, _page_intent(), _plan())
    btn = next(n for n in iter_nodes(out) if n.get("id") == "btn")
    assert btn["props"]["workflow"] == "ApproveDriver"
    assert btn["props"]["args"] == {"id": "{{item.id}}"}
    assert report["list_skipped"] is True       # data binding left intact
    assert report["buttons_bound"] == 1
    # existing dataSource untouched
    assert out["dataSources"] == [{"name": "driver", "entity": "Driver", "op": "list"}]
```

Note: `_page_intent()`/`_plan()`/`_drivers_schema()` are the existing helpers in the test file; `_page_intent()` already declares an `Approve` row_action → `ApproveDriver`.

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_binding.py -k "idempotent or wires_buttons" -v`
Expected: FAIL — `test_apply_bindings_idempotent` fails on missing `list_skipped`; the new test fails because the current top-level guard skips the whole page (button not wired).

- [ ] **Step 3: Refactor `apply_bindings`**

Replace the current `apply_bindings` body (the `already_bound` short-circuit + the rest) with:

```python
def apply_bindings(schema: dict, page_intent: dict, plan: dict) -> tuple[dict, dict]:
    """Apply list + button binding for one page, with PER-CONCERN idempotency:
    list binding is skipped when the page already has data binding (dataSources
    or any Repeat), but button binding still runs (apply_button_bindings skips
    only buttons that already carry props.workflow). validate-or-fallback reverts
    the whole page to the input on a structurally-invalid result."""
    import copy as _copy
    route = (page_intent or {}).get("file") or schema.get("id")
    original = _copy.deepcopy(schema)

    list_already = bool(schema.get("dataSources")) or any(
        n.get("type") == "Repeat" for n in iter_nodes(schema)
    )
    entity_def = _entity_def(plan, (page_intent or {}).get("entity"))
    if list_already:
        work, list_info = schema, {"bound": False, "reason": "already bound"}
    else:
        work, list_info = apply_list_binding(schema, page_intent, entity_def)

    work, btn_info = apply_button_bindings(work, page_intent)

    if not _is_structurally_valid(work):
        return original, {"route": route, "list_bound": False, "list_skipped": list_already,
                          "buttons_bound": 0, "buttons_unbound": 0, "reverted": True}

    return work, {
        "route": route,
        "reverted": False,
        "list_bound": bool(list_info.get("bound")),
        "list_skipped": list_already,
        "list_reason": list_info.get("reason"),
        "buttons_bound": len(btn_info.get("bound") or []),
        "buttons_unbound": len(btn_info.get("unbound") or []),
    }
```

(Leave `apply_list_binding`, `apply_button_bindings`, `_entity_def`, `_is_structurally_valid`, `iter_nodes` unchanged.)

- [ ] **Step 4: Run the full schema_binding suite**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_binding.py -v`
Expected: PASS — all existing Figma tests (the fully-unbound page still binds list+buttons; the Cemex E2E still passes), the updated idempotency test, and the new LLM-shaped test. (~25 tests.)

- [ ] **Step 5: Commit**

```bash
git add backend/services/schema_binding.py backend/tests/services/test_schema_binding.py
git commit -m "feat(binding): per-concern idempotency (wire buttons even when data bound)"
```

---

### Task 3: Planner declares per-page `actions[]` (Part A)

**Files:**
- Modify: `backend/agents/planner.py` — add a deterministic `_sanitize_page_actions(plan)` helper, call it from `_annotate_page_types`, and add an `actions[]` instruction to the planner system prompt (pages section).
- Test: `backend/tests/agents/test_planner_actions.py` (new; match the import/run style of existing planner tests if any, else this standalone unit test of the pure helper).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/test_planner_actions.py
from agents.planner import _sanitize_page_actions


def test_sanitize_keeps_valid_drops_invalid():
    plan = {
        "workflows": [{"name": "ApproveWF"}],
        "pages": [
            {"route": "/r", "entity": "R", "actions": [
                {"label": "Approve", "workflow": "ApproveWF", "kind": "row_action"},
                {"label": "Ghost", "workflow": "MissingWF", "kind": "row_action"},
                {"label": "NoKind", "workflow": "ApproveWF"},
                {"workflow": "ApproveWF", "kind": "page_action"},   # no label
            ]},
            {"route": "/q", "entity": "Q"},                          # no actions
        ],
    }
    out = _sanitize_page_actions(plan)
    assert out["pages"][0]["actions"] == [
        {"label": "Approve", "workflow": "ApproveWF", "kind": "row_action"}]
    assert out["pages"][1]["actions"] == []    # normalized to empty list


def test_sanitize_is_safe_on_missing_pages():
    assert _sanitize_page_actions({}) == {}          # no pages → unchanged
    assert _sanitize_page_actions({"pages": "nope"}) == {"pages": "nope"}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_planner_actions.py -v`
Expected: FAIL with `ImportError: cannot import name '_sanitize_page_actions'`

- [ ] **Step 3: Implement the sanitizer + wire it into `_annotate_page_types`**

Add this helper to `backend/agents/planner.py` (near `_annotate_page_types`):

```python
_ALLOWED_ACTION_KINDS = ("row_action", "page_action")


def _sanitize_page_actions(plan: dict) -> dict:
    """Normalize per-page `actions[]`: keep only well-formed actions whose
    `workflow` is declared in plan['workflows'] and whose `kind` is allowed;
    set `actions: []` on pages that have none. Mutates and returns plan."""
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return plan
    known = {w["name"] for w in (plan.get("workflows") or [])
             if isinstance(w, dict) and w.get("name")}
    for p in pages:
        if not isinstance(p, dict):
            continue
        clean = []
        for a in p.get("actions") or []:
            if (isinstance(a, dict) and a.get("label") and a.get("workflow") in known
                    and a.get("kind") in _ALLOWED_ACTION_KINDS):
                clean.append({"label": a["label"], "workflow": a["workflow"], "kind": a["kind"]})
        p["actions"] = clean
    return plan
```

Then call it at the END of `_annotate_page_types`, right before `return plan`:

```python
    plan = _sanitize_page_actions(plan)
    return plan
```

Finally, in the planner SYSTEM PROMPT's `pages[]` description (locate the
`"pages": [ ... ]` example around line 212), add `actions` to the page object so
the model emits it. Append to the page example and add an instruction line:

```
  "pages": [
    {"route": "/resource", "name": "ResourceListPage", "type": "list", "entity": "Resource",
     "description": "...",
     "actions": [
       {"label": "Approve", "workflow": "ResourceApprovalWorkflow", "kind": "row_action"},
       {"label": "Reject",  "workflow": "ResourceApprovalWorkflow", "kind": "row_action"}
     ]}
  ],
```

And add a bullet to the planner's rules (near the existing workflow_actions
guidance): `For every page whose entity has workflows, include an "actions" array
of {label, workflow, kind} where label is the EXACT button text, workflow is one
you declared in "workflows", and kind is "row_action" (a button repeated per
list row) or "page_action". Pages with no actions use [].`

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_planner_actions.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Confirm planner still imports + parses**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "import ast; ast.parse(open('agents/planner.py').read()); print('planner OK')"`
Expected: `planner OK`

- [ ] **Step 6: Commit**

```bash
git add backend/agents/planner.py backend/tests/agents/test_planner_actions.py
git commit -m "feat(binding): planner declares + sanitizes per-page actions[]"
```

---

### Task 4: Hook the binding pass into the LLM pipeline (Part D)

**Files:**
- Modify: `backend/services/schema_pipeline.py` — after each page schema is written (around the `run_page_schema_agent` call, ~line 131), apply the binding pass. Aggregate a `binding-report.json` at the output root.

First READ `backend/services/schema_pipeline.py` around `_emit_per_page` / the `run_page_schema_agent` call to see the exact variable names (`output_dir`, `plan`, `page`, the schema file path it writes) and whether the loop is sync or async-generator. Match that style.

- [ ] **Step 1: Add the binding application after each page schema is written**

After the schema agent writes a page's schema to disk, add (adjust variable names to the file's actuals — `out_dir`/`output_dir`, the `schema_path` it wrote):

```python
        # ── Plan-driven binding (LLM path) ───────────────────────────────────
        # Wire row/page action buttons to workflows declared in the plan. The
        # page agent already emits data binding (dataSources/Repeat); the
        # per-concern idempotency in apply_bindings leaves that intact and only
        # adds missing button workflow/args.
        try:
            from services.schema_binding import apply_bindings
            from services.llm_plan_binding_adapter import build_page_intent
            import json as _json
            _schema_file = Path(output_dir) / (page.get("file") or f"src/schemas/{_slug}.json")
            if _schema_file.exists():
                _schema = _json.loads(_schema_file.read_text())
                _intent = build_page_intent(page, plan)
                _bound, _report = apply_bindings(_schema, _intent, plan)
                _schema_file.write_text(_json.dumps(_bound, indent=2))
                _BINDING_REPORTS.append(_report)
        except Exception as _bind_ex:
            logger.warning("[Binding][LLM] %s skipped: %s", page.get("route"), _bind_ex)
```

Where `_slug` is the page's route slug already computed in that loop (or compute
`(page.get("route","/").strip("/").replace("/","-") or "home")`). Declare
`_BINDING_REPORTS: list = []` before the page loop, and after the loop write it:

```python
    try:
        (Path(output_dir) / "binding-report.json").write_text(
            __import__("json").dumps(_BINDING_REPORTS, indent=2))
    except Exception:
        pass
```

Ensure `Path` and `logger` are imported in the module (add `from pathlib import Path` / a module logger if absent, matching the file's existing imports).

- [ ] **Step 2: Verify the module parses + imports**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "import ast; ast.parse(open('services/schema_pipeline.py').read()); print('schema_pipeline OK')"`
Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "from services import schema_pipeline; print('import OK')"`
Expected: both print OK.

- [ ] **Step 3: Commit**

```bash
git add backend/services/schema_pipeline.py
git commit -m "feat(binding): run plan-driven binding pass in LLM schema pipeline"
```

---

### Task 5: End-to-end integration smoke

**Files:**
- Test: `backend/tests/services/test_llm_plan_binding_adapter.py` (add an integration test exercising adapter → apply_bindings together)

- [ ] **Step 1: Write the test**

```python
def test_adapter_plus_apply_bindings_wires_llm_button():
    from services.schema_binding import apply_bindings, iter_nodes
    plan = {
        "data_models": [{"name": "Driver", "fields": [{"name": "id"}, {"name": "name"}]}],
        "workflows": [{"name": "ApproveDriver"}],
        "pages": [{"route": "/drivers", "entity": "Driver",
                   "file": "src/schemas/drivers.json",
                   "actions": [{"label": "Approve", "workflow": "ApproveDriver", "kind": "row_action"}]}],
    }
    page = plan["pages"][0]
    # LLM-shaped schema: data already bound, button not yet wired.
    schema = {"schemaVersion": "2", "id": "drivers",
              "dataSources": [{"name": "driver", "entity": "Driver", "op": "list"}],
              "root": {"id": "r", "type": "Stack", "children": [
                  {"id": "rep", "type": "Repeat", "bind": "driver", "children": [
                      {"id": "row", "type": "Card", "children": [
                          {"id": "btn", "type": "Button", "props": {"label": "Approve"}}]}]}]}}
    intent = build_page_intent(page, plan)
    out, report = apply_bindings(schema, intent, plan)
    btn = next(n for n in iter_nodes(out) if n.get("id") == "btn")
    assert btn["props"]["workflow"] == "ApproveDriver"
    assert btn["props"]["args"] == {"id": "{{item.id}}"}
    assert report["buttons_bound"] == 1 and report["list_skipped"] is True
```

- [ ] **Step 2: Run the full binding test set**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_llm_plan_binding_adapter.py tests/services/test_schema_binding.py tests/services/test_figma_plan_binding.py tests/agents/test_planner_actions.py -v`
Expected: ALL pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/services/test_llm_plan_binding_adapter.py
git commit -m "test(binding): adapter + apply_bindings LLM-path integration"
```

---

## Manual verification (after all tasks)

1. Restart the backend so the planner/pipeline changes load.
2. Generate a prompt app whose domain implies workflows (e.g. "leave request approval system"). At plan time, confirm the plan's pages carry `actions:[{label, workflow, kind}]`.
3. After build, inspect a list page schema in `output/<id>/src/schemas/*.json`: the row action button now has `props.workflow` + `props.args:{id:"{{item.id}}"}`, and the page agent's `dataSources`/`Repeat` are unchanged.
4. Check `output/<id>/binding-report.json` for `buttons_bound` > 0 and `list_skipped: true`.

## Out of scope (later slices)

- Detail-page action arg sourcing (record id from route/`op:"get"`, not `{{item.id}}`).
- `visible_when` conditional visibility.
- Forms (create/update submit) wiring.
