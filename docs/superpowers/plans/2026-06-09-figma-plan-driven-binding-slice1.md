# Figma Plan-Driven Binding — Slice 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Figma-generated apps live — bind list nodes to real DB rows and wire row/page buttons to workflows — driven by binding intent declared in the (user-approved) plan.

**Architecture:** Two layers. **Layer B** (`backend/services/schema_binding.py`) is a pure-Python applier that maps plan binding intent onto generated page schemas (deterministic, fully unit-tested). **Layer A** (`backend/services/figma_plan_binding.py`) enriches the Figma plan with structured binding intent (`data_models`, `workflows`, per-page `entity` + `actions`) at plan-build time so the user reviews it before the build. A pipeline phase in `_run_figma_relay_pipeline` runs Layer B after the schema refiner. **Group 1 (Layer B) is independently valuable and testable** against fixture plans; Group 2 (Layer A) feeds it real intent; Group 3 wires both into the pipeline.

**Tech Stack:** Python 3 (backend), pytest. The runtime (TypeScript renderer/engine) needs **no changes** — `dispatch.tsx` deep-interpolation, `Repeat` row scope, and Button `workflow`/`args` are already verified present.

**Spec:** `docs/superpowers/specs/2026-06-09-figma-plan-driven-binding-slice1-design.md`

**Data shapes (reference):**
- Page schema (Figma v2): `{"schemaVersion": "2.0", "id": str, "title"?: str, "dataSources": [...], "children": [node, ...]}`
- Node: `{"id": str, "type": str, "props": {...}, "children": [node, ...]}`
- Plan page (after Layer A): `{"route", "name", "figma_node_id", "type", "file", "entity": str|None, "actions": [{"label", "workflow", "kind": "row_action"|"page_action"}]}`
- Plan top-level (after Layer A adds): `"data_models": [{"name": str, "fields": [{"name": str, "type": str}]}]`, `"workflows": [{"name": str, "description": str}]`
- DataSource: `{"name": str, "entity": str, "op": "list"}`

**Test command (from `backend/`):** `python -m pytest tests/services/<file> -v`

---

## Group 1 — Layer B: deterministic applier (`backend/services/schema_binding.py`)

### Task 1: Node text + label helpers

**Files:**
- Create: `backend/services/schema_binding.py`
- Test: `backend/tests/services/test_schema_binding.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_schema_binding.py
from services.schema_binding import normalize_label, node_text, iter_nodes


def test_normalize_label_lowercases_strips_punct():
    assert normalize_label("  Approve Entry! ") == "approve entry"
    assert normalize_label("Re-Scan") == "re scan"
    assert normalize_label(None) == ""


def test_node_text_reads_common_keys():
    assert node_text({"type": "Text", "props": {"content": "Hi"}}) == "Hi"
    assert node_text({"type": "Button", "props": {"label": "Go"}}) == "Go"
    assert node_text({"type": "Text", "props": {"children": "Kid"}}) == "Kid"
    assert node_text({"type": "Box", "props": {}}) == ""


def test_iter_nodes_yields_every_node_depth_first():
    tree = {"id": "a", "type": "Stack", "children": [
        {"id": "b", "type": "Text", "props": {"content": "x"}},
        {"id": "c", "type": "Row", "children": [{"id": "d", "type": "Button", "props": {"label": "Y"}}]},
    ]}
    ids = [n["id"] for n in iter_nodes(tree)]
    assert ids == ["a", "b", "c", "d"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_schema_binding.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError: cannot import name 'normalize_label'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/schema_binding.py
"""Deterministic plan-driven binding applier (Slice 1: lists + buttons).

Takes generated Figma page schemas + plan binding intent and injects
dataSources/bind/{{item.field}}/workflow/args. Pure functions; no I/O here
(the pipeline phase in routers/generate.py handles file reads/writes).
"""
from __future__ import annotations

import re
from typing import Any, Iterator

_TEXT_KEYS = ("content", "label", "text", "children", "title", "value")


def normalize_label(text: Any) -> str:
    """Lowercase, drop punctuation, collapse whitespace. '' for non-strings."""
    if not isinstance(text, str):
        return ""
    cleaned = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def node_text(node: dict) -> str:
    """First string-valued text prop on a node, else ''."""
    props = node.get("props") or {}
    for k in _TEXT_KEYS:
        v = props.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def iter_nodes(node: Any) -> Iterator[dict]:
    """Depth-first walk yielding every dict node (parents before children)."""
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from iter_nodes(child)
    elif isinstance(node, list):
        for item in node:
            yield from iter_nodes(item)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_schema_binding.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/schema_binding.py backend/tests/services/test_schema_binding.py
git commit -m "feat(binding): node text/label/iter helpers for schema_binding"
```

---

### Task 2: Structural signature

**Files:**
- Modify: `backend/services/schema_binding.py`
- Test: `backend/tests/services/test_schema_binding.py`

- [ ] **Step 1: Write the failing test**

```python
from services.schema_binding import structural_signature


def test_signature_identical_for_same_shape():
    a = {"type": "Card", "children": [{"type": "Text"}, {"type": "Button"}]}
    b = {"type": "Card", "children": [{"type": "Text"}, {"type": "Button"}]}
    assert structural_signature(a) == structural_signature(b)


def test_signature_differs_for_different_shape():
    a = {"type": "Card", "children": [{"type": "Text"}]}
    b = {"type": "Card", "children": [{"type": "Button"}]}
    assert structural_signature(a) != structural_signature(b)


def test_signature_depth_bounded():
    # Beyond max_depth, deep structure is ignored — two cards equal at depth 1.
    a = {"type": "Card", "children": [{"type": "Row", "children": [{"type": "Text"}]}]}
    b = {"type": "Card", "children": [{"type": "Row", "children": [{"type": "Button"}]}]}
    assert structural_signature(a, max_depth=1) == structural_signature(b, max_depth=1)
    assert structural_signature(a, max_depth=3) != structural_signature(b, max_depth=3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_schema_binding.py -k signature -v`
Expected: FAIL with `ImportError: cannot import name 'structural_signature'`

- [ ] **Step 3: Write minimal implementation**

