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
    linked += _restore_named_entries(doc, tree, live)
    _drop_sign_in_entries(doc, tree)
    return linked


#: What a screen that nobody can reach from the menu is given: an entry for itself.
_ICON_FOR_PATTERN = {"settings": "settings"}


def _restore_named_entries(doc: dict, tree: list, live: set[str]) -> list[str]:
    """A screen names the menu entry it answers; when the menu has NO such entry (a later edit took it out and left the screen),
    the entry is put back at the end of the menu.

    PlantPal (2026-10-22): the menu listed "Account Settings" from the first draft; a repair step judged the screen out of the
    brief's scope, wrote Login over its entry, and left the screen in the plan. The screen was then in the plan and in the website,
    and in no menu: the phone's bar had no way to reach it. A path with a parent ("Admin > Coupons") is never made up here: only a
    top-level entry, for a screen that is a destination (no parameter in its route, not a sign-in page)."""
    have = {_key(path) for path, _ in _walk(tree)}
    linked_pages = {str(node.get("page")) for _, node in _walk(tree) if node.get("page")}
    added: list[str] = []
    for page in doc.get("pages") or []:
        if not isinstance(page, dict) or str(page.get("id")) not in live:
            continue
        entry = str(page.get("menuEntry") or "").strip()
        if (not entry or SEP.strip() in entry or _key(entry) in have or str(page["id"]) in linked_pages
                or "[" in str(page.get("route") or "") or str(page.get("pattern") or "") == "auth"):
            continue
        node: dict[str, Any] = {"label": entry, "page": str(page["id"]), "tab": True}
        icon = _ICON_FOR_PATTERN.get(str(page.get("pattern") or ""))
        if icon:
            node["icon"] = icon
        roles = _roles_of_neighbours(doc, tree)
        if roles:
            node["roles"] = roles
        tree.append(node)
        have.add(_key(entry))
        added.append(entry)
    return added


def _auth_page_ids(doc: dict) -> set[str]:
    return {str(p.get("id")) for p in doc.get("pages") or []
            if isinstance(p, dict) and p.get("status") != "DEPRECATED" and str(p.get("pattern") or "") == "auth"}


def _roles_of_neighbours(doc: dict, tree: list) -> list[str]:
    """The roles of the first entry that leads to a screen needing a sign-in: the new entry is for the same people."""
    auth = _auth_page_ids(doc)
    for _, node in _walk(tree):
        if node.get("roles") and str(node.get("page") or "") not in auth:
            return list(node["roles"])
    return []


def _drop_sign_in_entries(doc: dict, tree: list) -> list[str]:
    """Sign in and Sign up are not menu entries of an application that is signed in to: the gate sends a signed-out person to them
    and a signed-in one never needs them. PlantPal's menu (2026-10-22) listed Login and Sign Up beside My Plants and Today.

    Only when every other screen needs a person (an application with public screens may well show a sign-in link there), and
    only a top-level entry that leads to a sign-in page."""
    auth = _auth_page_ids(doc)
    if not auth:
        return []
    others = [p for p in doc.get("pages") or []
              if isinstance(p, dict) and p.get("status") != "DEPRECATED" and str(p.get("id")) not in auth]
    if not others or any(str(p.get("access") or "authenticated") == "public" for p in others):
        return []
    dropped = [str(n.get("label")) for n in tree if isinstance(n, dict) and str(n.get("page") or "") in auth]
    tree[:] = [n for n in tree if not (isinstance(n, dict) and str(n.get("page") or "") in auth)]
    return dropped
