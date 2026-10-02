"""Which of the application's modules are being built — the person's choice at
the product-model gate.

A module the person did not pick is `deferred`: its screens stay declared in
the Blueprint, so the product model still shows them and building them later
is the same run with the flag cleared, but nothing writes, lays out or serves
them. Its records, processes, rules and roles are built with everything else.
They are the application's substance, shared across modules and cheap next to
a screen, and building them once means a module added later lands in a
working application instead of beside one.

One question, asked in one place: `deferred_page_ids`. The fan-outs that write
a screen (`page_details`, `page_code`), the layout service and the frontend
projection all read it, so "which screens exist" cannot mean one thing to the
writer and another to the router.
"""
from __future__ import annotations

import copy
from typing import Any, Iterable, Mapping


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("status") != "DEPRECATED"]


def deferred_modules(doc: Mapping[str, Any]) -> set[str]:
    """The ids of the modules the person chose not to build yet."""
    return {str(m["id"]) for m in _live(doc.get("modules")) if m.get("id") and m.get("deferred")}


def module_of_page(doc: Mapping[str, Any]) -> dict[str, str]:
    """``{page id: module id}``. A page names its module; a module that lists
    a page the page does not claim back still owns it (the architect writes
    `modules[].pages` when it knows them)."""
    out: dict[str, str] = {}
    for m in _live(doc.get("modules")):
        for pid in m.get("pages") or []:
            out.setdefault(str(pid), str(m.get("id") or ""))
    for p in _live(doc.get("pages")):
        if p.get("id") and p.get("module"):
            out[str(p["id"])] = str(p["module"])
    return {k: v for k, v in out.items() if v}


def deferred_page_ids(doc: Mapping[str, Any]) -> set[str]:
    """Pages that belong to a deferred module. A sign-in page never does: it
    is how anybody reaches whatever was built."""
    held = deferred_modules(doc)
    if not held:
        return set()
    owner = module_of_page(doc)
    return {str(p["id"]) for p in _live(doc.get("pages"))
            if p.get("id") and p.get("pattern") != "auth" and owner.get(str(p["id"])) in held}


def _prune(nodes: Any, gone: set[str]) -> list[dict]:
    kept: list[dict] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        node = dict(node)
        had_children = bool(node.get("children"))
        if had_children:
            node["children"] = _prune(node["children"], gone)
        if node.get("page") in gone:
            if not node.get("children"):
                continue            # a destination that is not built is not shown
            node.pop("page")        # a group whose own page waits keeps its built children
        elif had_children and not node.get("children") and not node.get("page"):
            continue                # a heading whose every destination waits
        kept.append(node)
    return kept


def built_view(doc: Mapping[str, Any]) -> dict:
    """The document as the running application should see it: deferred
    modules' pages gone, and every way of reaching them gone with them.

    A copy — the Blueprint keeps the pages, because they are still the
    product the person agreed to. With nothing deferred it is the document
    itself, untouched, so every application built before modules could be
    picked projects exactly as it did."""
    gone = deferred_page_ids(doc)
    if not gone:
        return doc  # type: ignore[return-value]
    view = dict(doc)
    view["pages"] = [p for p in doc.get("pages") or []
                     if not (isinstance(p, dict) and str(p.get("id")) in gone)]
    routes = {str(p.get("route")) for p in doc.get("pages") or []
              if isinstance(p, dict) and str(p.get("id")) in gone and p.get("route")}
    nav = copy.deepcopy(doc.get("navigation") or {})
    if nav:
        nav["tree"] = _prune(nav.get("tree"), gone)
        nav["initialRoute"] = {role: route for role, route in (nav.get("initialRoute") or {}).items()
                               if route not in routes}
        view["navigation"] = nav
    held = deferred_modules(doc)
    view["modules"] = [m for m in doc.get("modules") or []
                       if not (isinstance(m, dict) and str(m.get("id")) in held)]
    for section in ("pageLayouts", "pageCode"):
        if doc.get(section):
            view[section] = [r for r in doc.get(section) or []
                             if not (isinstance(r, dict) and str(r.get("page")) in gone)]
    return view


def choose(svc: Any, modules: Iterable[str] | None) -> dict[str, list[str]]:
    """Record which modules this build is for. ``None`` means all of them.

    A module id that is not in the document is ignored rather than refused:
    the choice was made on a screen that may be a turn behind, and building
    what does exist is the answer the person asked for. Returns what is
    built and what waits, by name, for the build to say."""
    wanted = None if modules is None else {str(m) for m in modules}
    built: list[str] = []
    waiting: list[str] = []
    changed = False
    for m in _live(svc.doc.get("modules")):
        defer = wanted is not None and str(m.get("id")) not in wanted
        if bool(m.get("deferred")) != defer:
            changed = True
            if defer:
                m["deferred"] = True
            else:
                m.pop("deferred", None)
        (waiting if defer else built).append(str(m.get("name") or m.get("id")))
    if changed:
        svc.save()
    return {"built": built, "waiting": waiting}


__all__ = ["built_view", "choose", "deferred_modules", "deferred_page_ids", "module_of_page"]
