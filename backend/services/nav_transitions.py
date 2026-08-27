"""Build nav-flow.transitions authoritatively from the generated page schemas.

`nav-flow.json` is emitted from plan.pages BEFORE schemas exist, so its
`transitions[]` start empty. This runs AFTER schema generation: it walks every
page schema for navigation targets (Button/Link `navigate`, `rowHref`, `href`,
Hero-CTA `action.to`, `onClick` navigate) and records a transition per edge,
mapping the target route to the page it resolves to. It also adds the auth flow
edges (login↔signup and, when gated, login→first shell page) so the entry
journey is represented.

This is the single connection graph the Pages/Nav editor renders and (Slice 3)
edits — no longer a throwaway derivation. Deterministic + idempotent.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# Props whose value is a navigation target route.
_NAV_PROPS = ("navigate", "rowHref", "href", "to")


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _strip_expr(route: str) -> str:
    """`/orders/{{id}}` → `/orders`, `/orders/[id]` stays for matching."""
    route = route.split("?")[0]
    # Drop trailing interpolation/param segments so /orders/{{id}} matches /orders/[id].
    return route


def _route_to_page_id(target: str, routes: list[tuple[str, str]]) -> str | None:
    """Resolve a navigate target to a page id. `routes` = [(route, id)] sorted
    longest-first. Tolerant of params: /orders/123 or /orders/{{id}} → /orders/[id]."""
    t = _strip_expr((target or "").strip())
    if not t:
        return None
    # Exact route match first.
    for route, pid in routes:
        if route == t:
            return pid
    # Segment-count + prefix match, treating [param]/{{expr}}/:id/numeric as wildcards.
    t_segs = [s for s in t.strip("/").split("/") if s]
    for route, pid in routes:
        r_segs = [s for s in route.strip("/").split("/") if s]
        if len(r_segs) != len(t_segs):
            continue
        ok = True
        for rs, ts in zip(r_segs, t_segs):
            wild = rs.startswith("[") or ts.startswith("{{") or ts.startswith(":") or ts.isdigit()
            if rs != ts and not wild:
                ok = False
                break
        if ok:
            return pid
    return None


def build_transitions(output_dir: str) -> dict[str, Any]:
    """Rewrite nav-flow.transitions from the generated schemas. Returns a report."""
    root = Path(output_dir)
    nav_path = root / "src" / "contracts" / "nav-flow.json"
    if not nav_path.exists():
        return {"transitions": 0}
    try:
        nav = json.loads(nav_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {"transitions": 0}

    pages = nav.get("pages")
    if not isinstance(pages, list):
        return {"transitions": 0}

    # route → page id, longest route first for greedy matching.
    routes = sorted(
        ((p["route"], p["id"]) for p in pages
         if isinstance(p, dict) and p.get("route") and p.get("id")),
        key=lambda r: len(r[0]), reverse=True,
    )
    id_by_route = {r: i for r, i in routes}

    transitions: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(frm: str, trigger: str, to: str, nav_type: str = "link") -> None:
        key = (frm, trigger, to)
        if frm and to and key not in seen:
            seen.add(key)
            transitions.append({
                "id": f"t-{len(transitions) + 1}",
                "from": frm, "trigger": trigger, "to": to, "navType": nav_type,
            })

    # 1) Edges walked from each page's schema.
    for p in pages:
        if not isinstance(p, dict):
            continue
        sf = p.get("schemaFile")
        from_id = p.get("id")
        if not sf or not from_id:
            continue
        sp = root / sf
        if not sp.exists():
            continue
        try:
            schema = json.loads(sp.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for node in _walk(schema):
            # Only real component nodes carry navigation — a bare props dict is
            # walked too, so require a `type` to avoid double-counting.
            if not isinstance(node, dict) or "type" not in node:
                continue
            props = node.get("props") if isinstance(node.get("props"), dict) else {}
            target = None
            for src in (props, node):
                for key in _NAV_PROPS:
                    v = src.get(key)
                    if isinstance(v, str) and v.startswith("/"):
                        target = v
                        break
                if target:
                    break
            if target is None:
                oc = props.get("onClick") or props.get("action") or node.get("onClick") or node.get("action")
                if isinstance(oc, dict) and isinstance(oc.get("to"), str):
                    target = oc.get("to")
            if not isinstance(target, str) or not target.startswith("/"):
                continue
            to_id = _route_to_page_id(target, routes)
            if not to_id or to_id == from_id:
                continue
            label = (props.get("label") or props.get("content") or props.get("text") or "navigate")
            trigger = f"button:{label}" if node.get("type") in ("Button", "IconButton") else "link"
            _add(from_id, trigger, to_id)

    # 2) Auth-flow edges (login↔signup, and login→landing when gated).
    login_id = id_by_route.get("/login")
    signup_id = id_by_route.get("/signup")
    if login_id and signup_id:
        _add(login_id, "link:Sign up", signup_id)
        _add(signup_id, "link:Sign in", login_id)
    if nav.get("authGated") and login_id:
        landing = nav.get("post_login_redirect")
        land_id = id_by_route.get(landing) if landing else None
        if land_id:
            _add(login_id, "submit:login", land_id, "redirect")

    nav["transitions"] = transitions
    nav_path.write_text(json.dumps(nav, indent=2))
    return {"transitions": len(transitions)}
