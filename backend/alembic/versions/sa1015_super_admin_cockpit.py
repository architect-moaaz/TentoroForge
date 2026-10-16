"""the super admin cockpit: a platform role, disabled logins, organisation status, the actor on an audit row

One account runs the platform (`platform_role = 'super_admin'`), granted to
others from the cockpit. A login can be disabled (`disabled_at`, with the
reason and who did it) and is refused on its next request. An organisation
has a status — active, blocked (its members may not use it) or removed
(hidden, kept, reinstatable) — a plain string, not a Postgres enum, so a later
value needs no ALTER TYPE. An audit row names the actor beside the user it
acted as: impersonation is `actor_user_id != user_id`. A pending invite no
longer needs a placeholder user (`org_members.user_id` nullable).

Revision ID: sa1015_super_admin
Revises: bd0920_brand_profiles
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "sa1015_super_admin"
down_revision = "bd0920_brand_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("platform_users", sa.Column("platform_role", sa.String(32), nullable=True))
    op.add_column("platform_users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("platform_users", sa.Column("disabled_reason", sa.Text(), nullable=True))
    op.add_column("platform_users", sa.Column(
        "disabled_by", UUID(as_uuid=True),
        sa.ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True))
    op.add_column("platform_users", sa.Column("last_sign_in_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_platform_users_platform_role", "platform_users", ["platform_role"])

    op.add_column("organizations", sa.Column(
        "status", sa.String(16), nullable=False, server_default="active"))
    op.add_column("organizations", sa.Column("status_reason", sa.Text(), nullable=True))
    op.add_column("organizations", sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("organizations", sa.Column(
        "status_changed_by", UUID(as_uuid=True),
        sa.ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_organizations_status", "organizations", ["status"])

    op.alter_column("org_members", "user_id", existing_type=UUID(as_uuid=True), nullable=True)

    op.add_column("audit_logs", sa.Column(
        "org_id", UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True))
    op.add_column("audit_logs", sa.Column(
        "actor_user_id", UUID(as_uuid=True),
        sa.ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_audit_org", "audit_logs", ["org_id"])
    op.create_index("ix_audit_actor", "audit_logs", ["actor_user_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_actor", table_name="audit_logs")
    op.drop_index("ix_audit_org", table_name="audit_logs")
    op.drop_column("audit_logs", "actor_user_id")
    op.drop_column("audit_logs", "org_id")

    op.alter_column("org_members", "user_id", existing_type=UUID(as_uuid=True), nullable=False)

    op.drop_index("ix_organizations_status", table_name="organizations")
    op.drop_column("organizations", "status_changed_by")
    op.drop_column("organizations", "status_changed_at")
    op.drop_column("organizations", "status_reason")
    op.drop_column("organizations", "status")

    op.drop_index("ix_platform_users_platform_role", table_name="platform_users")
    op.drop_column("platform_users", "last_sign_in_at")
    op.drop_column("platform_users", "disabled_by")
    op.drop_column("platform_users", "disabled_reason")
    op.drop_column("platform_users", "disabled_at")
    op.drop_column("platform_users", "platform_role")
