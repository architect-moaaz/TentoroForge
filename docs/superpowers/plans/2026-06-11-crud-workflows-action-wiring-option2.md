# CRUD Workflows + Full Action Wiring (Option 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every nav/create/update/delete/process button maps to a real backend — a `navigate` target or a generated, dispatchable workflow.

**Architecture:** Deterministic CRUD workflow generation + per-page-type action derivation + form-submit wiring (Parts A–C), then an LLM completeness guard (Part D) that ties any remaining actionable button to a validated backend. Reuses the Slice-1/1b binding pass.

**Tech Stack:** Python 3, pytest. Generated-app runtime unchanged (the `db_*` workflow handlers already exist).

**Spec:** `docs/superpowers/specs/2026-06-11-crud-workflows-action-wiring-option2-design.md`

**Grounded shapes (reference):**
- Workflow JSON: `{"id", "name", "description", "processVariables":[{"name","type","required"}], "definition":{"nodes":[...], "edges":[...]}}`
- Node: `{"id","type","position":{"x","y"},"data":{"config":{...},"label":"..."}}`; action node `type:"action"`, config `{"actionType":"db_insert|db_update|db_delete","table","where":{col:procVar},"values":{col:procVar}}`; trigger node `type:"trigger"`, config `{"type":"manual"}`; end node `type:"end"`.
- `where`/`values` map a column name → a process-variable name (resolved from workflow input at runtime).
- Entity table name: `plan["entities"][Name]["table"]` (snake_case plural). Fields: `plan["entities"][Name]["fields"]` (list of `{name,type}`) or registry `entities[Name]["fields"]` (dict).
- Binding `page_intent.actions[]`: `{label, workflow, kind}` where kind ∈ `row_action`|`page_action` (this plan ADDS `navigate`).

**Test command (from `backend/`):** `python3 -m pytest tests/<path> -v`

---

## Group A — Deterministic CRUD workflow generator

### Task 1: `build_crud_workflow` (one entity, one op)

**Files:**
- Create: `backend/services/crud_workflow_generator.py`
- Test: `backend/tests/services/test_crud_workflow_generator.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_crud_workflow_generator.py
from services.crud_workflow_generator import build_crud_workflow

_FIELDS = [
    {"name": "id", "type": "uuid"},
    {"name": "title", "type": "varchar"},
    {"name": "status", "type": "varchar"},
    {"name": "createdAt", "type": "timestamp"},
    {"name": "updatedAt", "type": "timestamp"},
]


def test_create_workflow_inserts_writable_fields():
    wf = build_crud_workflow("Task", "tasks", _FIELDS, "create")
    assert wf["name"] == "CreateTask"
    nodes = wf["definition"]["nodes"]
    action = next(n for n in nodes if n["type"] == "action")
    cfg = action["data"]["config"]
    assert cfg["actionType"] == "db_insert"
    assert cfg["table"] == "tasks"
    # writable fields only (no id / timestamps)
    assert set(cfg["values"].keys()) == {"title", "status"}
    assert cfg["values"]["title"] == "title"
    # trigger -> action -> end, fully connected
    assert {n["type"] for n in nodes} == {"trigger", "action", "end"}
    assert len(wf["definition"]["edges"]) == 2
    # process variables cover the writable fields
    assert {p["name"] for p in wf["processVariables"]} == {"title", "status"}


def test_update_workflow_sets_where_id_and_values():
    wf = build_crud_workflow("Task", "tasks", _FIELDS, "update")
    assert wf["name"] == "UpdateTask"
    cfg = next(n for n in wf["definition"]["nodes"] if n["type"] == "action")["data"]["config"]
    assert cfg["actionType"] == "db_update"
    assert cfg["where"] == {"id": "id"}
    assert set(cfg["values"].keys()) == {"title", "status"}
    assert {p["name"] for p in wf["processVariables"]} == {"id", "title", "status"}


def test_delete_workflow_where_id_only():
    wf = build_crud_workflow("Task", "tasks", _FIELDS, "delete")
    assert wf["name"] == "DeleteTask"
    cfg = next(n for n in wf["definition"]["nodes"] if n["type"] == "action")["data"]["config"]
    assert cfg["actionType"] == "db_delete"
    assert cfg["where"] == {"id": "id"}
    assert "values" not in cfg
    assert {p["name"] for p in wf["processVariables"]} == {"id"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_crud_workflow_generator.py -k "create_workflow or update_workflow or delete_workflow" -v`
Expected: FAIL with `ModuleNotFoundError`/`ImportError`.

- [ ] **Step 3: Implement**

