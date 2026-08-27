"""Navigation & module endpoints — CRUD for navigation config and modules."""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.project import (
    AgentJob,
    AgentJobStatus,
    AgentType,
    Version,
)
from services.project_service import get_project_with_auth
from services.git_service import git_commit
from sse_helpers import sse_event, stream_agent_messages

router = APIRouter(tags=["navigation"])

NAV_FILE = "navigation.json"
MODULES_FILE = "modules.json"


def _nav_path(output_dir: str) -> Path:
    return Path(output_dir) / NAV_FILE


def _modules_path(output_dir: str) -> Path:
    return Path(output_dir) / MODULES_FILE


# ---------------------------------------------------------------------------
# Navigation config
# ---------------------------------------------------------------------------

class NavigationSave(BaseModel):
    screens: list[dict] = []
    edges: list[dict] = []
    sidebarLinks: list[dict] = []
    topbarLinks: list[dict] = []
    defaultScreen: str | None = None
    errorScreen: str | None = None


def _find_app_model(output_dir: str) -> Path | None:
    """app-model.json moved when the schema-mode pipeline put contracts under
    src/contracts/. Look in both legacy + current locations."""
    for rel in ("src/contracts/app-model.json", "app-model.json"):
        p = Path(output_dir) / rel
        if p.exists():
            return p
    return None


