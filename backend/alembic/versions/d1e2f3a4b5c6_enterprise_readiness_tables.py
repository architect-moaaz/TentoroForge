"""Enterprise readiness tables — workflow instances, tasks, notifications, audit, webhooks, environments

Revision ID: d1e2f3a4b5c6
Revises: c9d5e3f6a8b2
Create Date: 2026-03-03
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d1e2f3a4b5c6"
down_revision = "c9d5e3f6a8b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- PlatformUser: add SSO fields ---
    op.add_column("platform_users", sa.Column("auth_provider", sa.String(50), server_default="local"))
    op.add_column("platform_users", sa.Column("external_id", sa.String(255)))
    op.add_column("platform_users", sa.Column("avatar_url", sa.String(500)))
    # Allow null password_hash for SSO users
    op.alter_column("platform_users", "password_hash", nullable=True)

    # --- Workflow Instances ---
    workflow_instance_status = postgresql.ENUM(
        "created", "running", "waiting", "completed", "failed", "cancelled",
        name="workflow_instance_status", create_type=False,
    )
    workflow_instance_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "workflow_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_id", sa.String(255), nullable=False),
        sa.Column("workflow_name", sa.String(255), nullable=False),
        sa.Column("status", workflow_instance_status, default="created"),
        sa.Column("current_node_ids", postgresql.JSONB, default=[]),
        sa.Column("variables", postgresql.JSONB, default={}),
        sa.Column("initiated_by", postgresql.UUID(as_uuid=True)),
        sa.Column("error_message", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_wfi_project", "workflow_instances", ["project_id"])
    op.create_index("ix_wfi_status", "workflow_instances", ["status"])
    op.create_index("ix_wfi_workflow_id", "workflow_instances", ["workflow_id"])

    # --- Task Instances ---
    task_type = postgresql.ENUM(
        "user_task", "service_task", "timer_event", "gateway",
        name="task_type", create_type=False,
    )
    task_type.create(op.get_bind(), checkfirst=True)

    task_instance_status = postgresql.ENUM(
        "pending", "assigned", "active", "completed", "failed", "skipped", "cancelled",
        name="task_instance_status", create_type=False,
    )
    task_instance_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "task_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_instance_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workflow_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("node_label", sa.String(255)),
        sa.Column("task_type", task_type, nullable=False),
        sa.Column("status", task_instance_status, default="pending"),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True)),
        sa.Column("assignee_type", sa.String(50)),
        sa.Column("input_data", postgresql.JSONB, default={}),
        sa.Column("output_data", postgresql.JSONB, default={}),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_ti_workflow_instance", "task_instances", ["workflow_instance_id"])
    op.create_index("ix_ti_status", "task_instances", ["status"])
    op.create_index("ix_ti_assignee", "task_instances", ["assignee_id"])
    op.create_index("ix_ti_node_id", "task_instances", ["node_id"])

    # --- Notifications ---
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("link", sa.String(500)),
        sa.Column("metadata", postgresql.JSONB, default={}),
        sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_notif_user", "notifications", ["user_id"])
    op.create_index("ix_notif_user_unread", "notifications", ["user_id", "read_at"])
    op.create_index("ix_notif_created", "notifications", ["created_at"])

    # --- Audit Logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("platform_users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(255)),
        sa.Column("changes", postgresql.JSONB),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("user_agent", sa.String(500)),
        sa.Column("request_id", sa.String(50)),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_user", "audit_logs", ["user_id"])
    op.create_index("ix_audit_resource", "audit_logs", ["resource_type", "resource_id"])
    op.create_index("ix_audit_action", "audit_logs", ["action"])
    op.create_index("ix_audit_timestamp", "audit_logs", ["timestamp"])

    # --- Webhooks ---
    op.create_table(
        "webhooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("secret", sa.String(255)),
        sa.Column("events", postgresql.JSONB, default=[]),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("description", sa.Text),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True)),
        sa.Column("failure_count", sa.Integer, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_webhook_project", "webhooks", ["project_id"])
    op.create_index("ix_webhook_active", "webhooks", ["is_active"])

    # --- Environments ---
    op.create_table(
        "environments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("config", postgresql.JSONB, default={}),
        sa.Column("secrets", postgresql.JSONB, default={}),
        sa.Column("is_active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_env_project", "environments", ["project_id"])
    op.create_unique_constraint("uq_env_name", "environments", ["project_id", "name"])


def downgrade() -> None:
    op.drop_table("environments")
    op.drop_table("webhooks")
    op.drop_table("audit_logs")
    op.drop_table("notifications")
    op.drop_table("task_instances")
    op.drop_table("workflow_instances")

    op.execute("DROP TYPE IF EXISTS workflow_instance_status")
    op.execute("DROP TYPE IF EXISTS task_type")
    op.execute("DROP TYPE IF EXISTS task_instance_status")

    op.drop_column("platform_users", "avatar_url")
    op.drop_column("platform_users", "external_id")
    op.drop_column("platform_users", "auth_provider")
    op.alter_column("platform_users", "password_hash", nullable=False)
