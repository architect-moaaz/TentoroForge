"""Organization, identity, and RBAC models."""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
    UniqueConstraint,
    Index,
    Enum,
    func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OrgMemberRole(str, PyEnum):
    owner = "owner"
    admin = "admin"
    member = "member"


class InviteStatus(str, PyEnum):
    pending = "pending"
    accepted = "accepted"
    declined = "declined"
    expired = "expired"


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------

class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(500))
    settings: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    members: Mapped[list["OrgMember"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    departments: Mapped[list["Department"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    teams: Mapped[list["Team"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    people: Mapped[list["OrgPerson"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    roles: Mapped[list["OrgRole"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    groups: Mapped[list["OrgGroup"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Org membership (platform_users ↔ organizations)
# ---------------------------------------------------------------------------

class OrgMember(Base):
    __tablename__ = "org_members"
    __table_args__ = (
        UniqueConstraint("user_id", "org_id", name="uq_org_member"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("platform_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[OrgMemberRole] = mapped_column(
        Enum(OrgMemberRole, name="org_member_role"),
        default=OrgMemberRole.member,
    )
    invite_status: Mapped[InviteStatus] = mapped_column(
        Enum(InviteStatus, name="invite_status"),
        default=InviteStatus.accepted,
    )
    invite_email: Mapped[str | None] = mapped_column(String(255))
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    user: Mapped["PlatformUser"] = relationship("PlatformUser", back_populates="org_memberships")
    organization: Mapped["Organization"] = relationship(back_populates="members")


# ---------------------------------------------------------------------------
# Department
# ---------------------------------------------------------------------------

class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_dept_name"),
        Index("ix_dept_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL")
    )
    head_person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_people.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="departments")
    parent: Mapped["Department | None"] = relationship(
        remote_side="Department.id", foreign_keys=[parent_id]
    )
    teams: Mapped[list["Team"]] = relationship(back_populates="department")
    people: Mapped[list["OrgPerson"]] = relationship(
        back_populates="department", foreign_keys="OrgPerson.department_id"
    )


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_team_name"),
        Index("ix_team_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    lead_person_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_people.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="teams")
    department: Mapped["Department | None"] = relationship(back_populates="teams")
    people: Mapped[list["OrgPerson"]] = relationship(
        back_populates="team", foreign_keys="OrgPerson.team_id"
    )


# ---------------------------------------------------------------------------
# Org Person (end-users of generated apps — not platform users)
# ---------------------------------------------------------------------------

class OrgPerson(Base):
    __tablename__ = "org_people"
    __table_args__ = (
        UniqueConstraint("org_id", "email", name="uq_person_email"),
        Index("ix_person_org", "org_id"),
        Index("ix_person_dept", "department_id"),
        Index("ix_person_team", "team_id"),
        Index("ix_person_manager", "manager_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("departments.id", ondelete="SET NULL")
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL")
    )
    manager_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_people.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="people")
    department: Mapped["Department | None"] = relationship(
        back_populates="people", foreign_keys=[department_id]
    )
    team: Mapped["Team | None"] = relationship(
        back_populates="people", foreign_keys=[team_id]
    )
    manager: Mapped["OrgPerson | None"] = relationship(
        remote_side="OrgPerson.id", foreign_keys=[manager_id]
    )
    role_assignments: Mapped[list["OrgPersonRole"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )
    group_memberships: Mapped[list["OrgGroupMember"]] = relationship(
        back_populates="person", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Org Role
# ---------------------------------------------------------------------------

class OrgRole(Base):
    __tablename__ = "org_roles"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_role_name"),
        Index("ix_role_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    permissions: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="roles")
    person_assignments: Mapped[list["OrgPersonRole"]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Person ↔ Role assignment
# ---------------------------------------------------------------------------

class OrgPersonRole(Base):
    __tablename__ = "org_person_roles"
    __table_args__ = (
        UniqueConstraint("person_id", "role_id", name="uq_person_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_people.id", ondelete="CASCADE"),
        nullable=False,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_roles.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    person: Mapped["OrgPerson"] = relationship(back_populates="role_assignments")
    role: Mapped["OrgRole"] = relationship(back_populates="person_assignments")


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------

class OrgGroup(Base):
    __tablename__ = "org_groups"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_group_name"),
        Index("ix_group_org", "org_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="groups")
    members: Mapped[list["OrgGroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Group ↔ Person membership
# ---------------------------------------------------------------------------

class OrgGroupMember(Base):
    __tablename__ = "org_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "person_id", name="uq_group_member"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("org_people.id", ondelete="CASCADE"),
        nullable=False,
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    group: Mapped["OrgGroup"] = relationship(back_populates="members")
    person: Mapped["OrgPerson"] = relationship(back_populates="group_memberships")
