"""Project-scoped editor endpoints for output-directory-based projects.

These are the canonical Phase 5+ endpoints for reading/writing schemas
and theme tokens of generated apps that live in output/<project_id>/.

Route prefix: /api/projects
Note: these coexist with the database-backed /api/projects/{uuid} endpoints;
      UUID validation on those routes disambiguates between the two.
"""

import json
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from services.project_paths import project_root, list_projects
from services.route_slug import route_from_slug

router = APIRouter(prefix="/api/projects", tags=["editor-projects"])


async def _resolve_root(project_id: str):
    """Resolve an editor project id → its on-disk output dir.

    The editor addresses projects by the DB **UUID** (`project.id`), but these
    disk endpoints live under `output/<short_id>/`. So: try the id as a short_id
    (dir on disk = source of truth) first; if that misses and the id is a UUID,
    look up the project's short_id / output_dir in the DB. Without this, an
    editor that passes the UUID gets `output/<uuid>/` → nothing → no pages.
    """
    import uuid as _uuid
    from pathlib import Path as _Path

    try:
        r = project_root(project_id)
        if r.exists():
            return r
    except ValueError:
        pass

    try:
        pid = _uuid.UUID(str(project_id))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"unknown project: {project_id}")

    from sqlalchemy import select
    from database import async_session
    from models.project import Project

    async with async_session() as db:
        proj = (await db.execute(select(Project).where(Project.id == pid))).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="project not found")
    candidates = [proj.short_id, (proj.output_dir or "").rstrip("/").split("/")[-1] or None]
    for cand in candidates:
        if not cand:
            continue
        try:
            r = project_root(cand)
            if r.exists():
                return r
        except ValueError:
            pass
    # last resort: an absolute output_dir path recorded on the project
    if proj.output_dir and _Path(proj.output_dir).exists():
        return _Path(proj.output_dir)
    raise HTTPException(status_code=404, detail="project has no output directory on disk")


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get("", summary="List output-directory projects")
async def list_projects_endpoint():
    """Return [{id, name}] for every directory under output/."""
    return list_projects()


# ---------------------------------------------------------------------------
# Pages (schema discovery)
# ---------------------------------------------------------------------------

@router.get("/{project_id}/schemas")
async def list_schemas(project_id: str):
    """Schema files for a project — paths under src/schemas, no extension.

    THIS WAS REGISTERED AS `/pages` AND SHADOWED THE REAL ONE. Both this
    router and routers/pages.py claimed `/api/projects/{id}/pages`, and this
    one is included first, so FastAPI matched it every time and the endpoint
    backed by PageDefinition was unreachable for every project. Two callers
    then wanted different things from one URL: the workflow node panel asks
    for `PageDefinition[]` and got `{paths}` it cannot use, and the visual
    editor grew a union type to accept whichever arrived.

    Named for what it returns. A list of schema files is not a list of pages,
    and `/schemas` was already being requested by the frontend — answering 404,
    because the handler for it was sitting on the other name.
    """
    root = await _resolve_root(project_id)

    # THE GENERATED APP IS A SUBDIRECTORY, same as _debug/project-file next
    # door. The Blueprint's projections write `app/src/schemas/*.json`; this
    # looked in `<output_dir>/src/schemas`, which for a Blueprint-built project
    # does not exist, and returned an empty list rather than saying so.
    #
    # The output root is tried first so legacy projects, which are the only
    # thing that ever wrote there, keep resolving exactly as before.
    schemas_dir = next(
        (d for d in (root / "src" / "schemas", root / "app" / "src" / "schemas")
         if d.is_dir()),
        None,
    )
    if schemas_dir is None:
        return {"paths": []}

    paths: list[str] = []
    for p in sorted(schemas_dir.rglob("*.json")):
        rel = p.relative_to(schemas_dir).with_suffix("")
        paths.append(str(rel).replace("\\", "/"))
    return {"paths": paths}


