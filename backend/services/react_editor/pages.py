"""Pages and the menu, from the editor — Blueprint changes with the app written out.

A page is a Blueprint artifact: its name, its address (route), who may open
it, and — for a designed page — its two code files. The menu is the
Blueprint's `navigation.tree`; the app's rail, its public header, `nav-flow`,
the root redirect and the middleware are all projected from it, so a change
here is followed by the same projection Smith's own verbs run. Removing a
page goes through Smith's retire seam, which takes the links to it off other
screens and refuses to remove the last screen a visitor can arrive at.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from services.blueprint.app_sdk import page_keys, project_code_pages
from services.react_editor import adapter, service
from services.react_editor.service import EditorError, Project, _live, load_blueprint

logger = logging.getLogger(__name__)

_ROUTE = re.compile(r"^/(?:[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*)?$")


def slug_route(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return "/" + (s or "page")


def _blank_view(name: str) -> str:
    return ('"use client";\n\nimport type { load } from "./load";\n\n'
            "type Props = NonNullable<Awaited<ReturnType<typeof load>>>;\n\n"
            "export default function View(_props: Props) {\n"
            "  return (\n"
            '    <div className="mx-auto max-w-5xl px-4 py-6 md:px-6">\n'
            '      <div className="mb-6">\n'
            f'        <h1 className="text-2xl font-semibold text-foreground">{name}</h1>\n'
            '        <p className="mt-1 text-sm text-muted-foreground">Add things to this page from the Add panel.</p>\n'
            "      </div>\n"
            '      <section className="space-y-4">\n'
            "      </section>\n"
            "    </div>\n"
            "  );\n"
            "}\n")


_BLANK_LOAD = ('import type { PageContext } from "@/sdk/server";\n\n'
               "export async function load(_ctx: PageContext) {\n  return {};\n}\n")


def _reproject(svc: Any, project: Project) -> list[str]:
    from services.blueprint.projection import project_public_nav
    from services.smith.page_change import _project
    files = _project(svc, str(project.app_root))
    try:
        files.append(project_public_nav(svc.doc, project.app_root))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[react_editor.pages] public nav: %s", exc)
    files += project_code_pages(svc.doc, project.app_root)
    return sorted(set(files))


def _page(doc: dict, page_id: str) -> dict:
    return service._page(doc, page_id)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create(project: Project, spec: dict[str, Any]) -> dict[str, Any]:
    """A new designed page: its Blueprint row, a blank page that compiles,
    and — when asked — a place in the menu. Returns the page and its id."""
    svc = load_blueprint(project)
    doc = svc.doc
    name = str(spec.get("name") or "").strip()
    if not name:
        raise EditorError(422, "no-name", "Give the page a name.")
    route = str(spec.get("route") or slug_route(name)).strip().lower()
    if not route.startswith("/"):
        route = "/" + route
    if not _ROUTE.match(route):
        raise EditorError(422, "bad-route", "An address is lowercase words joined by dashes, like /team-members.")
    for p in _live(doc.get("pages")):
        if str(p.get("route") or "").rstrip("/") == route.rstrip("/"):
            raise EditorError(409, "route-taken", f"“{p.get('name')}” already lives at {route}. Choose another address.")
        if str(p.get("name") or "").strip().lower() == name.lower():
            raise EditorError(409, "name-taken", f"There is already a page called “{p.get('name')}”.")
    access = spec.get("access") if spec.get("access") in ("public", "authenticated") else "authenticated"
    body = {"name": name, "route": route, "purpose": str(spec.get("purpose") or f"{name}."),
            "pattern": "tool", "access": access, "navigatesTo": [], "status": "APPROVED"}
    from services.smith.section_change import bind_ids
    with svc.lock:
        before = svc.snapshot()
        # The id registry must know every id the document already uses, or a
        # new page would be handed one of them (a project made by the engine
        # is bound at bootstrap; one opened cold here may not be).
        bind_ids(svc)
        row = svc.upsert("pages", body, natural_key=f"page:{route}")
        pid = str(row.get("id"))
        svc.upsert("pageCode", {"page": pid, "load": _BLANK_LOAD, "view": _blank_view(name), "rationale": "A blank page made in the editor."},
                   natural_key=pid)
        if spec.get("menu", True):
            nav = svc.doc.setdefault("navigation", {})
            tree = nav.setdefault("tree", [])
            if not any(isinstance(n, dict) and n.get("page") == pid for n in tree):
                tree.append({"label": name, "page": pid})
        svc.commit(user_request=f"Add the page “{name}”", before=before, affected=[pid])
        files = _reproject(svc, project)
    return {"page": _summary(svc.doc, pid), "files": files}


def _summary(doc: dict, pid: str) -> dict:
    p = _page(doc, pid)
    return {"id": pid, "name": p.get("name"), "route": p.get("route"), "access": p.get("access") or "authenticated",
            "key": page_keys(doc).get(pid)}


# ---------------------------------------------------------------------------
# Rename — the name, the address, who may open it
# ---------------------------------------------------------------------------

def update(project: Project, page_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    svc = load_blueprint(project)
    doc = svc.doc
    page = _page(doc, page_id)
    old_key = page_keys(doc).get(page_id)
    changes: dict[str, Any] = {}
    if "name" in spec:
        name = str(spec.get("name") or "").strip()
        if not name:
            raise EditorError(422, "no-name", "A page needs a name.")
        for p in _live(doc.get("pages")):
            if str(p.get("id")) != page_id and str(p.get("name") or "").strip().lower() == name.lower():
                raise EditorError(409, "name-taken", f"There is already a page called “{p.get('name')}”.")
        changes["name"] = name
    if "route" in spec:
        route = str(spec.get("route") or "").strip().lower()
        if not _ROUTE.match(route):
            raise EditorError(422, "bad-route", "An address is lowercase words joined by dashes, like /team-members.")
        if re.search(r"\[[^\]]+\]", str(page.get("route") or "")):
            raise EditorError(409, "record-route", "This page shows one record; its address carries the record's id and cannot be changed here.")
        for p in _live(doc.get("pages")):
            if str(p.get("id")) != page_id and str(p.get("route") or "").rstrip("/") == route.rstrip("/"):
                raise EditorError(409, "route-taken", f"“{p.get('name')}” already lives at {route}.")
        changes["route"] = route
    if "access" in spec and spec["access"] in ("public", "authenticated"):
        changes["access"] = spec["access"]
    if "purpose" in spec:
        changes["purpose"] = str(spec.get("purpose") or "")
    if not changes:
        return {"page": _summary(doc, page_id), "renamed": None}
    with svc.lock:
        before = svc.snapshot()
        page.update(changes)
        if "name" in changes:
            for n in (svc.doc.get("navigation") or {}).get("tree") or []:
                if isinstance(n, dict) and n.get("page") == page_id and n.get("label") == before_name(before, page_id):
                    n["label"] = changes["name"]
        svc.commit(user_request=f"Change the page “{page.get('name')}”", before=before, affected=[page_id])
        new_key = page_keys(svc.doc).get(page_id)
        renamed = None
        if old_key and new_key and old_key != new_key:
            renamed = _rename_references(project, svc, old_key, new_key)
        files = _reproject(svc, project)
    return {"page": _summary(svc.doc, page_id), "renamed": renamed, "files": files}


def before_name(snapshot: dict, page_id: str) -> str:
    return next((str(p.get("name") or "") for p in snapshot.get("pages") or [] if str(p.get("id")) == page_id), "")


def _rename_references(project: Project, svc: Any, old: str, new: str) -> dict:
    """`pages.old` → `pages.new` in every coded page that names it, each as one checked revision."""
    pat = re.compile(r"\bpages\." + re.escape(old) + r"\b")
    touched = []
    for row in _live(svc.doc.get("pageCode")):
        view, load = str(row.get("view") or ""), str(row.get("load") or "")
        if not pat.search(view) and not pat.search(load):
            continue
        pid = str(row.get("page"))
        out = service.apply(project, pid, base_revision=adapter.revision_of(view, load), ops=[],
                            source={"view": pat.sub(f"pages.{new}", view), "load": pat.sub(f"pages.{new}", load)},
                            label=f"Page handle renamed to {new}", kind="edit")
        touched.append({"page": pid, "revision": out["revision"]})
    return {"from": old, "to": new, "pages": touched}


# ---------------------------------------------------------------------------
# Remove — through Smith's seam, which takes the links with it
# ---------------------------------------------------------------------------

def consequences(project: Project, page_id: str) -> dict[str, Any]:
    from services.smith.page_change import consequences as smith_consequences, refusal
    svc = load_blueprint(project)
    page = _page(svc.doc, page_id)
    out = dict(smith_consequences(svc.doc, page_id) or {})
    out["refusal"] = refusal(svc.doc, page) or None
    return out


def remove(project: Project, page_id: str) -> dict[str, Any]:
    from services.smith.page_change import remove_page
    from services.smith.section_change import SectionChangeError
    svc = load_blueprint(project)
    _page(svc.doc, page_id)
    try:
        with svc.lock:
            out = remove_page(svc, page_id, app_root=str(project.app_root))
            # The retire seam writes the app out but not its coded pages; the
            # page's route directory would otherwise stay and keep answering.
            project_code_pages(svc.doc, project.app_root)
    except SectionChangeError as exc:
        raise EditorError(409, "refused", str(exc)) from exc
    return {"removed": True, "name": out.get("name"), "links": out.get("links") or [], "menu": out.get("menu") or [],
            "opensOn": out.get("opens_on"), "files": out.get("edited_paths") or []}


# ---------------------------------------------------------------------------
# The menu
# ---------------------------------------------------------------------------

def navigation(doc: dict) -> dict[str, Any]:
    nav = doc.get("navigation") or {}
    initial = nav.get("initialRoute")
    if isinstance(initial, dict):
        initial = initial.get("default")
    pages = {str(p.get("id")): p for p in _live(doc.get("pages"))}
    tree = []
    for n in nav.get("tree") or []:
        if not isinstance(n, dict):
            continue
        tree.append({"label": n.get("label"), "page": n.get("page"), "icon": n.get("icon"),
                     "route": pages.get(str(n.get("page")), {}).get("route"),
                     "children": [{"label": c.get("label"), "page": c.get("page"), "route": pages.get(str(c.get("page")), {}).get("route")}
                                  for c in n.get("children") or [] if isinstance(c, dict)]})
    return {"style": nav.get("style") or "sidebar", "tree": tree, "initialRoute": initial or None}


def set_navigation(project: Project, spec: dict[str, Any]) -> dict[str, Any]:
    """The menu as the person arranged it: labels, order, nesting, the first page."""
    from services.smith.navigation_change import validate
    svc = load_blueprint(project)
    doc = svc.doc
    nav = dict(doc.get("navigation") or {})

    def clean(items: Any) -> list[dict]:
        out = []
        for n in items or []:
            if not isinstance(n, dict):
                continue
            row: dict[str, Any] = {"label": str(n.get("label") or "").strip()}
            if n.get("page"):
                row["page"] = str(n["page"])
            if n.get("icon"):
                row["icon"] = str(n["icon"])
            kids = clean(n.get("children"))
            if kids:
                row["children"] = kids
            out.append(row)
        return out

    if "tree" in spec:
        nav["tree"] = clean(spec.get("tree"))
    if "style" in spec and spec["style"] in ("sidebar", "topbar", "hybrid"):
        nav["style"] = spec["style"]
    if "initialRoute" in spec:
        if spec["initialRoute"]:
            nav["initialRoute"] = {"default": str(spec["initialRoute"])}
        else:
            nav.pop("initialRoute", None)
    problems = validate(doc, nav)
    if problems:
        raise EditorError(422, "bad-menu", " ".join(p[0].upper() + p[1:] + "." for p in problems), problems=problems)
    with svc.lock:
        before = svc.snapshot()
        svc.doc["navigation"] = nav
        # `entry` follows the first page: what the app opens on.
        first = (nav.get("initialRoute") or {}).get("default") if isinstance(nav.get("initialRoute"), dict) else None
        for p in _live(svc.doc.get("pages")):
            if first:
                p["entry"] = str(p.get("route")) == first
        svc.commit(user_request="Arrange the menu", before=before, affected=[])
        files = _reproject(svc, project)
    return {"navigation": navigation(svc.doc), "files": files}
