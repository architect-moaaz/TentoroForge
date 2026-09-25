"""A screen the owner is done with — gone from the application, kept in the record.

"Delete that page" was one of the sentences with nothing behind it. The verb
existed only to refuse: *a page can be hidden from the menu or retired with
its record type, never removed on its own*. That answer was true of the code
and useless to the person, who asked twice and kept seeing the page.

WHAT "REMOVED" MEANS HERE, AND WHY. Not deleted from the document. §22's
convention is DEPRECATED-not-deleted, and it is load-bearing in three ways a
delete would break:

  * the id. `PAGE-007` is cited by `codeMap`, by other pages' `navigatesTo`,
    by decisions and requirements. Delete the row and the counter still
    refuses to re-mint it, but nothing records that the id is spent — so
    `IdAllocator.retire` is called here and the id is spent explicitly. It is
    never handed to a different screen, and the same route coming back later
    revives its own id rather than taking someone else's.
  * the layout. A retired page keeps its composed tree behind it, which is
    what makes this undoable: `revert` restores the version this commits
    against and the screen comes back as it was, not as a stub.
  * the record. "Why is there no Wards page" is answerable a year later.

And the page GENUINELY DISAPPEARS, which is the half that was missing. Every
consumer reads live artifacts only: `plan_pages` skips it, so
`project_frontend` sweeps its schema file and drops its route from the
registry — the URL stops resolving. `_entry_route` recomputes, so "/" never
forwards to it. `project_middleware` recomputes the public matcher from the
pages that remain. The rail is pruned here. There is nothing left to find it
by, which is what the owner meant.

WHAT ELSE POINTS AT A SCREEN. A page is not a leaf. It is named by the menu,
by the landing route, by other pages' `navigatesTo`, by controls composed on
other pages (`navigate`, `href`, `to`, `rowHref`), and by workflows that say
they are launched from it. A delete that took the row and left those is the
defect this verb is supposed to be the cure for — a button that opens a 404 is
a dead end dressed as a screen.

So they are REWRITTEN, not refused: the links come off the screens that held
them and those screens stop declaring the verbs those links served, exactly as
a retired workflow's controls do (`move_dispatcher._retract`). Refusing and
naming them would leave the owner to go and remove three links by hand and ask
a third time. What the owner is NOT left to discover is the size of it: the
turn shows what the removal takes with it and waits for a yes
(`smith_session._confirm_cascade`), which is the same gate a field and an
entity already pass through.

ONE THING IS REFUSED, because no rewrite of it is coherent: the last screen a
visitor can arrive at. `landing_route` would then emit `redirect("/")` into
itself, and an application with nothing to open is not an application.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.llm_client import tell
from services.smith.section_change import SectionChangeError

logger = logging.getLogger(__name__)

#: Every way a composed control says where it goes. `to` is also a gradient's
#: end colour, which is why a value must BE this page's route to count — the
#: comparison is against one concrete route, so `#f5f5f5` can never match it.
LINK_KEYS = ("navigate", "href", "to", "rowHref", "onRowClick")

#: Controls that exist to be clicked. One whose only job was opening the
#: retired screen comes off the tree; a Table that merely linked its rows
#: keeps its rows and loses the link.
_CLICK_CONTROLS = ("Button", "IconButton", "Link", "ConfirmDialog")


def _pages(doc: dict) -> list[dict]:
    return [p for p in (doc.get("pages") or []) if isinstance(p, dict)]


def _live(doc: dict) -> list[dict]:
    return [p for p in _pages(doc) if p.get("status") != "DEPRECATED"]


def _layouts(doc: dict) -> dict[str, dict]:
    """Page id -> the layout currently standing for it."""
    return {str(l.get("page")): l for l in (doc.get("pageLayouts") or [])
            if isinstance(l, dict) and l.get("status") not in ("SUPERSEDED", "DEPRECATED")}


def _walk_nav(tree: Any) -> list[dict]:
    out: list[dict] = []
    for n in tree or []:
        if isinstance(n, dict):
            out.append(n)
            out.extend(_walk_nav(n.get("children") or []))
    return out


def _shape(route: str) -> str:
    from services.blueprint.functional_completeness import _route_shape
    return _route_shape(route)


def find_page(doc: dict, ref: str) -> dict | None:
    """The screen a person means: its id, its route, or its name."""
    from services.smith.labels import normalise

    want = normalise(ref)
    if not want:
        return None
    for page in _live(doc):
        if str(page.get("id") or "").lower() == (ref or "").strip().lower():
            return page
        if want in (normalise(page.get("route") or ""), normalise(page.get("name") or "")):
            return page
    return None


def routes(doc: dict) -> str:
    return ", ".join(f"{p.get('name')} ({p.get('route')})" for p in _live(doc)) or "(none)"


def arrivable(doc: dict, *, without: str = "") -> list[str]:
    """Routes a visitor can actually arrive at — concrete, not a record id.

    `/wards/[id]` is not somewhere anyone can be sent: Next refuses a route
    pattern as an href. What is left after a removal has to include one of
    these or the application has no front door.
    """
    return sorted(str(p.get("route")) for p in _live(doc)
                  if str(p.get("id")) != without
                  and str(p.get("route") or "").startswith("/")
                  and "[" not in str(p.get("route")))


def _names_route(obj: dict, shapes: set[str]) -> bool:
    return any(isinstance(obj.get(k), str) and obj[k].startswith("/")
               and _shape(obj[k]) in shapes for k in LINK_KEYS)


def _strip_links(node: Any, shapes: set[str]) -> list[dict]:
    """Every link to one of `shapes` comes off the tree, and a control that
    existed only to follow one comes off with it.

    Shaped after `workflow_change._strip_controls`, for the same reason: a
    link is as often a nested prop (`Table.rowActions[]`, `emptyAction`,
    `Form.onSuccess`) as a node of its own, and a walk that reads one misses
    the rest. Returns what was removed, for the reply.
    """
    removed: list[dict] = []
    if isinstance(node, list):
        keep = []
        for n in node:
            props = (n.get("props") or {}) if isinstance(n, dict) else {}
            if isinstance(n, dict) and n.get("type") in _CLICK_CONTROLS and _names_route(props, shapes):
                removed.append({**props, "_type": n.get("type")})
            else:
                removed.extend(_strip_links(n, shapes))
                keep.append(n)
        node[:] = keep
        return removed
    if not isinstance(node, dict):
        return removed
    props = node.get("props")
    if isinstance(props, dict):
        for key, val in list(props.items()):
            if key in LINK_KEYS and isinstance(val, str) and val.startswith("/") and _shape(val) in shapes:
                removed.append({key: val, "_type": node.get("type")})
                del props[key]
            elif isinstance(val, dict) and _names_route(val, shapes):
                removed.append({**val, "_type": node.get("type")})
                del props[key]
            elif isinstance(val, list) and val and all(isinstance(v, dict) for v in val):
                gone = [v for v in val if _names_route(v, shapes)]
                if not gone:
                    continue
                removed.extend({**v, "_type": node.get("type")} for v in gone)
                kept = [v for v in val if not _names_route(v, shapes)]
                if kept:
                    props[key] = kept
                else:
                    del props[key]
    removed.extend(_strip_links(node.get("children") or [], shapes))
    return removed


def _label(control: dict) -> str:
    """What the owner would call the thing that came off.

    A control has visible words and is quoted by them. A link that is a prop
    rather than a control — a table's `rowHref` — has none, and quoting its
    route back ("“/nurse-registration” on Master Data") reads as if the route
    were the label a person clicks. Named for what it did instead.
    """
    for key in ("label", "submitLabel", "aria-label"):
        text = control.get(key)
        if isinstance(text, str) and text.strip():
            return f"“{text.strip()}”"
    if control.get("rowHref") or control.get("onRowClick"):
        return "the row link"
    return f"the {str(control.get('_type') or 'link').lower()} link"


def inbound(doc: dict, page: dict) -> dict:
    """Everything that points at this screen, WITHOUT changing any of it.

    The set used to be computed one line before the removal started, where
    nobody could be shown it. Returned here so the question can be asked first
    — `remove_entity` learned the same lesson.
    """
    pid = str(page.get("id") or "")
    route = str(page.get("route") or "")
    shapes = {_shape(route)} if route else set()
    nav = doc.get("navigation") or {}
    initial = nav.get("initialRoute")
    initial = initial.get("default") if isinstance(initial, dict) else initial

    others = [p for p in _live(doc) if str(p.get("id")) != pid]
    layouts = _layouts(doc)
    links: list[str] = []
    for other in others:
        layout = layouts.get(str(other.get("id")))
        if not layout:
            continue
        # A copy, because this reports and does not remove.
        root = json.loads(json.dumps(layout.get("root")))
        for control in _strip_links(root, shapes):
            links.append(f"{_label(control)} on {other.get('name') or other.get('route')}")
    return {
        "menu": [str(n.get("label")) for n in _walk_nav(nav.get("tree"))
                 if str(n.get("page") or "") == pid],
        "landing": bool(initial) and str(initial) == route,
        "links": links,
        "arrows": [str(p.get("name") or p.get("route")) for p in others
                   if pid in (p.get("navigatesTo") or [])],
        "launches": [str(w.get("name") or w.get("id")) for w in (doc.get("workflows") or [])
                     if isinstance(w, dict) and w.get("status") != "DEPRECATED"
                     and pid in (w.get("launchedFrom") or [])],
        "widgets": sum(1 for w in (doc.get("widgets") or []) if isinstance(w, dict)
                       and str(w.get("page") or "") == pid and w.get("status") != "DEPRECATED"),
    }


def refusal(doc: dict, page: dict) -> str:
    """Why this screen cannot go, or "" when it can.

    One condition, and it is an invariant rather than a taste: an application
    has to have somewhere a visitor arrives. Take the last such screen and
    `landing_route` emits `redirect("/")` into itself.
    """
    if arrivable(doc, without=str(page.get("id"))):
        return ""
    return (f"{page.get('name') or page.get('route')} is the only screen anyone can arrive at, so removing "
            "it would leave the application with nothing to open — the root would redirect to itself. "
            "Add the screen that should replace it first, and then I can take this one out.")


def why_not(doc: dict, ref: str) -> str:
    """`refusal` for a screen named the way a person names one, and "" when
    there is nothing to say yet — the screen is unknown, or already gone, and
    the seam itself answers both better than a pre-check could.

    Consulted by the turn BEFORE the cascade is offered: "shall I go ahead?"
    followed by "I cannot" is a worse turn than the refusal on its own.
    """
    page = find_page(doc, ref)
    return refusal(doc, page) if page is not None else ""


def consequences(doc: dict, ref: str) -> dict:
    """What removing `ref` would take with it, taking none of it."""
    page = find_page(doc, ref)
    if page is None:
        return {"found": False, "pages": routes(doc)}
    return {"found": True, "name": str(page.get("name") or ""), "id": str(page.get("id")),
            "route": str(page.get("route") or ""), **inbound(doc, page)}


def retire(svc: Any, pages: list[dict]) -> dict:
    """Take these screens out of the application, keeping them in the record.

    Shared with `entity_change`, which retires a record's screens for the same
    reasons and used to do a smaller version of this — it pruned the menu and
    left every link, arrow and widget pointing at a route that had stopped
    resolving.

    Order matters. The links come off BEFORE the pages are marked, because
    `_served_verbs` resolves a `navigate` against the LIVE pages to decide
    which declared verb the link was the control for: marked first, every
    retraction reads as a link to nothing and the calling screens keep
    declaring `view` with nothing left to view with.
    """
    from services.smith.move_dispatcher import _retract

    if not pages:
        return {"routes": [], "menu": [], "landing": False, "links": [], "notes": [], "widgets": 0}
    going = {str(p.get("id")) for p in pages}
    shapes = {_shape(str(p.get("route") or "")) for p in pages if p.get("route")}
    doc = svc.doc
    layouts = _layouts(doc)
    by_id = {str(p.get("id")): p for p in _live(doc)}

    links: list[str] = []
    notes: list[str] = []
    for pid, layout in layouts.items():
        if pid in going:
            continue                      # going too; nothing to keep coherent
        removed = _strip_links(layout.get("root"), shapes)
        if not removed:
            continue
        caller = by_id.get(pid) or {}
        for control in removed:
            links.append(f"{_label(control)} on {caller.get('name') or caller.get('route') or pid}")
        notes.extend(_retract(doc, caller, layout, removed))

    for other in _live(doc):
        if str(other.get("id")) in going:
            continue
        arrows = [a for a in (other.get("navigatesTo") or []) if a not in going]
        if arrows != list(other.get("navigatesTo") or []):
            other["navigatesTo"] = arrows

    for w in (doc.get("workflows") or []):
        if isinstance(w, dict) and any(p in going for p in (w.get("launchedFrom") or [])):
            w["launchedFrom"] = [p for p in w["launchedFrom"] if p not in going]

    widgets = 0
    for w in (doc.get("widgets") or []):
        if isinstance(w, dict) and str(w.get("page") or "") in going and w.get("status") != "DEPRECATED":
            w["status"] = "DEPRECATED"
            widgets += 1

    for layout in doc.get("pageLayouts") or []:
        if isinstance(layout, dict) and str(layout.get("page")) in going \
                and layout.get("status") not in ("SUPERSEDED", "DEPRECATED"):
            layout["status"] = "DEPRECATED"

    nav = doc.get("navigation") or {}
    menu: list[str] = [str(n.get("label")) for n in _walk_nav(nav.get("tree"))
                       if str(n.get("page") or "") in going]

    def prune(tree: list) -> list:
        out = []
        for n in tree or []:
            if not isinstance(n, dict):
                continue
            if str(n.get("page") or "") in going:
                continue
            if n.get("children"):
                n["children"] = prune(n["children"])
                if not n["children"] and not n.get("page"):
                    continue
            out.append(n)
        return out

    if nav.get("tree"):
        nav["tree"] = prune(nav["tree"])
    gone_routes = [str(p.get("route")) for p in pages]
    initial = (nav.get("initialRoute") or {}).get("default") if isinstance(nav.get("initialRoute"), dict) else None
    landing = initial in gone_routes
    if landing:
        nav["initialRoute"] = {}

    for page in pages:
        page["status"] = "DEPRECATED"

    # THE ID IS SPENT, AND SAID TO BE. Counters never rewind, so no other
    # screen could take it anyway — but until this is recorded nothing can
    # answer whether `PAGE-007` is a page that exists. §22's revival still
    # holds: the same route coming back later comes back as its own id.
    _retire_ids(svc, going)
    return {"routes": gone_routes, "menu": menu, "landing": landing,
            "links": links, "notes": notes, "widgets": widgets}


def _retire_ids(svc: Any, ids: set[str]) -> None:
    from services.blueprint.ids import IdAllocator
    try:
        with IdAllocator.session(output_dir=svc.output_dir) as alloc:
            for pid in sorted(ids):
                alloc.retire(pid)
    except Exception as exc:  # noqa: BLE001 — the registry must not fail the change
        logger.warning("[page] could not record %s as retired: %s", ", ".join(sorted(ids)), exc)


def _project(svc: Any, app_root: str | None) -> list[str]:
    """Write the application out again so the screen is actually gone.

    `apply_frontend_projection` is what makes this real: the retired page no
    longer plans, so its schema file is swept and its route leaves the
    registry — and the registry carries `entryRoute`, so "/" stops forwarding
    to a page that no longer answers. The shell is the rail, the root route is
    the redirect, and the middleware's public matcher is rebuilt from the
    pages that remain.
    """
    if not app_root:
        return []
    from services.blueprint.projection import (
        apply_frontend_projection, project_dispatches, project_middleware,
        project_navigation, project_public_resources,
    )
    files = [str(f) for f in (apply_frontend_projection(svc, app_root) or {}).get("files", [])]
    # `project_navigation` is the rail, the route graph, the root redirect and
    # the edge pages' way home, together. `project_dispatches` carries the
    # incident map with it, which lists the routes a crash may be reported
    # against. A retired page left in it would have the running application
    # name a screen nobody can open.
    for fn in (project_navigation, project_middleware, project_public_resources, project_dispatches):
        try:
            files += list((fn(svc.doc, app_root) or {}).get("files") or [])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[page] %s failed: %s", fn.__name__, exc)
    return sorted(set(files))


def remove_page(svc: Any, ref: str, *, app_root: str | None = None, reasoning: Any = None) -> dict:
    ref = (ref or "").strip()
    page = find_page(svc.doc, ref)
    if page is None:
        gone = next((p for p in _pages(svc.doc) if p.get("status") == "DEPRECATED"
                     and ref and ref.strip("/").lower() in
                     (str(p.get("route") or "").strip("/").lower(), str(p.get("name") or "").lower())), None)
        if gone is not None:
            # ASKED TWICE. The honest answer is that it is already gone — and
            # the useful one is to write the application out again, because
            # the reason someone asks twice is that they can still see it.
            files = _project(svc, app_root)
            return {"applied": True, "page": str(gone.get("id")), "name": str(gone.get("name") or ""),
                    "route": str(gone.get("route") or ""), "already": True, "edited_paths": files,
                    "menu": [], "links": [], "notes": [], "widgets": 0, "landing": False, "opens_on": ""}
        raise SectionChangeError(
            f"I cannot tell which screen {ref!r} means. The screens are: {routes(svc.doc)}.")

    refused = refusal(svc.doc, page)
    if refused:
        raise SectionChangeError(refused)

    before = svc.snapshot()
    out = retire(svc, [page])
    svc.validate()
    svc.commit(user_request=f"remove the {page.get('name') or page.get('route')} screen",
               smith_interpretation=(f"retire {page.get('id')} and the {len(out['links'])} link(s) to it"),
               before=before, affected=[str(page.get("id"))])
    from services.blueprint.projection import _entry_route
    opens_on = _entry_route(svc.doc) or "/"
    tell(reasoning, f"Retired {page.get('name') or page.get('route')}"
                    + (f"; took {len(out['links'])} link(s) to it off other screens" if out["links"] else "") + ".",
         "step")
    return {"applied": True, "page": str(page.get("id")), "name": str(page.get("name") or ""),
            "route": str(page.get("route") or ""), "already": False, "opens_on": opens_on,
            "edited_paths": _project(svc, app_root), **out}


def summary_of(out: dict) -> str:
    where = out.get("name") or out.get("route")
    if out.get("already"):
        return (f"**{where}** was already removed — it is not in the menu and `{out.get('route')}` does not "
                "resolve. I wrote the application out again so what is running matches; reload the page.")
    s = (f"Removed **{where}** (`{out.get('route')}`). Its route no longer resolves and it is out of the "
         "menu; the screen is kept in the record as retired, with its layout behind it, so “undo” "
         "brings it back exactly as it was.")
    if out.get("menu"):
        s += f" Off the menu: {', '.join(out['menu'])}."
    if out.get("links"):
        s += f" Took {len(out['links'])} link(s) to it off other screens: {', '.join(out['links'][:6])}."
    if out.get("notes"):
        s += " " + "; ".join(out["notes"][:4]) + "."
    if out.get("widgets"):
        s += f" {out['widgets']} widget(s) on it are retired with it."
    if out.get("landing"):
        s += f" The application opened on it, and now opens on {out.get('opens_on')}."
    return s


def run(output_dir: str, *, route: str = "", reasoning: Any = None) -> dict:
    """`{applied, edited_paths, diff_summary, reason}` — the shape every seam
    returns, so the session and the tool share one implementation."""
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": "this project has no Blueprint yet, so it has no screens to remove."}
    app_root = str(Path(output_dir) / "app")
    try:
        out = remove_page(svc, route, app_root=app_root, reasoning=reasoning)
    except SectionChangeError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a seam degrades, it does not crash
        logger.exception("[smith] remove_page failed")
        return {"applied": False, "edited_paths": [], "reason": f"{type(exc).__name__}: {exc}"}
    return {"applied": True, "edited_paths": out.get("edited_paths") or [], "diff_summary": summary_of(out),
            "reason": "", **{k: v for k, v in out.items() if k != "edited_paths"}}


__all__ = ["remove_page", "retire", "inbound", "consequences", "refusal", "why_not",
           "find_page", "arrivable", "run", "summary_of", "LINK_KEYS"]
