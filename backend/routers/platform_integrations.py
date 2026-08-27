"""GET/PUT /api/orgs/{org_id}/integrations — platform-side credential store.
Plus POST /api/projects/{project_id}/integrations/sync — rewrites a project's
.env.local from the current platform values.


Admin-in-org gate. GET returns the catalog (every provider+key the pipeline
knows about) with an `is_set` flag; plaintext values are NEVER returned.
PUT upserts one encrypted row; `value == ""` clears the row.

The generation pipeline (services.env_writer) reads this store to populate
each generated app's `.env.local`.

Spec: docs/superpowers/specs/2026-07-22-integrations-settings.md.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.org import OrgMember, OrgMemberRole
from models.platform_integration import PlatformIntegration
from services.node_config_specs import (
    NODE_CONFIG_SPECS,
    all_providers,
    keys_for_provider,
)
from services.platform_integrations_crypto import CryptoError, encrypt


log = logging.getLogger(__name__)
router = APIRouter()


# --------------------------------------------------------------------------- #
# Request/response models
# --------------------------------------------------------------------------- #

class IntegrationEntry(BaseModel):
    provider: str
    key: str
    label: str
    kind: str
    required: bool
    default: str | None = None
    help_url: str | None = None
    options: list[str] | None = None
    is_set: bool
    updated_at: str | None = None


class IntegrationPutRequest(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64)
    key: str = Field(..., min_length=1, max_length=128)
    value: str  # empty string clears the row


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

async def _require_org_admin(
    org_id: uuid.UUID, user: PlatformUser, db: AsyncSession
) -> OrgMember:
    """Same shape as orgs router's helper — inlined to avoid a cross-router
    import. Bumped to admin-only; member role can't touch integrations."""
    from models.org import InviteStatus  # local to avoid cycle
    res = await db.execute(
        select(OrgMember).where(
            OrgMember.org_id == org_id,
            OrgMember.user_id == user.id,
            OrgMember.invite_status == InviteStatus.accepted,
        )
    )
    m = res.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    rank = {OrgMemberRole.owner: 3, OrgMemberRole.admin: 2, OrgMemberRole.member: 1}
    if rank.get(m.role, 0) < rank.get(OrgMemberRole.admin, 2):
        raise HTTPException(status_code=403, detail="Admin role required")
    return m


def _key_known(provider: str, key: str) -> bool:
    """Refuse writes for keys not declared in the spec registry. Prevents
    a malicious/mistyped write from creating orphan rows."""
    if provider not in all_providers():
        return False
    return any(e.key == key for e in keys_for_provider(provider))


# --------------------------------------------------------------------------- #
# GET
# --------------------------------------------------------------------------- #

