"""add runtime_exceptions table

Revision ID: a9b7c2e8f4d1
Revises: f3ffbf62087c
Create Date: 2026-07-16 16:20:00.000000

Ledger of runtime errors captured from generated apps. First occurrence
of an error (deduped by hash) kicks off Smith's self-healing loop —
subsequent hits of the same error bump `occurrence_count`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a9b7c2e8f4d1"
down_revision: Union[str, None] = "f3ffbf62087c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    kind_enum = postgresql.ENUM(
        "workflow", "api_route", "page_render", "unhandled",
        name="runtime_exception_kind",
        create_type=False,  # created explicitly below so we can checkfirst
    )
    status_enum = postgresql.ENUM(
        "open", "in_progress", "resolved", "unresolvable", "dismissed",
        name="runtime_exception_status",
        create_type=False,
    )
    kind_enum.create(op.get_bind(), checkfirst=True)
    status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "runtime_exceptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", kind_enum, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("stack", sa.Text()),
        sa.Column("source_file", sa.String(512)),
        sa.Column("source_line", sa.Integer()),
        sa.Column("workflow_id", sa.String(255)),
        sa.Column("node_id", sa.String(255)),
        sa.Column("page_route", sa.String(512)),
        sa.Column("request_url", sa.String(2048)),
        sa.Column("request_method", sa.String(16)),
        sa.Column("request_body", postgresql.JSONB()),
        sa.Column("user_context", postgresql.JSONB()),
        sa.Column("dedup_key", sa.String(64), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at",  sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("status", status_enum, nullable=False, server_default="open"),
        sa.Column("heal_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_commit", sa.String(64)),
        sa.Column("resolution_summary", sa.Text()),
        sa.Column(
            "smith_conversation_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
        ),
        sa.UniqueConstraint("project_id", "dedup_key", name="uq_runtime_exc_dedup"),
    )
    op.create_index(
        "ix_runtime_exc_project_status", "runtime_exceptions",
        ["project_id", "status"],
    )
    op.create_index(
        "ix_runtime_exc_last_seen", "runtime_exceptions", ["last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_exc_last_seen", table_name="runtime_exceptions")
    op.drop_index("ix_runtime_exc_project_status", table_name="runtime_exceptions")
    op.drop_table("runtime_exceptions")
    sa.Enum(name="runtime_exception_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="runtime_exception_kind").drop(op.get_bind(), checkfirst=True)
