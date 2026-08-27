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
    """Depth-first walk yielding every dict node (parents before children).
    A top-level page schema may carry its tree under `root` (LLM path) instead
    of `children` (Figma path); descend into `root` when present so both shapes
    are walked uniformly."""
    if isinstance(node, dict):
        yield node
        root = node.get("root")
        if isinstance(root, (dict, list)):
            yield from iter_nodes(root)
        for child in node.get("children") or []:
            yield from iter_nodes(child)
    elif isinstance(node, list):
        for item in node:
            yield from iter_nodes(item)


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
            # A real list row is a container: its template subtree must have
            # more than one node (the row plus at least one child cell).
            if template_size < 2:
                continue
            score = (len(members), template_size)
            if score > best_score:
                best_score = score
                start = kids.index(members[0])
                best = {"parent": parent, "signature": sig, "members": members, "start_index": start}
    return best


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
        for k in ("content", "label", "text", "children", "title", "value"):
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


def _page_list_source(schema: dict, entity: str | None) -> str | None:
    """Pick the page's list dataSource name to feed a DataGrid — prefer one whose
    entity matches the page entity, else the first op:list source."""
    lists = [d for d in (schema.get("dataSources") or [])
             if isinstance(d, dict) and d.get("op") == "list" and d.get("name")]
    if entity:
        for d in lists:
            if (d.get("entity") or "").lower() == str(entity).lower():
                return d["name"]
    return lists[0]["name"] if lists else None


def apply_datagrid_binding(schema: dict, page_intent: dict, entity_def: dict | None) -> tuple[dict, dict]:
    """Bind any unbound DataGrid's `rows` prop to the page's list dataSource.

    The schema agent emits DataGrid nodes with a literal ``rows: []``; the runtime
    renderer interpolates props, so ``rows: "{{tasks}}"`` resolves to the dataSource
    array (a whole-template interpolation yields the array itself). This is the
    DataGrid analogue of the Repeat ``bind`` the agent already sets — but DataGrid
    has no top-level bind, so the binding lives on ``props.rows``.

    Runs independently of apply_bindings' list-already guard: a page can have
    dataSources + bound Repeats yet still leave a DataGrid unbound. Idempotent —
    skips a DataGrid already bound to a ``{{...}}`` expression."""
    entity = (page_intent or {}).get("entity") or (entity_def or {}).get("name")
    grids = [n for n in iter_nodes(schema) if n.get("type") == "DataGrid"]
    if not grids:
        return schema, {"bound": 0}
    source = _page_list_source(schema, entity)
    if not source and entity:
        # No list dataSource present — create one so the grid has data to bind to.
        source = _slugify(entity)
        schema.setdefault("dataSources", [])
        if not any(ds.get("name") == source for ds in schema["dataSources"]):
            schema["dataSources"].append({"name": source, "entity": entity, "op": "list"})
    if not source:
        return schema, {"bound": 0, "reason": "no list dataSource"}
    bound = 0
    for g in grids:
        props = g.setdefault("props", {})
        rows = props.get("rows")
        if isinstance(rows, str) and "{{" in rows:
            continue  # already bound
        props["rows"] = f"{{{{{source}}}}}"
        bound += 1
    return schema, {"bound": bound, "source": source}


# A single static option authored as a {{source[0].field}} template — the LLM's
# stand-in for "the first row of this list". This is exactly the dynamic-options
# intent (iterate `source`, use `.field` for value/label); we lift it to optionsFrom.
_OPTION_TPL = re.compile(r"^\{\{\s*([A-Za-z_]\w*)\s*\[\s*\d+\s*\]\s*\.\s*(\w+)\s*\}\}$")
_OPTION_NODE_TYPES = {"Select", "Combobox", "MultiSelect"}


def _detect_options_from(node: dict, data_sources: list) -> dict | None:
    """If a Select/Combobox/MultiSelect's first option is bound to {{src[0].field}}
    and the page declares a `src` dataSource, return the optionsFrom spec
    {source, value, label}. Else None."""
    props = node.get("props") or {}
    opts = props.get("options")
    if not isinstance(opts, list) or not opts or not isinstance(opts[0], dict):
        return None
    vm = _OPTION_TPL.match(str(opts[0].get("value", "")))
    if not vm:
        return None
    source, value_field = vm.group(1), vm.group(2)
    lm = _OPTION_TPL.match(str(opts[0].get("label", "")))
    label_field = lm.group(2) if (lm and lm.group(1) == source) else value_field
    if not any(isinstance(ds, dict) and ds.get("name") == source for ds in data_sources):
        return None
    return {"source": source, "value": value_field, "label": label_field}


