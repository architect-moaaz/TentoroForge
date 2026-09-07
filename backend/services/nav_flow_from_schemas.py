"""Synthesize nav-flow.json from a generated app's on-disk page schemas.

The pipeline emits ``src/contracts/nav-flow.json`` from the planner output
(``nav_flow_from_plan`` / ``nav_flow_emitter``). But apps generated before that
wiring — or any run where the plan-driven emit failed — have no nav-flow, and
the visual editor's Canvas hard-depends on it to list pages (falls back to
"No nav-flow."). This module rebuilds an equivalent nav-flow purely from the
``src/schemas/*.json`` files that always exist, so the editor can open any app.

It is deliberately dependency-light (reads files, no LLM, no plan) so it can run
as a lazy fallback in the debug file endpoint and as a pipeline safety-net.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.route_slug import route_from_slug

# Route prefixes that identify unauthenticated (auth) pages — these render
# outside the app shell and drive post-login / post-logout redirects.
_AUTH_PREFIXES = ("/login", "/signin", "/sign-in", "/signup", "/sign-up", "/register")
# Schema files that aren't navigable pages.
_SKIP_NAMES = {"registry.json", "load.json", "nav-flow.json", "shell.json"}


def _humanize(slug: str) -> str:
    return (
        slug.replace("-", " ")
        .replace("/", " · ")
        .replace("[id]", "detail")
        .strip()
        .title()
    )


def _is_auth(route: str, page_type: str) -> bool:
    return page_type == "auth" or any((route or "").startswith(p) for p in _AUTH_PREFIXES)


def build_nav_flow_from_schemas(base_dir: str | Path) -> dict[str, Any] | None:
    """Return a nav-flow dict built from ``base_dir/src/schemas`` or None if none.

    Shape matches ``nav_flow_from_plan``: pages carry ``id`` (the editor's page
    key), ``route``, ``title``, ``schemaFile`` (authoritative path the Canvas
    reads), and ``shell``. Non-shell (auth) pages are ordered last; a dashboard/
    home-style page is preferred as ``initialPage``.
    """
    base = Path(base_dir)
    schemas = base / "src" / "schemas"
    if not schemas.exists():
        return None

    pages: list[dict[str, Any]] = []
    for f in sorted(schemas.rglob("*.json")):
        if f.name in _SKIP_NAMES:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        rel = str(f.relative_to(schemas).with_suffix("")).replace("\\", "/")
        route = data.get("route") or route_from_slug(rel)
        page_type = (data.get("page_type") or rel.split("/")[-1] or "").lower()
        is_auth = _is_auth(route, page_type)
        pages.append({
            "id": data.get("id") or rel,
            "route": route,
            "title": data.get("title") or _humanize(rel),
            "schemaFile": f"src/schemas/{rel}.json",
            "shell": not is_auth,
        })

    if not pages:
        return None

    def _rank(p: dict[str, Any]) -> tuple[int, str]:
        r = p["route"] or ""
        if not p["shell"]:
            return (3, r)  # auth pages last
        if r in ("/", "/dashboard", "/home") or p["id"] in ("dashboard", "home"):
            return (0, r)  # landing pages first
        return (1, r)

    pages.sort(key=_rank)

    non_auth = [p["route"] for p in pages if p["shell"]]
    auth_routes = [p["route"] for p in pages if not p["shell"]]
    nav: dict[str, Any] = {
        "version": "1.0",
        "pages": pages,
        "auth_routes": auth_routes,
        "transitions": [],
        "guards": {},
        "initialPage": next((p["id"] for p in pages if p["shell"]), pages[0]["id"]),
    }
    if non_auth:
        nav["post_login_redirect"] = non_auth[0]
    if auth_routes:
        nav["post_logout_redirect"] = auth_routes[0]
    return nav


def ensure_nav_flow(base_dir: str | Path) -> Path | None:
    """Write ``src/contracts/nav-flow.json`` from schemas if it's missing.

    Idempotent: returns the existing path untouched when present; synthesizes and
    writes it otherwise. Returns None when there are no schemas to build from.
    """
    base = Path(base_dir)
    target = base / "src" / "contracts" / "nav-flow.json"
    if target.exists():
        return target
    nav = build_nav_flow_from_schemas(base)
    if not nav:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(nav, indent=2), encoding="utf-8")
    return target
