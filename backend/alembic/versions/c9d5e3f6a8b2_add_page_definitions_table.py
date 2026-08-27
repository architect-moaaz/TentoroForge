"""Add page_definitions table

Revision ID: c9d5e3f6a8b2
Revises: b8c4d2e5f7a1
Create Date: 2026-03-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c9d5e3f6a8b2"
down_revision = "b8c4d2e5f7a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("route", sa.String(500), nullable=False, server_default="/"),
        sa.Column("html", sa.Text, nullable=False, server_default=""),
        sa.Column("css", sa.Text, nullable=False, server_default=""),
        sa.Column("data_bindings", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_page_project", "page_definitions", ["project_id"])


def downgrade() -> None:
    op.drop_index("idx_page_project")
    op.drop_table("page_definitions")
