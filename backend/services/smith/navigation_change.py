"""The navigation is a Blueprint section, and Smith can change it.

"Put Master Data first", "call the menu item Nurse Directory", "hide the
registration page from the menu", "land on Master Data", "group these under
Admin": every one of these is a change to `navigation` — the tree the shell
is projected from (`src/schemas/shell.json`: labels, order, icons, groups,
the landing route) — and nothing in Smith's verb set touched that section.

Blueprint-first, the shape the other seams take: the tree is revised against
the ask by a small structured call that sees the pages and the current tree;
the result is held to a contract (every entry names a live page with a
concrete route, no page twice, labels present, groups non-empty, the landing
route real); it is committed through `apply_change`; and the shell, the route
graph and the root route are re-projected. No page is composed — the rail is
not a page.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2

_NODE = {
    "type": "object",
    "properties": {
        "label": {"type": "string"},
        "page": {"type": "string", "description": "the page id (PAGE-001) this entry opens; omit for a group heading"},
        "icon": {"type": "string"},
    },
    "required": ["label"],
    "additionalProperties": False,
}

#: What the revision returns. Two levels — a group heading holds leaves —
#: which is what the shell renders; deeper trees have no rail to land on.
NAV_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "style": {"type": "string", "enum": ["sidebar", "topbar", "hybrid"]},
        "initialRoute": {
            "type": "array",
            "description": "where the app opens, per kind of user: `for` is \"default\" or one of the role "
                           "names given, `route` a route from the pages given. Only the landings the request "
                           "changes; [] keeps every landing as it is",
            "items": {
                "type": "object",
                "properties": {"for": {"type": "string"}, "route": {"type": "string"}},
                "required": ["for", "route"],
                "additionalProperties": False,
            },
        },
        "tree": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "page": {"type": "string"},
                    "icon": {"type": "string"},
                    "children": {"type": "array", "items": _NODE},
                },
                "required": ["label"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string", "description": "what could not be done and why, if anything"},
    },
    "required": ["tree"],
    "additionalProperties": False,
}


class NavigationChangeError(Exception):
    """The change could not be made, with the reason a user can act on."""


def _live_pages(doc: dict) -> list[dict]:
    return [p for p in (doc.get("pages") or []) if isinstance(p, dict) and p.get("status") != "DEPRECATED"]


def _navigable(route: str) -> bool:
    return bool(route) and "[" not in route


def shown_to(doc: dict) -> dict[str, list[str]]:
    """Who each page's menu entry is shown to, by page id — the roles the
    shell's rail shows it to (`projection.menu_scopes`); [] is everyone.

    THE MENU HAS NO VISIBILITY OF ITS OWN. An entry is shown to whoever its
    page is for, so "show the admin items only to admins" is a change to who
    may open those pages. Told nothing of this, the revision answered that the
    navigation "has no mechanism for per-role visibility", and Smith spent a
    turn reconciling that with a layout that plainly filters by role
    (wz7a99ir, 2026-10-04)."""
    from services.blueprint.projection import menu_scopes
    roles, audience = menu_scopes(doc)
    return {str(p.get("id")): roles.get(str(p.get("id"))) or audience.get(str(p.get("id"))) or []
            for p in _live_pages(doc)}


def pages_brief(doc: dict) -> list[dict]:
    from services.blueprint.functional_completeness import page_family
    who = shown_to(doc)
    out = []
    for p in _live_pages(doc):
        route = str(p.get("route") or "")
        out.append({"id": str(p.get("id")), "route": route, "name": str(p.get("name") or ""),
                    "kind": page_family(p) or str(p.get("pattern") or ""),
                    "canBeInMenu": _navigable(route),
                    "shownTo": who.get(str(p.get("id"))) or "everyone"})
    return out


def without_removed(doc: dict, nav: dict) -> dict:
    """The navigation with every entry whose page was removed left out, and a
    group left empty with it. A removed page's entry stayed in F&B's stored
    tree; shown to the revision, it was kept, and the whole menu was refused
    for opening "a page that is not a page of this application"."""
    live = {str(p.get("id")) for p in _live_pages(doc)}

    def keep(node: Any) -> Any:
        if not isinstance(node, dict):
            return None
        kids = [k for k in (keep(c) for c in node.get("children") or []) if k]
        if node.get("page") and str(node["page"]) not in live:
            return None
        if node.get("children") and not kids and not node.get("page"):
            return None
        out = {k: v for k, v in node.items() if k != "children"}
        if kids:
            out["children"] = kids
        return out

    return {**nav, "tree": [n for n in (keep(n) for n in nav.get("tree") or []) if n]}


def _walk(tree: list) -> list[dict]:
    out = []
    for n in tree or []:
        if isinstance(n, dict):
            out.append(n)
            out.extend(_walk(n.get("children") or []))
    return out


def validate(doc: dict, nav: dict) -> list[str]:
    """The contract a revised navigation is held to."""
    problems: list[str] = []
    pages = {str(p.get("id")): p for p in _live_pages(doc)}
    routes = {str(p.get("route") or ""): str(p.get("id")) for p in pages.values()}
    tree = nav.get("tree")
    if not isinstance(tree, list) or not tree:
        return ["the tree is empty — a menu with nothing in it"]
    seen: set[str] = set()
    for n in _walk(tree):
        if not str(n.get("label") or "").strip():
            problems.append("an entry has no label")
        pid = str(n.get("page") or "")
        kids = n.get("children") or []
        if pid:
            if pid not in pages:
                removed = any(str(p.get("id")) == pid for p in doc.get("pages") or [] if isinstance(p, dict))
                problems.append(f"{n.get('label')!r} opens {pid}, which " + (
                    "was removed from this application — leave its entry out" if removed
                    else "is not a page of this application"))
            elif not _navigable(str(pages[pid].get("route") or "")):
                problems.append(f"{n.get('label')!r} opens {pid} ({pages[pid].get('route')}), a record route that "
                                "cannot be a menu destination")
            elif pid in seen:
                problems.append(f"{pid} appears twice in the menu")
            seen.add(pid)
        elif not kids:
            problems.append(f"{n.get('label')!r} opens nothing and holds nothing")
    # EVERY LANDING, NOT JUST THE DEFAULT. `initialRoute` is a map per kind of
    # user, and each entry is a door someone is sent through.
    initial = nav.get("initialRoute")
    landings = initial if isinstance(initial, dict) else ({"default": initial} if initial else {})
    kinds = {"default"} | {k.lower() for k in _role_keys(doc)}
    for who, route in landings.items():
        if str(who).lower() not in kinds:
            problems.append(f"{who!r} is not a kind of user of this application, so it has no landing")
        if route and (str(route) not in routes or not _navigable(str(route))):
            problems.append(f"the landing route {route!r} for {who} is not a page's concrete route")
    if nav.get("style") and nav["style"] not in ("sidebar", "topbar", "hybrid"):
        problems.append(f"style {nav['style']!r} is not sidebar, topbar or hybrid")
    return problems


def _role_keys(doc: dict) -> list[str]:
    """The kinds of user a landing may be declared for: each role's name and
    id, as the Blueprint's `initialRoute` may be keyed by either."""
    out: list[str] = []
    for r in doc.get("roles") or []:
        if not isinstance(r, dict) or r.get("status") == "DEPRECATED":
            continue
        out += [str(v) for v in (r.get("name"), r.get("id")) if v]
    return out