```python
def structural_signature(node: dict, max_depth: int = 3) -> str:
    """Recursive type fingerprint, depth-bounded. Two subtrees with the same
    signature have the same shape (used to detect repeated list rows)."""
    if not isinstance(node, dict):
        return ""
    t = node.get("type") or "?"
    if max_depth <= 0:
        return t
    kids = node.get("children") or []
    inner = ",".join(structural_signature(c, max_depth - 1) for c in kids if isinstance(c, dict))
    return f"{t}({inner})"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_schema_binding.py -k signature -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/schema_binding.py backend/tests/services/test_schema_binding.py
git commit -m "feat(binding): depth-bounded structural signature"
```

---

### Task 3: Repeater detection

**Files:**
- Modify: `backend/services/schema_binding.py`
- Test: `backend/tests/services/test_schema_binding.py`

- [ ] **Step 1: Write the failing test**

```python
from services.schema_binding import find_repeater


def _row(i):
    return {"id": f"r{i}", "type": "Card", "children": [
        {"id": f"t{i}", "type": "Text", "props": {"content": f"Row {i}"}},
        {"id": f"b{i}", "type": "Button", "props": {"label": "View"}},
    ]}


def test_find_repeater_picks_largest_identical_sibling_group():
    schema = {"children": [{"id": "list", "type": "Stack", "children": [_row(1), _row(2), _row(3)]}]}
    match = find_repeater(schema)
    assert match is not None
    assert match["parent"]["id"] == "list"
    assert [m["id"] for m in match["members"]] == ["r1", "r2", "r3"]


def test_find_repeater_returns_none_for_single_row():
    schema = {"children": [{"id": "list", "type": "Stack", "children": [_row(1)]}]}
    assert find_repeater(schema) is None


def test_find_repeater_ignores_heterogeneous_siblings():
    schema = {"children": [{"id": "hdr", "type": "Stack", "children": [
        {"id": "title", "type": "Text", "props": {"content": "T"}},
        {"id": "sub", "type": "Image", "props": {}},
    ]}]}
    assert find_repeater(schema) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_schema_binding.py -k repeater -v`
Expected: FAIL with `ImportError: cannot import name 'find_repeater'`

- [ ] **Step 3: Write minimal implementation**

```python
def find_repeater(schema: dict) -> dict | None:
    """Walk the schema; among every container's direct children, find the
    largest group (>=2) of siblings sharing a structural signature. Returns
    {parent, signature, members, start_index} for the best match, or None.
    'Best' = most members, tie-broken by larger template subtree (more nodes)."""
    best: dict | None = None
    best_score: tuple = (0, 0)
    for parent in iter_nodes(schema):
        kids = parent.get("children") or []
        if len(kids) < 2:
            continue
        groups: dict[str, list[dict]] = {}
        for child in kids:
            if not isinstance(child, dict):
                continue
            groups.setdefault(structural_signature(child), []).append(child)
        for sig, members in groups.items():
            if len(members) < 2 or not sig.strip("?()"):
                continue
            template_size = sum(1 for _ in iter_nodes(members[0]))
            score = (len(members), template_size)
            if score > best_score:
                best_score = score
                start = kids.index(members[0])
                best = {"parent": parent, "signature": sig, "members": members, "start_index": start}
    return best
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_schema_binding.py -k repeater -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/schema_binding.py backend/tests/services/test_schema_binding.py
git commit -m "feat(binding): repeater detection by structural-signature grouping"
```

---

### Task 4: Cell-to-field mapping

**Files:**
- Modify: `backend/services/schema_binding.py`
- Test: `backend/tests/services/test_schema_binding.py`

- [ ] **Step 1: Write the failing test**

```python
from services.schema_binding import map_cells_to_fields


def test_map_cells_by_name_substring():
    row = {"type": "Card", "children": [
        {"id": "c1", "type": "Text", "props": {"content": "Driver Name"}},
        {"id": "c2", "type": "Text", "props": {"content": "Status"}},
    ]}
    fields = [{"name": "name"}, {"name": "status"}, {"name": "id"}]
    assert map_cells_to_fields(row, fields) == {"c1": "name", "c2": "status"}


def test_map_cells_positional_when_no_name_match():
    row = {"type": "Card", "children": [
        {"id": "c1", "type": "Text", "props": {"content": "ABC-123"}},
        {"id": "c2", "type": "Text", "props": {"content": "Pending"}},
    ]}
    fields = [{"name": "licensePlate"}, {"name": "status"}]
    assert map_cells_to_fields(row, fields) == {"c1": "licensePlate", "c2": "status"}


def test_map_cells_skips_when_no_fields():
    row = {"type": "Card", "children": [{"id": "c1", "type": "Text", "props": {"content": "X"}}]}
    assert map_cells_to_fields(row, []) == {}


def test_map_cells_excludes_interactive_buttons():
    row = {"type": "Card", "children": [
        {"id": "c1", "type": "Text", "props": {"content": "Name"}},
        {"id": "btn", "type": "Button", "props": {"label": "Approve"}},
    ]}
    fields = [{"name": "name"}, {"name": "status"}]
    result = map_cells_to_fields(row, fields)
    assert "btn" not in result          # button never treated as a display cell
    assert result == {"c1": "name"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_schema_binding.py -k cells -v`
Expected: FAIL with `ImportError: cannot import name 'map_cells_to_fields'`

- [ ] **Step 3: Write minimal implementation**

