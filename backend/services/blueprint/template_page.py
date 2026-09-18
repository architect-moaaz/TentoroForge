"""The page a Blueprint can compose without a model — the composer of last resort.

When the a2ui composer and the authoring agent have both been refused at the
attempt cap, the choice used to be a route that 404s (with a good error
message) or a placeholder saying "this screen has not been laid out yet".
Neither is a page. This composes one from the page's OWN contract — its
pattern, its entity's fields, its declared actions, and the workflows that
exist for that entity — with no guessing: a control appears only when the
Blueprint has something for it to run or somewhere for it to go, which is
exactly the condition the completeness rules check. The tree is plain, it
renders, it binds its data, and it is held to the same contract as a composed
one before it is proposed. `composedBy: "deterministic"` (the contract's own value) says so on the layout, and
the completion line counts them, so nothing about it is silent.

Three families, resolved from the page's pattern and route:

* **collection** — heading, "Add <Entity>" to the form page, a searchable
  Table of the entity's fields with View / Edit / Delete row actions;
* **form** — heading, a Form over the entity's writable fields that runs the
  create workflow;
* **record** — heading from the record's label field, a DescriptionList of
  its fields, Edit and Delete controls.

A page outside those families (auth, static, dashboard) gets nothing here
and keeps the honest placeholder.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from services.blueprint.functional_completeness import (
    _live, _workflow_db_ops, _workflow_targets_entity, page_family,
)

_MANAGED = frozenset({"id", "createdat", "updatedat", "deletedat",
                      "created_at", "updated_at", "deleted_at"})

_ROUTE_ID = re.compile(r"\[[^\]]+\]")


def _humanise(name: str) -> str:
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", (name or "").strip())
    spaced = re.sub(r"[_\-]+", " ", spaced)
    return " ".join(w[:1].upper() + w[1:] for w in spaced.split())


def family_of(page: Mapping[str, Any]) -> str | None:
    """The completeness rules' own family — one definition for both."""
    return page_family(dict(page))


def _entity(doc: Mapping[str, Any], page: Mapping[str, Any]) -> dict | None:
    eid = str((page.get("data") or {}).get("primaryEntity") or "")
    for e in _live((doc.get("data") or {}).get("entities")):
        if str(e.get("id")) == eid or str(e.get("name")) == eid:
            return e
    return None


def _fields(entity: Mapping[str, Any]) -> list[dict]:
    out = []
    for f in entity.get("fields") or []:
        if not isinstance(f, dict) or not f.get("name"):
            continue
        if str(f["name"]).lower() in _MANAGED or f.get("references") or f.get("foreignKey"):
            continue
        out.append(f)
    return out


def _workflow_for(doc: Mapping[str, Any], entity_id: str, op: str) -> dict | None:
    for w in _live(doc.get("workflows")):
        if op in _workflow_db_ops(w) and _workflow_targets_entity(dict(doc), w, entity_id):
            return w
    return None


def _sibling(doc: Mapping[str, Any], page: Mapping[str, Any], family: str,
             *, with_id: bool | None = None) -> dict | None:
    """A sibling page of `family` for the same entity. ``with_id`` picks a form
    that edits (route carries `[id]`) or one that creates (no id) — the
    platform's own distinction — so an Edit never navigates to the create form."""
    eid = str((page.get("data") or {}).get("primaryEntity") or "")
    for p in _live(doc.get("pages")):
        if p is page or str(p.get("id")) == str(page.get("id")):
            continue
        if str((p.get("data") or {}).get("primaryEntity") or "") != eid:
            continue
        if family_of(p) != family:
            continue
        if with_id is not None and (("[" in str(p.get("route") or "")) != with_id):
            continue
        return p
    return None


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "", (name or "records").lower())
    return s or "records"


