"""A person may be in more than one team: team_members rows beside the home
team_id on the person; every existing home team becomes a membership row.

Revision ID: tm1015_team_members
Revises: dp1015_deployment_url
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "tm1015_team_members"
down_revision = "dp1015_deployment_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "team_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("teams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("org_people.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("team_id", "person_id", name="uq_team_member"),
    )
    op.create_index("ix_team_member_person", "team_members", ["person_id"])
    op.execute(
        "INSERT INTO team_members (id, team_id, person_id) "
        "SELECT gen_random_uuid(), team_id, id FROM org_people WHERE team_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_team_member_person", table_name="team_members")
    op.drop_table("team_members")