```python
# Interactive nodes carry text (a button label) but are NOT display cells —
# never rewrite their text to {{item.field}} (that would corrupt the control).
_INTERACTIVE_TYPES = {
    "Button", "IconButton", "Link", "NavLink", "Input", "Textarea", "Select",
    "Switch", "Checkbox", "Radio", "RadioGroup", "Combobox",
}


def map_cells_to_fields(template_row: dict, fields: list[dict]) -> dict[str, str]:
    """Map display text leaf nodes in a template row to entity field names.
    Skips interactive nodes (buttons/inputs). Priority: (1) cell text
    contains/equals a field name; (2) leftover cells assigned positionally to
    leftover fields. Returns {node_id: field_name}."""
    if not fields:
        return {}
    cells = [n for n in iter_nodes(template_row)
             if n is not template_row and node_text(n) and not n.get("children")
             and n.get("type") not in _INTERACTIVE_TYPES]
    field_names = [f["name"] for f in fields if isinstance(f, dict) and f.get("name")]
    out: dict[str, str] = {}
    used_fields: set[str] = set()
    used_cells: set[str] = set()

    # Pass 1: name-substring match.
    for cell in cells:
        norm = normalize_label(node_text(cell)).replace(" ", "")
        for fname in field_names:
            if fname in used_fields:
                continue
            if fname.lower() in norm or norm in fname.lower():
                out[cell["id"]] = fname
                used_fields.add(fname)
                used_cells.add(cell["id"])
                break

    # Pass 2: positional fill for remaining cells/fields, in order.
    remaining_fields = [f for f in field_names if f not in used_fields]
    for cell in cells:
        if cell["id"] in used_cells:
            continue
        if not remaining_fields:
            break
        out[cell["id"]] = remaining_fields.pop(0)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_schema_binding.py -k cells -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/schema_binding.py backend/tests/services/test_schema_binding.py
git commit -m "feat(binding): cell-to-field mapping (name then positional)"
```

---

### Task 5: Apply list binding

**Files:**
- Modify: `backend/services/schema_binding.py`
- Test: `backend/tests/services/test_schema_binding.py`

- [ ] **Step 1: Write the failing test**

```python
import copy
from services.schema_binding import apply_list_binding


def _list_schema():
    def row(i):
        return {"id": f"r{i}", "type": "Card", "children": [
            {"id": f"t{i}", "type": "Text", "props": {"content": "Driver Name"}},
            {"id": f"s{i}", "type": "Text", "props": {"content": "Status"}},
        ]}
    return {"schemaVersion": "2.0", "id": "p", "dataSources": [],
            "children": [{"id": "list", "type": "Stack", "children": [row(1), row(2), row(3)]}]}


def test_apply_list_binding_adds_datasource_and_repeat():
    schema = _list_schema()
    entity = {"name": "Driver", "fields": [{"name": "name"}, {"name": "status"}]}
    out, info = apply_list_binding(copy.deepcopy(schema), {"entity": "Driver"}, entity)
    assert out["dataSources"] == [{"name": "driver", "entity": "Driver", "op": "list"}]
    # The 3 rows collapse to one Repeat bound to the source.
    stack = out["children"][0]
    assert len(stack["children"]) == 1
    rep = stack["children"][0]
    assert rep["type"] == "Repeat"
    assert rep["bind"] == "driver"
    assert info["bound"] is True


def test_apply_list_binding_rewrites_cells_to_item_fields():
    schema = _list_schema()
    entity = {"name": "Driver", "fields": [{"name": "name"}, {"name": "status"}]}
    out, _ = apply_list_binding(copy.deepcopy(schema), {"entity": "Driver"}, entity)
    rep = out["children"][0]["children"][0]
    texts = [n["props"].get("content") for n in iter_nodes(rep) if n.get("type") == "Text"]
    assert "{{item.name}}" in texts
    assert "{{item.status}}" in texts


def test_apply_list_binding_unbound_when_no_repeater():
    schema = {"schemaVersion": "2.0", "id": "p", "dataSources": [],
              "children": [{"id": "x", "type": "Text", "props": {"content": "solo"}}]}
    entity = {"name": "Driver", "fields": [{"name": "name"}]}
    out, info = apply_list_binding(copy.deepcopy(schema), {"entity": "Driver"}, entity)
    assert info["bound"] is False
    assert out["dataSources"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_schema_binding.py -k list_binding -v`
Expected: FAIL with `ImportError: cannot import name 'apply_list_binding'`

- [ ] **Step 3: Write minimal implementation**

```python
def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower()) or "items"


def apply_list_binding(schema: dict, page_intent: dict, entity_def: dict | None) -> tuple[dict, dict]:
    """Detect the list repeater, collapse it to one Repeat bound to a new
    page dataSource, and rewrite the template row's cells to {{item.field}}.
    Returns (schema, info) where info = {bound: bool, source?, entity?, reason?}."""
    entity = (page_intent or {}).get("entity") or (entity_def or {}).get("name")
    if not entity:
        return schema, {"bound": False, "reason": "no entity"}
    match = find_repeater(schema)
    if match is None:
        return schema, {"bound": False, "reason": "no repeater"}

    source = _slugify(entity)
    template = match["members"][0]
    fields = (entity_def or {}).get("fields") or []
    cell_map = map_cells_to_fields(template, fields)
    for node in iter_nodes(template):
        field = cell_map.get(node.get("id"))
        if not field:
            continue
        props = node.setdefault("props", {})
        for k in ("content", "label", "text", "children", "value"):
            if isinstance(props.get(k), str):
                props[k] = f"{{{{item.{field}}}}}"
                break

    repeat = {"id": f"repeat-{source}", "type": "Repeat", "bind": source, "children": [template]}
    parent_kids = match["parent"]["children"]
    member_ids = {id(m) for m in match["members"]}
    new_kids = [k for k in parent_kids if id(k) not in member_ids]
    new_kids.insert(match["start_index"], repeat)
    match["parent"]["children"] = new_kids

    schema.setdefault("dataSources", [])
    if not any(ds.get("name") == source for ds in schema["dataSources"]):
        schema["dataSources"].append({"name": source, "entity": entity, "op": "list"})
    return schema, {"bound": True, "source": source, "entity": entity}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_schema_binding.py -k list_binding -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/schema_binding.py backend/tests/services/test_schema_binding.py
git commit -m "feat(binding): apply list binding (dataSource + Repeat + item fields)"
```

---

### Task 6: Apply button bindings

**Files:**
- Modify: `backend/services/schema_binding.py`
- Test: `backend/tests/services/test_schema_binding.py`

- [ ] **Step 1: Write the failing test**

