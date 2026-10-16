"""Who may read what, over HTTP: the entities and widgets each audience may ask `/api/read/*` for.

The web reads on the server, inside a page that carries the page's roles. `/api/read/<op>` (the phone's reads) takes the
entity from the caller, so by itself it opened EVERY entity to EVERY signed-in person: an entity shown only on an
Admin page (audit, settings, invoices) was listable by a Member with their cookie, and on an app with no sign-in by
anyone. The route now asks this: an entity or widget is readable by exactly the people who may open a page that
reads it.

  * a PUBLIC page (or any page, on an app with no sign-in) -> anyone, signed in or not;
  * an `authenticated` page -> any signed-in person (the web's own rule: `users` there only says who it is for);
  * a `role_restricted` page -> the roles it names (`restricted_roles`: the administrator's when it names none);
  * the administrator may read every entity and widget: the back office is theirs.

What a page reads is what the page says it reads: its primary and supporting entities, the sources of its layout, its
widgets, and the entities its code names. An entity no page reads is readable by nobody but the administrator."""
from __future__ import annotations

import re
from typing import Any


def _live(rows: Any) -> list[dict]:
    return [r for r in (rows or []) if isinstance(r, dict)
            and str(r.get("status") or "").upper() not in ("DEPRECATED", "REMOVED", "SUPERSEDED")]


def _entity_name(ref: Any, names: dict[str, str]) -> str | None:
    if isinstance(ref, dict):
        ref = ref.get("entity")
    return names.get(str(ref)) if ref else None


def page_entities(doc: dict, page: dict, names: dict[str, str]) -> set[str]:
    """The entity names one page reads."""
    pid = str(page.get("id"))
    found: set[str] = set()
    data = page.get("data") if isinstance(page.get("data"), dict) else {}
    for ref in [data.get("primaryEntity"), *(data.get("supportingEntities") or [])]:
        name = _entity_name(ref, names)
        if name:
            found.add(name)
    for layout in doc.get("pageLayouts") or []:
        if isinstance(layout, dict) and str(layout.get("page")) == pid:
            for src in layout.get("dataSources") or []:
                name = _entity_name(src, names)
                if name:
                    found.add(name)
    for widget in _live(doc.get("widgets")):
        if str(widget.get("page")) == pid:
            name = _entity_name(widget.get("dataSource"), names)
            if name:
                found.add(name)
    # The entities the page's own code names: what the web page and the phone screen actually read.
    for key, field in (("pageCode", "load"), ("pageCode", "view"), ("nativeCode", "screen")):
        for row in doc.get(key) or []:
            if isinstance(row, dict) and str(row.get("page")) == pid:
                code = str(row.get(field) or "")
                for name in set(names.values()):
                    if re.search(r"[\"'`]" + re.escape(name) + r"[\"'`]", code):
                        found.add(name)
    return found


def read_access(doc: dict) -> dict[str, dict[str, dict]]:
    """`{entities: {name: Access}, widgets: {id: Access}}`; Access is `{anyone, signedIn, roles}`."""
    from services.blueprint.account_model import admin_role, has_sign_in
    from services.blueprint.projection import restricted_roles

    entities = _live((doc.get("data") or {}).get("entities"))
    names: dict[str, str] = {}
    for e in entities:
        if e.get("name"):
            names[str(e["name"])] = str(e["name"])
            if e.get("id"):
                names[str(e["id"])] = str(e["name"])
    gated = has_sign_in(doc)
    admin = admin_role(doc)

    ent: dict[str, dict] = {n: {"anyone": False, "signedIn": False, "roles": set()} for n in set(names.values())}
    wid: dict[str, dict] = {str(w.get("id")): {"anyone": False, "signedIn": False, "roles": set()}
                            for w in _live(doc.get("widgets")) if w.get("id")}

    def grant(access: dict, page: dict) -> None:
        kind = str(page.get("access") or "")
        if not gated or kind == "public":
            access["anyone"] = True
        elif kind == "role_restricted":
            access["roles"].update(restricted_roles(doc, page))
        else:
            access["signedIn"] = True

    for page in _live(doc.get("pages")):
        for name in page_entities(doc, page, names):
            grant(ent[name], page)
        for widget in _live(doc.get("widgets")):
            if str(widget.get("page")) == str(page.get("id")) and str(widget.get("id")) in wid:
                grant(wid[str(widget["id"])], page)

    for table in (ent, wid):
        for access in table.values():
            if admin:
                access["roles"].add(admin)
            access["roles"] = sorted(access["roles"])
    return {"entities": ent, "widgets": wid}


__all__ = ["page_entities", "read_access"]