@router.get(
    "/api/orgs/{org_id}/integrations",
    response_model=list[IntegrationEntry],
)
async def list_integrations(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[IntegrationEntry]:
    """Every provider+key in the spec, with is_set + updated_at metadata.
    Never returns plaintext values. The UI shows Set/Not Set indicators."""
    await _require_org_admin(org_id, user, db)

    res = await db.execute(
        select(PlatformIntegration).where(PlatformIntegration.org_id == org_id)
    )
    rows = res.scalars().all()
    by_key: dict[tuple[str, str], PlatformIntegration] = {
        (r.provider, r.key): r for r in rows
    }

    out: list[IntegrationEntry] = []
    for provider in all_providers():
        for entry in keys_for_provider(provider):
            row = by_key.get((entry.provider, entry.key))
            out.append(IntegrationEntry(
                provider=entry.provider,
                key=entry.key,
                label=entry.label,
                kind=entry.kind,
                required=entry.required,
                default=entry.default,
                help_url=entry.help_url,
                options=list(entry.options) if entry.options else None,
                is_set=bool(row and row.value_ct),
                updated_at=row.updated_at.isoformat() if row and row.updated_at else None,
            ))
    return out


# --------------------------------------------------------------------------- #
# PUT
# --------------------------------------------------------------------------- #

@router.put("/api/orgs/{org_id}/integrations")
async def upsert_integration(
    org_id: uuid.UUID,
    req: IntegrationPutRequest,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Upsert one row. Value is encrypted with a per-provider HKDF subkey.
    An empty value clears the row (nullable ct/iv marks it as cleared —
    distinguishes 'explicitly cleared' from 'never set')."""
    await _require_org_admin(org_id, user, db)

    if not _key_known(req.provider, req.key):
        raise HTTPException(
            status_code=400,
            detail=f"unknown provider/key: {req.provider}/{req.key}. "
                   f"Add it to services.node_config_specs first.",
        )

    # kind=select fields must have a value from the declared options list.
    # Empty string is always allowed (that's "clear").
    if req.value:
        entry = next(
            (e for e in keys_for_provider(req.provider) if e.key == req.key),
            None,
        )
        if entry and entry.kind == "select" and entry.options:
            if req.value not in entry.options:
                raise HTTPException(
                    status_code=400,
                    detail=f"value must be one of: {', '.join(entry.options)}",
                )

    # Fetch existing row (if any).
    res = await db.execute(
        select(PlatformIntegration).where(
            PlatformIntegration.org_id == org_id,
            PlatformIntegration.provider == req.provider,
            PlatformIntegration.key == req.key,
        )
    )
    existing = res.scalar_one_or_none()

    if req.value == "":
        # Clear. Keep the row so audit history (updated_at, updated_by) survives.
        if existing:
            existing.value_ct = None
            existing.value_iv = None
            existing.updated_by = user.id
            await db.flush()
        await db.commit()
        await _sync_org_projects_env(org_id, db)
        return {"ok": True, "cleared": True, "synced_projects": True}

    try:
        ct, iv = encrypt(req.provider, req.value)
    except CryptoError as e:
        # e.g. FORGE_INTEGRATIONS_SECRET missing on the platform — the
        # operator hit the UI before setting the env var. Fail loudly.
        raise HTTPException(status_code=500, detail=str(e))

    if existing:
        existing.value_ct = ct
        existing.value_iv = iv
        existing.updated_by = user.id
    else:
        row = PlatformIntegration(
            org_id=org_id,
            provider=req.provider,
            key=req.key,
            value_ct=ct,
            value_iv=iv,
            updated_by=user.id,
        )
        db.add(row)
    await db.commit()
    # P1-O1: auto-sync every project in this org so a saved key lands in
    # each generated app's .env.local immediately — no manual "sync" click.
    # Failures are logged but don't fail the PUT (audit rows already saved).
    await _sync_org_projects_env(org_id, db)
    return {"ok": True, "cleared": False, "synced_projects": True}


async def _sync_org_projects_env(org_id: uuid.UUID, db: AsyncSession) -> None:
    """After an integration is saved/cleared, rewrite .env.local for every
    project in the org that has an output_dir. Best-effort — individual
    project failures are logged; a bad path never blocks the credential save."""
    try:
        from models.project import Project  # local import — avoids cycles at import time
        from services.env_writer import write_env_local_from_platform
    except Exception as exc:  # pragma: no cover — safety net for stale imports
        log.warning("integrations auto-sync unavailable: %s", exc)
        return
    try:
        res = await db.execute(
            select(Project).where(Project.org_id == org_id, Project.output_dir.isnot(None))
        )
        projects = res.scalars().all()
    except Exception as exc:
        log.warning("integrations auto-sync could not list projects for org %s: %s", org_id, exc)
        return
    for proj in projects:
        try:
            await write_env_local_from_platform(proj.output_dir, org_id, db)
        except Exception as exc:
            log.warning(
                "integrations auto-sync failed for project %s (%s): %s",
                proj.id, proj.output_dir, exc,
            )


# --------------------------------------------------------------------------- #
# Catalog (public — for the settings-page UI to know what to render).
# No auth required: the catalog itself is not sensitive; only values are.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# POST /api/projects/{project_id}/integrations/sync
# --------------------------------------------------------------------------- #

@router.post("/api/projects/{project_id}/integrations/sync")
async def sync_project_env(
    project_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Rewrite <output_dir>/.env.local from the platform integrations table.
    Admin gate applies to the project's org. Requires the project to have
    an output_dir; otherwise 400."""
    from services.project_service import get_project_with_auth
    from services.env_writer import write_env_local_from_platform

    project = await get_project_with_auth(project_id, user, db)
    if not project.output_dir:
        raise HTTPException(status_code=400, detail="project has no output_dir yet")
    await _require_org_admin(project.org_id, user, db)

    result = await write_env_local_from_platform(project.output_dir, project.org_id, db)
    return result


@router.get("/api/integrations/catalog")
async def integrations_catalog() -> list[dict[str, Any]]:
    """Return the full catalog (all providers, all keys) for the settings-page
    UI. Values are NOT included — this endpoint just tells the UI what fields
    to render + their metadata (label, kind, required, help_url)."""
    out: list[dict[str, Any]] = []
    for provider in all_providers():
        for e in keys_for_provider(provider):
            out.append({
                "provider": e.provider,
                "key": e.key,
                "label": e.label,
                "kind": e.kind,
                "required": e.required,
                "default": e.default,
                "help_url": e.help_url,
                "options": list(e.options) if e.options else None,
            })
    return out