def _field_kind(f: Mapping[str, Any]) -> dict:
    t = str(f.get("type") or "string").lower()
    opts = f.get("enumValues") or f.get("enum") or f.get("options")   # `enumValues` is the Blueprint's key
    spec: dict[str, Any] = {"name": str(f["name"]), "label": _humanise(str(f["name"])),
                            "required": bool(f.get("required", False))}
    if t.endswith("[]") or t in ("array", "list"):
        spec["kind"] = "tags"                   # several values, submitted as an array
    elif isinstance(opts, list) and opts:
        spec["kind"] = "select"
        spec["options"] = [{"label": str(o), "value": str(o)} if not isinstance(o, dict) else
                           {"label": str(o.get("label") or o.get("value")), "value": str(o.get("value"))}
                           for o in opts]
    elif t in ("integer", "int", "number", "decimal", "float", "numeric"):
        spec["kind"] = "number"
    elif t in ("boolean", "bool"):
        spec["kind"] = "checkbox"
    elif t == "date":
        spec["kind"] = "date"
    elif t in ("timestamp", "datetime"):
        spec["kind"] = "date"                   # the Form has no datetime field
    elif t in ("text", "longtext"):
        spec["kind"] = "textarea"
    elif "email" in str(f.get("name")).lower():
        spec["kind"] = "email"
    else:
        spec["kind"] = "text"
    return spec


def _column(f: Mapping[str, Any]) -> dict:
    t = str(f.get("type") or "").lower()
    col = {"key": str(f["name"]), "label": _humanise(str(f["name"]))}
    if t in ("date",):
        col["format"] = "date"
    elif t in ("timestamp", "datetime"):
        col["format"] = "datetime"
    elif t in ("boolean", "bool"):
        col["format"] = "boolean"
    elif t in ("integer", "int", "number", "decimal", "float", "numeric"):
        col["format"] = "number"
    return col


def template_layout(doc: Mapping[str, Any], page: Mapping[str, Any]) -> dict:
    """The `pageLayouts` body for `page`. Every page gets one: a page outside
    the three families, or one its family cannot serve (a form with no create
    workflow, a page with no entity), is composed as a workspace."""
    return _family_layout(doc, page) or workspace_layout(doc, page)


