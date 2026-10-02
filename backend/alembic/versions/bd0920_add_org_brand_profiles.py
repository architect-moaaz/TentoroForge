"""add org_brand_profiles — the company design language discovered at signup

One row per organisation, holding what a company's own website says it is and
what it looks like: the three discovery answers, the design tokens read off
the site, the mark, and the design.md generated from both.

The unique constraint on `org_id` is the model, not an optimisation. A second
profile for one organisation would make "the company's design language"
ambiguous at exactly the moment a build asks for it, and nothing in the flow
wants two — a re-run from Settings updates the row it finds.

Revision ID: bd0920_brand_profiles
Revises: rx0918_drop_crash_payload
Create Date: 2026-09-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, UUID, JSONB


revision = "bd0920_brand_profiles"
down_revision = "rx0918_drop_crash_payload"
branch_labels = None
depends_on = None


_LABELS = ("pending", "extracting", "ready", "failed", "skipped")

#: The type as the COLUMN refers to it. `create_type=False` is load-bearing:
#: SQLAlchemy emits CREATE TYPE inline from `create_table`, so a plain
#: `sa.Enum` here makes the migration create the type twice in its own
#: transaction and fail on `DuplicateObject` — which it did.
_STATUS = ENUM(*_LABELS, name="brand_discovery_status", create_type=False)

#: The same type, as the thing that CREATES it. Done as its own statement
#: with `checkfirst` so a re-run against a database where a previous partial
#: upgrade already made the type does not fail on it either.
_STATUS_TYPE = ENUM(*_LABELS, name="brand_discovery_status")


def upgrade() -> None:
    _STATUS_TYPE.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "org_brand_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True),
                  sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        # SET NULL, not CASCADE: the profile belongs to the company, so the
        # person who happened to run discovery leaving must not delete the
        # design language every app is built from.
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("platform_users.id", ondelete="SET NULL"),
                  nullable=True),
        sa.Column("status", _STATUS, nullable=False, server_default="pending"),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("logo_path", sa.String(500), nullable=True),
        sa.Column("identity", JSONB(), nullable=True),
        sa.Column("design", JSONB(), nullable=True),
        sa.Column("design_md", sa.Text(), nullable=True),
        sa.Column("evidence", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("org_id", name="uq_brand_profile_org"),
    )


def downgrade() -> None:
    op.drop_table("org_brand_profiles")
    _STATUS_TYPE.drop(op.get_bind(), checkfirst=True)