```python
import copy
from services.schema_binding import apply_button_bindings


def test_row_action_button_gets_workflow_and_item_id():
    schema = {"children": [
        {"id": "rep", "type": "Repeat", "bind": "trucks", "children": [
            {"id": "row", "type": "Card", "children": [
                {"id": "btn", "type": "Button", "props": {"label": "Approve"}},
            ]},
        ]},
    ]}
    intent = {"actions": [{"label": "Approve", "workflow": "ApproveEntry", "kind": "row_action"}]}
    out, info = apply_button_bindings(copy.deepcopy(schema), intent)
    btn = next(n for n in iter_nodes(out) if n.get("id") == "btn")
    assert btn["props"]["workflow"] == "ApproveEntry"
    assert btn["props"]["args"] == {"id": "{{item.id}}"}
    assert "btn" in info["bound"]


def test_page_action_button_gets_workflow_no_item_args():
    schema = {"children": [{"id": "btn", "type": "Button", "props": {"label": "New Truck"}}]}
    intent = {"actions": [{"label": "New Truck", "workflow": "CreateTruck", "kind": "page_action"}]}
    out, _ = apply_button_bindings(copy.deepcopy(schema), intent)
    btn = next(n for n in iter_nodes(out) if n.get("id") == "btn")
    assert btn["props"]["workflow"] == "CreateTruck"
    assert "args" not in btn["props"]


def test_unmatched_button_left_inert():
    schema = {"children": [{"id": "btn", "type": "Button", "props": {"label": "Cancel"}}]}
    intent = {"actions": [{"label": "Approve", "workflow": "W", "kind": "row_action"}]}
    out, info = apply_button_bindings(copy.deepcopy(schema), intent)
    btn = next(n for n in iter_nodes(out) if n.get("id") == "btn")
    assert "workflow" not in btn["props"]
    assert "btn" in info["unbound"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_schema_binding.py -k button -v`
Expected: FAIL with `ImportError: cannot import name 'apply_button_bindings'`

- [ ] **Step 3: Write minimal implementation**

```python
def _actions_by_label(intent: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for a in (intent or {}).get("actions") or []:
        lab = normalize_label(a.get("label"))
        if lab and a.get("workflow"):
            out[lab] = a
    return out


def apply_button_bindings(schema: dict, page_intent: dict) -> tuple[dict, dict]:
    """Wire Button nodes to workflows by matching their label to a plan action.
    row_action buttons get args={'id': '{{item.id}}'}; page_action buttons get
    just the workflow. Returns (schema, {bound: [ids], unbound: [ids]})."""
    actions = _actions_by_label(page_intent)
    bound: list[str] = []
    unbound: list[str] = []

    def _walk(node: Any, in_repeat: bool) -> None:
        if isinstance(node, list):
            for n in node:
                _walk(n, in_repeat)
            return
        if not isinstance(node, dict):
            return
        here_repeat = in_repeat or node.get("type") == "Repeat"
        if node.get("type") == "Button":
            props = node.setdefault("props", {})
            if "workflow" in props:
                pass  # idempotent: already bound
            else:
                action = actions.get(normalize_label(node_text(node)))
                bid = node.get("id") or "?"
                if action:
                    props["workflow"] = action["workflow"]
                    if action.get("kind") == "row_action":
                        props["args"] = {"id": "{{item.id}}"}
                    bound.append(bid)
                else:
                    unbound.append(bid)
        for child in node.get("children") or []:
            _walk(child, here_repeat)

    _walk(schema.get("children") if "children" in schema else schema.get("root"), False)
    return schema, {"bound": bound, "unbound": unbound}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_schema_binding.py -k button -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/schema_binding.py backend/tests/services/test_schema_binding.py
git commit -m "feat(binding): apply button bindings (row/page action workflows)"
```

---

### Task 7: Orchestrator + validate-or-fallback + report

**Files:**
- Modify: `backend/services/schema_binding.py`
- Test: `backend/tests/services/test_schema_binding.py`

- [ ] **Step 1: Write the failing test**

```python
import copy
from services.schema_binding import apply_bindings


def _plan():
    return {
        "data_models": [{"name": "Driver", "fields": [{"name": "name"}, {"name": "status"}]}],
        "workflows": [{"name": "ApproveDriver", "description": "approve"}],
    }


def _page_intent():
    return {"file": "src/schemas/drivers.json", "entity": "Driver",
            "actions": [{"label": "Approve", "workflow": "ApproveDriver", "kind": "row_action"}]}


def _drivers_schema():
    def row(i):
        return {"id": f"r{i}", "type": "Card", "children": [
            {"id": f"n{i}", "type": "Text", "props": {"content": "Driver Name"}},
            {"id": f"a{i}", "type": "Button", "props": {"label": "Approve"}},
        ]}
    return {"schemaVersion": "2.0", "id": "drivers", "dataSources": [],
            "children": [{"id": "list", "type": "Stack", "children": [row(1), row(2)]}]}


def test_apply_bindings_end_to_end():
    out, report = apply_bindings(_drivers_schema(), _page_intent(), _plan())
    assert out["dataSources"] == [{"name": "driver", "entity": "Driver", "op": "list"}]
    rep = out["children"][0]["children"][0]
    assert rep["type"] == "Repeat" and rep["bind"] == "driver"
    btn = next(n for n in iter_nodes(out) if n.get("type") == "Button")
    assert btn["props"]["workflow"] == "ApproveDriver"
    assert btn["props"]["args"] == {"id": "{{item.id}}"}
    assert report["list_bound"] is True
    assert report["buttons_bound"] == 1


def test_apply_bindings_idempotent():
    once, _ = apply_bindings(_drivers_schema(), _page_intent(), _plan())
    twice, report = apply_bindings(copy.deepcopy(once), _page_intent(), _plan())
    assert twice == once
    assert report["skipped"] is True


def test_apply_bindings_reverts_on_invalid_result(monkeypatch):
    import services.schema_binding as sb
    # Force the applier to produce a structurally-broken schema.
    monkeypatch.setattr(sb, "apply_list_binding",
                        lambda s, pi, ed: ({"children": [{"type": ""}]}, {"bound": True, "source": "x"}))
    original = _drivers_schema()
    out, report = apply_bindings(copy.deepcopy(original), _page_intent(), _plan())
    assert out == original  # reverted
    assert report["reverted"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_schema_binding.py -k apply_bindings -v`
