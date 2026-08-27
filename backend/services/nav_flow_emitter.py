"""Build nav-flow.json from plan.pages + transitions extracted from schemas.

Runs after schemas are emitted and photo URLs are injected. Deterministic —
re-running on the same inputs produces byte-identical output.
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Any

from contracts.nav_flow import NavFlow, NavFlowPageEntry, NavFlowTransition, NavFlowGuard

_NAV_OUT = "src/contracts/nav-flow.json"
_SCHEMA_DIR = "src/schemas"

_COLON_PARAM_RE = re.compile(r":(\w+)")
_BRACKET_PARAM_RE = re.compile(r"\[\w+\]")


def _normalise_route(route: str) -> str:
    """Convert Express-style `:param` to Next.js-style `[param]`."""
    if not route:
        return ""
    return _COLON_PARAM_RE.sub(lambda m: f"[{m.group(1)}]", route)


def _slug_from_route(route: str) -> str:
    """`/` → 'home', `/users/[id]` → 'users-detail', `/notes` → 'notes'."""
    if route in ("/", ""):
        return "home"
    cleaned = route.strip("/")
    if "[" in cleaned:
        cleaned = _BRACKET_PARAM_RE.sub("detail", cleaned)
    return cleaned.replace("/", "-")


def _schema_file_from_route(route: str) -> str:
    """Map a normalised route to its on-disk schema file path.

    Delegates to services.route_slug.slugify_route so this matches EXACTLY
    where page_schema_agent writes its files (out_path = src/schemas/<slug>.json).

    ``/``               → 'src/schemas/home.json'
    ``/requests``       → 'src/schemas/requests.json'
    ``/requests/new``   → 'src/schemas/requests/new.json'
    ``/users/[id]``     → 'src/schemas/users/[id].json'
    ``/users/:id``      → 'src/schemas/users/[id].json'  (normalised first)
    """
    from services.route_slug import slugify_route
    slug = slugify_route(route)
    return f"{_SCHEMA_DIR}/{slug}.json"


def _extract_route_params(route: str) -> list[str]:
    return re.findall(r"\[(\w+)\]", route or "")


def _walk_nodes(node: Any):
    """Yield every node dict in a schema tree.

    Walks all dict values so the top-level schema envelope (with a 'root'
    key) is fully traversed, as well as the standard children/props/slots
    structural keys inside each component node.
    """
    if isinstance(node, list):
        for n in node:
            yield from _walk_nodes(n)
        return
    if not isinstance(node, dict):
        return
    yield node
    # Recurse into every dict value so the top-level schema envelope
    # ('root', 'nodes', etc.) is traversed as well as nested component trees.
    for v in node.values():
        if isinstance(v, (dict, list)):
            yield from _walk_nodes(v)


def _collect_transitions(output_dir: Path, page_ids: set[str]) -> list[NavFlowTransition]:
    """Scan each page schema for onClick navigate actions; emit transition records."""
    transitions: list[NavFlowTransition] = []
    seen: set[tuple[str, str]] = set()
    schemas_dir = output_dir / _SCHEMA_DIR
    if not schemas_dir.exists():
        return transitions
    for schema_file in sorted(schemas_dir.rglob("*.json")):
        try:
            schema = json.loads(schema_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        from_id = schema.get("id") or schema_file.stem
        for node in _walk_nodes(schema):
            on_click = (node.get("props") or {}).get("onClick")
            if not isinstance(on_click, dict):
                continue
            if on_click.get("action") != "navigate":
                continue
            trigger = on_click.get("trigger") or on_click.get("to")
            if not trigger:
                continue
            # Resolve trigger to a target page id
            to_id = on_click.get("to") or trigger
            if to_id not in page_ids:
                candidate = (to_id or "").lstrip("/").replace("/", "-") or "home"
                if candidate in page_ids:
                    to_id = candidate
                else:
                    # Unknown target — skip this transition
                    continue
            key = (from_id, trigger)
            if key in seen:
                continue
            seen.add(key)
            transitions.append(NavFlowTransition(
                id=f"t-{len(transitions)+1}",
                from_page=from_id,
                trigger=trigger,
                to=to_id,
            ))
    return transitions


def emit_nav_flow(output_dir: str, plan: dict) -> None:
    """Build nav-flow.json from the plan + emitted schemas.

    Idempotent — re-running on the same inputs produces byte-identical output.
    """
    out = Path(output_dir)
    pages: list[NavFlowPageEntry] = []
    guards: dict[str, NavFlowGuard] = {}
    initial: str | None = None

    auth_routes: list[str] = []

    for p in (plan or {}).get("pages", []):
        # Normalise Express-style :param → [param] so slugify and schemaFile
        # both produce the correct Next.js bracket convention.
        route = _normalise_route(p.get("route", "/"))
        slug = _slug_from_route(route)
        guard_name: str | None = None
        if p.get("requires_auth"):
            guard_name = "requiresAuth"
            guards.setdefault("requiresAuth", NavFlowGuard(
                redirect_to="login",
                condition="global.user.isAuthenticated == true",
            ))
        page_type = (p.get("type") or "").lower()
        is_auth = page_type == "auth"
        if is_auth:
            auth_routes.append(route)
        pages.append(NavFlowPageEntry(
            id=slug,
            route=route,
            title=p.get("name") or slug.capitalize(),
            schema_file=_schema_file_from_route(route),
            guard=guard_name,
            params=_extract_route_params(route),
            shell=not is_auth,
        ))
        if route in ("/", "/home") and initial is None:
            initial = slug

    # Entry point derives from auth-gating (the single decision on the plan).
    # Gated: unauthenticated users start at /login; after login → first shell
    # page; after logout → /login. Not gated: start at the first shell page (/).
    auth_gated = bool(plan.get("authGated")) or bool(auth_routes)
    shell_pages = [p for p in pages if p.shell]
    first_shell_route = shell_pages[0].route if shell_pages else "/"
    login_page = next((p for p in pages if p.route == "/login"), None)

    post_login_redirect = first_shell_route
    post_logout_redirect = None
    if auth_gated:
        initial = login_page.id if login_page else (initial or (pages[0].id if pages else ""))
        post_logout_redirect = "/login"
    elif initial is None:
        # Not gated and no "/" page found in the loop → first shell page.
        initial = shell_pages[0].id if shell_pages else (pages[0].id if pages else "")

    page_ids = {p.id for p in pages}
    transitions = _collect_transitions(out, page_ids)

    nav = NavFlow(
        initial_page=initial or "",
        pages=pages,
        transitions=transitions,
        guards=guards,
        auth_routes=auth_routes,
        auth_gated=auth_gated,
        post_login_redirect=post_login_redirect,
        post_logout_redirect=post_logout_redirect,
    )

    nav_path = out / _NAV_OUT
    nav_path.parent.mkdir(parents=True, exist_ok=True)

    # Preserve additive metadata written by an EARLIER pass through
    # ``nav_flow_from_plan`` (e.g. `personas`) — this emitter rebuilds
    # the pages/transitions structure from scratch but must not clobber
    # keys other builders own. Read what's already on disk, merge only
    # the known additive keys onto the fresh nav.
    _existing: dict = {}
    if nav_path.exists():
        try:
            _existing = json.loads(nav_path.read_text()) or {}
        except Exception:  # noqa: BLE001 — a corrupt file gets replaced
            _existing = {}

    serialized = json.loads(nav.model_dump_json(by_alias=True, indent=2))
    # ``personas`` is written by nav_flow_from_plan._persona_metadata_from_brief
    # (Slice B). Preserve it here so the persona-pill top strip in the app
    # shell keeps rendering after this rebuild.
    for _key in ("personas",):
        if _key in _existing and _key not in serialized:
            serialized[_key] = _existing[_key]

    nav_path.write_text(json.dumps(serialized, indent=2) + "\n")
