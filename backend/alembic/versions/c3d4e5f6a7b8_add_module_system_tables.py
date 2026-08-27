"""Add module system tables — enhanced modules, module_files, dependency_type

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-06
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Dependency type enum ---
    dependency_type_enum = postgresql.ENUM(
        "uses", "extends", "imports",
        name="dependency_type", create_type=False,
    )
    dependency_type_enum.create(op.get_bind(), checkfirst=True)

    # --- Module file type enum ---
    module_file_type_enum = postgresql.ENUM(
        "page", "component", "api", "model", "service",
        "hook", "util", "config", "style", "test", "other",
        name="module_file_type", create_type=False,
    )
    module_file_type_enum.create(op.get_bind(), checkfirst=True)

    # --- Alter modules table ---
    # Drop old module_type column (no longer used)
    op.drop_column("modules", "module_type")

    # Add new columns
    op.add_column("modules", sa.Column("slug", sa.String(255), nullable=True))
    op.add_column("modules", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "modules",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Backfill slug from name for existing rows
    op.execute(
        "UPDATE modules SET slug = LOWER(REGEXP_REPLACE(name, '[^a-zA-Z0-9]+', '-', 'g')) WHERE slug IS NULL"
    )
    op.alter_column("modules", "slug", nullable=False)

    # Add unique index for project_id + slug
    op.create_index("ix_module_slug", "modules", ["project_id", "slug"], unique=True)

    # --- Add dependency_type to module_dependencies ---
    op.add_column(
        "module_dependencies",
        sa.Column(
            "dependency_type",
            dependency_type_enum,
            server_default="uses",
            nullable=False,
        ),
    )

    # --- Create module_files table ---
    op.create_table(
        "module_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("file_type", module_file_type_enum, server_default="other", nullable=False),
    )
    op.create_index("ix_module_file_module", "module_files", ["module_id"])


def downgrade() -> None:
    op.drop_index("ix_module_file_module", table_name="module_files")
    op.drop_table("module_files")

    op.drop_column("module_dependencies", "dependency_type")

    op.drop_index("ix_module_slug", table_name="modules")
    op.drop_column("modules", "updated_at")
    op.drop_column("modules", "description")
    op.drop_column("modules", "slug")

    op.add_column(
        "modules",
        sa.Column("module_type", sa.String(50), nullable=True),
    )
    op.execute("UPDATE modules SET module_type = 'frontend' WHERE module_type IS NULL")
    op.alter_column("modules", "module_type", nullable=False)

    # Drop enums
    op.execute("DROP TYPE IF EXISTS module_file_type")
    op.execute("DROP TYPE IF EXISTS dependency_type")