def _pages_from_schemas(output_dir: str) -> list[dict]:
    """Build a page list for the navigation panel.

    Source priority:
      1. src/contracts/nav-flow.json (canonical — generated alongside schemas)
      2. src/schemas/<entity>/<page>.json — legacy format where the schema
         itself carries its route at the top level.

    Returns [] when neither source yields any pages."""
    # 1. Preferred — nav-flow.json explicitly lists pages with routes + titles.
    nav_flow_path = Path(output_dir) / "src" / "contracts" / "nav-flow.json"
    if nav_flow_path.exists():
        try:
            nav_flow = json.loads(nav_flow_path.read_text())
        except (json.JSONDecodeError, OSError):
            nav_flow = None
        if isinstance(nav_flow, dict):
            pages: list[dict] = []
            for entry in nav_flow.get("pages") or []:
                if not isinstance(entry, dict):
                    continue
                route = entry.get("route")
                if not isinstance(route, str):
                    continue
                pages.append({
                    "route": route,
                    "name": entry.get("title") or entry.get("id") or route,
                    "description": entry.get("id") or "",
                })
            if pages:
                return pages

    # 2. Fallback — legacy schema files with top-level `route` field.
    schemas_dir = Path(output_dir) / "src" / "schemas"
    if not schemas_dir.exists():
        return []
    pages: list[dict] = []
    for json_file in sorted(schemas_dir.rglob("*.json")):
        try:
            schema = json.loads(json_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        route = schema.get("route")
        if not isinstance(route, str):
            continue
        rel = json_file.relative_to(schemas_dir).with_suffix("")
        parts = str(rel).replace("\\", "/").split("/")
        entity = parts[0] if parts else ""
        page_type = parts[-1] if parts else ""
        title = (schema.get("meta") or {}).get("title") if isinstance(schema.get("meta"), dict) else None
        label = title or f"{entity.replace('-', ' ').title()} · {page_type}"
        pages.append({
            "route": route,
            "name": label,
            "description": f"{entity} {page_type}",
        })
    return pages


def _route_to_pattern(route: str) -> str:
    """Normalise route patterns so we can match cross-page links even when one
    side uses /:id and the other uses /[id]. Both collapse to /<param>."""
    # Replace [param] with :param (Next.js dynamic-segment syntax)
    pattern = re.sub(r"\[([^\]]+)\]", r":\1", route)
    return pattern


def _route_matches(actual: str, target: str) -> bool:
    """Tolerant route equality: /requests/:id matches /requests/123, /:foo, etc."""
    a = _route_to_pattern(actual).rstrip("/")
    t = _route_to_pattern(target).rstrip("/")
    if a == t:
        return True
    # Match dynamic segments — replace any :param in either side with a wildcard
    a_re = "^" + re.sub(r":[A-Za-z_][\w]*", r"[^/]+", a) + "$"
    return bool(re.match(a_re, t))


def _derive_edges_from_schemas(output_dir: str, screens: list[dict]) -> list[dict]:
    """Walk every src/schemas/*.json and emit a navigation edge for each
    Button.navigate / Link.navigate / Hero CTA action.to that targets another
    page in this project. Each edge connects source screen → target screen,
    with `label` from the originating CTA / button label.

    Supports both schema formats:
      • legacy: { route: "/x", root: { ... children ... } }
      • current: { id: "...", children: [ ... ] } — route comes from
        nav-flow.json's `pages[].schemaFile` mapping.
    """
    schemas_dir = Path(output_dir) / "src" / "schemas"
    if not schemas_dir.exists():
        return []

    # Build schemaFile → route lookup from nav-flow.json (current format).
    schemafile_to_route: dict[str, str] = {}
    nav_flow_path = Path(output_dir) / "src" / "contracts" / "nav-flow.json"
    if nav_flow_path.exists():
        try:
            nav_flow = json.loads(nav_flow_path.read_text())
            for entry in nav_flow.get("pages") or []:
                sf = entry.get("schemaFile")
                rt = entry.get("route")
                if isinstance(sf, str) and isinstance(rt, str):
                    schemafile_to_route[sf] = rt
        except (json.JSONDecodeError, OSError):
            pass

    # Build a route → screen-id map for fast lookup. Routes like /users/:id
    # match Button.navigate values like /users/123 via _route_matches.
    route_to_screen = {s["data"]["route"]: s["id"] for s in screens}
    routes_sorted = sorted(route_to_screen.keys(), key=len, reverse=True)

    def find_screen_id(target: str) -> str | None:
        """Return the screen-id whose route matches `target`, preferring
        the most specific (longest) route so /users/:id wins over /users."""
        for route in routes_sorted:
            if _route_matches(target, route):
                return route_to_screen[route]
        return None

    edges: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    def add_edge(source_screen_id: str, target_route: str, label: str) -> None:
        target_id = find_screen_id(target_route)
        if not target_id or target_id == source_screen_id:
            return
        key = (source_screen_id, target_id)
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        edges.append({
            "id": f"edge_{len(edges)}",
            "source": source_screen_id,
            "target": target_id,
            "label": label,
        })

    def walk_node(node: dict, source_screen_id: str) -> None:
        if not isinstance(node, dict):
            return
        t = node.get("type")
        p = node.get("props") or {}
        # Buttons + Links
        nav = p.get("navigate")
        if isinstance(nav, str) and nav.startswith("/"):
            label = p.get("label", "Navigate") if isinstance(p.get("label"), str) else "Navigate"
            add_edge(source_screen_id, nav, label)
        # Hero CTAs
        if t == "Hero":
            ctas = p.get("ctas") or []
            for cta in ctas if isinstance(ctas, list) else []:
                if not isinstance(cta, dict):
                    continue
                action = cta.get("action") or {}
                if isinstance(action, dict) and action.get("type") == "navigate":
                    to = action.get("to")
                    if isinstance(to, str) and to.startswith("/"):
                        cta_label = cta.get("label", "CTA") if isinstance(cta.get("label"), str) else "CTA"
                        add_edge(source_screen_id, to, cta_label)
        # Recurse
        for child in node.get("children") or []:
            walk_node(child, source_screen_id)

    # Map each schema file to the screen at its route
    for json_file in schemas_dir.rglob("*.json"):
        try:
            schema = json.loads(json_file.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        # Resolve route: legacy schemas put it at top level; current schemas
        # look it up via nav-flow.json's schemaFile → route map.
        route = schema.get("route")
        if not isinstance(route, str):
            rel = json_file.relative_to(Path(output_dir)).as_posix()
            route = schemafile_to_route.get(rel)
        if not isinstance(route, str):
            continue
        screen_id = find_screen_id(route)
        if not screen_id:
            continue
        # Current schemas put children at the top level; legacy wraps in `root`.
        root = schema.get("root")
        if isinstance(root, dict):
            walk_node(root, screen_id)
        else:
            for child in schema.get("children") or []:
                walk_node(child, screen_id)

    return edges


def _build_nav_from_app_model(output_dir: str) -> dict:
    """Auto-generate navigation.json content.

    Called when navigation.json doesn't exist yet. Source-of-truth priority:
    1. src/schemas/<entity>/<page>.json — these are what the runtime actually
       renders. Use the schema's `route` + `meta.title` for each screen.
    2. app-model.json pages — fallback for non-schema-mode projects.
    Edges are derived by walking each schema and emitting a relationship for
    every Button.navigate / Link.navigate / Hero CTA action.to.
    """
    pages = _pages_from_schemas(output_dir)
    if not pages:
        app_model_path = _find_app_model(output_dir)
        if not app_model_path:
            return {"screens": [], "edges": [], "sidebarLinks": [], "topbarLinks": []}
        try:
            app_model = json.loads(app_model_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {"screens": [], "edges": [], "sidebarLinks": [], "topbarLinks": []}
        pages = app_model.get("pages", [])
    if not pages:
        return {"screens": [], "edges": [], "sidebarLinks": [], "topbarLinks": []}

    # Layout screens in a grid: 3 columns, each 220px wide, 140px tall, 60px gap
    col_count = 3
    col_width = 220
    row_height = 140
    x_gap = 60
    y_gap = 60

    screens = []
    sidebar_links = []

    for i, page in enumerate(pages):
        route = page.get("path") or page.get("route") or "/"
        name = page.get("component") or page.get("name") or route
        description = page.get("description", "")

        col = i % col_count
        row = i // col_count
        x = col * (col_width + x_gap)
        y = row * (row_height + y_gap)

        screens.append({
            "id": f"screen_{i}",
            "type": "screen",
            "position": {"x": x, "y": y},
            "data": {
                "label": name,
                "route": route,
                "description": description,
                "isHome": route == "/" or i == 0,
            },
        })

        # Add to sidebar links (top-level routes without params)
        if ":" not in route and "[" not in route:
            sidebar_links.append({
                "id": f"link_{i}",
                "label": name,
                "route": route,
                "icon": "layout-dashboard" if route == "/" else "file",
            })

    edges = _derive_edges_from_schemas(output_dir, screens)

    nav_data = {
        "screens": screens,
        "edges": edges,
        "sidebarLinks": sidebar_links[:8],  # limit sidebar to 8 items
        "topbarLinks": [],
        "defaultScreen": "screen_0" if screens else None,
    }

    # Persist so subsequent reads don't re-generate
    try:
        nav_file = Path(output_dir) / NAV_FILE
        nav_file.write_text(json.dumps(nav_data, indent=2))
    except OSError:
        pass

    return nav_data


def _reconcile_nav_with_schemas(output_dir: str, saved: dict) -> dict:
    """Treat current schemas as the source of truth for which screens exist,
    while preserving canvas positions / sidebar config from a previously saved
    navigation.json. Stale screens that no longer have a matching schema are
    dropped; new schemas get auto-placed via the same grid layout as the
    cold-start builder."""
    fresh = _build_nav_from_app_model(output_dir)
    fresh_by_route = {s["data"]["route"]: s for s in fresh.get("screens", [])}
    if not fresh_by_route:
        return saved  # No schemas yet — keep whatever the user saved.

    saved_screens = saved.get("screens", []) or []
    saved_pos_by_route: dict[str, dict] = {}
    for s in saved_screens:
        route = (s.get("data") or {}).get("route")
        if isinstance(route, str):
            saved_pos_by_route[route] = s.get("position") or {}

    # Overlay saved positions onto the fresh screens.
    for route, screen in fresh_by_route.items():
        if route in saved_pos_by_route and saved_pos_by_route[route]:
            screen["position"] = saved_pos_by_route[route]

    # BUG-012: preserve USER-ADDED screens that have no backing schema (their
    # route isn't in the fresh/schema-derived set). Previously they were silently
    # dropped here — so "Add Screen" + Save never persisted — and the file was
    # overwritten with the schema-only set. Schema pages stay authoritative
    # (new ones appear, deleted ones drop); extra user screens are kept.
    extra_screens = [
        s
        for s in saved_screens
        if (s.get("data") or {}).get("route") not in fresh_by_route
    ]
    fresh["screens"] = list(fresh.get("screens", [])) + extra_screens

    # Keep saved edges whose endpoints still exist (schema pages + kept extras),
    # unioned with the freshly-derived ones (dedup by id).
    surviving_ids = {s["id"] for s in fresh["screens"]}
    edges_by_id: dict[str, dict] = {e["id"]: e for e in fresh.get("edges", [])}
    for e in saved.get("edges", []) or []:
        if e.get("source") in surviving_ids and e.get("target") in surviving_ids:
            edges_by_id[e["id"]] = e
    fresh["edges"] = list(edges_by_id.values())

    fresh["sidebarLinks"] = saved.get("sidebarLinks") or fresh.get("sidebarLinks", [])
    fresh["topbarLinks"] = saved.get("topbarLinks") or fresh.get("topbarLinks", [])
    if saved.get("defaultScreen"):
        fresh["defaultScreen"] = saved["defaultScreen"]

    # Persist the merged result so user-saved positions survive the next read
    # (the build helper above wrote fresh-without-positions over the file).
    try:
        (Path(output_dir) / NAV_FILE).write_text(json.dumps(fresh, indent=2))
    except OSError:
        pass
    return fresh


@router.get("/api/projects/{project_id}/navigation")
async def get_navigation(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return {"screens": [], "edges": [], "sidebarLinks": [], "topbarLinks": []}

    nav_file = _nav_path(project.output_dir)
    if not nav_file.exists():
        return _build_nav_from_app_model(project.output_dir)

    saved = json.loads(nav_file.read_text())
    return _reconcile_nav_with_schemas(project.output_dir, saved)


@router.post("/api/projects/{project_id}/navigation")
async def save_navigation(
    project_id: uuid.UUID,
    req: NavigationSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    nav_file = _nav_path(project.output_dir)
    nav_file.write_text(json.dumps(req.model_dump(), indent=2))
    return {"saved": True}


@router.post("/api/projects/{project_id}/navigation/apply")
async def apply_navigation(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply navigation config to generated app via code_editor (SSE)."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    nav_file = _nav_path(project.output_dir)
    if not nav_file.exists():
        raise HTTPException(status_code=404, detail="No navigation config")

    nav_data = json.loads(nav_file.read_text())
    instruction = _build_navigation_instruction(nav_data)

    async def event_stream():
        yield sse_event("status", {"message": "Applying navigation config..."})

        # Deterministic fast-path: translate the editor's edges into
        # nav-flow.transitions and rewrite navigate props directly — instant,
        # lossless, no LLM. The code_editor pass below still runs for anything
        # deterministic apply can't express.
        try:
            from services.nav_apply import apply_editor_nav
            det = apply_editor_nav(project.output_dir, nav_data)
            yield sse_event("status", {
                "message": f"Applied {det['applied']} navigation link(s) deterministically "
                           f"({det['transitions']} connection(s))",
            })
        except Exception as _det_ex:  # noqa: BLE001 — never let the fast-path abort apply
            yield sse_event("log", {"text": f"[Nav] deterministic apply skipped: {_det_ex}"})

        try:
            total_cost = 0
            total_turns = 0
            total_duration = 0

            from agents.code_editor import run_code_editor
            yield sse_event("status", {"message": "Generating routes and navigation..."})

            async for evt in stream_agent_messages(
                run_code_editor(output_dir=project.output_dir, instruction=instruction),
                output_dir=project.output_dir,
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            from agents.validator import run_validator
            yield sse_event("status", {"message": "Validating build..."})

            async for evt in stream_agent_messages(
                run_validator(output_dir=project.output_dir),
                output_dir=project.output_dir,
                event_prefix="[Validator] ",
            ):
                if evt.get("event") == "agent_result":
                    data = json.loads(evt["data"])
                    total_cost += data.get("cost_usd", 0)
                    total_turns += data.get("num_turns", 0)
                    total_duration += data.get("duration_ms", 0)
                else:
                    yield evt

            commit_hash = await git_commit(project.output_dir,
                "nav: apply navigation config",
            actor="editor")

            from database import async_session
            async with async_session() as sess:
                job = AgentJob(
                    project_id=project.id,
                    agent_type=AgentType.code_editor,
                    status=AgentJobStatus.completed,
                    instruction=instruction[:500],
                    result={
                        "intent": "NAV_APPLY",
                        "num_turns": total_turns,
                        "cost_usd": total_cost,
                        "duration_ms": total_duration,
                    },
                    started_at=datetime.now(timezone.utc),
                    completed_at=datetime.now(timezone.utc),
                )
                sess.add(job)
                await sess.flush()

                if commit_hash:
                    version = Version(
                        project_id=project.id,
                        commit_hash=commit_hash,
                        message="nav: apply navigation config",
                        agent_job_id=job.id,
                    )
                    sess.add(version)

                await sess.commit()

            yield sse_event("complete", {
                "project_id": str(project.id),
                "commit_hash": commit_hash,
            })
        except Exception as e:
            yield sse_event("error", {"message": str(e)})

    return EventSourceResponse(event_stream(), ping=15)


def _build_navigation_instruction(nav_data: dict) -> str:
    screens = nav_data.get("screens", [])
    edges = nav_data.get("edges", [])
    sidebar = nav_data.get("sidebarLinks", [])
    topbar = nav_data.get("topbarLinks", [])
    default_screen = nav_data.get("defaultScreen")

    parts = ["Update the application routing and navigation structure.", ""]

    if screens:
        parts.append("## Routes / Screens")
        for s in screens:
            data = s.get("data", {})
            route = data.get("route", "/")
            label = data.get("label", s.get("id", ""))
            parts.append(f"- {label}: route={route}")
        parts.append("")

    if edges:
        parts.append("## Navigation Links (edges)")
        for e in edges:
            src = e.get("source", "?")
            tgt = e.get("target", "?")
            parts.append(f"- {src} → {tgt}")
        parts.append("")

    if sidebar:
        parts.append("## Sidebar Navigation")
        for link in sidebar:
            parts.append(f"- {link.get('label', '?')}: {link.get('route', '/')}")
        parts.append("")

    if topbar:
        parts.append("## Top Bar Navigation")
        for link in topbar:
            parts.append(f"- {link.get('label', '?')}: {link.get('route', '/')}")
        parts.append("")

    if default_screen:
        parts.append(f"Default/home route: {default_screen}")
        parts.append("")

    parts.extend([
        "## Requirements",
        "1. Create or update Next.js app routes for each screen",
        "2. Create a sidebar/navbar component with the specified links",
        "3. Add role-based visibility if roles are specified on links",
        "4. Set the default route to redirect to the home screen",
        "5. Add a 404 page if an error screen is defined",
    ])

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Modules (file-based layout config — kept for backward compatibility)
# DB-backed module CRUD is in routers/modules.py
# ---------------------------------------------------------------------------

class ModuleSave(BaseModel):
    modules: list[dict] = []
    dependencies: list[dict] = []


@router.get("/api/projects/{project_id}/modules/layout")
async def get_modules_layout(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        return {"modules": [], "dependencies": []}

    modules_file = _modules_path(project.output_dir)
    if not modules_file.exists():
        return {"modules": [], "dependencies": []}

    return json.loads(modules_file.read_text())


@router.post("/api/projects/{project_id}/modules/layout")
async def save_modules_layout(
    project_id: uuid.UUID,
    req: ModuleSave,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="No output directory")

    modules_file = _modules_path(project.output_dir)
    modules_file.write_text(json.dumps(req.model_dump(), indent=2))
    return {"saved": True}
