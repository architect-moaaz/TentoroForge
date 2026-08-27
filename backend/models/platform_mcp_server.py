"""Platform-side registry of approved MCP servers, one row per (org, name).

Admins register an MCP server once at the platform level; every app-agent
in the org can then pick a tool from that server by name (see
`services.mcp_client` for discovery and invocation, and the Agent Builder
tool-node `tool_type: mcp`).

Auth credentials (bearer token or API key) are AES-GCM encrypted at rest
using `services.platform_integrations_crypto` with the provider salt
`"mcp"`. Plaintext is only decrypted at the point of use: `env_writer`
(when materialising `.env.local` for a generated app) and `mcp_client`
(for platform-side `tools/list` discovery + `test connection`).

Spec: docs/superpowers/specs/2026-08-01-visual-product-search-mcp-agent.md
Plan: docs/superpowers/plans/2026-08-01-mcp-tool-type-agent-builder.md
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class PlatformMcpServer(Base):
    __tablename__ = "platform_mcp_servers"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_platform_mcp_servers_org_name"),
        CheckConstraint(
            "transport IN ('http', 'sse')",
            name="ck_platform_mcp_servers_transport",
        ),
        CheckConstraint(
            "auth_kind IN ('none', 'bearer', 'apikey_header')",
            name="ck_platform_mcp_servers_auth_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        default=uuid.uuid4,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    server_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    transport: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="http", default="http",
    )
    auth_kind: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="none", default="none",
    )
    # AES-GCM ciphertext + IV (both base64). Nullable so an "unset"
    # credential is distinguishable from a "cleared" one.
    auth_secret_ct: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_secret_iv: Mapped[str | None] = mapped_column(Text, nullable=True)
    # For auth_kind="apikey_header": the header name to send the secret in
    # (e.g. "X-API-Key"). Ignored for other auth_kinds.
    auth_header_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true", default=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True,
    )
