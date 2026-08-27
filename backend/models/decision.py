"""Decision table models — decision tables, versions, and execution logs."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class DecisionTable(Base):
    """A decision table definition attached to a project."""

    __tablename__ = "decision_tables"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project = relationship("Project", backref="decision_tables")
    versions = relationship(
        "DecisionTableVersion",
        backref="decision_table",
        cascade="all, delete-orphan",
        order_by="DecisionTableVersion.version.desc()",
    )
    execution_logs = relationship(
        "DecisionExecutionLog",
        backref="decision_table",
        cascade="all, delete-orphan",
        order_by="DecisionExecutionLog.created_at.desc()",
    )

    __table_args__ = (
        Index("idx_decision_table_project", "project_id"),
    )


class DecisionTableVersion(Base):
    """Versioned snapshot of a decision table definition."""

    __tablename__ = "decision_table_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    decision_table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("decision_tables.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_decision_version_table", "decision_table_id"),
        Index("idx_decision_version_number", "decision_table_id", "version"),
    )


class DecisionExecutionLog(Base):
    """Audit log of decision table evaluations."""

    __tablename__ = "decision_execution_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    decision_table_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("decision_tables.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    inputs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    outputs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    matched_rule_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    hit_policy: Mapped[str | None] = mapped_column(String(1), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("idx_decision_log_table", "decision_table_id"),
        Index("idx_decision_log_workflow", "workflow_instance_id"),
    )
