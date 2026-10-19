"""templates are reviewed before the Gallery; their uses and ratings are kept

A template submitted from an app waits for a Tentoro admin; approved, it is in
the Templates Gallery for everyone. These tables hold its listing (status,
review, version, price), each step of its review, every project made from it,
and the ratings people gave it. Statuses are plain strings, as elsewhere.

Revision ID: tg1017_template_gallery
Revises: tp1016_test_and_production
Create Date: 2026-10-17
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "tg1017_template_gallery"
down_revision = "tp1016_test_and_production"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "template_listings",
        sa.Column("template_id", sa.String(32), primary_key=True),
        sa.Column("org_id", UUID, sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("platform_users.id", ondelete="SET NULL")),
        sa.Column("source_project_id", UUID),
        sa.Column("lineage", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("pricing_model", sa.String(8), nullable=False, server_default="free"),
        sa.Column("price_cents", sa.Integer),
        sa.Column("currency", sa.String(3)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_by", UUID, sa.ForeignKey("platform_users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by", UUID, sa.ForeignKey("platform_users.id", ondelete="SET NULL")),
        sa.Column("review_note", sa.Text),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_template_listings_status", "template_listings", ["status"])
    op.create_index("ix_template_listings_org", "template_listings", ["org_id"])
    op.create_index("ix_template_listings_lineage", "template_listings", ["lineage"])

    op.create_table(
        "template_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("template_id", sa.String(32),
                  sa.ForeignKey("template_listings.template_id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("actor_id", UUID, sa.ForeignKey("platform_users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_template_events_template", "template_events", ["template_id", "created_at"])

    op.create_table(
        "template_uses",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("template_id", sa.String(32), nullable=False),
        sa.Column("lineage", sa.String(80), nullable=False),
        sa.Column("project_id", UUID, sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column("user_id", UUID, sa.ForeignKey("platform_users.id", ondelete="SET NULL")),
        sa.Column("org_id", UUID),
        sa.Column("is_review", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", name="uq_template_uses_project"),
    )
    op.create_index("ix_template_uses_lineage", "template_uses", ["lineage"])

    op.create_table(
        "template_reviews",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("lineage", sa.String(80), nullable=False),
        sa.Column("template_id", sa.String(32), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rating", sa.SmallInteger, nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("lineage", "user_id", name="uq_template_reviews_lineage_user"),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_template_reviews_rating"),
    )
    op.create_index("ix_template_reviews_lineage", "template_reviews", ["lineage", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_template_reviews_lineage", table_name="template_reviews")
    op.drop_table("template_reviews")
    op.drop_index("ix_template_uses_lineage", table_name="template_uses")
    op.drop_table("template_uses")
    op.drop_index("ix_template_events_template", table_name="template_events")
    op.drop_table("template_events")
    op.drop_index("ix_template_listings_lineage", table_name="template_listings")
    op.drop_index("ix_template_listings_org", table_name="template_listings")
    op.drop_index("ix_template_listings_status", table_name="template_listings")
    op.drop_table("template_listings")
