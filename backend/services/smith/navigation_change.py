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
        "initialRoute": {"type": "string", "description": "the route the app opens on, e.g. /master-data; \"\" to keep"},
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


def pages_brief(doc: dict) -> list[dict]:
    from services.blueprint.functional_completeness import page_family
    out = []
    for p in _live_pages(doc):
        route = str(p.get("route") or "")
        out.append({"id": str(p.get("id")), "route": route, "name": str(p.get("name") or ""),
                    "kind": page_family(p) or str(p.get("pattern") or ""),
                    "canBeInMenu": _navigable(route)})
    return out


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
                problems.append(f"{n.get('label')!r} opens {pid}, which is not a page of this application")
            elif not _navigable(str(pages[pid].get("route") or "")):
                problems.append(f"{n.get('label')!r} opens {pid} ({pages[pid].get('route')}), a record route that "
                                "cannot be a menu destination")
            elif pid in seen:
                problems.append(f"{pid} appears twice in the menu")
            seen.add(pid)
        elif not kids:
            problems.append(f"{n.get('label')!r} opens nothing and holds nothing")
    initial = nav.get("initialRoute")
    if isinstance(initial, dict):
        initial = initial.get("default")
    if initial and (str(initial) not in routes or not _navigable(str(initial))):
        problems.append(f"the landing route {initial!r} is not a page's concrete route")
    if nav.get("style") and nav["style"] not in ("sidebar", "topbar", "hybrid"):
        problems.append(f"style {nav['style']!r} is not sidebar, topbar or hybrid")
    return problems


def _prompt(doc: dict, change: str) -> tuple[str, str]:
    nav = doc.get("navigation") or {}
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
        "- `initialRoute` is a route from the pages given, or \"\" to leave it as it is.\n"
        "- If part of the request cannot be honoured (the page does not exist, the entry is "
        "already as asked), do what can be done and say the rest in `note`."
    )
    user = (
        f"The request: \"{change}\".\n\n"
        f"The pages:\n{json.dumps(pages_brief(doc), indent=1)}\n\n"
        f"The navigation as it stands:\n{json.dumps(nav, indent=1)}\n\n"
        "Return the whole navigation as it should be after the change."
    )
    return system, user


def _client(reasoning: Any = None) -> Any:
    from services.blueprint.executors import AGENT_MODEL, AnthropicModel
    return AnthropicModel(model=AGENT_MODEL, effort="medium")


def _labels(nav: dict) -> list[str]:
    out = []
    for n in (nav.get("tree") or []):
        if not isinstance(n, dict):
            continue
        kids = [str(k.get("label")) for k in (n.get("children") or []) if isinstance(k, dict)]
        out.append(f"{n.get('label')} [{', '.join(kids)}]" if kids else str(n.get("label")))
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
                   "initialRoute": ({"default": data["initialRoute"]} if data.get("initialRoute")
                                    else (before.get("initialRoute") or {}))}
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
        from services.blueprint.projection import project_nav_flow, project_root_route, project_shell
        files += project_shell(svc.doc, app_root).get("files") or []
        files += project_nav_flow(svc.doc, app_root).get("files") or []
        files += project_root_route(svc.doc, app_root).get("files") or []
    after = svc.doc.get("navigation") or {}
    return {"applied": True, "before": _labels(before), "after": _labels(after),
            "landing": ((after.get("initialRoute") or {}).get("default") if isinstance(after.get("initialRoute"), dict) else None),
            "style": after.get("style"), "note": note, "version": out.version, "edited_paths": files}


def summary_of(out: dict, change: str) -> str:
    s = f"Changed the menu for \"{change}\": now {' · '.join(out['after'])}"
    if out.get("before") != out.get("after"):
        s += f" (was {' · '.join(out['before'])})"
    s += "."
    if out.get("landing"):
        s += f" The app opens on {out['landing']}."
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
