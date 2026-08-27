"""CRUD + probe + tools discovery for platform_mcp_servers.

Admin-gated. Mirrors `routers.platform_integrations` for the auth check
and encryption call sites — the underlying crypto module is shared, keyed
by provider `"mcp"` so an MCP secret is not decryptable with another
provider's HKDF subkey.

  GET    /api/orgs/{org_id}/mcp-servers            list rows
  POST   /api/orgs/{org_id}/mcp-servers            create
  PATCH  /api/orgs/{org_id}/mcp-servers/{id}       update (partial)
  DELETE /api/orgs/{org_id}/mcp-servers/{id}       204
  GET    /api/orgs/{org_id}/mcp-servers/{id}/tools cached tools/list
  POST   /api/orgs/{org_id}/mcp-servers/{id}/test  probe → {ok, tool_count, error?}

Secrets are never returned by any endpoint; the list/detail shape exposes
a boolean `has_auth` flag only. `auth_secret == ""` on PATCH clears the
row's secret (same convention as platform_integrations).
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.auth import PlatformUser
from models.platform_mcp_server import PlatformMcpServer
from routers.platform_integrations import _require_org_admin
from services import mcp_client
from services.platform_integrations_crypto import CryptoError, encrypt


log = logging.getLogger(__name__)
router = APIRouter(tags=["platform-mcp-servers"])


# --------------------------------------------------------------------------- #
# Request/response models
# --------------------------------------------------------------------------- #

_TRANSPORTS = ("http", "sse")
_AUTH_KINDS = ("none", "bearer", "apikey_header")


class McpServerOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    server_url: str
    transport: str
    auth_kind: str
    auth_header_name: str | None = None
    has_auth: bool
    enabled: bool
    created_at: str | None = None
    updated_at: str | None = None


class McpServerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    server_url: str = Field(..., min_length=1, max_length=1024)
    transport: Literal["http", "sse"] = "http"
    auth_kind: Literal["none", "bearer", "apikey_header"] = "none"
    auth_secret: str | None = None
    auth_header_name: str | None = Field(default=None, max_length=64)
    enabled: bool = True

    @field_validator("auth_header_name")
    @classmethod
    def _strip_header(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v


class McpServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    server_url: str | None = Field(default=None, min_length=1, max_length=1024)
    transport: Literal["http", "sse"] | None = None
    auth_kind: Literal["none", "bearer", "apikey_header"] | None = None
    # Empty string clears the stored secret; None leaves it alone.
    auth_secret: str | None = None
    auth_header_name: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None


class TestResult(BaseModel):
    ok: bool
    tool_count: int
    error: str | None = None
    kind: str | None = None


class ToolOut(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _to_out(row: PlatformMcpServer) -> McpServerOut:
    return McpServerOut(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        server_url=row.server_url,
        transport=row.transport,
        auth_kind=row.auth_kind,
        auth_header_name=row.auth_header_name,
        has_auth=bool(row.auth_secret_ct),
        enabled=row.enabled,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


async def _get_row(
    org_id: uuid.UUID, server_id: uuid.UUID, db: AsyncSession
) -> PlatformMcpServer:
    res = await db.execute(
        select(PlatformMcpServer).where(
            PlatformMcpServer.id == server_id,
            PlatformMcpServer.org_id == org_id,
        )
    )
    row = res.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="mcp server not found")
    return row


def _encrypt_secret(plaintext: str) -> tuple[str, str]:
    try:
        return encrypt("mcp", plaintext)
    except CryptoError as e:
        raise HTTPException(status_code=500, detail=str(e))


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #

@router.get(
    "/api/orgs/{org_id}/mcp-servers",
    response_model=list[McpServerOut],
)
async def list_mcp_servers(
    org_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[McpServerOut]:
    await _require_org_admin(org_id, user, db)
    res = await db.execute(
        select(PlatformMcpServer)
        .where(PlatformMcpServer.org_id == org_id)
        .order_by(PlatformMcpServer.name)
    )
    return [_to_out(r) for r in res.scalars().all()]


@router.post(
    "/api/orgs/{org_id}/mcp-servers",
    response_model=McpServerOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_mcp_server(
    org_id: uuid.UUID,
    body: McpServerCreate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> McpServerOut:
    await _require_org_admin(org_id, user, db)

    if body.auth_kind == "apikey_header" and not (body.auth_header_name or "").strip():
        raise HTTPException(
            status_code=400,
            detail="auth_header_name is required when auth_kind='apikey_header'",
        )
    if body.auth_kind != "none" and not body.auth_secret:
        raise HTTPException(
            status_code=400,
            detail=f"auth_secret is required when auth_kind='{body.auth_kind}'",
        )

    ct: str | None = None
    iv: str | None = None
    if body.auth_secret:
        ct, iv = _encrypt_secret(body.auth_secret)

    row = PlatformMcpServer(
        org_id=org_id,
        name=body.name.strip(),
        server_url=body.server_url.strip(),
        transport=body.transport,
        auth_kind=body.auth_kind,
        auth_secret_ct=ct,
        auth_secret_iv=iv,
        auth_header_name=body.auth_header_name,
        enabled=body.enabled,
        updated_by=user.id,
    )
    db.add(row)
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        # Most likely a UNIQUE(org_id, name) violation.
        raise HTTPException(status_code=409, detail=f"could not create: {e}") from e
    await db.refresh(row)
    return _to_out(row)


@router.patch(
    "/api/orgs/{org_id}/mcp-servers/{server_id}",
    response_model=McpServerOut,
)
async def update_mcp_server(
    org_id: uuid.UUID,
    server_id: uuid.UUID,
    body: McpServerUpdate,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> McpServerOut:
    await _require_org_admin(org_id, user, db)
    row = await _get_row(org_id, server_id, db)

    updates = body.model_dump(exclude_unset=True)

    # Apply simple fields (skip auth_secret, handled below).
    for field in ("name", "server_url", "transport", "auth_kind", "auth_header_name", "enabled"):
        if field in updates and updates[field] is not None:
            setattr(row, field, updates[field].strip() if isinstance(updates[field], str) and field in ("name", "server_url", "auth_header_name") else updates[field])

    if "auth_secret" in updates:
        secret = updates["auth_secret"]
        if secret == "":
            # Explicit clear.
            row.auth_secret_ct = None
            row.auth_secret_iv = None
        elif secret is not None:
            ct, iv = _encrypt_secret(secret)
            row.auth_secret_ct = ct
            row.auth_secret_iv = iv

    # Post-condition: apikey_header must have a header name; non-none must have a secret.
    if row.auth_kind == "apikey_header" and not (row.auth_header_name or "").strip():
        raise HTTPException(
            status_code=400,
            detail="auth_header_name is required when auth_kind='apikey_header'",
        )
    if row.auth_kind != "none" and not row.auth_secret_ct:
        raise HTTPException(
            status_code=400,
            detail=f"auth_secret is required when auth_kind='{row.auth_kind}'",
        )

    row.updated_by = user.id
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"could not update: {e}") from e
    await db.refresh(row)
    return _to_out(row)


@router.delete(
    "/api/orgs/{org_id}/mcp-servers/{server_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_mcp_server(
    org_id: uuid.UUID,
    server_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _require_org_admin(org_id, user, db)
    row = await _get_row(org_id, server_id, db)
    await db.delete(row)
    await db.commit()
    return None


# --------------------------------------------------------------------------- #
# Discovery + probe
# --------------------------------------------------------------------------- #

@router.get(
    "/api/orgs/{org_id}/mcp-servers/{server_id}/tools",
    response_model=list[ToolOut],
)
async def list_server_tools(
    org_id: uuid.UUID,
    server_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ToolOut]:
    """Cached (5-min) tools/list result for the Agent Builder tool picker."""
    await _require_org_admin(org_id, user, db)
    row = await _get_row(org_id, server_id, db)
    try:
        tools = await mcp_client.list_tools(row)
    except mcp_client.McpClientError as e:
        # Surface the domain error as a 502 with the kind — the UI will
        # render an explanatory banner rather than a generic 500.
        raise HTTPException(
            status_code=502,
            detail={"error": e.detail, "kind": e.kind},
        ) from e
    return [
        ToolOut(name=t.name, description=t.description, input_schema=t.input_schema)
        for t in tools
    ]


@router.post(
    "/api/orgs/{org_id}/mcp-servers/{server_id}/test",
    response_model=TestResult,
)
async def test_mcp_server(
    org_id: uuid.UUID,
    server_id: uuid.UUID,
    user: PlatformUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TestResult:
    """Probe — never 5xx's on connection errors; the payload carries the
    error so the UI can render it in-line next to the row."""
    await _require_org_admin(org_id, user, db)
    row = await _get_row(org_id, server_id, db)
    result = await mcp_client.probe(row)
    return TestResult(**result)