Expected: FAIL with `ImportError: cannot import name 'apply_bindings'`

- [ ] **Step 3: Write minimal implementation**

```python
def _is_structurally_valid(schema: Any) -> bool:
    """Cheap structural check (no Node toolchain): a node list/root exists and
    every node's `type`, when present, is a non-empty string."""
    if not isinstance(schema, dict):
        return False
    if "children" not in schema and "root" not in schema:
        return False
    ok = True

    def _chk(n: Any) -> None:
        nonlocal ok
        if isinstance(n, dict):
            if "type" in n and not (isinstance(n["type"], str) and n["type"]):
                ok = False
            for v in n.values():
                _chk(v)
        elif isinstance(n, list):
            for v in n:
                _chk(v)

    _chk(schema)
    return ok


def _entity_def(plan: dict, name: str | None) -> dict | None:
    for e in (plan or {}).get("data_models") or []:
        if isinstance(e, dict) and e.get("name") == name:
            return e
    return None


def apply_bindings(schema: dict, page_intent: dict, plan: dict) -> tuple[dict, dict]:
    """Orchestrate list + button binding for one page. Idempotent (skips when
    already bound) and validate-or-fallback (reverts to the input schema if the
    result is structurally invalid). Returns (schema, report)."""
    import copy as _copy
    route = (page_intent or {}).get("file") or schema.get("id")

    already_bound = bool(schema.get("dataSources")) or any(
        (n.get("type") == "Repeat") or ("workflow" in (n.get("props") or {}))
        for n in iter_nodes(schema)
    )
    if already_bound:
        return schema, {"route": route, "skipped": True, "list_bound": False,
                        "buttons_bound": 0, "reverted": False}

    original = _copy.deepcopy(schema)
    entity_def = _entity_def(plan, (page_intent or {}).get("entity"))
    work, list_info = apply_list_binding(schema, page_intent, entity_def)
    work, btn_info = apply_button_bindings(work, page_intent)

    if not _is_structurally_valid(work):
        return original, {"route": route, "skipped": False, "list_bound": False,
                          "buttons_bound": 0, "reverted": True}

    return work, {
        "route": route,
        "skipped": False,
        "reverted": False,
        "list_bound": bool(list_info.get("bound")),
        "list_reason": list_info.get("reason"),
        "buttons_bound": len(btn_info.get("bound") or []),
        "buttons_unbound": len(btn_info.get("unbound") or []),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_schema_binding.py -v`
Expected: PASS (all schema_binding tests, ~22)

- [ ] **Step 5: Commit**

```bash
git add backend/services/schema_binding.py backend/tests/services/test_schema_binding.py
git commit -m "feat(binding): orchestrator with idempotency + validate-or-fallback"
```

---

## Group 2 — Layer A: Figma plan binding enrichment (`backend/services/figma_plan_binding.py`)

### Task 8: Assemble analysis input from the plan + Figma file meta

**Files:**
- Create: `backend/services/figma_plan_binding.py`
- Test: `backend/tests/services/test_figma_plan_binding.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/services/test_figma_plan_binding.py
from services.figma_plan_binding import build_binding_analysis_input


def test_build_input_lists_pages_and_button_texts():
    plan = {"pages": [{"route": "/trucks", "name": "Trucks", "type": "list",
                       "figma_node_id": "1:2", "file": "src/schemas/trucks.json"}]}
    file_meta = {"document": {"children": [{"type": "CANVAS", "children": [
        {"type": "FRAME", "id": "1:2", "name": "Trucks", "children": [
            {"type": "TEXT", "characters": "Approve"},
            {"type": "TEXT", "characters": "Truck Name"},
        ]},
    ]}]}}
    out = build_binding_analysis_input(plan, file_meta)
    page = out["pages"][0]
    assert page["route"] == "/trucks"
    assert "Approve" in page["texts"]
    assert "Truck Name" in page["texts"]


def test_build_input_handles_missing_frame():
    plan = {"pages": [{"route": "/x", "name": "X", "figma_node_id": "9:9", "file": "f"}]}
    out = build_binding_analysis_input(plan, {"document": {"children": []}})
    assert out["pages"][0]["texts"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_figma_plan_binding.py -k build_input -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/services/figma_plan_binding.py
"""Layer A — enrich the Figma plan with structured binding intent.

Adds top-level data_models[] + workflows[] and per-page entity + actions[]
so the deterministic applier (services/schema_binding.py) can wire schemas.
The enrichment runs at plan-build time, before plan_ready, so the user can
review/correct bindings at approval.
"""
from __future__ import annotations

from typing import Any


def _find_frame(node: Any, frame_id: str) -> dict | None:
    if isinstance(node, dict):
        if node.get("id") == frame_id:
            return node
        for c in node.get("children") or []:
            found = _find_frame(c, frame_id)
            if found:
                return found
    elif isinstance(node, list):
        for c in node:
            found = _find_frame(c, frame_id)
            if found:
                return found
    return None


def _frame_texts(frame: dict | None) -> list[str]:
    out: list[str] = []
    if not frame:
        return out

    def _walk(n: Any) -> None:
        if isinstance(n, dict):
            if n.get("type") == "TEXT" and isinstance(n.get("characters"), str):
                t = n["characters"].strip()
                if t:
                    out.append(t)
            for c in n.get("children") or []:
                _walk(c)
        elif isinstance(n, list):
            for c in n:
                _walk(c)

    _walk(frame)
    return out


def build_binding_analysis_input(plan: dict, file_meta: dict) -> dict:
    """Compact per-page summary (route/name/type + visible text) for the LLM."""
    document = (file_meta or {}).get("document") or {}
    pages = []
    for p in (plan or {}).get("pages") or []:
        frame = _find_frame(document, p.get("figma_node_id")) if p.get("figma_node_id") else None
        pages.append({
            "route": p.get("route"),
            "name": p.get("name"),
            "type": p.get("type"),
            "file": p.get("file"),
            "texts": _frame_texts(frame),
        })
    return {"app_name": (plan or {}).get("name"), "pages": pages}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_figma_plan_binding.py -k build_input -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/figma_plan_binding.py backend/tests/services/test_figma_plan_binding.py
git commit -m "feat(binding): assemble Figma binding-analysis input from plan+meta"
```