def apply_select_options_binding(schema: dict) -> tuple[dict, dict]:
    """Lift relational-FK dropdowns to dynamic options. The schema agent emits a
    Select/MultiSelect with ONE static option bound to `{{projects[0].id}}` —
    which submits the literal template string and fails the insert. We attach
    `props.optionsFrom = {source, value, label}` so the renderer builds the full
    option list from the page's dataSource at render time. Idempotent; the static
    option is left as the empty-state fallback. Returns (schema, {bound})."""
    data_sources = schema.get("dataSources") or []
    bound = 0
    for node in iter_nodes(schema):
        if node.get("type") not in _OPTION_NODE_TYPES:
            continue
        props = node.get("props")
        if not isinstance(props, dict) or props.get("optionsFrom"):
            continue
        spec = _detect_options_from(node, data_sources)
        if spec:
            props["optionsFrom"] = spec
            bound += 1
    return schema, {"bound": bound}


def _actions_by_label(intent: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for a in (intent or {}).get("actions") or []:
        lab = normalize_label(a.get("label"))
        if lab and (a.get("workflow") or a.get("kind") == "navigate"):
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
        for child in node.get("children") or []:
            _walk(child, here_repeat)

    _walk(schema.get("children") if "children" in schema else schema.get("root"), False)
    return schema, {"bound": bound, "unbound": unbound}


_APPROVE_WORDS = ("approve", "accept", "confirm", "grant", "authorize")
_REJECT_WORDS = ("reject", "deny", "decline", "refuse")


def annotate_decision_actions(schema: dict) -> tuple[dict, dict]:
    """Give approve/reject-labelled workflow buttons a distinct `args.__decision`
    ('approved'/'rejected') so the execute route can resolve + resume the pending
    approval task with the manager's decision.

    Without this the two buttons dispatch identical args and are indistinguishable
    no-ops. Only touches Buttons that already carry `props.workflow`; the entity id
    arg is preserved. Idempotent.
    """
    n = 0
    for node in iter_nodes(schema):
        if node.get("type") != "Button":
            continue
        p = node.get("props")
        if not isinstance(p, dict) or not p.get("workflow"):
            continue
        label = normalize_label(p.get("label") or p.get("text"))
        if any(w in label for w in _APPROVE_WORDS):
            decision = "approved"
        elif any(w in label for w in _REJECT_WORDS):
            decision = "rejected"
        else:
            continue
        args = p.setdefault("args", {})
        if not isinstance(args, dict):
            continue
        if args.get("__decision") != decision:
            args["__decision"] = decision
            n += 1
    return schema, {"decisions_annotated": n}


def _norm_wf_key(s: Any) -> str:
    """Collapse a workflow reference to a comparison key: lowercase, strip every
    non-alphanumeric char. So `createLeaveRequest`, `create-leaverequest`,
    `CreateLeaveRequest`, and `create_leave_request` all map to the same key."""
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def canonicalize_and_guard_workflow_buttons(
    schema: dict,
    workflow_index: dict | None,
    status_index: dict | None = None,
    entity: Any = None,
) -> tuple[dict, dict]:
    """Make every Button's `props.workflow` resolve to a real runtime cache key.

    The generated runtime caches each workflow by BOTH `definition.id` and
    `definition.name` (see src/lib/workflows/index.ts). A reference in another
    casing/separator (e.g. `createLeaveRequest` when the id is `create-leaverequest`
    and the name is `CreateLeaveRequest`) is a DEAD dispatch — `triggerWorkflow`
    returns "Workflow not found" and the button silently does nothing.

    `workflow_index` (from `crud_actions.build_workflow_index`) carries:
      - `exact`: every id/name string the cache is keyed by,
      - `norm`:  normalized-key → canonical name (the preferred cache key).

    For each Button carrying `props.workflow`:
      - namespaced builtins (`auth.signOut`, anything with a ".") are left alone,
      - a value already in `exact` is left alone (it resolves),
      - a value that normalizes to a known workflow is REWRITTEN to the canonical
        name (fixes casing/separator drift),
      - anything else is a true phantom → strip `workflow` + `args` so the button
        never fires a dead dispatch.

    The SAME reconciliation is applied to action-workflow refs the page agent emits
    OUTSIDE Button nodes — a data node's `props.rowActions[].action.workflow`
    (`{label, action:{type:"workflow", workflow}}`). A phantom row action is a dead
    button that renders but 404s, so the whole entry is DROPPED (a Button just loses
    its workflow; a row action has no other purpose, so it's removed).

    Backward-compatible: an empty/absent index is a no-op (the pipeline threads the
    index; unit callers that don't get the deterministic pass unchanged).
    """
    idx = workflow_index or {}
    exact = set(idx.get("exact") or [])
    norm = idx.get("norm") or {}
    counts = {"canonicalized": 0, "neutralized": 0, "mapped": 0}
    if not exact and not norm:
        return schema, {"workflows_canonicalized": 0, "workflows_neutralized": 0,
                        "workflows_mapped": 0}

    def _resolve(w: Any) -> tuple[str, str | None]:
        """Classify a workflow ref against the index.
        Returns (verdict, canonical) where verdict is 'skip' (leave as-is),
        'rewrite' (use canonical), or 'strip' (dead phantom)."""
        if not isinstance(w, str) or not w or "." in w:
            return "skip", None       # unset, or a namespaced renderer builtin
        if w in exact:
            return "skip", None       # already a valid cache key
        target = norm.get(_norm_wf_key(w))
        return ("rewrite", target) if target else ("strip", None)

    def _map_status(label: Any) -> dict | None:
        """Before treating a phantom as dead, try to map it to the entity's real
        status-transition workflow (e.g. Confirm → AppointmentStatusWorkflow with
        {appointmentId, targetStatus:'confirmed'}). Returns {workflow, args} or None."""
        if not status_index or not isinstance(label, str) or not label:
            return None
        try:
            from services.workflow_action_mapper import map_status_action
            return map_status_action(label, entity, status_index)
        except Exception:  # noqa: BLE001 — mapping is best-effort
            return None

    for node in iter_nodes(schema):
        p = node.get("props")
        if not isinstance(p, dict):
            continue

        # (1) Button.props.workflow — strip only the workflow ref, keep the button.
        if node.get("type") == "Button":
            verdict, target = _resolve(p.get("workflow"))
            if verdict == "rewrite":
                p["workflow"] = target
                counts["canonicalized"] += 1
            elif verdict == "strip":
                mapped = _map_status(p.get("label") or p.get("text"))
                if mapped:
                    p["workflow"] = mapped["workflow"]
                    p["args"] = {**(p.get("args") or {}), **mapped["args"]}
                    counts["mapped"] += 1
                else:
                    p.pop("workflow", None)
                    p.pop("args", None)
                    counts["neutralized"] += 1

        # (2) props.rowActions[].action.workflow — canonicalize, else map to the
        # real status workflow, else drop the entry (a dead row action is a button
        # that renders but 404s, with no other role).
        row_actions = p.get("rowActions")
        if isinstance(row_actions, list):
            kept = []
            for ra in row_actions:
                act = ra.get("action") if isinstance(ra, dict) else None
                if not (isinstance(act, dict) and act.get("type") == "workflow"):
                    kept.append(ra)
                    continue
                verdict, target = _resolve(act.get("workflow"))
                if verdict == "rewrite":
                    act["workflow"] = target
                    counts["canonicalized"] += 1
                    kept.append(ra)
                elif verdict == "strip":
                    mapped = _map_status(ra.get("label"))
                    if mapped:
                        act["workflow"] = mapped["workflow"]
                        act["args"] = {**(act.get("args") or {}), **mapped["args"]}
                        counts["mapped"] += 1
                        kept.append(ra)
                    else:
                        counts["neutralized"] += 1    # drop the entry
                else:
                    kept.append(ra)
            if len(kept) != len(row_actions):
                p["rowActions"] = kept

    return schema, {
        "workflows_canonicalized": counts["canonicalized"],
        "workflows_neutralized": counts["neutralized"],
        "workflows_mapped": counts["mapped"],
    }


def apply_form_bindings(schema: dict, *, entity: str | None, page_type: str | None,
                        route: str | None, existing_workflows: set) -> tuple[dict, dict]:
    """Wire a Form's submit to Create<Entity>/Update<Entity> on form pages.
    Update when the route looks like an edit (has 'edit' or an :id segment),
    else Create. Sets the workflow when the Form has NO workflow OR its current
    workflow is phantom (not in existing_workflows); a Form already wired to a
    real workflow is left untouched. Returns (schema, {forms_bound})."""
    bound = 0
    if entity and (page_type or "").lower() == "form":
        r = (route or "").lower()
        is_edit = "edit" in r or ":id" in r or "{id}" in r or "[id]" in r
        wf = f"Update{entity}" if is_edit else f"Create{entity}"
        # The entity list route the Cancel button returns to: /owners/new → /owners.
        _stripped = (route or "").strip("/")
        list_route = "/" + _stripped.rsplit("/", 1)[0] if "/" in _stripped else "/"
        if wf in existing_workflows:
            for node in iter_nodes(schema):
                if node.get("type") == "Form":
                    props = node.setdefault("props", {})
                    current = props.get("workflow")
                    # Set when absent or phantom; never override a real workflow.
                    if not current or current not in existing_workflows:
                        props["workflow"] = wf
                        bound += 1
            # Wire the form's buttons so the submit actually fires the workflow:
            # the primary/save button becomes a native submit trigger (the Form
            # collects field values + dispatches), and Cancel navigates back.
            _SUBMIT_WORDS = ("save", "create", "register", "submit", "add", "confirm")
            _CANCEL_WORDS = ("cancel", "back", "discard", "close")
            for node in iter_nodes(schema):
                if node.get("type") != "Button":
                    continue
                p = node.setdefault("props", {})
                label = str(p.get("label") or p.get("text") or "").lower()
                if any(c in label for c in _CANCEL_WORDS):
                    p.pop("workflow", None)
                    if not p.get("navigate"):
                        p["navigate"] = list_route
                elif p.get("workflow") == wf or p.get("variant") == "primary" or any(s in label for s in _SUBMIT_WORDS):
                    p["submit"] = True       # native type="submit" → triggers Form.onSubmit
                    p.pop("workflow", None)  # the Form owns the dispatch (with field values)
                    p.pop("navigate", None)  # a submit button must not also navigate (reloads + aborts submit)
    return schema, {"forms_bound": bound}


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


_BUILTIN_EMPTY = ("Table", "DataGrid")   # render their own in-frame empty state
_DATA_LISTS = ("Table", "DataGrid", "Repeat", "List", "Kanban", "Timeline")


def _list_source(node: dict) -> str | None:
    """The dataSource name a list node is bound to (for a count() guard)."""
    if not isinstance(node, dict):
        return None
    if isinstance(node.get("bind"), str) and node["bind"]:
        return node["bind"]
    p = node.get("props") or {}
    for k in ("rows", "data", "events", "items", "bind"):
        v = p.get(k)
        if isinstance(v, str):
            m = re.match(r"^\s*\{\{\s*([A-Za-z_]\w*)", v)
            if m:
                return m.group(1)
    return None


def _is_data_list(node: dict) -> bool:
    """A list container bound to a dataSource (Repeat bind, or Table/Kanban/etc.
    with a `{{…}}` rows/data binding)."""
    if not isinstance(node, dict) or node.get("type") not in _DATA_LISTS:
        return False
    if node.get("type") == "Repeat":
        return bool(node.get("bind"))
    return _list_source(node) is not None


def _find_data_list(node: dict):
    """First data-list node anywhere in a subtree, else None."""
    if isinstance(node, dict):
        if _is_data_list(node):
            return node
        for c in node.get("children") or []:
            r = _find_data_list(c)
            if r:
                return r
    return None


def strip_redundant_empty_states(schema: dict) -> tuple[dict, dict]:
    """Reconcile a page-level EmptyState with its data list so it never shows WITH data.

    An `EmptyState*` node placed next to a data list (Table/DataGrid/Repeat/…) has no
    condition, so it stacks below the list and shows even when there ARE rows. Fix by:
      - Table/DataGrid (own in-frame empty state) → REMOVE the sibling empty-state.
      - Repeat/List/Kanban (no built-in) → gate it with `visibleIf: "count(src) = 0"`
        so it only appears when the bound source is empty.
    The list may be nested inside a sibling (Section→Grid→Repeat), so subtrees are
    searched. Idempotent."""
    removed = 0
    gated = 0

    def walk(node):
        nonlocal removed, gated
        if not isinstance(node, dict):
            return
        kids = node.get("children")
        if isinstance(kids, list):
            empties = [c for c in kids if isinstance(c, dict) and str(c.get("type", "")).lower().startswith("emptystate")]
            if empties:
                list_node = next((_find_data_list(c) for c in kids if c not in empties and _find_data_list(c)), None)
                if list_node is not None:
                    if list_node.get("type") in _BUILTIN_EMPTY:
                        kids = [c for c in kids if c not in empties]
                        removed += len(empties)
                        node["children"] = kids
                    else:
                        src = _list_source(list_node)
                        if src:
                            for es in empties:
                                if not es.get("visibleIf"):
                                    es["visibleIf"] = f"count({src}) = 0"
                                    gated += 1
        for c in (kids or []):
            walk(c)
        if isinstance(node.get("root"), dict):
            walk(node["root"])

    walk(schema)
    return schema, {"empty_states_removed": removed, "empty_states_gated": gated}


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

    # Form submit wiring (Create/Update<Entity>). Threaded via page_intent by the
    # pipeline hooks: _existing_workflows/_page_type/_route. Backward-compatible:
    # no workflow set → no-op (forms_bound stays 0).
    existing_workflows = set((page_intent or {}).get("_existing_workflows") or [])
    page_type = (page_intent or {}).get("_page_type")
    form_route = (page_intent or {}).get("_route") or route
    work, form_info = apply_form_bindings(
        work,
        entity=(page_intent or {}).get("entity"),
        page_type=page_type,
        route=form_route,
        existing_workflows=existing_workflows,
    )

    # DataGrid row binding — runs REGARDLESS of list_already, because the schema
    # agent emits dataSources + bound Repeats (so list_already=True) yet leaves a
    # DataGrid's rows as a literal []. Idempotent; binds props.rows to the page's
    # list dataSource so DataGrid-based list pages render real records.
    work, grid_info = apply_datagrid_binding(work, page_intent, entity_def)

    # Relational FK dropdowns — lift single {{source[0].field}} options to a
    # dataSource-driven optionsFrom so the control offers every real row (and
    # submits a real id, not the literal template). Independent of the other
    # passes; acts only on Select/Combobox/MultiSelect with detectable templates.
    work, opt_info = apply_select_options_binding(work)

    # Drop empty-state siblings of a data Table — the Table renders its own
    # in-frame empty state, so a separate one stacks below (and shows with data).
    work, empty_info = strip_redundant_empty_states(work)

    # Canonicalize / phantom-guard action-button workflow refs — every props.workflow
    # must resolve to a real runtime cache key (id or name). Fixes casing/separator
    # drift (createLeaveRequest → CreateLeaveRequest) and strips dead dispatches so a
    # button never silently 404s. No-op unless the pipeline threaded _workflow_index.
    work, wf_btn_info = canonicalize_and_guard_workflow_buttons(
        work,
        (page_intent or {}).get("_workflow_index"),
        status_index=(page_intent or {}).get("_status_index"),
        entity=(page_intent or {}).get("entity"),
    )

    # Distinguish Approve vs Reject — each gets a `__decision` arg so the execute
    # route can resolve + resume the pending approval task with the right outcome.
    work, dec_info = annotate_decision_actions(work)

    if not _is_structurally_valid(work):
        return original, {"route": route, "list_bound": False, "list_skipped": list_already,
                          "buttons_bound": 0, "buttons_unbound": 0, "forms_bound": 0,
                          "datagrids_bound": 0, "select_options_bound": 0, "reverted": True}

    return work, {
        "route": route,
        "reverted": False,
        "list_bound": bool(list_info.get("bound")),
        "list_skipped": list_already,
        "list_reason": list_info.get("reason"),
        "buttons_bound": len(btn_info.get("bound") or []),
        "buttons_unbound": len(btn_info.get("unbound") or []),
        "forms_bound": form_info.get("forms_bound", 0),
        "datagrids_bound": grid_info.get("bound", 0),
        "select_options_bound": opt_info.get("bound", 0),
        "empty_states_removed": empty_info.get("empty_states_removed", 0),
        "empty_states_gated": empty_info.get("empty_states_gated", 0),
        "workflows_canonicalized": wf_btn_info.get("workflows_canonicalized", 0),
        "workflows_neutralized": wf_btn_info.get("workflows_neutralized", 0),
        "decisions_annotated": dec_info.get("decisions_annotated", 0),
    }
