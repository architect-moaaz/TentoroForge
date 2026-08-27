"""initial org and identity tables

Revision ID: 2cd38d3a50ff
Revises:
Create Date: 2026-02-28 19:46:03.072633
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '2cd38d3a50ff'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Independent tables first
    op.create_table('organizations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=100), nullable=False),
        sa.Column('logo_url', sa.String(length=500), nullable=True),
        sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )

    op.create_table('platform_users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
    )

    # 2. Departments — without head_person_id FK (added later)
    op.create_table('departments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('parent_id', sa.UUID(), nullable=True),
        sa.Column('head_person_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['departments.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_dept_name'),
    )
    op.create_index('ix_dept_org', 'departments', ['org_id'])

    # 3. Org people — without team_id FK (added later)
    op.create_table('org_people',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('last_name', sa.String(length=100), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=True),
        sa.Column('department_id', sa.UUID(), nullable=True),
        sa.Column('team_id', sa.UUID(), nullable=True),
        sa.Column('manager_id', sa.UUID(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['manager_id'], ['org_people.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'email', name='uq_person_email'),
    )
    op.create_index('ix_person_org', 'org_people', ['org_id'])
    op.create_index('ix_person_dept', 'org_people', ['department_id'])
    op.create_index('ix_person_manager', 'org_people', ['manager_id'])
    op.create_index('ix_person_team', 'org_people', ['team_id'])

    # 4. Teams — now org_people exists, can reference it
    op.create_table('teams',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('department_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('lead_person_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['department_id'], ['departments.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['lead_person_id'], ['org_people.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_team_name'),
    )
    op.create_index('ix_team_org', 'teams', ['org_id'])

    # 5. Add deferred circular FKs
    op.create_foreign_key('fk_dept_head_person', 'departments', 'org_people',
                          ['head_person_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_person_team', 'org_people', 'teams',
                          ['team_id'], ['id'], ondelete='SET NULL')

    # 6. Org members (platform_users ↔ organizations)
    op.create_table('org_members',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('role', sa.Enum('owner', 'admin', 'member', name='org_member_role'), nullable=False),
        sa.Column('invite_status', sa.Enum('pending', 'accepted', 'declined', 'expired', name='invite_status'), nullable=False),
        sa.Column('invite_email', sa.String(length=255), nullable=True),
        sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['platform_users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'org_id', name='uq_org_member'),
    )

    # 7. Org roles
    op.create_table('org_roles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('permissions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_role_name'),
    )
    op.create_index('ix_role_org', 'org_roles', ['org_id'])

    # 8. Person ↔ Role assignments
    op.create_table('org_person_roles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('person_id', sa.UUID(), nullable=False),
        sa.Column('role_id', sa.UUID(), nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['person_id'], ['org_people.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['org_roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('person_id', 'role_id', name='uq_person_role'),
    )

    # 9. Groups
    op.create_table('org_groups',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'name', name='uq_group_name'),
    )
    op.create_index('ix_group_org', 'org_groups', ['org_id'])

    # 10. Group ↔ Person memberships
    op.create_table('org_group_members',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('group_id', sa.UUID(), nullable=False),
        sa.Column('person_id', sa.UUID(), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['org_groups.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['person_id'], ['org_people.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('group_id', 'person_id', name='uq_group_member'),
    )


def downgrade() -> None:
    op.drop_table('org_group_members')
    op.drop_table('org_groups')
    op.drop_table('org_person_roles')
    op.drop_table('org_roles')
    op.drop_table('org_members')
    op.drop_constraint('fk_person_team', 'org_people', type_='foreignkey')
    op.drop_constraint('fk_dept_head_person', 'departments', type_='foreignkey')
    op.drop_table('teams')
    op.drop_table('org_people')
    op.drop_table('departments')
    op.drop_table('platform_users')
    op.drop_table('organizations')
