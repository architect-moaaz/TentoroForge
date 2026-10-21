"""The whole application on one map: every screen, how a person gets to it,
and the paths people take through it.

Two views used to split this. Pages & Nav drew the screens and the links
between them; App Flow drew only the screens a flow touched. A screen no
flow reached was on one and missing from the other (Mark 8's tax
calculator, 2026-10-17), and Smith saw neither picture — only a list of
pages and one line per flow.

`app_map(doc)` is the one picture, for the App Map view; `describe(doc)` is
the same picture in a few lines, for Smith.

  * screens — every live page: who may open it, its menu entry, the roles
    that land on it after signing in, the flows that pass through it, the
    processes it starts.
  * links — where a page says it leads (`navigatesTo`).
  * menu — the navigation tree, resolved to routes.
  * gaps — what the map shows is missing: a screen nothing leads to (not on
    the menu, not a landing, no link, no flow reaches it), and, when the
    application has flows, a screen no flow passes through.

Read-only and deterministic: no model, nothing written.
"""
from __future__ import annotations

from typing import Any


#: Signing in and out are everyone's door, not a goal: no path is expected to
#: pass through them, and naming them as gaps is noise.
_ACCOUNT_ROUTES = frozenset({"/login", "/signup", "/register", "/forgot-password", "/reset-password",
                             "/set-password", "/verify-email", "/logout"})


def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict)
            and str(r.get("status") or "").upper() not in ("DEPRECATED", "SUPERSEDED", "REMOVED")]


def _menu(doc: dict, pages: dict[str, dict]) -> list[dict]:
    def walk(nodes: Any) -> list[dict]:
        out = []
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            page = pages.get(str(n.get("page") or ""))
            out.append({"label": str(n.get("label") or (page or {}).get("name") or ""),
                        "page": str(page.get("id")) if page else "",
                        "route": str((page or {}).get("route") or ""),
                        "children": walk(n.get("children"))})
        return out
    return walk((doc.get("navigation") or {}).get("tree"))


def _menu_entries(tree: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for n in tree:
        if n.get("page") and n["page"] not in out:
            out[n["page"]] = n["label"]
        out.update({k: v for k, v in _menu_entries(n.get("children") or []).items() if k not in out})
    return out


def app_map(doc: dict) -> dict:
    """`{screens, links, menu, gaps}` — see the module's docstring."""
    from services.blueprint.app_flows import flows as _flows

    pages = {str(p.get("id")): p for p in _live(doc.get("pages")) if p.get("id") and p.get("route")}
    roles = {str(r.get("id")): str(r.get("name") or r.get("id")) for r in _live(doc.get("roles"))}
    procs = {str(w.get("id")): w for w in _live(doc.get("workflows"))}
    tree = _menu(doc, pages)
    on_menu = _menu_entries(tree)

    try:
        from services.blueprint.account_model import landing_by_role
        landings = landing_by_role(doc)
    except Exception:  # noqa: BLE001 — a map without landings is still a map
        landings = {}
    lands_on: dict[str, list[str]] = {}
    by_route = {str(p.get("route")): pid for pid, p in pages.items()}
    for role, route in landings.items():
        pid = by_route.get(str(route))
        if pid:
            lands_on.setdefault(pid, []).append(role)
    # WHERE A NEW ACCOUNT GOES FIRST is reached, though no menu or link names
    # it: an onboarding screen a prerequisite sends people to.
    after_signup = ""
    try:
        from services.blueprint.account_model import after_signup_route
        after_signup = by_route.get(str(after_signup_route(doc)), "")
    except Exception:  # noqa: BLE001
        pass

    links: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for pid, p in pages.items():
        for target in p.get("navigatesTo") or []:
            t = str(target)
            if t in pages and t != pid and (pid, t) not in seen:
                seen.add((pid, t))
                links.append({"from": pid, "to": t})

    flows = _flows(doc)
    in_flows: dict[str, list[str]] = {}
    reached_by_flow: set[str] = set()
    for f in flows:
        for i, st in enumerate(f["steps"]):
            pid = str(st.get("page") or "")
            if pid in pages:
                names = in_flows.setdefault(pid, [])
                if f.get("name") and f["name"] not in names:
                    names.append(str(f["name"]))
                if i > 0:
                    reached_by_flow.add(pid)

    starts: dict[str, list[str]] = {}
    for w in procs.values():
        for pid in w.get("launchedFrom") or []:
            if str(pid) in pages:
                starts.setdefault(str(pid), []).append(str(w.get("name") or w.get("id")))

    linked_to = {l["to"] for l in links}
    screens, gaps = [], []
    for pid, p in pages.items():
        route = str(p.get("route"))
        public = str(p.get("access") or "") == "public"
        screens.append({
            "id": pid, "name": str(p.get("name") or route), "route": route,
            "purpose": str(p.get("purpose") or ""), "pattern": str(p.get("pattern") or ""),
            "access": str(p.get("access") or ""),
            "who": [roles.get(str(u), str(u)) for u in p.get("users") or []],
            "menu": on_menu.get(pid, ""), "landing": sorted(lands_on.get(pid, [])),
            "entry": bool(p.get("entry")), "afterSignup": pid == after_signup, "flows": in_flows.get(pid, []),
            "starts": starts.get(pid, []),
        })
        reachable = (pid in on_menu or pid in lands_on or pid in linked_to or pid in reached_by_flow
                     or p.get("entry") or route == "/" or public or pid == after_signup)
        if not reachable:
            gaps.append({"kind": "unreachable", "page": pid,
                         "text": f"{p.get('name') or route} ({route}) — nothing leads here: not on the menu, "
                                 "no screen links to it, and no path reaches it"})
        elif flows and pid not in in_flows and "[" not in route and route not in _ACCOUNT_ROUTES:
            gaps.append({"kind": "no_path", "page": pid,
                         "text": f"{p.get('name') or route} ({route}) — no path anyone takes passes through it"})
    return {"screens": screens, "links": links, "menu": tree, "gaps": gaps}


def describe(doc: dict) -> list[str]:
    """The map in a few lines, for Smith: where each kind of person lands,
    the menu, the links between screens, and what is missing."""
    m = app_map(doc)
    by_id = {s["id"]: s for s in m["screens"]}
    out: list[str] = []
    lands = [f"{role} → {s['route']}" for s in m["screens"] for role in s["landing"]]
    if lands:
        out.append("Lands on after signing in: " + "; ".join(lands))

    def menu_line(nodes: list[dict]) -> str:
        parts = []
        for n in nodes:
            part = f"{n['label']} ({n['route']})" if n["route"] else n["label"]
            if n["children"]:
                part += " [" + menu_line(n["children"]) + "]"
            parts.append(part)
        return ", ".join(parts)
    if m["menu"]:
        out.append("Menu: " + menu_line(m["menu"]))
    if m["links"]:
        out.append("Links between screens: " + "; ".join(
            f"{by_id[l['from']]['route']} → {by_id[l['to']]['route']}" for l in m["links"][:40]))
    for g in m["gaps"][:20]:
        out.append("Gap: " + g["text"])
    return out


__all__ = ["app_map", "describe"]