@router.get("/{project_id}/schema-list")
async def list_schema_routes(project_id: str):
    """Return every schema as a flat list with route metadata.

    Each entry: {route, slug, page_type, entity, id}. Works against both the
    new route-slug layout (e.g. ``notes/new.json``) and the legacy
    entity-trio layout (e.g. ``notes/list.json``). Schemas missing explicit
    ``route``/``slug``/``page_type``/``entity`` keys have them derived from
    the file path.
    """
    root = await _resolve_root(project_id)

    schemas_dir = root / "src" / "schemas"
    if not schemas_dir.exists():
        return []

    entries: list[dict] = []
    for f in sorted(schemas_dir.rglob("*.json")):
        if f.name in ("registry.json", "load.json"):
            continue
        try:
            data = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        rel = f.relative_to(schemas_dir).with_suffix("")
        slug = str(rel).replace("\\", "/")
        # Derive route, page_type, entity from slug when the schema doesn't
        # carry them explicitly. Legacy entity-trio layouts have slugs like
        # "notes/list" — the first segment is the entity, the last is the
        # page_type. Single-segment slugs (e.g. "home") have no entity.
        parts = slug.split("/")
        derived_entity = parts[0] if len(parts) > 1 else None
        derived_page_type = parts[-1]
        entries.append({
            "route": data.get("route") or route_from_slug(slug),
            "slug": data.get("slug") or slug,
            "page_type": data.get("page_type") or derived_page_type,
            "entity": data.get("entity") or derived_entity,
            "id": data.get("id") or slug,
        })
    return entries


# ---------------------------------------------------------------------------
# Load schema
# ---------------------------------------------------------------------------

@router.get("/{project_id}/load")
async def load_schema(project_id: str, path: str):
    """Load a schema JSON by path (no extension)."""
    root = await _resolve_root(project_id)

    target = root / "src" / "schemas" / f"{path}.json"
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"schema '{path}' not found")
    return {"schema": json.loads(target.read_text())}


# ---------------------------------------------------------------------------
# Save schema
# ---------------------------------------------------------------------------

class SaveBody(BaseModel):
    path: str
    # Use alias "schema" to match the wire format; avoids clash with
    # BaseModel.schema() classmethod by naming the attribute schema_data.
    schema_data: dict = Field(alias="schema")

    model_config = {"populate_by_name": True}


@router.post("/{project_id}/save")
async def save_schema(project_id: str, body: SaveBody):
    """Atomically save a schema JSON file."""
    root = await _resolve_root(project_id)

    target = root / "src" / "schemas" / f"{body.path}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(f".tmp.{int(time.time() * 1000)}.json")
    tmp.write_text(json.dumps(body.schema_data, indent=2))
    tmp.replace(target)
    return {"ok": True, "savedSchema": body.schema_data, "suggestions": []}


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

@router.get("/{project_id}/theme")
async def get_theme(project_id: str):
    """Return custom theme tokens if present, otherwise indicate default."""
    root = await _resolve_root(project_id)

    custom_path = root / "src" / "theme" / "tokens.custom.json"
    if custom_path.exists():
        return {"tokens": json.loads(custom_path.read_text()), "source": "custom"}
    return {"tokens": {}, "source": "default"}


@router.post("/{project_id}/theme")
async def save_theme(project_id: str, body: dict):
    """Save custom theme tokens."""
    root = await _resolve_root(project_id)

    target = root / "src" / "theme" / "tokens.custom.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    tokens = body.get("tokens", {})
    target.write_text(json.dumps(tokens, indent=2))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Production CSS — the editor canvas mounts this so its preview matches what