```python
# backend/services/crud_workflow_generator.py
"""Deterministic CRUD workflow generation.

For each entity, emit Create/Update/Delete<Entity> workflow definitions whose
single action node runs db_insert/db_update/db_delete. Shape matches the runtime
workflow contract (node.data.config.actionType + table + where/values maps of
column -> process-variable). Mechanical — no LLM, so no hallucinated names.
"""
from __future__ import annotations

from typing import Any

# Columns the platform manages itself — never user-supplied on create/update.
_MANAGED = {"id", "createdat", "updatedat", "created_at", "updated_at"}


def _writable(fields: list[dict]) -> list[str]:
    out = []
    for f in fields or []:
        name = f.get("name") if isinstance(f, dict) else None
        if name and name.lower() not in _MANAGED:
            out.append(name)
    return out


def _node(node_id: str, ntype: str, x: int, config: dict, label: str) -> dict:
    return {"id": node_id, "type": ntype, "position": {"x": x, "y": 0},
            "data": {"config": config, "label": label}}


def build_crud_workflow(entity: str, table: str, fields: list[dict], op: str) -> dict:
    """Build one CRUD workflow dict. op in {create, update, delete}."""
    writable = _writable(fields)
    op_cap = op.capitalize()
    name = f"{op_cap}{entity}"
    slug = f"{op}-{entity.lower()}"

    if op == "create":
        config = {"actionType": "db_insert", "table": table,
                  "values": {f: f for f in writable}}
        pvars = writable
        action_type = "db_insert"
    elif op == "update":
        config = {"actionType": "db_update", "table": table,
                  "where": {"id": "id"}, "values": {f: f for f in writable}}
        pvars = ["id", *writable]
        action_type = "db_update"
    elif op == "delete":
        config = {"actionType": "db_delete", "table": table, "where": {"id": "id"}}
        pvars = ["id"]
        action_type = "db_delete"
    else:
        raise ValueError(f"unknown crud op: {op}")

    nodes = [
        _node("trigger", "trigger", 0, {"type": "manual"}, "Start"),
        _node(action_type, "action", 200, config, f"{op_cap} {entity}"),
        _node("end", "end", 400, {}, "End"),
    ]
    edges = [
        {"id": "e_trigger_action", "source": "trigger", "target": action_type},
        {"id": "e_action_end", "source": action_type, "target": "end"},
    ]
    process_vars = [{"name": p, "type": "string", "required": True} for p in pvars]
    return {
        "id": slug,
        "name": name,
        "description": f"{op_cap} a {entity} record.",
        "processVariables": process_vars,
        "definition": {"nodes": nodes, "edges": edges},
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_crud_workflow_generator.py -v`
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add backend/services/crud_workflow_generator.py backend/tests/services/test_crud_workflow_generator.py
git commit -m "feat(crud): build_crud_workflow (deterministic create/update/delete defs)"
```

---

### Task 2: `generate_crud_workflows` — write files, idempotent

**Files:**
- Modify: `backend/services/crud_workflow_generator.py`
- Test: `backend/tests/services/test_crud_workflow_generator.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path
from services.crud_workflow_generator import generate_crud_workflows


def _plan():
    return {"entities": {
        "Task": {"table": "tasks", "fields": [
            {"name": "id", "type": "uuid"}, {"name": "title", "type": "varchar"}]},
        "Tag": {"fields": [{"name": "id"}, {"name": "label"}]},  # no table -> derive
    }}


def test_generate_writes_three_per_entity(tmp_path):
    created = generate_crud_workflows(_plan(), str(tmp_path))
    files = {p.name for p in (tmp_path / "workflows").glob("*.json")}
    assert "CreateTask.json" in files and "UpdateTask.json" in files and "DeleteTask.json" in files
    assert "CreateTag.json" in files  # table derived as "tags"
    cfg = json.loads((tmp_path / "workflows" / "CreateTag.json").read_text())
    table = next(n for n in cfg["definition"]["nodes"] if n["type"] == "action")["data"]["config"]["table"]
    assert table == "tags"
    assert "CreateTask" in created


def test_generate_does_not_overwrite_existing_nonempty(tmp_path):
    wdir = tmp_path / "workflows"; wdir.mkdir()
    existing = {"id": "create-task", "name": "CreateTask",
                "definition": {"nodes": [{"id": "x", "type": "action"}], "edges": []}}
    (wdir / "CreateTask.json").write_text(json.dumps(existing))
    generate_crud_workflows(_plan(), str(tmp_path))
    # untouched (still the 1-node hand version)
    assert json.loads((wdir / "CreateTask.json").read_text())["definition"]["nodes"][0]["id"] == "x"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_crud_workflow_generator.py -k generate -v`
Expected: FAIL with `ImportError: cannot import name 'generate_crud_workflows'`.

- [ ] **Step 3: Implement**

```python
import json
import re
from pathlib import Path


