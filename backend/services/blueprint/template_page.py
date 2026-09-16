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
    if isinstance(opts, list) and opts:
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
        spec["kind"] = "datetime"
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


def template_layout(doc: Mapping[str, Any], page: Mapping[str, Any]) -> dict | None:
    """The `pageLayouts` body for `page`, or ``None`` when its family has no
    template or its entity is unknown."""
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
        form_fields = [_field_kind(f) for f in fields]
        if not form_fields:
            return None
        root = {"type": "Stack", "props": {"direction": "vertical", "gap": "lg"}, "children": [
            {"type": "Row", "props": {"justify": "between", "align": "center"}, "children": [
                heading(name),
                *([{"type": "Button", "props": {"label": f"Back to {list_page.get('name') or 'list'}",
                                                 "variant": "secondary",
                                                 "navigate": str(list_page.get("route"))}, "children": []}]
                  if list_page else [])]},
            *([para(purpose)] if purpose else []),
            {"type": "Card", "props": {"title": f"{ename} details"}, "children": [
                {"type": "Form", "props": {"workflow": str(create.get("id")), "entity": ename,
                                           "fields": form_fields,
                                           "submitLabel": f"Create {ename}"}, "children": []}]},
        ]}
        sources = []

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
        if delete:
            actions.append({"type": "Button", "props": {"label": f"Delete {ename}", "variant": "danger",
                                                        "workflow": str(delete.get("id")),
                                                        "args": {"record": f"{{{{{src}.id}}}}"}}, "children": []})
        root = {"type": "Stack", "props": {"direction": "vertical", "gap": "lg"}, "children": [
            heading(f"{{{{{src}.{label_field}}}}}"),
            *([para(purpose)] if purpose else []),
            {"type": "Card", "props": {"title": f"{ename} details"}, "children": [
                {"type": "DescriptionList", "props": {"items": items, "orientation": "horizontal"}, "children": []}]},
            *([{"type": "Row", "props": {"gap": "sm", "justify": "end"}, "children": actions}] if actions else []),
        ]}
        sources = [{"name": src, "entity": ename, "op": "get"}]

    return {
        "page": str(page.get("id")),
        "root": root,
        "dataSources": sources,
        "composedBy": "deterministic",
        "rationale": (f"composed from the {family} template after the composer was refused at the "
                      f"attempt cap — {ename}'s fields, the page's declared actions, the workflows "
                      f"that exist for it; plain, but it renders and every control is bound"),
        "requirements": list(page.get("requirements") or []),
    }


__all__ = ["template_layout", "family_of"]
