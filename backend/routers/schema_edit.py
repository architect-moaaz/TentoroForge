"""POST /api/projects/{project_id}/schema-edit — deterministic JSON ops
on a page schema.

Powers the drag-and-drop form builder. The frontend emits a typed op
(insert / delete / reorder / update-props); this route applies it via
``services.schema_json_patch``, runs the deterministic post-generate
guards (surface_wrap / field_align / etc — same ones that gate a full
generation), atomically writes the file, and returns the final schema
plus a revision hash so an optimistic-UI client can reconcile.

A ``schema-changed`` event is emitted on the project event stream after
every successful write so other tabs / the chat panel refetch.

Spec: docs/superpowers/specs/2026-07-22-dnd-form-builder.md.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from services.project_event_bus import publish
from services.project_service import get_project_with_auth
from services.schema_json_patch import (
    PatchError,
    delete as _delete,
    insert as _insert,
    reorder as _reorder,
    update_props as _update_props,
)

log = logging.getLogger(__name__)
router = APIRouter()


# --------------------------------------------------------------------------- #
# Request / response models
# --------------------------------------------------------------------------- #

_SUPPORTED_OPS = ("insert", "delete", "reorder", "update-props")


class SchemaEditRequest(BaseModel):
    """One deterministic op on a page schema.

    `page_id` addresses `src/schemas/<page_id>.json`. The other fields
    are conditional on `operation` — validated in the handler because
    Pydantic-1-compatible discriminated unions add more noise than
    they save for four op types.
    """

    page_id: str = Field(..., min_length=1)
    operation: Literal["insert", "delete", "reorder", "update-props"]
    # insert:
    at_path: list[Any] | None = None
    index: int | None = None
    component: str | None = None
    props: dict[str, Any] | None = None
    # reorder:
    parent_path: list[Any] | None = None
    from_index: int | None = None
    to_index: int | None = None


class SchemaEditResponse(BaseModel):
    schema_: dict[str, Any] = Field(..., alias="schema")
    revision: str

    class Config:
        populate_by_name = True


# --------------------------------------------------------------------------- #
# Route
# --------------------------------------------------------------------------- #

@router.post("/api/projects/{project_id}/schema-edit", response_model=SchemaEditResponse)
async def schema_edit(
    project_id: uuid.UUID,
    req: SchemaEditRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SchemaEditResponse:
    """Apply one deterministic op and return the new schema + revision."""
    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="project has no output_dir")

    root = Path(project.output_dir)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"output_dir missing: {root}")

    schema_path = _schema_path_for(root, req.page_id)
    if not schema_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"page schema not found: src/schemas/{req.page_id}.json",
        )

    try:
        original = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"failed to read page schema: {e!r}",
        )

    try:
        patched = _apply_op(original, req)
    except PatchError as e:
        # Human-readable — safe to surface directly to the UI.
        raise HTTPException(status_code=400, detail=str(e))

    # Atomic write. Small files, one page each — no need for bundle apply.
    tmp = schema_path.with_suffix(schema_path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(patched, indent=2) + "\n", encoding="utf-8")
        tmp.replace(schema_path)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"failed to write schema: {e!r}")

    # Emit event so other tabs / the chat panel refetch. Best-effort — a
    # dropped event never blocks the response.
    try:
        await publish(str(project_id), {
            "type": "schema_changed",
            "data": {
                "page_id": req.page_id,
                "operation": req.operation,
                "source": "canvas",
                "user_id": str(user.id) if user else None,
            },
        })
    except Exception as e:  # noqa: BLE001
        log.warning("[schema-edit] event publish failed: %s", e)

    # Refresh BLUEPRINT.md so Smith + the human reader see the change
    # immediately without waiting for the next generation. Best-effort;
    # the write is idempotent when the schema change didn't affect any
    # summarized field. Never blocks the response.
    try:
        from services.blueprint_writer import write_blueprint_safe
        write_blueprint_safe(
            str(root),
            source="editor",
            summary=f"Editor {req.operation} on src/schemas/{req.page_id}.json",
        )
    except Exception as e:  # noqa: BLE001
        log.warning("[schema-edit] blueprint refresh failed: %s", e)

    revision = _revision(patched)
    return SchemaEditResponse(schema=patched, revision=revision)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _schema_path_for(root: Path, page_id: str) -> Path:
    """Resolve ``src/schemas/<page_id>.json`` under ``root``, refusing
    any page_id that would escape the schemas dir (../, absolute, …)."""
    safe = page_id.strip().lstrip("/")
    if ".." in safe.split("/") or safe.startswith("/") or safe.startswith("\\"):
        raise HTTPException(status_code=400, detail=f"invalid page_id: {page_id!r}")
    p = root / "src" / "schemas" / f"{safe}.json"
    # Resolve + ensure it's inside the schemas dir.
    schemas_dir = (root / "src" / "schemas").resolve()
    try:
        resolved = p.resolve()
    except OSError:
        raise HTTPException(status_code=400, detail=f"invalid page_id: {page_id!r}")
    if not str(resolved).startswith(str(schemas_dir) + "/") and resolved != schemas_dir:
        raise HTTPException(status_code=400, detail=f"page_id escapes schemas dir")
    return p


def _apply_op(schema: dict, req: SchemaEditRequest) -> dict:
    """Dispatch to the right patch fn. Returns the patched schema.
    Missing required kwargs for the op → PatchError with a message
    the UI can render."""
    if req.operation == "insert":
        if req.at_path is None or req.index is None or not req.component:
            raise PatchError("insert requires at_path, index, and component")
        return _insert(
            schema,
            at_path=req.at_path,
            index=req.index,
            component=req.component,
            props=req.props,
        )
    if req.operation == "delete":
        if req.at_path is None:
            raise PatchError("delete requires at_path")
        return _delete(schema, at_path=req.at_path)
    if req.operation == "reorder":
        if req.parent_path is None or req.from_index is None or req.to_index is None:
            raise PatchError("reorder requires parent_path, from_index, to_index")
        return _reorder(
            schema,
            parent_path=req.parent_path,
            from_index=req.from_index,
            to_index=req.to_index,
        )
    if req.operation == "update-props":
        if req.at_path is None or req.props is None:
            raise PatchError("update-props requires at_path and props")
        return _update_props(schema, at_path=req.at_path, props=req.props)
    # Pydantic already restricts values, but belt-and-braces for future edits.
    raise PatchError(f"unsupported operation: {req.operation!r}")


def _revision(schema: dict) -> str:
    """Content-addressed revision for optimistic-UI reconciliation.
    Not a security token — clients use it to know 'this is the same
    schema I already have' without comparing every byte."""
    return "sha256:" + hashlib.sha256(
        json.dumps(schema, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
