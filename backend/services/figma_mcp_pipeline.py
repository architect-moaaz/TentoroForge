"""Orchestrator for the Figma MCP get_design_context pipeline.

Ties together:
1. JSX parsing (extract_asset_urls)
2. Asset caching (download_figma_assets)
3. Schema transformation (transform_jsx_to_schema with src rewriting)
4. nav-flow.json update (add/update the page entry for this route)

Converts get_design_context output → PageV2 schema with local asset paths.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from services.figma_asset_downloader import extract_asset_urls, download_figma_assets
from services.jsx_to_schema import transform_jsx_to_schema

_NAV_FLOW_PATH = "src/contracts/nav-flow.json"
_SCHEMAS_DIR = "src/schemas"

_AUTH_ROUTE_PATTERNS = [
    re.compile(
        r"^/?(?:login|signin|sign-in|signup|sign-up|register|forgot-password|"
        r"reset-password|verify-email|onboarding)/?$",
        re.I,
    ),
]


def _is_auth_route(route: str) -> bool:
    """Return True when *route* looks like an auth/onboarding page."""
    stripped = route.strip("/")
    return any(p.match(stripped) or p.match(route) for p in _AUTH_ROUTE_PATTERNS)


def _slug_from_route(route: str) -> str:
    """``/`` → 'home',  ``/intent-intelligence`` → 'intent-intelligence'."""
    if route in ("/", ""):
        return "home"
    return route.strip("/").replace("/", "-")


def _schema_file_from_route(route: str) -> str:
    if route in ("/", ""):
        return f"{_SCHEMAS_DIR}/home.json"
    cleaned = re.sub(r"\[\w+\]", "detail", route.strip("/"))
    return f"{_SCHEMAS_DIR}/{cleaned}.json"


def _upsert_nav_flow(output_dir: str, route: str, title: str, schema_file: str) -> None:
    """Read existing nav-flow.json (or create fresh), add/update the page entry.

    Idempotent: calling twice with the same route replaces the existing entry.
    """
    nav_path = Path(output_dir) / _NAV_FLOW_PATH
    nav_path.parent.mkdir(parents=True, exist_ok=True)

    if nav_path.exists():
        try:
            nav = json.loads(nav_path.read_text())
        except (OSError, json.JSONDecodeError):
            nav = {}
    else:
        nav = {}

    # Ensure top-level keys exist with sensible defaults
    nav.setdefault("version", "1.0")
    nav.setdefault("pages", [])
    nav.setdefault("transitions", [])
    nav.setdefault("guards", {})

    page_id = _slug_from_route(route)
    shell = not _is_auth_route(route)
    new_entry = {
        "id": page_id,
        "route": route,
        "title": title,
        "schemaFile": schema_file,
        "layout": None,
        "guard": None,
        "params": [],
        "shell": shell,
    }

    # Replace existing entry for this route or append
    pages = nav["pages"]
    for i, p in enumerate(pages):
        if p.get("id") == page_id or p.get("route") == route:
            pages[i] = new_entry
            break
    else:
        pages.append(new_entry)

    # Set initialPage to the first registered page if not set or points to nothing
    existing_ids = {p["id"] for p in pages}
    if nav.get("initialPage") not in existing_ids:
        nav["initialPage"] = pages[0]["id"] if pages else ""

    # Recompute auth_routes and redirect targets from all pages
    nav["auth_routes"] = [p["route"] for p in pages if not p.get("shell", True)]
    non_auth = [p["route"] for p in pages if p.get("shell", True)]
    if non_auth and "post_login_redirect" not in nav:
        nav["post_login_redirect"] = non_auth[0]
    if nav["auth_routes"] and "post_logout_redirect" not in nav:
        nav["post_logout_redirect"] = nav["auth_routes"][0]

    nav_path.write_text(json.dumps(nav, indent=2) + "\n")


async def build_schema_from_jsx(
    jsx_source: str,
    output_dir: str,
    project_id: str | None = None,
    route: str | None = None,
    title: str | None = None,
    schema_filename: str | None = None,
    canvas: tuple[float, float] | None = None,
) -> tuple[dict, dict[str, str]]:
    """Build PageV2 schema from Figma MCP JSX source with local asset caching.

    Orchestrates the pipeline:
    1. Extract MCP asset URLs (figma.com/api/mcp/asset/...)
    2. Download them to output_dir/public/figma/ (idempotent)
    3. Transform JSX → PageV2 schema with src rewriting via asset_paths
    4. Upsert the page into nav-flow.json when ``route`` is provided

    Args:
        jsx_source: Raw JSX from get_design_context
        output_dir: Base output directory (assets go to output_dir/public/figma/)
        project_id: Optional project identifier. When supplied, asset src paths
            are emitted as /api/asset/<project_id>/figma/<file> so the
            render-scaffold can serve them via its per-project route handler.
        route: URL route for this page (e.g. ``"/login"``). When supplied,
            nav-flow.json is updated with a page entry. Omit to skip nav-flow.
        title: Human-readable page title. Defaults to the slug-capitalised
            form of ``route`` when ``route`` is provided.
        schema_filename: Basename for the schema file, e.g. ``"login.json"``.
            Inferred from ``route`` when omitted.

    Returns:
        (schema, asset_paths) where:
        - schema: PageV2-shaped dict {schemaVersion, id, title, dataSources, children}
        - asset_paths: {original_cdn_url: local_path} for logging/debugging
    """
    urls = extract_asset_urls(jsx_source)
    asset_paths = (
        await download_figma_assets(urls, output_dir, project_id=project_id)
        if urls
        else {}
    )
    schema = transform_jsx_to_schema(jsx_source, asset_paths, canvas=canvas)

    # Stamp a marker so downstream (renderer/shell) can identify pages that
    # came from Figma and skip its own chrome + theme override. The Figma
    # design supplies its own bg + layout; the dashboard shell must not
    # paint over it or wrap it in a sidebar that never existed in the design.
    if isinstance(schema, dict):
        schema["_figmaDerived"] = True
        # The frame's own dimensions, so the renderer can scale the canvas to
        # whatever width it is given instead of cropping it.
        if canvas is not None:
            schema["_figmaCanvas"] = {"width": canvas[0], "height": canvas[1]}

    # ── Auto-binding pass ─────────────────────────────────────────────
    # Attach dataSources + Repeat wrappers + {{item.field}} bindings by
    # matching the JSX-derived tree against the app's resource registry.
    # No-op when registry.json isn't there yet (early in the pipeline).
    try:
        from services.figma_binding_extractor import extract_bindings
        reg_path = Path(output_dir) / "registry.json"
        if reg_path.is_file():
            try:
                registry = json.loads(reg_path.read_text())
            except Exception:
                registry = {}
            if registry:
                schema = extract_bindings(schema, registry)
    except Exception:
        # Best-effort: never break the pipeline if the extractor fails.
        pass

    # Patch schema id/title when route is supplied so the schema is
    # self-consistent with nav-flow (id == page slug, title == page label).
    if route:
        page_slug = _slug_from_route(route)
        page_title = title or page_slug.replace("-", " ").title()
        schema["id"] = page_slug
        schema["title"] = page_title

        # Determine which file this schema will be written to
        if schema_filename:
            sf = f"{_SCHEMAS_DIR}/{schema_filename}"
        else:
            sf = _schema_file_from_route(route)

        _upsert_nav_flow(output_dir, route, page_title, sf)

    return schema, asset_paths