def _landings(doc: dict, before: dict, answer: Any) -> dict:
    """The landing map after the answer: the entries it names laid over the
    ones that stand.

    The map is per kind of user ("default", and one per role). The reply used
    to carry one string and the verb wrote `{"default": it}` — so "put Master
    Data first" silently took away every role's own landing, and the 403 page's
    per-role map emptied with it. Now an entry changes only the kind it names;
    a role the reply is silent about keeps its door. A key is matched to the
    map's own spelling case-insensitively ("admin" answers for "Admin"), and a
    bare string still means the default.
    """
    current = dict(before.get("initialRoute") or {}) if isinstance(before.get("initialRoute"), dict) else {}
    if isinstance(answer, str):
        entries = [{"for": "default", "route": answer}] if answer else []
    elif isinstance(answer, dict):
        entries = [{"for": k, "route": v} for k, v in answer.items()]
    else:
        entries = [e for e in (answer or []) if isinstance(e, dict)]
    spelled = {k.lower(): k for k in current}
    spelled.update({k.lower(): k for k in _role_keys(doc) if k.lower() not in spelled})
    for e in entries:
        who, route = str(e.get("for") or "").strip(), str(e.get("route") or "").strip()
        if not who or not route:
            continue
        current[spelled.get(who.lower(), who)] = route
    return current