def _family_layout(doc: Mapping[str, Any], page: Mapping[str, Any]) -> dict | None:
    family = family_of(page)
    entity = _entity(doc, page)
    if not family or not entity:
        return None
    eid, ename = str(entity.get("id")), str(entity.get("name") or entity.get("id"))
    fields = _fields(entity)
    name = str(page.get("name") or page.get("route") or ename)
    purpose = str(page.get("purpose") or "").strip()
    create = _workflow_for(doc, eid, "db_insert")
    update = _workflow_for(doc, eid, "db_update")
    delete = _workflow_for(doc, eid, "db_delete")
    form_page = _sibling(doc, page, "form", with_id=False) or _sibling(doc, page, "form")
    edit_page = _sibling(doc, page, "form", with_id=True)
    record_page = _sibling(doc, page, "record")
    list_page = _sibling(doc, page, "collection")
    src = _slug(ename)

    def heading(text: str, level: int = 1) -> dict:
        return {"type": "Heading", "props": {"content": text, "level": level}, "children": []}

    def para(text: str) -> dict:
        return {"type": "Text", "props": {"as": "p", "content": text}, "children": []}

    if family == "collection":
        header = [heading(name)]
        if form_page:
            header.append({"type": "Button", "props": {
                "label": f"Add {ename}", "variant": "primary",
                "navigate": str(form_page.get("route"))}, "children": []})
        row_actions: list[dict] = []
        if record_page:
            row_actions.append({"label": "View",
                                "navigate": _ROUTE_ID.sub("{{id}}", str(record_page.get("route")))})
        if edit_page:
            row_actions.append({"label": "Edit",
                                "navigate": _ROUTE_ID.sub("{{id}}", str(edit_page.get("route")))})
        elif form_page and update:
            row_actions.append({"label": "Edit",
                                "navigate": f"{form_page.get('route')}?id={{{{id}}}}"})
        if delete:
            row_actions.append({"label": "Delete", "workflow": str(delete.get("id")), "variant": "danger"})
        table: dict[str, Any] = {"data": f"{{{{{src}}}}}",
                                 "columns": [_column(f) for f in fields] or [{"key": "id", "label": "Id"}],
                                 "searchable": True, "striped": True,
                                 "emptyText": f"No {ename.lower()} records yet."}
        if row_actions:
            table["rowActions"] = row_actions
        root = {"type": "Stack", "props": {"direction": "vertical", "gap": "lg"}, "children": [
            {"type": "Row", "props": {"justify": "between", "align": "center"}, "children": header},
            *([para(purpose)] if purpose else []),
            {"type": "Table", "props": table, "children": []},
        ]}
        sources = [{"name": src, "entity": ename, "op": "list"}]

    elif family == "form":
        if not create:
            return None                    # a form with nothing to run is not a page
        sources = []
        form = _workflow_form(doc, page, create, entity, None, sources) if create.get("inputs") \
            else _node("Form", {"workflow": str(create.get("id")), "entity": ename,
                                "fields": [_field_kind(f) for f in fields],
                                "submitLabel": f"Create {ename}"})
        if form is None or not (form.get("props") or {}).get("fields"):
            return None
        form["props"]["submitLabel"] = f"Create {ename}"
        root = {"type": "Stack", "props": {"direction": "vertical", "gap": "lg"}, "children": [
            {"type": "Row", "props": {"justify": "between", "align": "center"}, "children": [
                heading(name),
                *([{"type": "Button", "props": {"label": f"Back to {list_page.get('name') or 'list'}",
                                                 "variant": "secondary",
                                                 "navigate": str(list_page.get("route"))}, "children": []}]
                  if list_page else [])]},
            *([para(purpose)] if purpose else []),
            {"type": "Card", "props": {"title": f"{ename} details"}, "children": [form]},
        ]}

    else:  # record
        label_field = str(entity.get("labelField") or (fields[0]["name"] if fields else "id"))
        items = [{"label": _humanise(str(f["name"])), "value": f"{{{{{src}.{f['name']}}}}}"} for f in fields]
        actions: list[dict] = []
        if list_page:
            actions.append({"type": "Button", "props": {"label": f"Back to {list_page.get('name') or 'list'}",
                                                        "variant": "secondary",
                                                        "navigate": str(list_page.get("route"))}, "children": []})
        if edit_page:
            actions.append({"type": "Button", "props": {"label": f"Edit {ename}", "variant": "secondary",
                                                        "navigate": _ROUTE_ID.sub(f"{{{{{src}.id}}}}", str(edit_page.get("route")))},
                            "children": []})
        elif form_page and update:
            actions.append({"type": "Button", "props": {"label": f"Edit {ename}", "variant": "secondary",
                                                        "navigate": f"{form_page.get('route')}?id={{{{{src}.id}}}}"},
                            "children": []})
        edit_here, extra = None, [{"name": src, "entity": ename, "op": "get"}]
        if update and not edit_page and not form_page:
            # Nowhere to go to edit it, so the record page edits it in place.
            edit_here = _workflow_form(doc, page, update, entity, src, extra)
            if edit_here is not None and edit_here.get("type") == "Form":
                edit_here["props"]["submitLabel"] = f"Save {ename}"
        if delete:
            actions.append({"type": "Button", "props": {"label": f"Delete {ename}", "variant": "danger",
                                                        "workflow": str(delete.get("id")),
                                                        "args": {"record": f"{{{{{src}.id}}}}"}}, "children": []})
        root = {"type": "Stack", "props": {"direction": "vertical", "gap": "lg"}, "children": [
            heading(f"{{{{{src}.{label_field}}}}}"),
            *([para(purpose)] if purpose else []),
            {"type": "Card", "props": {"title": f"{ename} details"}, "children": [
                {"type": "DescriptionList", "props": {"items": items, "orientation": "horizontal"}, "children": []}]},
            *([{"type": "Card", "props": {"title": f"Edit {ename}"}, "children": [edit_here]}]
              if edit_here else []),
            *([{"type": "Row", "props": {"gap": "sm", "justify": "end"}, "children": actions}] if actions else []),
        ]}
        sources = extra                    # the record, then any list a dropdown reads

    return {
        "page": str(page.get("id")),
        "root": root,
        "dataSources": sources,
        "composedBy": "deterministic",
        "rationale": (f"composed from the {family} template — {ename}'s fields, the page's "
                      f"declared actions, the workflows that exist for it"),
        "requirements": list(page.get("requirements") or []),
    }