---

### Task 9: Merge analysis result into the plan

**Files:**
- Modify: `backend/services/figma_plan_binding.py`
- Test: `backend/tests/services/test_figma_plan_binding.py`

- [ ] **Step 1: Write the failing test**

```python
from services.figma_plan_binding import merge_binding_analysis


def test_merge_adds_models_workflows_and_page_intent():
    plan = {"pages": [{"route": "/trucks", "name": "Trucks", "file": "src/schemas/trucks.json", "entity": None}]}
    analysis = {
        "data_models": [{"name": "Truck", "fields": [{"name": "name", "type": "varchar"}]}],
        "workflows": [{"name": "ApproveTruck", "description": "approve a truck"}],
        "pages": [{"route": "/trucks", "entity": "Truck",
                   "actions": [{"label": "Approve", "workflow": "ApproveTruck", "kind": "row_action"}]}],
    }
    out = merge_binding_analysis(plan, analysis)
    assert out["data_models"][0]["name"] == "Truck"
    assert out["workflows"][0]["name"] == "ApproveTruck"
    page = out["pages"][0]
    assert page["entity"] == "Truck"
    assert page["actions"][0]["workflow"] == "ApproveTruck"


def test_merge_drops_actions_with_unknown_workflow():
    plan = {"pages": [{"route": "/x", "file": "f", "entity": None}]}
    analysis = {"data_models": [], "workflows": [{"name": "Known", "description": ""}],
                "pages": [{"route": "/x", "entity": "E", "actions": [
                    {"label": "Good", "workflow": "Known", "kind": "page_action"},
                    {"label": "Bad", "workflow": "Ghost", "kind": "page_action"},
                ]}]}
    out = merge_binding_analysis(plan, analysis)
    labels = [a["label"] for a in out["pages"][0]["actions"]]
    assert labels == ["Good"]


def test_merge_is_safe_with_empty_analysis():
    plan = {"pages": [{"route": "/x", "file": "f", "entity": None}]}
    out = merge_binding_analysis(plan, {})
    assert out["pages"][0]["entity"] is None
    assert out["pages"][0]["actions"] == []
    assert out["data_models"] == []
    assert out["workflows"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_figma_plan_binding.py -k merge -v`
Expected: FAIL with `ImportError: cannot import name 'merge_binding_analysis'`

- [ ] **Step 3: Write minimal implementation**

```python
def merge_binding_analysis(plan: dict, analysis: dict) -> dict:
    """Merge LLM analysis into the plan: set top-level data_models/workflows and
    per-page entity + actions. Drops actions whose workflow isn't declared.
    Returns the same plan dict (mutated) for convenience."""
    analysis = analysis or {}
    models = [m for m in (analysis.get("data_models") or []) if isinstance(m, dict) and m.get("name")]
    workflows = [w for w in (analysis.get("workflows") or []) if isinstance(w, dict) and w.get("name")]
    plan["data_models"] = models
    plan["workflows"] = workflows
    known_wf = {w["name"] for w in workflows}

    by_route = {}
    for ap in analysis.get("pages") or []:
        if isinstance(ap, dict) and ap.get("route"):
            by_route[ap["route"]] = ap

    for page in plan.get("pages") or []:
        ap = by_route.get(page.get("route")) or {}
        page["entity"] = ap.get("entity") if ap.get("entity") else page.get("entity")
        actions = []
        for a in ap.get("actions") or []:
            if (isinstance(a, dict) and a.get("label") and a.get("workflow") in known_wf
                    and a.get("kind") in ("row_action", "page_action")):
                actions.append({"label": a["label"], "workflow": a["workflow"], "kind": a["kind"]})
        page["actions"] = actions
    return plan
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_figma_plan_binding.py -k merge -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/figma_plan_binding.py backend/tests/services/test_figma_plan_binding.py
git commit -m "feat(binding): merge binding analysis into plan (validated)"
```

---

### Task 10: LLM enrichment orchestrator (injectable client)

**Files:**
- Modify: `backend/services/figma_plan_binding.py`
- Test: `backend/tests/services/test_figma_plan_binding.py`

Look at `backend/agents/figma_schema_refiner.py` for the project's Anthropic client/streaming pattern and reuse the same model id (`claude-sonnet-4-20250514`) and JSON-extraction approach. The function below takes an injected `call_llm` so tests don't hit the network.

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from services.figma_plan_binding import enrich_figma_plan_with_bindings


def test_enrich_uses_injected_llm_and_merges():
    plan = {"name": "Gate App",
            "pages": [{"route": "/trucks", "name": "Trucks", "figma_node_id": "1:2",
                       "file": "src/schemas/trucks.json", "entity": None}]}
    file_meta = {"document": {"children": []}}

    async def fake_llm(prompt: str) -> dict:
        return {"data_models": [{"name": "Truck", "fields": [{"name": "name", "type": "varchar"}]}],
                "workflows": [{"name": "ApproveTruck", "description": "x"}],
                "pages": [{"route": "/trucks", "entity": "Truck",
                           "actions": [{"label": "Approve", "workflow": "ApproveTruck", "kind": "row_action"}]}]}

    out = asyncio.run(enrich_figma_plan_with_bindings(plan, file_meta, call_llm=fake_llm))
    assert out["pages"][0]["entity"] == "Truck"
    assert out["data_models"][0]["name"] == "Truck"


def test_enrich_falls_back_to_unmodified_plan_on_llm_error():
    plan = {"pages": [{"route": "/x", "file": "f", "entity": None}]}

    async def boom(prompt: str) -> dict:
        raise RuntimeError("llm down")

    out = asyncio.run(enrich_figma_plan_with_bindings(plan, {}, call_llm=boom))
    assert out["pages"][0]["entity"] is None
    assert out.get("data_models", []) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/services/test_figma_plan_binding.py -k enrich -v`
Expected: FAIL with `ImportError: cannot import name 'enrich_figma_plan_with_bindings'`

- [ ] **Step 3: Write minimal implementation**

```python
import json
import logging

