"""a deployment keeps its own address beside the app's

`url` is the app's own address — its main domain, else the production alias —
the same after every publish; `deployment_url` is this build's frozen address.

Revision ID: dp1015_deployment_url
Revises: ft1015_features
Create Date: 2026-10-15
"""
from alembic import op
import sqlalchemy as sa


revision = "dp1015_deployment_url"
down_revision = "ft1015_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deployments", sa.Column("deployment_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("deployments", "deployment_url")
