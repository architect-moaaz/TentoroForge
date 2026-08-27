"""IR API routes — serve and update IR documents for the visual editor.

Endpoints:
  GET  /api/projects/{project_id}/ir       — Load IR manifest
  PUT  /api/projects/{project_id}/ir       — Save full IR (from editor)
  POST /api/projects/{project_id}/ir/compile — Recompile IR → code files
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services.ir_compiler import (
    compile_ir,
    write_compiled_files,
    save_ir,
    load_ir,
    IRCompileError,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["ir"])

OUTPUT_BASE = Path(__file__).resolve().parent.parent.parent / "output"


async def _resolve_output_dir(project_id: str) -> str:
    """Resolve the output directory for a project.

    Tries the database first (project.output_dir), falls back to
    OUTPUT_BASE / project_id for direct filesystem access.
    """
    # Try DB lookup
    try:
        from database import get_db
        from models.project import Project
        from sqlalchemy import select

        async for db in get_db():
            try:
                pid = uuid.UUID(project_id)
            except ValueError:
                break
            stmt = select(Project).where(Project.id == pid)
            result = await db.execute(stmt)
            project = result.scalar_one_or_none()
            if project and project.output_dir:
                return project.output_dir
            break
    except Exception:
        pass

    # Fallback: direct path
    return str(OUTPUT_BASE / project_id)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class IRSaveRequest(BaseModel):
    """Full AppIR JSON body."""
    model_config = {"extra": "allow"}


class CompileResponse(BaseModel):
    files: list[str]
    errors: list[str]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/{project_id}/ir")
async def get_ir(project_id: str) -> dict[str, Any]:
    """Load the IR manifest for a project.

    If no IR exists but a registry does, auto-migrates the project.
    """
    output = await _resolve_output_dir(project_id)
    ir = load_ir(output)

    if ir is None:
        # Try auto-migration from registry
        from services.ir_migrate import migrate_to_ir
        from pathlib import Path
        registry_path = Path(output) / "registry.json"
        if registry_path.exists():
            result = await migrate_to_ir(output)
            if result["success"]:
                ir = load_ir(output)

    if ir is None:
        raise HTTPException(status_code=404, detail="No IR found for this project")
    return ir


@router.put("/{project_id}/ir")
async def update_ir(project_id: str, body: dict[str, Any]) -> dict[str, str]:
    """Save a full IR document (from the visual editor)."""
    output = await _resolve_output_dir(project_id)

    # Validate basic structure
    if "$schema" not in body or "pages" not in body:
        raise HTTPException(status_code=422, detail="Invalid IR: missing $schema or pages")

    await save_ir(output, body)
    return {"status": "ok"}


@router.post("/{project_id}/ir/compile")
async def compile_project_ir(project_id: str) -> CompileResponse:
    """Recompile the project's IR to code files.

    Reads the stored IR, compiles it, and writes files to the output dir.
    """
    output = await _resolve_output_dir(project_id)
    ir = load_ir(output)
    if ir is None:
        raise HTTPException(status_code=404, detail="No IR found for this project")

    try:
        result = await compile_ir(ir)
    except IRCompileError as e:
        return CompileResponse(files=[], errors=e.errors, warnings=[])

    files = result.get("files", {})
    errors = result.get("errors", [])
    warnings = result.get("warnings", [])

    if errors:
        return CompileResponse(files=[], errors=errors, warnings=warnings)

    written = await write_compiled_files(output, files)
    return CompileResponse(files=written, errors=[], warnings=warnings)


# ---------------------------------------------------------------------------
# IR Edit (AI-powered structured editing)
# ---------------------------------------------------------------------------

class IREditRequest(BaseModel):
    instruction: str
    page_id: str | None = None

class IREditResponse(BaseModel):
    success: bool
    page_id: str | None = None
    operations: list[dict] = []
    message: str = ""

@router.post("/{project_id}/ir/edit")
async def ir_edit(project_id: str, body: IREditRequest) -> IREditResponse:
    """Apply an AI-powered IR edit from a natural language instruction.

    The IR edit agent analyzes the instruction and current IR,
    then produces structured operations instead of rewriting code.
    """
    output = await _resolve_output_dir(project_id)
    ir = load_ir(output)
    if ir is None:
        raise HTTPException(status_code=404, detail="No IR found for this project")

    from agents.ir_router import route_to_ir_edit

    result = await route_to_ir_edit(
        output_dir=output,
        user_message=body.instruction,
        page_id=body.page_id,
    )

    return IREditResponse(
        success=result.get("success", False),
        page_id=result.get("page_id"),
        operations=result.get("operations", []),
        message=result.get("response_text", ""),
    )


# ---------------------------------------------------------------------------
# IR QA (validation + auto-fix)
# ---------------------------------------------------------------------------

class EjectResponse(BaseModel):
    ejected: bool
    files_stripped: int
    ir_deleted: bool


class MigrateResponse(BaseModel):
    success: bool
    pages_created: int
    entities_found: int
    message: str


class ThemeListItem(BaseModel):
    name: str
    description: str


@router.post("/{project_id}/ir/eject")
async def eject_ir(project_id: str) -> EjectResponse:
    """Eject from IR — strips boundary comments, deletes .ir/ directory.

    One-way operation. The project becomes fully code-owned.
    """
    from services.ir_export import eject_from_ir

    output = await _resolve_output_dir(project_id)
    result = await eject_from_ir(output)
    return EjectResponse(**result)


@router.get("/{project_id}/ir/export")
async def export_ir_endpoint(project_id: str) -> dict[str, Any]:
    """Export the IR JSON for backup."""
    from services.ir_export import export_ir

    output = await _resolve_output_dir(project_id)
    ir = export_ir(output)
    if ir is None:
        raise HTTPException(status_code=404, detail="No IR found")
    return ir


@router.post("/{project_id}/ir/migrate")
async def migrate_to_ir(project_id: str) -> MigrateResponse:
    """Migrate an existing code-first project to IR (non-destructive)."""
    from services.ir_migrate import migrate_to_ir

    output = await _resolve_output_dir(project_id)
    result = await migrate_to_ir(output)
    return MigrateResponse(**result)


@router.get("/themes")
async def list_themes() -> list[ThemeListItem]:
    """List available IR themes."""
    # Import from the Node.js package isn't practical here,
    # so we maintain a simple Python-side list
    return [
        ThemeListItem(name="default", description="Clean, neutral theme"),
        ThemeListItem(name="ocean", description="Blue-toned professional theme"),
        ThemeListItem(name="forest", description="Green-toned natural theme"),
        ThemeListItem(name="sunset", description="Warm orange/amber theme"),
        ThemeListItem(name="sharp", description="No border radius, high contrast"),
        ThemeListItem(name="pill", description="Fully rounded, soft appearance"),
    ]


class IRQAResponse(BaseModel):
    valid: bool
    errors: list[str] = []
    warnings: list[str] = []
    fixes_applied: list[str] = []

@router.post("/{project_id}/ir/qa")
async def ir_qa(project_id: str) -> IRQAResponse:
    """Run IR-aware QA: validate, auto-fix, and recompile."""
    output = await _resolve_output_dir(project_id)
    ir = load_ir(output)
    if ir is None:
        raise HTTPException(status_code=404, detail="No IR found for this project")

    from agents.ir_qa_agent import run_ir_qa

    result = await run_ir_qa(output, ir)

    return IRQAResponse(
        valid=result["valid"],
        errors=result["errors"],
        warnings=result["warnings"],
        fixes_applied=result["fixes_applied"],
    )


# ---------------------------------------------------------------------------
# Registry binding helpers — used by the Data Binding UI
# ---------------------------------------------------------------------------

class EntityFieldSchema(BaseModel):
    name: str
    type: str
    required: bool = False
    description: str = ""


class EntitySchema(BaseModel):
    name: str
    fields: list[EntityFieldSchema]
    apiRoutes: list[str] = []


class WorkflowSchema(BaseModel):
    id: str
    name: str
    description: str = ""
    trigger: str = ""
    inputs: list[dict] = []


@router.get("/{project_id}/registry/entities")
async def get_registry_entities(project_id: str) -> list[EntitySchema]:
    """Return all entities from the project's registry.json.

    Used by the Data Binding panel in the IR editor to populate
    entity / field dropdowns.
    """
    output = await _resolve_output_dir(project_id)
    try:
        from services.registry import load_registry
        registry = load_registry(output)
    except Exception:
        return []

    entities = registry.get("entities", {})
    api_routes = registry.get("api_routes", {})

    result: list[EntitySchema] = []
    for name, entity_data in entities.items():
        fields = []
        for field_name, field_data in entity_data.get("fields", {}).items():
            fields.append(EntityFieldSchema(
                name=field_name,
                type=field_data.get("type", "string") if isinstance(field_data, dict) else str(field_data),
                required=field_data.get("required", False) if isinstance(field_data, dict) else False,
                description=field_data.get("description", "") if isinstance(field_data, dict) else "",
            ))

        # Collect API routes that reference this entity
        entity_routes = [
            path for path, route_data in api_routes.items()
            if isinstance(route_data, dict) and route_data.get("entity") == name
        ]

        result.append(EntitySchema(name=name, fields=fields, apiRoutes=entity_routes))

    return result


@router.get("/{project_id}/registry/workflows")
async def get_registry_workflows(project_id: str) -> list[WorkflowSchema]:
    """Return all workflow definitions for a project — for the editor's
    ActionPicker / Workflow Binding panel.

    Reads registry.json's `workflows` map first, then falls back to the on-disk
    `workflows/*.json` files. The fallback is load-bearing: generation writes
    the actual workflows as `workflows/<Name>.json` but commonly leaves
    `registry.workflows` empty, so reading only registry.json returned [] and
    the picker showed "registry empty" even though the app had ~50 workflows.
    A workflow's `processVariables` ([{name,type,required}]) are its inputs.
    """
    import json as _json
    from pathlib import Path as _Path

    output = await _resolve_output_dir(project_id)
    result: list[WorkflowSchema] = []
    seen: set[str] = set()

    def _trigger_of(d: dict) -> str:
        trig = d.get("trigger")
        if not trig:
            defn = d.get("definition") or {}
            t = defn.get("trigger") if isinstance(defn, dict) else None
            trig = (t.get("type") if isinstance(t, dict) else t) or ""
        return str(trig or "")

    # 1) registry.json workflows (when populated).
    try:
        from services.registry import load_registry
        registry = load_registry(output)
        for wf_id, wf_data in (registry.get("workflows") or {}).items():
            if wf_id in seen:
                continue
            seen.add(wf_id)
            d = wf_data if isinstance(wf_data, dict) else {}
            result.append(WorkflowSchema(
                id=wf_id,
                name=d.get("name", wf_id),
                description=d.get("description", ""),
                trigger=_trigger_of(d),
                inputs=d.get("inputs") or d.get("processVariables") or [],
            ))
    except Exception:
        pass

    # 2) Fall back to the on-disk workflow files (the actual generated workflows).
    wf_dir = _Path(output) / "workflows"
    if wf_dir.is_dir():
        for f in sorted(wf_dir.glob("*.json")):
            try:
                d = _json.loads(f.read_text())
            except Exception:
                continue
            wf_id = d.get("id") or f.stem
            if wf_id in seen:
                continue
            seen.add(wf_id)
            result.append(WorkflowSchema(
                id=wf_id,
                name=d.get("name", wf_id),
                description=d.get("description", ""),
                trigger=_trigger_of(d),
                inputs=d.get("processVariables") or d.get("inputs") or [],
            ))

    return result