# ---------------------------------------------------------------------------
# THE WORKSPACE — every page the three families do not cover.
#
# A dashboard, an approval inbox, a wizard, a settings screen: what each one
# is FOR is in its contract, and what a person can DO there is the workflows
# launched from it. So the page is those, in a fixed order — heading and
# purpose; a count per entity it reads, when it is an overview; one card per
# workflow it launches, a Form when the workflow needs fields; the primary
# entity's record or list; and the pages it leads to. A workflow control is
# included only when the page can supply everything the workflow needs,
# judged by the completeness rule itself, so nothing here is a button that
# does nothing.
# ---------------------------------------------------------------------------

_OVERVIEW_PATTERNS = frozenset({"dashboard", "analytics", "command_center", "overview",
                                "home", "landing", "report", "reports"})
_MAX_STATS = 4
_MAX_LINKS = 6


def _node(kind: str, props: dict, children: list | None = None) -> dict:
    return {"type": kind, "props": props, "children": children or []}


def _entity_by_id(doc: Mapping[str, Any], ref: str) -> dict | None:
    for e in _live((doc.get("data") or {}).get("entities")):
        if str(e.get("id")) == ref or str(e.get("name")) == ref:
            return e
    return None


def _source_name(doc: Mapping[str, Any], entity: Mapping[str, Any]) -> str:
    """The data resource the runtime registers the entity under — the
    projector's own name, so a dropdown's `optionsFrom` resolves."""
    from services.blueprint.projection import _var_name
    return _var_name(dict(entity))


def _launched_from(doc: Mapping[str, Any], page: Mapping[str, Any]) -> list[dict]:
    pid = str(page.get("id"))
    return [w for w in _live(doc.get("workflows"))
            if pid in [str(x) for x in (w.get("launchedFrom") or [])]]


def _input_field(doc: Mapping[str, Any], inp: Mapping[str, Any],
                 entity: Mapping[str, Any] | None) -> dict:
    """A Form field for one workflow input: the entity's own column when the
    name matches one (so an enum keeps its options), its declared type else."""
    name = str(inp.get("name"))
    column = next((f for f in (entity or {}).get("fields") or []
                   if isinstance(f, dict) and str(f.get("name")) == name), None)
    spec = _field_kind(column or {"name": name, "type": inp.get("type") or "string"})
    spec["name"] = name
    spec["required"] = bool(inp.get("required", True))
    if spec["kind"] == "select" and not spec.get("options"):
        spec["kind"] = "text"             # an enum with no declared values is typed
    return spec


