"""The menu linked to the screens that answer it.

THE MENU IS DESIGNED BEFORE THE PAGES. `ux_architecture` writes
`navigation.tree` — labels and icons, grouped — before `page_contracts` has
planned a single page, and every reader of the menu (the rail, the route
graph, the navigation check, Smith's menu tool) follows an entry's `page` id.
Nothing wrote those ids: Mozato's 56 entries (forge-v3, 2026-10-06) pointed at
no page, so its rail would have been labels going nowhere.

So the planner names, for each screen it plans, the menu entry it answers
(`pages[].menuEntry`, a label path from the tree it is shown), and a tab of a
screen that is a menu destination of its own names one too
(`sections[].menuEntry`). When pages land, each named entry is linked: its
`page`, and its `section` for a tab. An entry already pointing at a live page
is left alone — a person or Smith may have pointed it there.
"""
from __future__ import annotations

from typing import Any, Iterator

#: Between the labels of a path, as the planner is shown and answers them.
SEP = " > "


def _walk(nodes: Any, trail: tuple[str, ...] = ()) -> Iterator[tuple[str, dict]]:
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        here = trail + (str(node.get("label") or "").strip(),)
        yield SEP.join(here), node
        yield from _walk(node.get("children"), here)


def menu_paths(doc: dict) -> list[str]:
    """Every entry of the menu as its label path, in tree order."""
    return [path for path, _ in _walk((doc.get("navigation") or {}).get("tree"))]


def _key(path: Any) -> str:
    return SEP.join(part.strip().lower() for part in str(path or "").split(">") if part.strip())


def bind_menu(doc: dict) -> list[str]:
    """Link every menu entry a page or section names to it. Returns the paths
    it linked."""
    tree = (doc.get("navigation") or {}).get("tree")
    if not tree:
        return []
    live = {str(p.get("id")) for p in doc.get("pages") or []
            if isinstance(p, dict) and p.get("id") and p.get("status") != "DEPRECATED"}
    wanted: dict[str, tuple[str, str | None]] = {}
    for page in doc.get("pages") or []:
        if not isinstance(page, dict) or str(page.get("id")) not in live:
            continue
        if page.get("menuEntry"):
            wanted.setdefault(_key(page["menuEntry"]), (str(page["id"]), None))
        for sec in page.get("sections") or []:
            if isinstance(sec, dict) and sec.get("menuEntry") and sec.get("key"):
                wanted.setdefault(_key(sec["menuEntry"]), (str(page["id"]), str(sec["key"])))
    linked: list[str] = []
    for path, node in _walk(tree):
        hit = wanted.get(_key(path))
        if hit is None or str(node.get("page") or "") in live:
            continue
        node["page"] = hit[0]
        if hit[1]:
            node["section"] = hit[1]
        else:
            node.pop("section", None)
        linked.append(path)
    # A SAVED VIEW FOLLOWS ITS SCREEN. "Orders > Active orders" carries
    # `view: active` — the Orders screen, filtered — so once "Orders" is
    # linked, its view children are too.
    for path, node in _walk(tree):
        page = str(node.get("page") or "")
        if page not in live:
            continue
        for child, label in ((c, str(c.get("label") or "")) for c in node.get("children") or []
                             if isinstance(c, dict)):
            if child.get("view") and str(child.get("page") or "") not in live:
                child["page"] = page
                linked.append(path + SEP + label)
    return linked