def _prompt(doc: dict, change: str) -> tuple[str, str]:
    nav = doc.get("navigation") or {}
    roles = [str(r.get("name")) for r in (doc.get("roles") or [])
             if isinstance(r, dict) and r.get("name") and r.get("status") != "DEPRECATED"]
    system = (
        "You revise the navigation of an application that is already built — the menu the "
        "app shell renders: its entries, their order, their labels and icons, optional group "
        "headings holding entries, the menu style, and the route the app opens on.\n\n"
        "Rules:\n"
        "- Change ONLY what the request asks. Every other entry keeps its label, icon, "
        "position and grouping.\n"
        "- An entry opens a page by its id, from the pages given. Never invent a page; a "
        "page whose canBeInMenu is false (a record route) cannot be an entry.\n"
        "- A page appears at most once. Removing a page from the menu hides it; the page "
        "still exists.\n"
        "- A group heading has children and no page; it must hold at least one entry.\n"
        "- `initialRoute` is where the app opens, per kind of user: an entry for \"default\" and "
        "one per role name given, each a route from the pages given. Return only the landings the "
        "request changes; a kind of user you leave out keeps its landing.\n"
        "- Who sees an entry is not set in the menu: each entry is shown to the people its page is "
        "for (`shownTo` on each page). A request to show or hide entries for a kind of user is a "
        "change to who may open those pages — make any menu part of the request, and say in `note`, "
        "naming the pages, that who may open them is changed with edit_access.\n"
        "- If part of the request cannot be honoured (the page does not exist, the entry is "
        "already as asked), do what can be done and say the rest in `note`."
    )
    kinds_note = '(one kind of user; only "default" applies)'
    user = (
        f"The request: \"{change}\".\n\n"
        f"The pages:\n{json.dumps(pages_brief(doc), indent=1)}\n\n"
        f"The kinds of user (roles): {', '.join(roles) or kinds_note}\n\n"
        f"The navigation as it stands:\n{json.dumps(without_removed(doc, nav), indent=1)}\n\n"
        "Return the whole navigation as it should be after the change."
    )
    return system, user


def _client(reasoning: Any = None) -> Any:
    from services.blueprint.executors import AGENT_MODEL, AnthropicModel
    return AnthropicModel(model=AGENT_MODEL, effort="medium")


def _labels(nav: dict, who: dict[str, list[str]] | None = None) -> list[str]:
    """Each entry's label, and — with `who` — whom it is shown to, so what the
    menu looks like to each kind of user is said, never assumed."""
    def one(n: dict) -> str:
        roles = (who or {}).get(str(n.get("page") or ""))
        return f"{n.get('label')} ({', '.join(roles)} only)" if roles else str(n.get("label"))
    out = []
    for n in (nav.get("tree") or []):
        if not isinstance(n, dict):
            continue
        kids = [one(k) for k in (n.get("children") or []) if isinstance(k, dict)]
        out.append(f"{n.get('label')} [{', '.join(kids)}]" if kids else one(n))
    return out