logger = logging.getLogger(__name__)

_ANALYSIS_PROMPT = """You are wiring a generated app's data + actions.
Given these screens (with their visible text), propose:
- data_models: the entities the screens display, each with fields [{name, type}]
- workflows: the actions buttons should trigger, each {name, description}
- pages: for each screen route, its primary {entity} and {actions:[{label, workflow, kind}]}
  where kind is "row_action" (a button repeated per list row) or "page_action".
Only use workflow names you declared in `workflows`. Use the EXACT button label text.
Return ONLY a JSON object with keys data_models, workflows, pages.

SCREENS:
{screens}
"""


async def enrich_figma_plan_with_bindings(plan: dict, file_meta: dict, *, call_llm) -> dict:
    """Run the binding analysis and merge it into the plan. `call_llm` is an
    async callable (prompt:str) -> dict. On any error, returns the plan with
    empty binding intent (build proceeds; pages just stay unbound)."""
    plan.setdefault("data_models", [])
    plan.setdefault("workflows", [])
    for p in plan.get("pages") or []:
        p.setdefault("actions", [])
    try:
        analysis_input = build_binding_analysis_input(plan, file_meta)
        prompt = _ANALYSIS_PROMPT.format(screens=json.dumps(analysis_input["pages"], indent=1))
        analysis = await call_llm(prompt)
        if not isinstance(analysis, dict):
            raise ValueError("analysis not a dict")
        return merge_binding_analysis(plan, analysis)
    except Exception as exc:  # noqa: BLE001 — enrichment is best-effort
        logger.warning("Figma binding enrichment failed: %s — plan left unbound", exc)
        return plan
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/services/test_figma_plan_binding.py -v`
Expected: PASS (all figma_plan_binding tests, ~7)

- [ ] **Step 5: Commit**

```bash
git add backend/services/figma_plan_binding.py backend/tests/services/test_figma_plan_binding.py
git commit -m "feat(binding): LLM plan-enrichment orchestrator (injectable client)"
```

---

### Task 11: Real Anthropic `call_llm` adapter

**Files:**
- Modify: `backend/services/figma_plan_binding.py`

This wraps the project's Anthropic client into the `call_llm` signature. No new unit test (it's a thin network adapter, covered by Task 10's injected-client tests); verify by import.

- [ ] **Step 1: Read the existing client usage**

Run: `grep -n "AsyncAnthropic\|client.messages\|model=\|json.loads\|```json" backend/agents/figma_schema_refiner.py | head`
Note the client construction + model id + how JSON is extracted from the response.

- [ ] **Step 2: Add the adapter (mirror the refiner's client setup)**

```python
def make_anthropic_call_llm(*, model: str = "claude-sonnet-4-20250514", max_tokens: int = 4096):
    """Return an async call_llm(prompt)->dict backed by Anthropic. Mirrors the
    client construction used in agents/figma_schema_refiner.py."""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic()

    async def _call(prompt: str) -> dict:
        msg = await client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON object in LLM response")
        return json.loads(text[start:end + 1])

    return _call
```

- [ ] **Step 3: Verify import**

Run: `cd backend && python -c "from services.figma_plan_binding import make_anthropic_call_llm; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/services/figma_plan_binding.py
git commit -m "feat(binding): real Anthropic call_llm adapter for plan enrichment"
```

---

## Group 3 — Pipeline wiring

### Task 12: Binding pass phase in `_run_figma_relay_pipeline`

**Files:**
- Modify: `backend/routers/generate.py` (immediately after the schema-refiner block, ≈ line 1802)

The refiner block ends near line 1802 with `yield sse_event("log", {"text": f"[Refiner] block skipped: ..."})`. Add the binding phase right after it. It reuses the same `plan_pages` / `p.get("file")` pattern the refiner uses.

- [ ] **Step 1: Add the binding phase (after the refiner block)**

```python
    # ── BINDING PASS (plan-driven) ───────────────────────────────────────────
    # Apply plan binding intent (entity + actions) onto each generated page
    # schema: dataSources/bind/{{item.field}} for lists, workflow/args for
    # buttons. Deterministic; see docs/superpowers/specs/2026-06-09-figma-plan-
    # driven-binding-slice1-design.md.
    try:
        from services.schema_binding import apply_bindings
        import json as _json
        binding_reports = []
        for p in (plan.get("pages") or []):
            slug = (p.get("route", "/").strip("/").replace("/", "-") or "home")
            schema_path = Path(output_dir) / p.get("file", f"src/schemas/{slug}.json")
            if not schema_path.exists():
                continue
            try:
                page_schema = _json.loads(schema_path.read_text())
            except Exception:
                continue
            bound_schema, report = apply_bindings(page_schema, p, plan)
            schema_path.write_text(_json.dumps(bound_schema, indent=2))
            binding_reports.append(report)
            if report.get("list_bound") or report.get("buttons_bound"):
                yield sse_event("log", {"text": (
                    f"[Binding] {p.get('route')} → list={report.get('list_bound')} "
                    f"buttons={report.get('buttons_bound')}")})
            elif report.get("reverted"):
                yield sse_event("log", {"text": f"[Binding] {p.get('route')} reverted (invalid) — kept unbound"})
        (Path(output_dir) / "binding-report.json").write_text(_json.dumps(binding_reports, indent=2))
        yield sse_event("log", {"text": f"[Binding] applied to {len(binding_reports)} page(s)"})
    except Exception as _bind_ex:
        yield sse_event("log", {"text": f"[Binding] phase skipped: {_bind_ex}"})
