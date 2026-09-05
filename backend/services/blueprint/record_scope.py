"""A control on a record page carries the record.

The engine finds the record a workflow acts on in its input — `input.id`,
or the input the workflow named — and a button on `/cases/[id]` that ran
"Submit for approval" sent `{}`: the page knew which case it showed, the
button did not, and the first step failed to find it. Every author was left
to rediscover the same argument; none did.

The page's record is a page-level fact, stated once here at projection: on
a detail page, every control that runs a workflow needing that entity's
record carries the record's id, read from the page's own `get` source
(`{{cases.id}}`), under the workflow's input name and under `id`. Nothing is
invented — a page with no such source, or a workflow needing another
entity, is left as authored, and the completeness rule says what is missing.
"""
from __future__ import annotations

from typing import Any, Iterable


def _live(items: Any) -> list[dict]:
    return [i for i in (items or []) if isinstance(i, dict) and i.get("status") != "DEPRECATED"]


def record_source(layout: dict, entity_id: str, entity_name: str) -> str | None:
    """The name of the page's `get` source for this entity, if it has one."""
    for src in layout.get("dataSources") or []:
        if isinstance(src, dict) and src.get("op") == "get" \
                and str(src.get("entity") or "") in (entity_id, entity_name):
            return str(src.get("name") or "") or None
    return None


def carry_record(doc: dict, page: dict, layout: dict) -> int:
    """Give every workflow control on a detail page the record it acts on.

    Mutates the layout's tree in place; returns how many controls changed.
    """
    route = str(page.get("route") or "")
    primary = str((page.get("data") or {}).get("primaryEntity") or "")
    if not route.endswith("]") or not primary:
        return 0
    entities = {str(e.get("id")): str(e.get("name") or "") for e in _live((doc.get("data") or {}).get("entities"))}
    name_of = entities.get(primary, primary)
    source = record_source(layout, primary, name_of)
    if not source:
        return 0
    workflows = {str(w.get("id")): w for w in _live(doc.get("workflows"))}
    changed = 0

    def walk(node: Any) -> None:
        nonlocal changed
        if not isinstance(node, dict):
            return
        props = node.get("props") or {}
        wf = workflows.get(str(props.get("workflow") or ""))
        if wf:
            args = dict(props.get("args") or {}) if isinstance(props.get("args"), dict) else {}
            before = dict(args)
            for inp in wf.get("inputs") or []:
                if inp.get("kind") == "record" and str(inp.get("entity") or "") in (primary, name_of):
                    args.setdefault(str(inp.get("name") or "id"), f"{{{{{source}.id}}}}")
                    args.setdefault("id", f"{{{{{source}.id}}}}")
            if args != before:
                props["args"] = args
                node["props"] = props
                changed += 1
        for child in node.get("children") or []:
            walk(child)

    walk(layout.get("root"))
    return changed


def carry_entity(doc: dict, page: dict, root: Any) -> int:
    """Every Form on the page that names no entity is the page's entity's
    form — the model its form-side rules are evaluated for. Returns how
    many were named."""
    primary = str((page.get("data") or {}).get("primaryEntity") or "")
    if not primary:
        return 0
    entities = {str(e.get("id")): str(e.get("name") or "") for e in _live((doc.get("data") or {}).get("entities"))}
    name = entities.get(primary) or primary
    named = 0

    def walk(node: Any) -> None:
        nonlocal named
        if not isinstance(node, dict):
            return
        if node.get("type") == "Form":
            props = node.get("props") or {}
            if not props.get("entity"):
                props["entity"] = name
                node["props"] = props
                named += 1
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    return named