def _workflow_form(doc: Mapping[str, Any], page: Mapping[str, Any], wf: Mapping[str, Any],
                   entity: Mapping[str, Any] | None, record_src: str | None,
                   sources: list[dict]) -> dict | None:
    """The control that runs `wf` from this page — a Form over its inputs, or
    a Button when it needs none — or ``None`` when the page cannot supply what
    it needs. `sources` gains any list a dropdown reads."""
    from services.blueprint.functional_completeness import unsatisfied_inputs

    wid, label = str(wf.get("id")), str(wf.get("name") or wf.get("id"))
    primary = str((entity or {}).get("id") or "")
    fields: list[dict] = []
    args: dict[str, str] = {}
    added: list[dict] = []
    for inp in wf.get("inputs") or []:
        if not isinstance(inp, dict) or not inp.get("name"):
            continue
        name = str(inp["name"])
        if inp.get("kind") == "record":
            target = _entity_by_id(doc, str(inp.get("entity") or ""))
            if target is None:
                continue
            if record_src and str(target.get("id")) == primary:
                args[name] = f"{{{{{record_src}.id}}}}"    # the record this page shows
                continue
            src = _source_name(doc, target)
            label_field = str(target.get("labelField") or next(
                (f["name"] for f in _fields(target)), "id"))
            fields.append({"kind": "select", "name": name, "label": _humanise(name),
                           "required": bool(inp.get("required", True)), "options": [],
                           "interaction": {"optionsFrom": {"source": src, "label": label_field,
                                                           "value": "id"}}})
            if not any(s.get("name") == src for s in sources + added):
                added.append({"name": src, "entity": str(target.get("name")), "op": "list",
                              "limit": 50})
        else:
            fields.append(_input_field(doc, inp, entity))

    if fields:
        props: dict[str, Any] = {"workflow": wid, "fields": fields, "submitLabel": label}
        if entity:
            props["entity"] = str(entity.get("name"))
        if args:
            props["args"] = args
        control = _node("Form", props)
    else:
        props = {"label": label, "variant": "primary", "workflow": wid}
        if args:
            props["args"] = args
        control = _node("Button", props)

    probe = {"page": str(page.get("id")), "root": control, "dataSources": sources + added}
    if unsatisfied_inputs(dict(doc), dict(page), probe, control, wid) or _refused(doc, page, probe):
        return None
    sources.extend(added)
    return control


#: What the whole page owes rather than what one control does wrong — judged
#: on the finished page, never on a control alone.
_PAGE_LEVEL_RULES = frozenset({"declared-action-without-control", "page-not-composed"})


def _refused(doc: Mapping[str, Any], page: Mapping[str, Any], probe: dict) -> bool:
    """Whether the completeness rules refuse this control on this page — a
    label whose verb the workflow does not do, a workflow that does not exist,
    a value it reads that nothing sends. The same rules `check_pattern_templates`
    applies, so a control that would cost the page its layout is left out."""
    from services.blueprint.functional_completeness import ADVISORY_PAGE_RULES, page_findings

    pid = str(page.get("id"))
    others = [p for p in _live(doc.get("pages")) if str(p.get("id")) != pid]
    findings = page_findings({"pages": [dict(page), *others],
                              "workflows": doc.get("workflows") or [],
                              "data": doc.get("data") or {},
                              "security": doc.get("security") or {},
                              "businessRules": [],
                              "pageLayouts": [probe]})
    return any(str(f.get("page")) == pid
               and f.get("rule") not in ADVISORY_PAGE_RULES | _PAGE_LEVEL_RULES
               for f in findings)


def _workflow_control(doc: Mapping[str, Any], page: Mapping[str, Any], wf: Mapping[str, Any],
                      entity: Mapping[str, Any] | None, record_src: str | None,
                      sources: list[dict]) -> dict | None:
    """`_workflow_form` in a card that says what the workflow is for."""
    control = _workflow_form(doc, page, wf, entity, record_src, sources)
    if control is None:
        return None
    label = str(wf.get("name") or wf.get("id"))
    purpose = str(wf.get("purpose") or "").strip()
    return _node("Card", {"title": label}, [
        *([_node("Text", {"as": "p", "content": purpose})] if purpose else []),
        control,
    ])


