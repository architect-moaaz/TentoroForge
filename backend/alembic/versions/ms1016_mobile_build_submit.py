"""a mobile build can be submitted to its store: say where that stands

A finished production build is sent to Google Play or App Store Connect by `eas submit`. That is a second step with its
own outcome (it can fail on a missing app record or a refused key while the build itself is fine), so it gets its own
two columns and never touches `status`, which stays the build's.

Revision ID: ms1016_mobile_build_submit
Revises: tm1015_team_members
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa


revision = "ms1016_mobile_build_submit"
down_revision = "tm1015_team_members"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mobile_builds", sa.Column("submit_status", sa.String(32), nullable=True))
    op.add_column("mobile_builds", sa.Column("submit_message", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("mobile_builds", "submit_message")
    op.drop_column("mobile_builds", "submit_status")
