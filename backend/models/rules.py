"""Rules & access control models — project rules, app access policies, field access policies."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class ProjectRule(Base):
    """A rule definition attached to a project (validation, access, business, computed, state_machine, trigger)."""

    __tablename__ = "project_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # validation, access, business, computed, state_machine, trigger
    model_name: Mapped[str | None] = mapped_column(String(255))
    field_name: Mapped[str | None] = mapped_column(String(255))
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project = relationship("Project", backref="rules")

    __table_args__ = (
        Index("idx_rule_project", "project_id"),
        Index("idx_rule_type", "project_id", "rule_type"),
    )


class AppAccessPolicy(Base):
    """Which org roles/groups/departments can access this app."""

    __tablename__ = "app_access_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # role, group, department, person
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    access_level: Mapped[str] = mapped_column(
        String(50), nullable=False, default="user"
    )  # user, admin, none
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project = relationship("Project", backref="access_policies")

    __table_args__ = (
        UniqueConstraint("project_id", "target_type", "target_id", name="uq_app_access_policy"),
    )


class FieldAccessPolicy(Base):
    """Field-level view/edit/hidden per role per model."""

    __tablename__ = "field_access_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(String(255), nullable=False)
    field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # role, group, department, person
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    condition: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project = relationship("Project", backref="field_access_policies")

    __table_args__ = (
        Index("idx_field_access", "project_id", "model_name", "field_name"),
    )
