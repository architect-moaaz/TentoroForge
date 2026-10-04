"""Which dicts in a page schema are COMPONENTS, and which are data.

A page tree mixes both: a Table's ``rows`` are records, and a record may well
have a ``type`` column ("Product type", "Ticket type", even "Button"). A guard
that treats any dict with a string ``type`` as a component edits the person's
data. So a node is a component only when its ``type`` is a KNOWN component
name (the library catalog plus the layout primitives), and the walk never
descends into data: ``rows``/``data``/``items`` of a data component, nor any
``rows``/``seed``/``fixture`` key.

Link-list components (Breadcrumb, Tabs, nav bars ...) keep their ``items`` /
``links`` read by component name - ``LINK_LIST_COMPONENTS`` is the one place
to add a name.
"""
from __future__ import annotations

import re
from typing import Any, Iterator

#: Layout and content primitives the catalog may not list.
PRIMITIVES = frozenset("""Stack Row Grid Box Container Spacer Text Image Icon Heading Split Cluster Section Slot Repeat
Conditional DataBoundary Custom PageOutlet Link Button""".split())

#: Components whose list props are LINKS, read by component name.
LINK_LIST_COMPONENTS = frozenset({
    "breadcrumb", "navlink", "nav", "navbar", "topnav", "topbar", "header", "sidenav", "sidebar", "tabs",
    "tabpanel", "tabpanelwithdeeplink", "menu", "menubar", "dropdownmenu", "contextmenu", "footer", "mobilenav",
    "pagination", "commandpalette", "appshell", "stepper", "wizard",
})
LINK_LIST_PROPS = ("items", "links", "tabs", "crumbs", "breadcrumbs", "navigation", "menu", "pages")

#: Components whose props hold records, never links to check.
DATA_COMPONENTS = frozenset({"table", "datagrid", "list", "chart", "kanban", "calendar", "timeline", "activityfeed",
                             "repeat", "descriptionlist", "keyvaluelist", "heatmap", "resourcetimeline", "tree",
                             "searchresults", "carousel", "datalist", "cardlist"})
#: Keys that hold data wherever they appear.
DATA_KEYS = frozenset({"rows", "data", "seed", "seed_data", "sample_data", "fixtures", "fixture", "records",
                       "dataSources", "clientState", "defaultValues", "options"})

_names_cache: frozenset[str] | None = None


def canon(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def known_names() -> frozenset[str]:
    """Canonical names of every component the app can render."""
    global _names_cache
    if _names_cache is None:
        names = {canon(n) for n in PRIMITIVES}
        try:
            from services.component_catalog import component_names
            names |= {canon(n) for n in component_names()}
        except Exception:  # noqa: BLE001 — the primitives and link lists still stand
            pass
        names |= set(LINK_LIST_COMPONENTS) | set(DATA_COMPONENTS) | {"form", "confirmdialog", "iconbutton", "navlink"}
        _names_cache = frozenset(names)
    return _names_cache


def is_component(node: Any) -> bool:
    return isinstance(node, dict) and isinstance(node.get("type"), str) and canon(node["type"]) in known_names()


def components(node: Any) -> Iterator[dict]:
    """Every component node under ``node``, never entering data."""
    if isinstance(node, dict):
        comp = is_component(node)
        if comp:
            yield node
        data_comp = comp and canon(node.get("type")) in DATA_COMPONENTS
        for k, v in node.items():
            if k in DATA_KEYS or not isinstance(v, (dict, list)):
                continue
            if k == "props":
                # props hold settings; they may hold nested component trees
                # (a slot, a header) but not a data component's records.
                if data_comp:
                    yield from _props_without_data(v)
                else:
                    yield from components(v)
            elif comp or k in ("root", "children"):
                yield from components(v)
            elif not comp:
                yield from components(v)
    elif isinstance(node, list):
        for v in node:
            yield from components(v)


def _props_without_data(props: Any) -> Iterator[dict]:
    if not isinstance(props, dict):
        return
    for k, v in props.items():
        if k in ("rows", "data", "items", "records", "events", "entries", "resources", "rowActions", "emptyAction", "columns"):
            continue
        if isinstance(v, (dict, list)):
            yield from components(v)


def link_items(node: dict) -> Iterator[dict]:
    """The link dicts of a link-list component's props (by component name)."""
    if canon(node.get("type")) not in LINK_LIST_COMPONENTS:
        return
    props = node.get("props") if isinstance(node.get("props"), dict) else {}
    for key in LINK_LIST_PROPS:
        val = props.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    yield item
                    for sub in item.get("items") or item.get("children") or []:
                        if isinstance(sub, dict):
                            yield sub