def workspace_layout(doc: Mapping[str, Any], page: Mapping[str, Any]) -> dict:
    """The `pageLayouts` body for a page no family template serves."""
    entity = _entity(doc, page)
    name = str(page.get("name") or page.get("route") or "Page")
    purpose = str(page.get("purpose") or "").strip()
    route = str(page.get("route") or "")
    pattern = str(page.get("pattern") or "").strip().lower()
    holds_record = bool(entity) and bool(_ROUTE_ID.search(route))
    sources: list[dict] = []
    body: list[dict] = []

    header: list[dict] = [_node("Heading", {"content": name, "level": 1})]
    ename = str((entity or {}).get("name") or "")
    src = _slug(ename) if entity else None
    create = _workflow_for(doc, str(entity.get("id")), "db_insert") if entity else None
    form_page = _sibling(doc, page, "form", with_id=False) if entity else None
    if form_page and create and not holds_record:
        header.append(_node("Button", {"label": f"Add {ename}", "variant": "primary",
                                       "navigate": str(form_page.get("route"))}))
    body.append(_node("Row", {"justify": "between", "align": "center"}, header))
    if purpose:
        body.append(_node("Text", {"as": "p", "content": purpose}))

    if pattern in _OVERVIEW_PATTERNS:
        refs = [str((page.get("data") or {}).get("primaryEntity") or "")]
        refs += [str(r) for r in (page.get("data") or {}).get("supportingEntities") or []]
        stats: list[dict] = []
        for ref in dict.fromkeys(r for r in refs if r):
            ent = _entity_by_id(doc, ref)
            if ent is None or len(stats) >= _MAX_STATS:
                continue
            count = f"{_slug(str(ent.get('name')))}_count"
            sources.append({"name": count, "entity": str(ent.get("name")), "op": "aggregate",
                            "metrics": {"value": {"fn": "count"}}})
            stats.append(_node("Stat", {"label": _humanise(str(ent.get("name"))),
                                        "value": f"{{{{{count}.value}}}}"}))
        if stats:
            body.append(_node("Grid", {"columns": min(len(stats), 4), "gap": "md"}, stats))

    if holds_record and entity:
        sources.append({"name": src, "entity": ename, "op": "get"})
        items = [{"label": _humanise(str(f["name"])), "value": f"{{{{{src}.{f['name']}}}}}"}
                 for f in _fields(entity)]
        if items:
            body.append(_node("Card", {"title": f"{ename} details"}, [
                _node("DescriptionList", {"items": items, "orientation": "horizontal"})]))

    for wf in _launched_from(doc, page):
        card = _workflow_control(doc, page, wf, entity, src if holds_record else None, sources)
        if card is not None:
            body.append(card)

    if entity and not holds_record:
        fields = _fields(entity)
        record_page = _sibling(doc, page, "record")
        edit_page = _sibling(doc, page, "form", with_id=True)
        delete = _workflow_for(doc, str(entity.get("id")), "db_delete")
        row_actions: list[dict] = []
        if record_page:
            row_actions.append({"label": "View",
                                "navigate": _ROUTE_ID.sub("{{id}}", str(record_page.get("route")))})
        if edit_page:
            row_actions.append({"label": "Edit",
                                "navigate": _ROUTE_ID.sub("{{id}}", str(edit_page.get("route")))})
        if delete:
            row_actions.append({"label": "Delete", "workflow": str(delete.get("id")),
                                "variant": "danger"})
        table: dict[str, Any] = {"data": f"{{{{{src}}}}}",
                                 "columns": [_column(f) for f in fields] or [{"key": "id", "label": "Id"}],
                                 "searchable": True, "striped": True,
                                 "emptyText": f"No {ename.lower()} records yet."}
        if row_actions:
            table["rowActions"] = row_actions
        sources.append({"name": src, "entity": ename, "op": "list", "limit": 25})
        body.append(_node("Card", {"title": _humanise(ename)}, [_node("Table", table)]))

    by_id = {str(p.get("id")): p for p in _live(doc.get("pages"))}
    links = [by_id[str(t)] for t in page.get("navigatesTo") or []
             if str(t) in by_id and not _ROUTE_ID.search(str(by_id[str(t)].get("route") or ""))
             and str(t) != str(page.get("id"))][:_MAX_LINKS]
    if links:
        body.append(_node("Row", {"gap": "sm", "wrap": True}, [
            _node("Button", {"label": str(p.get("name") or p.get("route")), "variant": "secondary",
                             "navigate": str(p.get("route"))}) for p in links]))

    return {
        "page": str(page.get("id")),
        "root": _node("Stack", {"direction": "vertical", "gap": "lg"}, body),
        "dataSources": sources,
        "composedBy": "deterministic",
        "rationale": ("composed as a workspace — the page's purpose, the workflows launched "
                      "from it, its entity's records and the pages it leads to"),
        "requirements": list(page.get("requirements") or []),
    }


__all__ = ["template_layout", "workspace_layout", "family_of"]