def change_navigation(svc: Any, change: str, *, app_root: str | None = None,
                      client: Any = None, reasoning: Any = None) -> dict:
    from services.blueprint.agent_contract import ArtifactProposal
    from services.blueprint.service import BlueprintInvalid
    from services.smith.change import apply_change

    change = (change or "").strip()
    if not change:
        raise NavigationChangeError("nothing was described, so there is nothing to change in the menu.")
    if not _live_pages(svc.doc):
        raise NavigationChangeError("this application has no pages yet, so it has no menu to change.")
    before = json.loads(json.dumps(svc.doc.get("navigation") or {}))
    call = client or _client(reasoning)
    system, user = _prompt(svc.doc, change)
    feedback = ""
    revised: dict = {}
    for attempt in range(1, MAX_ATTEMPTS + 1):
        tell(reasoning, f"Revising the menu: {change}.", "step")
        raw = call(system=system, user=user + (f"\n\nYour previous answer was refused:\n{feedback}" if feedback else ""),
                   schema=NAV_SCHEMA)
        text = getattr(raw, "text", raw)
        try:
            data = json.loads(str(text))
        except ValueError as exc:
            feedback = f"not JSON: {exc}"
            continue
        revised = {"style": data.get("style") or before.get("style") or "sidebar",
                   "tree": data.get("tree") or [],
                   "initialRoute": _landings(svc.doc, before, data.get("initialRoute"))}
        for n in _walk(revised["tree"]):
            if "children" in n and not n["children"]:
                n.pop("children")
        problems = validate(svc.doc, revised)
        if not problems:
            revised["_note"] = str(data.get("note") or "").strip()
            break
        feedback = "; ".join(problems)
        if attempt == MAX_ATTEMPTS:
            raise NavigationChangeError(f"the revised menu was refused {MAX_ATTEMPTS} times and nothing has been "
                                        f"changed. The last reason was: {feedback}")
        tell(reasoning, f"That menu was refused — {feedback}. Asking again.", "step")
    note = revised.pop("_note", "")
    if json.dumps(revised, sort_keys=True) == json.dumps(
            {k: before.get(k) for k in ("style", "tree", "initialRoute")}, sort_keys=True):
        raise NavigationChangeError("the menu came back exactly as it is" + (f" — {note}" if note else "") + ".")
    try:
        out = apply_change(svc, change, proposals=[ArtifactProposal("navigation", "navigation", revised)],
                           interpretation=f"change the navigation: {change}", agent="solution_architecture",
                           app_root=app_root, regenerate=False)
    except BlueprintInvalid as exc:
        raise NavigationChangeError(f"the revised menu does not fit the Blueprint: {exc}") from exc
    if not out.applied:
        raise NavigationChangeError(str(out.reason or "the change was refused"))
    files: list[str] = []
    if app_root:
        from services.blueprint.projection import project_navigation
        files += project_navigation(svc.doc, app_root)["files"]
    after = svc.doc.get("navigation") or {}
    landings = after.get("initialRoute") if isinstance(after.get("initialRoute"), dict) else {}
    return {"applied": True, "before": _labels(before), "after": _labels(after, shown_to(svc.doc)),
            "landing": landings.get("default"),
            "landings": {k: v for k, v in landings.items() if k != "default"
                         and v != (before.get("initialRoute") or {}).get(k)},
            "style": after.get("style"), "note": note, "version": out.version, "edited_paths": files}


def summary_of(out: dict, change: str) -> str:
    s = f"Changed the menu for \"{change}\": now {' · '.join(out['after'])}"
    if out.get("before") != out.get("after"):
        s += f" (was {' · '.join(out['before'])})"
    s += "."
    if out.get("landing"):
        s += f" The app opens on {out['landing']}."
    for who, route in (out.get("landings") or {}).items():
        s += f" {who} opens on {route}."
    if out.get("note"):
        s += f" {out['note']}"
    return s


def run(output_dir: str, change: str, *, reasoning: Any = None) -> dict:
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": "this project has no Blueprint yet, so there is no menu to change."}
    app_root = str(Path(output_dir) / "app")
    try:
        out = change_navigation(svc, change, app_root=app_root, reasoning=reasoning)
    except NavigationChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[smith] navigation change failed")
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out["edited_paths"], "diff_summary": summary_of(out, change),
            "version": out["version"], "reason": ""}


__all__ = ["change_navigation", "validate", "pages_brief", "run", "summary_of", "NAV_SCHEMA", "NavigationChangeError"]
