"""A city Select narrows to its state because the data model says so.

The dependency is a fact in the data model — City carries a foreign key to
State, declared as a relationship — not something a page author invents.
When a Form holds two Selects whose option sources are entities in that
relationship, the child's options are scoped by the parent's current value:
`optionsFrom.dependsOn = {field: <parent select>, column: <foreign key>}`.
Stated here at projection, once, from the relationship; the completeness
rule refuses a dependency whose parent is not on the form or whose column
the entity lacks. A dependency the author wrote is kept.
"""
from __future__ import annotations

from typing import Any


def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if isinstance(i, dict) and i.get("status") != "DEPRECATED"]


def _forms(node: Any):
    if isinstance(node, dict):
        if node.get("type") == "Form":
            yield node
        for c in node.get("children") or []:
            yield from _forms(c)


def _selects(node: Any):
    if isinstance(node, dict):
        if node.get("type") in ("Select", "Combobox", "MultiSelect"):
            yield node
        for c in node.get("children") or []:
            yield from _selects(c)


def wire_dependent_options(doc: dict, layout: dict) -> int:
    """Give every child Select its parent, from the relationships. Returns
    how many were wired."""
    entities = {str(e.get("id")): e for e in _live((doc.get("data") or {}).get("entities"))}
    by_name = {str(e.get("name")): str(e.get("id")) for e in entities.values()}
    source_entity: dict[str, str] = {}
    for s in layout.get("dataSources") or []:
        if isinstance(s, dict) and s.get("name") and s.get("entity"):
            ref = str(s["entity"])
            source_entity[str(s["name"])] = ref if ref in entities else by_name.get(ref, ref)
    rels = _live((doc.get("data") or {}).get("relationships"))
    wired = 0
    for form in _forms(layout.get("root")):
        selects = [n for n in _selects(form)
                   if isinstance((n.get("props") or {}).get("optionsFrom"), dict) and (n.get("props") or {}).get("name")]
        for child in selects:
            cp = child["props"]; of = cp["optionsFrom"]
            if of.get("dependsOn"):
                continue
            child_ent = source_entity.get(str(of.get("source") or ""))
            if not child_ent:
                continue
            for parent in selects:
                if parent is child:
                    continue
                parent_ent = source_entity.get(str((parent["props"].get("optionsFrom") or {}).get("source") or ""))
                if not parent_ent:
                    continue
                rel = next((r for r in rels if str(r.get("from")) == child_ent and str(r.get("to")) == parent_ent), None)
                if rel is None:
                    continue
                parent_name = str(entities.get(parent_ent, {}).get("name") or "")
                column = str(rel.get("fromField") or "") or (parent_name[:1].lower() + parent_name[1:] + "Id")
                of["dependsOn"] = {"field": str(parent["props"]["name"]), "column": column}
                wired += 1
                break
    return wired