```

- [ ] **Step 2: Verify the module imports + the file still parses**

Run: `cd backend && python -c "import ast; ast.parse(open('routers/generate.py').read()); print('generate.py OK')"`
Expected: `generate.py OK`

Run: `cd backend && python -c "from services.schema_binding import apply_bindings; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add backend/routers/generate.py
git commit -m "feat(binding): run plan-driven binding pass after Figma refiner"
```

---

### Task 13: Layer A hook — enrich the plan before approval

**Files:**
- Modify: `backend/routers/generate.py` (after each `build_plan_from_figma(...)` call that precedes a `plan_ready` emit — sites near lines 2612 and 3169)

- [ ] **Step 1: Locate the two enrichment sites**

Run: `grep -n "build_plan_from_figma" backend/routers/generate.py`
Expected: matches near lines 2612 and 3169 where the Figma scope plan is built.

- [ ] **Step 2: Add enrichment after the first site (≈ line 2612)**

After the line that assigns the scope plan (e.g. `req.plan = await build_plan_from_figma(req.figma_url, req.figma_token)`), add:

```python
            # Enrich the scope plan with binding intent (entity + actions +
            # data_models + workflows) so the user reviews bindings at approval.
            try:
                from services.figma_plan_binding import (
                    enrich_figma_plan_with_bindings, make_anthropic_call_llm,
                )
                from services.figma_client import fetch_figma_file
                from figma_parser import parse_figma_url as _parse
                _fk = _parse(req.figma_url)["file_key"]
                _meta = await fetch_figma_file(_fk, req.figma_token, depth=3)
                req.plan = await enrich_figma_plan_with_bindings(
                    req.plan, _meta, call_llm=make_anthropic_call_llm())
            except Exception as _enr_ex:
                logger.warning("[Figma Plan] binding enrichment skipped: %s", _enr_ex)
```

- [ ] **Step 3: Add the same enrichment after the second site (≈ line 3169)**

After `figma_plan = await build_plan_from_figma(figma_url, figma_token)`, add the same block but using the local variable names in that scope:

```python
                                try:
                                    from services.figma_plan_binding import (
                                        enrich_figma_plan_with_bindings, make_anthropic_call_llm,
                                    )
                                    from services.figma_client import fetch_figma_file
                                    from figma_parser import parse_figma_url as _parse
                                    _fk = _parse(figma_url)["file_key"]
                                    _meta = await fetch_figma_file(_fk, figma_token, depth=3)
                                    figma_plan = await enrich_figma_plan_with_bindings(
                                        figma_plan, _meta, call_llm=make_anthropic_call_llm())
                                except Exception as _enr_ex:
                                    logger.warning("[chat] binding enrichment skipped: %s", _enr_ex)
```

- [ ] **Step 4: Verify the file still parses**

Run: `cd backend && python -c "import ast; ast.parse(open('routers/generate.py').read()); print('generate.py OK')"`
Expected: `generate.py OK`

- [ ] **Step 5: Commit**

```bash
git add backend/routers/generate.py
git commit -m "feat(binding): enrich Figma plan with binding intent before approval"
```

---

### Task 14: End-to-end smoke on a fixture page

**Files:**
- Test: `backend/tests/services/test_schema_binding.py` (add an integration-style test using a realistic Cemex-like fixture)

- [ ] **Step 1: Write the test**

```python
def test_cemex_like_page_binds_list_and_row_button():
    # A list of trucks, each row showing plate + status with an Approve button.
    def row(i):
        return {"id": f"row{i}", "type": "Card", "children": [
            {"id": f"plate{i}", "type": "Text", "props": {"content": "License Plate"}},
            {"id": f"status{i}", "type": "Text", "props": {"content": "Status"}},
            {"id": f"app{i}", "type": "Button", "props": {"label": "Approve"}},
        ]}
    schema = {"schemaVersion": "2.0", "id": "trucks", "dataSources": [],
              "children": [{"id": "wrap", "type": "Stack", "children": [
                  {"id": "title", "type": "Text", "props": {"content": "Trucks"}},
                  {"id": "list", "type": "Stack", "children": [row(1), row(2), row(3), row(4)]},
              ]}]}
    plan = {"data_models": [{"name": "Truck", "fields": [
                {"name": "licensePlate"}, {"name": "status"}, {"name": "id"}]}],
            "workflows": [{"name": "ApproveTruck", "description": "approve"}]}
    intent = {"file": "src/schemas/trucks.json", "entity": "Truck",
              "actions": [{"label": "Approve", "workflow": "ApproveTruck", "kind": "row_action"}]}

    out, report = apply_bindings(schema, intent, plan)

    assert {"name": "truck", "entity": "Truck", "op": "list"} in out["dataSources"]
    repeats = [n for n in iter_nodes(out) if n.get("type") == "Repeat"]
    assert len(repeats) == 1 and repeats[0]["bind"] == "truck"
    # exactly one template row remains under the repeat
    assert len(repeats[0]["children"]) == 1
    btn = next(n for n in iter_nodes(out) if n.get("type") == "Button")
    assert btn["props"]["workflow"] == "ApproveTruck"
    assert btn["props"]["args"] == {"id": "{{item.id}}"}
    assert report["list_bound"] and report["buttons_bound"] == 1
```

- [ ] **Step 2: Run the full suite**

Run: `cd backend && python -m pytest tests/services/test_schema_binding.py tests/services/test_figma_plan_binding.py -v`
Expected: PASS (all binding tests green)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/services/test_schema_binding.py
git commit -m "test(binding): Cemex-like end-to-end list+button binding"
```

---

## Manual verification (after all tasks)

1. Regenerate the Cemex Figma app (or run the figma pipeline on `dif7qzm8`'s source design). Confirm at plan-approval the plan now shows per-page `entity` + `actions` and top-level `data_models`/`workflows`.
2. After build, inspect a list page schema in `output/<id>/src/schemas/*.json`: it should contain a page-level `dataSources` entry, a `Repeat` node with `bind`, `{{item.field}}` in row cells, and `workflow`+`args:{id:"{{item.id}}"}` on the row action button.
3. Inspect `output/<id>/binding-report.json` to see what bound vs. stayed unbound.
4. (If a DB is available) run the app and confirm the list renders real rows and the row button dispatches the workflow against that row.

## Out of scope (later slices — do NOT build here)

- Forms (create/update submit wiring) — slice 2
- Detail views (`op:"get"`) + stat/metric aggregates — slice 3
- Layer C LLM fallback for leftovers the deterministic pass couldn't bind — slice 4
- LLM-path unification (point Layer B at the LLM plan's existing intent) — folds in after Layer B proven