# the generated app actually renders. Returns the raw text of the project's
# src/app/globals.css. Tailwind's build is project-side; this just serves the
# source file and lets the editor inline it (we don't run a Tailwind compile
# in the platform). For projects whose globals.css is pure CSS (HSL vars +
# component selectors), the inlined content is directly usable. Tailwind
# directives (@tailwind base/etc) are no-ops in the editor browser context
# and degrade gracefully — the HSL variables and any plain-CSS selectors
# still apply.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Illustrations — serve bundled SVGs that live in <project>/public/illustrations/
# so the scaffold's IllustrationResolver-emitted <img src="/p/<id>/illustrations/X.svg">
# tags resolve through the backend during preview rendering. Production
# generated apps serve their /illustrations/ folder via Next.js public/ directly.
# ---------------------------------------------------------------------------

@router.get("/{project_id}/illustrations/{slug}.svg")
async def get_project_illustration(project_id: str, slug: str):
    """Serve a bundled SVG from a project's public/illustrations/ dir.

    The slug must not contain path separators or traversal segments;
    project_root() already enforces this on project_id.
    """
    if "/" in slug or ".." in slug or slug.startswith("."):
        raise HTTPException(status_code=400, detail=f"invalid slug: {slug!r}")
    root = await _resolve_root(project_id)

    candidate = root / "public" / "illustrations" / f"{slug}.svg"
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="illustration not found")
    return FileResponse(candidate, media_type="image/svg+xml")


@router.get("/{project_id}/css")
async def get_project_css(project_id: str):
    """Return the raw text of the project's src/app/globals.css (or empty if missing)."""
    root = await _resolve_root(project_id)

    css_path = root / "src" / "app" / "globals.css"
    css = css_path.read_text() if css_path.exists() else ""
    return {"css": css, "exists": css_path.exists()}


# ---------------------------------------------------------------------------
# Editor mirror — Phase D2
#
# The visual editor is authoritative for its own edits (the user saved
# through the UI). This endpoint records what happened in the Blueprint
# change_log with source="editor" so Smith's next turn sees the app
# has moved. Failure to mirror MUST NOT block the editor's save — the
# endpoint returns 200 with ``mirrored=false`` on any Blueprint error.
# ---------------------------------------------------------------------------

class EditorMirrorRequest(BaseModel):
    artifact_path: str = Field(..., description="Repo-relative path the editor just wrote")
    summary: str = Field(..., description="Short human-readable diff summary")
    why: str = Field("editor edit", description="Why this edit was made")


@router.post("/{project_id}/editor/mirror", summary="Record editor edit in Smith's blueprint")
async def record_editor_edit(project_id: str, req: EditorMirrorRequest):
    """Mirror an editor save into the blueprint change_log.

    Never raises 5xx — the editor's save has already succeeded before
    it calls us; the mirror is best-effort observability for Smith."""
    root = await _resolve_root(project_id)

    try:
        from services.smith_concurrency import EditorMirror
        mirror = EditorMirror(
            project_id=project_id, output_dir=str(root),
        )
        mirror.record_edit(
            artifact_path=req.artifact_path,
            summary=req.summary,
            why=req.why,
        )
        return {"mirrored": True}
    except Exception as exc:  # noqa: BLE001
        return {"mirrored": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Smith warmup — pre-load the app-map into the in-process cache
#
# The frontend fires this when the chat panel mounts so that by the time
# the user types the first ask, ``services.app_map.get_app_map`` has
# already populated its cache. The response returns a compact summary
# (counts + intent) that the UI can also display verbatim if it wants.
# ---------------------------------------------------------------------------

@router.post("/{project_id}/smith/warmup", summary="Preload Smith's app-map for this project")
async def smith_warmup(project_id: str):
    """Build and cache the app-map for this project. Safe to call
    repeatedly — subsequent calls are cache hits."""
    root = await _resolve_root(project_id)
    from services.app_map import get_app_map
    try:
        m = get_app_map(str(root))
    except Exception as exc:  # noqa: BLE001 — warmup must never 5xx
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "ok": True,
        "intent":    m.get("intent") or "",
        "counts": {
            "entities":  len(m.get("entities") or {}),
            "pages":     len(m.get("pages") or []),
            "workflows": len(m.get("workflows") or {}),
        },
    }