def _derive_table(entity: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", entity).lower()
    return s if s.endswith("s") else s + "s"


def generate_crud_workflows(plan: dict, output_dir: str) -> list[str]:
    """Write Create/Update/Delete<Entity>.json for each entity into
    output_dir/workflows/. Idempotent: never overwrite a workflow file that
    already has nodes (a domain/bizlogic workflow). Returns names written."""
    entities = (plan or {}).get("entities") or {}
    wdir = Path(output_dir) / "workflows"
    wdir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for name, info in entities.items():
        if not isinstance(info, dict):
            continue
        table = info.get("table") or _derive_table(name)
        fields = info.get("fields")
        if isinstance(fields, dict):  # registry shape -> list
            fields = [{"name": k, **(v or {})} for k, v in fields.items()]
        for op in ("create", "update", "delete"):
            wf = build_crud_workflow(name, table, fields or [], op)
            dest = wdir / f"{wf['name']}.json"
            if dest.exists():
                try:
                    prev = json.loads(dest.read_text())
                    if (prev.get("definition") or {}).get("nodes"):
                        continue  # has real content already
                except Exception:
                    pass
            dest.write_text(json.dumps(wf, indent=2))
            written.append(wf["name"])
    return written
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_crud_workflow_generator.py -v`
Expected: PASS (5).

- [ ] **Step 5: Commit**

```bash
git add backend/services/crud_workflow_generator.py backend/tests/services/test_crud_workflow_generator.py
git commit -m "feat(crud): generate_crud_workflows (idempotent file emit + table derive)"
```

---

### Task 3: Hook CRUD generation into both pipelines

**Files:**
- Modify: `backend/routers/generate.py`

READ how the registry/plan entities are available in `_run_relay_pipeline` and `_run_figma_relay_pipeline` after the schema phase (grep `merge_section(registry, "entities"` and the existing workflow-definition generation `generate_workflow_definitions`). Add the CRUD call right AFTER the existing workflow-definition generation in BOTH pipelines, passing the plan (which carries `entities` with `table`/`fields`). If the plan lacks `entities` but the registry has them, pass a merged dict `{"entities": registry.get("entities")}`.

- [ ] **Step 1: Add the hook after `generate_workflow_definitions` (both pipelines)**

```python
        # Deterministic CRUD workflows — Create/Update/Delete<Entity> so action
        # buttons have a real workflow to dispatch (idempotent; won't clobber
        # domain workflows).
        try:
            from services.crud_workflow_generator import generate_crud_workflows
            _crud_plan = plan if (plan or {}).get("entities") else {"entities": (registry or {}).get("entities") or {}}
            _crud_written = generate_crud_workflows(_crud_plan, output_dir)
            if _crud_written:
                yield sse_event("log", {"text": f"[CRUD] generated {len(_crud_written)} workflow(s): {', '.join(_crud_written[:6])}"})
        except Exception as _crud_ex:
            yield sse_event("log", {"text": f"[CRUD] generation skipped: {_crud_ex}"})
```

Locate `generate_workflow_definitions(` in `generate.py` (grep it) and insert the block immediately after each call site (there should be one per pipeline; if the figma pipeline reuses the same code path, one insertion may cover both — verify by grep).

- [ ] **Step 2: Verify it parses + imports**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "import ast; ast.parse(open('routers/generate.py').read()); print('OK')"`
Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "from services.crud_workflow_generator import generate_crud_workflows; print('ok')"`
Expected: both OK.

- [ ] **Step 3: Commit**

```bash
git add backend/routers/generate.py
git commit -m "feat(crud): generate CRUD workflows in both relay pipelines"
```

---

## Group B — CRUD action derivation + binding `navigate` kind

### Task 4: `derive_crud_actions`

**Files:**
- Create: `backend/services/crud_actions.py`
- Test: `backend/tests/services/test_crud_actions.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_crud_actions.py
from services.crud_actions import derive_crud_actions

_WF = {"CreateTask", "UpdateTask", "DeleteTask"}
_PAGES = [
    {"route": "/tasks", "type": "list", "entity": "Task"},
    {"route": "/tasks/new", "type": "form", "entity": "Task"},
    {"route": "/tasks/:id", "type": "detail", "entity": "Task"},
]


def test_list_page_gets_new_nav_and_row_delete():
    acts = derive_crud_actions(_PAGES[0], "Task", _WF, _PAGES)
    kinds = {(a["label"], a["kind"], a.get("workflow"), a.get("to")) for a in acts}
    assert ("New", "navigate", None, "/tasks/new") in kinds
    assert ("Delete", "row_action", "DeleteTask", None) in kinds


def test_detail_page_gets_edit_nav_and_delete():
    acts = derive_crud_actions(_PAGES[2], "Task", _WF, _PAGES)
    labels = {(a["label"], a["kind"]) for a in acts}
    assert ("Edit", "navigate") in labels
    assert ("Delete", "page_action") in labels


def test_only_targets_existing_workflows():
    acts = derive_crud_actions(_PAGES[0], "Task", set(), _PAGES)  # no workflows
    # Delete dropped (no DeleteTask); New nav still present (nav needs no workflow)
    assert all(a["kind"] == "navigate" for a in acts)


def test_form_and_entityless_pages_get_nothing():
    assert derive_crud_actions(_PAGES[1], "Task", _WF, _PAGES) == []
    assert derive_crud_actions({"route": "/x", "type": "dashboard", "entity": None}, None, _WF, _PAGES) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_crud_actions.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/services/crud_actions.py
"""Deterministic CRUD action derivation per page-type.

Given a page + its entity + the set of workflows that actually exist, return the
standard action buttons: navigate (New/Edit) and workflow (Delete). These merge
into the plan page's actions[] for the binding pass to wire. CRUD only — domain
process actions stay LLM-declared.
"""
from __future__ import annotations


def _form_route(entity: str, pages: list[dict], kind: str) -> str | None:
    """Find a form page route for this entity ('new'/'edit' heuristics)."""
    want = "new" if kind == "new" else "edit"
    for p in pages or []:
        if p.get("type") == "form" and p.get("entity") == entity:
            r = (p.get("route") or "").lower()
            if want in r or (want == "new" and "edit" not in r):
                return p.get("route")
    return None


def derive_crud_actions(page: dict, entity: str | None, existing_workflows: set,
                        pages: list[dict]) -> list[dict]:
    """Standard CRUD actions for a page. Each action is
    {label, kind, workflow?, to?}. Only emits Delete when Delete<Entity> exists;
    nav actions only when a target route exists."""
    if not entity:
        return []
    ptype = (page.get("type") or "").lower()
    out: list[dict] = []
    delete_wf = f"Delete{entity}"

    if ptype == "list":
        new_route = _form_route(entity, pages, "new")
        if new_route:
            out.append({"label": "New", "kind": "navigate", "to": new_route})
        if delete_wf in existing_workflows:
            out.append({"label": "Delete", "kind": "row_action", "workflow": delete_wf})
    elif ptype == "detail":
        edit_route = _form_route(entity, pages, "edit")
        if edit_route:
            out.append({"label": "Edit", "kind": "navigate", "to": edit_route})
        if delete_wf in existing_workflows:
            out.append({"label": "Delete", "kind": "page_action", "workflow": delete_wf})
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_crud_actions.py -v`
Expected: PASS (4).

- [ ] **Step 5: Commit**

```bash
git add backend/services/crud_actions.py backend/tests/services/test_crud_actions.py
git commit -m "feat(crud): derive_crud_actions per page-type (nav + delete)"
```

---

### Task 5: Binding understands a `navigate` action kind

**Files:**
- Modify: `backend/services/schema_binding.py` (`apply_button_bindings`)
- Test: `backend/tests/services/test_schema_binding.py`

- [ ] **Step 1: Write the failing test**

```python
import copy
from services.schema_binding import apply_button_bindings, iter_nodes


def test_navigate_action_sets_navigate_prop():
    schema = {"children": [{"id": "b", "type": "Button", "props": {"label": "New"}}]}
    intent = {"actions": [{"label": "New", "kind": "navigate", "to": "/tasks/new"}]}
    out, info = apply_button_bindings(copy.deepcopy(schema), intent)
    btn = next(n for n in iter_nodes(out) if n.get("id") == "b")
    assert btn["props"].get("navigate") == "/tasks/new"
    assert "workflow" not in btn["props"]
    assert "b" in info["bound"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_binding.py -k navigate_action -v`
Expected: FAIL (navigate prop not set / button reported unbound).

- [ ] **Step 3: Implement**

In `apply_button_bindings`, where an action is matched, handle the `navigate` kind BEFORE the workflow branch. Locate the block that currently does (roughly):

```python
                action = actions.get(normalize_label(node_text(node)))
                bid = node.get("id") or "?"
                if action:
                    props["workflow"] = action["workflow"]
                    if action.get("kind") == "row_action":
                        props["args"] = {"id": "{{item.id}}"}
                    bound.append(bid)
                else:
                    unbound.append(bid)
```

Replace the `if action:` body with:

```python
                if action:
                    if action.get("kind") == "navigate":
                        if action.get("to") and not props.get("navigate"):
                            props["navigate"] = action["to"]
                    elif action.get("workflow") and not props.get("workflow"):
                        props["workflow"] = action["workflow"]
                        if action.get("kind") == "row_action":
                            props["args"] = {"id": "{{item.id}}"}
                    bound.append(bid)
                else:
                    unbound.append(bid)
```

(Note: this also makes workflow wiring **fill-only-if-absent** — `not props.get("workflow")` — per the chosen behavior. The idempotency early-out `if "workflow" in props: pass` higher in the function still applies for already-workflow'd buttons; this guards the navigate/fill path.)

Also extend `_actions_by_label` (the dict builder) to include navigate actions (which have no `workflow`). Change its filter from requiring `a.get("workflow")` to: keep an action if it has a label AND (`workflow` OR kind == `navigate`).

- [ ] **Step 4: Run the whole schema_binding suite**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_binding.py -v`
Expected: PASS (existing + the new navigate test).

- [ ] **Step 5: Commit**

```bash
git add backend/services/schema_binding.py backend/tests/services/test_schema_binding.py
git commit -m "feat(crud): binding supports navigate action kind (fill-only-if-absent)"
```

---

### Task 6: Merge derived CRUD actions in the binding hooks

**Files:**
- Modify: `backend/services/schema_pipeline.py` (LLM-path binding hook) and `backend/routers/generate.py` (figma-path binding phase)
- Modify: `backend/services/llm_plan_binding_adapter.py` and/or `backend/services/figma_plan_binding.py` if needed so derived actions reach `page_intent`.

The simplest, single place: in the binding application (both paths), before calling `apply_bindings`, compute the merged actions and attach to the page dict. READ how each hook builds the page/intent (Slice-1b: `build_page_intent(page, plan)` for LLM path; figma uses `p` directly). Add a shared helper and call it.

- [ ] **Step 1: Add a merge helper to `crud_actions.py`**

```python
def merge_crud_into_page(page: dict, plan: dict, existing_workflows: set) -> dict:
    """Return a COPY of page whose actions[] include derived CRUD actions
    (appended, de-duped by (label, kind)). Non-mutating."""
    import copy as _copy
    entity = page.get("entity")
    derived = derive_crud_actions(page, entity, existing_workflows,
                                  (plan or {}).get("pages") or [])
    out = _copy.deepcopy(page)
    existing = out.get("actions") or []
    seen = {(a.get("label"), a.get("kind")) for a in existing if isinstance(a, dict)}
    out["actions"] = existing + [a for a in derived if (a["label"], a["kind"]) not in seen]
    return out
```

- [ ] **Step 2: Wire it in the LLM-path hook (`schema_pipeline.py`)**

In `_apply_plan_binding` (Slice-1b), before `build_page_intent(page, plan)`, compute the existing workflow set from disk and merge:

```python
    from services.crud_actions import merge_crud_into_page
    import os as _os
    _wf_dir = _os.path.join(output_dir, "workflows")
    _existing_wf = {f[:-5] for f in (_os.listdir(_wf_dir) if _os.path.isdir(_wf_dir) else []) if f.endswith(".json")}
    page = merge_crud_into_page(page, plan, _existing_wf)
```

(then the existing `build_page_intent(page, plan)` sees the merged actions). The Slice-1b adapter already passes `kind` through; ensure it also passes `to` for navigate actions — update `build_page_intent`'s action filter to keep `to` and accept kind `navigate`.

- [ ] **Step 3: Wire it in the figma-path binding phase (`generate.py`)**

In the figma BINDING PASS loop, before `apply_bindings(page_schema, p, plan)`:

```python
            from services.crud_actions import merge_crud_into_page
            import os as _os
            _wfd = _os.path.join(output_dir, "workflows")
            _exwf = {f[:-5] for f in (_os.listdir(_wfd) if _os.path.isdir(_wfd) else []) if f.endswith(".json")}
            p = merge_crud_into_page(p, plan, _exwf)
```

- [ ] **Step 4: Verify both modules parse + the binding adapter passes `to`/`navigate`**

Add/confirm a test in `test_llm_plan_binding_adapter.py`:

```python
def test_build_page_intent_keeps_navigate_actions():
    from services.llm_plan_binding_adapter import build_page_intent
    page = {"route": "/tasks", "entity": "Task", "file": "src/schemas/tasks.json",
            "actions": [{"label": "New", "kind": "navigate", "to": "/tasks/new"}]}
    intent = build_page_intent(page, {"workflows": []})
    assert {"label": "New", "kind": "navigate", "to": "/tasks/new"} in intent["actions"]
```

Update `build_page_intent`'s `_from_page_actions` to keep navigate actions (label + kind navigate + `to`), not only workflow actions.

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_llm_plan_binding_adapter.py tests/services/test_crud_actions.py -v`
Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "import ast; ast.parse(open('routers/generate.py').read()); ast.parse(open('services/schema_pipeline.py').read()); print('OK')"`
Expected: tests pass; parse OK.

- [ ] **Step 5: Commit**

```bash
git add backend/services/crud_actions.py backend/services/llm_plan_binding_adapter.py backend/services/schema_pipeline.py backend/routers/generate.py backend/tests/services/test_llm_plan_binding_adapter.py
git commit -m "feat(crud): merge derived CRUD actions into binding (both paths)"
```

---

## Group C — Form submit wiring

### Task 7: Wire `Form` submit → Create/Update workflow

**Files:**
- Modify: `backend/services/schema_binding.py` (add `apply_form_bindings`)
- Test: `backend/tests/services/test_schema_binding.py`

- [ ] **Step 1: Write the failing test**

```python
import copy
from services.schema_binding import apply_form_bindings, iter_nodes


def test_form_on_new_page_wires_create_workflow():
    schema = {"root": {"id": "r", "type": "Stack", "children": [
        {"id": "f", "type": "Form", "props": {"fields": [{"name": "title"}]}}]}}
    out, info = apply_form_bindings(copy.deepcopy(schema), entity="Task",
                                    page_type="form", route="/tasks/new",
                                    existing_workflows={"CreateTask", "UpdateTask"})
    form = next(n for n in iter_nodes(out) if n.get("type") == "Form")
    assert form["props"]["workflow"] == "CreateTask"
    assert info["forms_bound"] == 1


def test_form_on_edit_page_wires_update_and_skips_when_present():
    schema = {"root": {"type": "Stack", "children": [
        {"id": "f", "type": "Form", "props": {"workflow": "Custom"}}]}}
    out, info = apply_form_bindings(copy.deepcopy(schema), entity="Task",
                                    page_type="form", route="/tasks/123/edit",
                                    existing_workflows={"UpdateTask"})
    form = next(n for n in iter_nodes(out) if n.get("type") == "Form")
    assert form["props"]["workflow"] == "Custom"   # fill-only-if-absent
    assert info["forms_bound"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_binding.py -k form -v`
Expected: FAIL with `ImportError: cannot import name 'apply_form_bindings'`.

- [ ] **Step 3: Implement**

```python
def apply_form_bindings(schema: dict, *, entity: str | None, page_type: str | None,
                        route: str | None, existing_workflows: set) -> tuple[dict, dict]:
    """Wire a Form's submit to Create<Entity>/Update<Entity> on form pages.
    Update when the route looks like an edit (has 'edit' or an :id segment),
    else Create. Fill-only-if-absent. Returns (schema, {forms_bound})."""
    bound = 0
    if entity and (page_type or "").lower() == "form":
        r = (route or "").lower()
        is_edit = "edit" in r or ":id" in r or "{id}" in r or "[id]" in r
        wf = f"Update{entity}" if is_edit else f"Create{entity}"
        if wf in existing_workflows:
            for node in iter_nodes(schema):
                if node.get("type") == "Form":
                    props = node.setdefault("props", {})
                    if not props.get("workflow"):
                        props["workflow"] = wf
                        bound += 1
    return schema, {"forms_bound": bound}
```

Then call `apply_form_bindings` from `apply_bindings` (the orchestrator) — pass `existing_workflows`. Since `apply_bindings(schema, page_intent, plan)` doesn't currently receive the workflow set, thread it via `page_intent`: in the binding hooks (Task 6) add `page["_existing_workflows"] = list(_existing_wf)` and `page["_route"]`/`page["_page_type"]`, and in `apply_bindings` read `page_intent.get("_existing_workflows")`/`.get("_page_type")`/route. Add `forms_bound` to the report. Keep it backward compatible (default empty set → no-op).

- [ ] **Step 4: Run the schema_binding suite**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/services/test_schema_binding.py -v`
Expected: PASS (existing + 2 form tests).

- [ ] **Step 5: Commit**

```bash
git add backend/services/schema_binding.py backend/tests/services/test_schema_binding.py
git commit -m "feat(crud): wire Form submit to Create/Update workflow (form pages)"
```

---

## Group D — LLM completeness guard

### Task 8: Guard input + validated-repair application (pure)

**Files:**
- Create: `backend/agents/wiring_guard.py`
- Test: `backend/tests/agents/test_wiring_guard.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/test_wiring_guard.py
from agents.wiring_guard import collect_actionable, apply_guard_repairs


def _schema():
    return {"root": {"type": "Stack", "children": [
        {"id": "b1", "type": "Button", "props": {"label": "Approve", "workflow": "ApproveTask"}},
        {"id": "b2", "type": "Button", "props": {"label": "Escalate"}},          # unwired
        {"id": "b3", "type": "Button", "props": {"label": "Back", "navigate": "/tasks"}},
    ]}}


def test_collect_actionable_lists_unwired_and_wired():
    items = collect_actionable(_schema())
    by_id = {i["id"]: i for i in items}
    assert by_id["b1"]["wired"] is True
    assert by_id["b2"]["wired"] is False
    assert by_id["b3"]["wired"] is True


def test_apply_repairs_only_accepts_real_backends():
    repairs = [
        {"id": "b2", "kind": "workflow", "workflow": "EscalateTask"},   # real
        {"id": "b2b", "kind": "workflow", "workflow": "GhostWF"},        # phantom -> reject
        {"id": "b9", "kind": "navigate", "to": "/ghost"},                # bad route -> reject
    ]
    schema = {"root": {"type": "Stack", "children": [
        {"id": "b2", "type": "Button", "props": {"label": "Escalate"}},
        {"id": "b2b", "type": "Button", "props": {"label": "X"}},
        {"id": "b9", "type": "Button", "props": {"label": "Y"}}]}}
    out, applied = apply_guard_repairs(schema, repairs,
                                       real_workflows={"EscalateTask"}, real_routes={"/tasks"})
    def find(i):
        from agents.wiring_guard import _walk_nodes
        return next(n for n in _walk_nodes(out) if n.get("id") == i)
    assert find("b2")["props"]["workflow"] == "EscalateTask"
    assert "workflow" not in find("b2b")["props"]   # phantom rejected
    assert "navigate" not in find("b9")["props"]    # bad route rejected
    assert {a["id"] for a in applied} == {"b2"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_wiring_guard.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# backend/agents/wiring_guard.py
"""LLM completeness guard — ensure every actionable button is tied to a real
backend (workflow or navigate). Deterministic validation: only apply repairs
referencing a real workflow / real route. Safety net over the deterministic
binding; degrades to no-op without an API key.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_ACTIONABLE = {"Button", "IconButton"}


def _walk_nodes(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_nodes(v)


def collect_actionable(schema: dict) -> list[dict]:
    """List actionable nodes with a `wired` flag (has workflow/navigate/onClick)."""
    out: list[dict] = []
    for n in _walk_nodes(schema):
        if isinstance(n, dict) and n.get("type") in _ACTIONABLE:
            p = n.get("props") or {}
            wired = bool(p.get("workflow") or p.get("navigate") or p.get("onClick"))
            out.append({"id": n.get("id"), "label": p.get("label") or p.get("children"),
                        "wired": wired})
    return out


def apply_guard_repairs(schema: dict, repairs: list[dict], *, real_workflows: set,
                        real_routes: set) -> tuple[dict, list[dict]]:
    """Apply only repairs that reference a real workflow or real route.
    Returns (schema, applied_repairs)."""
    by_id = {n.get("id"): n for n in _walk_nodes(schema) if isinstance(n, dict) and n.get("id")}
    applied: list[dict] = []
    for r in repairs or []:
        node = by_id.get(r.get("id"))
        if not node:
            continue
        props = node.setdefault("props", {})
        if r.get("kind") == "workflow" and r.get("workflow") in real_workflows:
            if not props.get("workflow"):
                props["workflow"] = r["workflow"]
                applied.append(r)
        elif r.get("kind") == "navigate" and r.get("to") in real_routes:
            if not props.get("navigate"):
                props["navigate"] = r["to"]
                applied.append(r)
    return schema, applied
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_wiring_guard.py -v`
Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add backend/agents/wiring_guard.py backend/tests/agents/test_wiring_guard.py
git commit -m "feat(guard): actionable collection + validated-repair application"
```

---

### Task 9: Guard orchestrator (injectable LLM) + report + hook

**Files:**
- Modify: `backend/agents/wiring_guard.py` (add `run_wiring_guard`)
- Modify: `backend/services/schema_pipeline.py` (call after binding; aggregate `wiring-report.json`)
- Test: `backend/tests/agents/test_wiring_guard.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from agents.wiring_guard import run_wiring_guard


def test_run_guard_applies_validated_repair_via_injected_llm():
    schema = {"root": {"type": "Stack", "children": [
        {"id": "b2", "type": "Button", "props": {"label": "Escalate"}}]}}

    async def fake_llm(prompt: str) -> list:
        return [{"id": "b2", "kind": "workflow", "workflow": "EscalateTask"}]

    out, report = asyncio.run(run_wiring_guard(
        schema, real_workflows={"EscalateTask"}, real_routes=set(), call_llm=fake_llm))
    btn = next(n for n in __import__("agents.wiring_guard", fromlist=["_walk_nodes"])._walk_nodes(out) if n.get("id") == "b2")
    assert btn["props"]["workflow"] == "EscalateTask"
    assert report["repaired"] == 1


def test_run_guard_noops_without_llm():
    schema = {"root": {"type": "Stack", "children": [
        {"id": "b", "type": "Button", "props": {"label": "X"}}]}}
    out, report = asyncio.run(run_wiring_guard(schema, real_workflows=set(),
                                               real_routes=set(), call_llm=None))
    assert out == schema and report["repaired"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_wiring_guard.py -k run_guard -v`
Expected: FAIL with `ImportError: cannot import name 'run_wiring_guard'`.

- [ ] **Step 3: Implement `run_wiring_guard`**

```python
_GUARD_PROMPT = """Some buttons on a generated app page have no action wired.
For each UNWIRED actionable button below, decide if it should dispatch a workflow
or navigate. Only use a workflow name from REAL_WORKFLOWS or a route from
REAL_ROUTES. If a button is intentionally inert (UI toggle, export, etc.), omit it.
Return ONLY a JSON array of {id, kind:"workflow"|"navigate", workflow?, to?}.

UNWIRED_BUTTONS:
__BUTTONS__
REAL_WORKFLOWS: __WORKFLOWS__
REAL_ROUTES: __ROUTES__
"""


async def run_wiring_guard(schema: dict, *, real_workflows: set, real_routes: set,
                           call_llm) -> tuple[dict, dict]:
    """Verify completeness; apply only validated repairs. call_llm is an async
    (prompt)->list or None (then no-op). Returns (schema, report)."""
    items = collect_actionable(schema)
    unwired = [i for i in items if not i["wired"]]
    report = {"actionable": len(items), "unwired": len(unwired), "repaired": 0,
              "still_unwired": len(unwired)}
    if not unwired or call_llm is None:
        return schema, report
    try:
        prompt = (_GUARD_PROMPT
                  .replace("__BUTTONS__", json.dumps([{"id": i["id"], "label": i["label"]} for i in unwired]))
                  .replace("__WORKFLOWS__", json.dumps(sorted(real_workflows)))
                  .replace("__ROUTES__", json.dumps(sorted(real_routes))))
        repairs = await call_llm(prompt)
        if not isinstance(repairs, list):
            raise ValueError("guard LLM did not return a list")
        schema, applied = apply_guard_repairs(schema, repairs,
                                              real_workflows=real_workflows, real_routes=real_routes)
        report["repaired"] = len(applied)
        report["still_unwired"] = len(unwired) - len(applied)
    except Exception as exc:  # noqa: BLE001 — guard is best-effort
        logger.warning("wiring guard failed: %s", exc)
    return schema, report
```

Also add a thin `make_anthropic_guard_llm()` factory mirroring `figma_plan_binding.make_anthropic_call_llm` but parsing a JSON **array** (first `[` … last `]`). No unit test (covered by injected-client tests); verify by import.

- [ ] **Step 4: Hook into `schema_pipeline.py`**

After the binding application for each page (and after CRUD workflows exist), call the guard with the real workflow set (from `workflows/`) and the real route set (from `plan.pages[].route`), write its per-page result into a `wiring-report.json` at the output root. Wrap so failure only logs. Use `make_anthropic_guard_llm()` when `ANTHROPIC_API_KEY` is set, else `call_llm=None`.

- [ ] **Step 5: Run the guard tests + import check**

Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -m pytest tests/agents/test_wiring_guard.py -v`
Run: `cd /Users/m/Work/code/poc/design2ui-forge-v3/backend && python3 -c "import ast; ast.parse(open('services/schema_pipeline.py').read()); print('OK')"`
Expected: tests pass; parse OK.

- [ ] **Step 6: Commit**

```bash
git add backend/agents/wiring_guard.py backend/services/schema_pipeline.py backend/tests/agents/test_wiring_guard.py
git commit -m "feat(guard): completeness guard orchestrator + report + pipeline hook"
```

---

## Group E — Live E2E re-run (manual, after all tasks)

1. Restart backend (clean env). Generate the leave-request prompt app.
2. Confirm `output/<id>/workflows/` has `CreateLeaveRequest.json` / `UpdateLeaveRequest.json` / `DeleteLeaveRequest.json` with correct `db_*` nodes + `LeaveApprovalWorkflow.json` intact.
3. Inspect list/detail/form schemas: New/Edit carry `navigate`; Delete carries `workflow:DeleteLeaveRequest` + `args.id`; the new/edit Form carries `workflow:Create/UpdateLeaveRequest`; Approve/Reject carry their process workflow.
4. Check `wiring-report.json`: no actionable button left `still_unwired` (or only intentional UI/utility ones).
5. (If DB available) click through: create persists, delete removes, approve transitions.

## Out of scope (later)

- UI-state (filter/sort/expand) and utility (export/print/download) buttons.
- `visible_when` permission gating.
- A runtime data-mutation primitive.
