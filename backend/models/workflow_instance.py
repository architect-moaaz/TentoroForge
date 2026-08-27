"""Workflow runtime models — executable workflow and task instances."""

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    String,
    Text,
    Integer,
    DateTime,
    ForeignKey,
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

class WorkflowInstanceStatus(str, PyEnum):
    created = "created"
    running = "running"
    waiting = "waiting"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class TaskInstanceStatus(str, PyEnum):
    pending = "pending"
    assigned = "assigned"
    active = "active"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
    cancelled = "cancelled"


class TaskType(str, PyEnum):
    user_task = "user_task"
    service_task = "service_task"
    timer_event = "timer_event"
    gateway = "gateway"


# ---------------------------------------------------------------------------
# WorkflowInstance — a running instance of a workflow definition
# ---------------------------------------------------------------------------

class WorkflowInstance(Base):
    __tablename__ = "workflow_instances"
    __table_args__ = (
        Index("ix_wfi_project", "project_id"),
        Index("ix_wfi_status", "status"),
        Index("ix_wfi_workflow_id", "workflow_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[WorkflowInstanceStatus] = mapped_column(
        Enum(WorkflowInstanceStatus, name="workflow_instance_status"),
        default=WorkflowInstanceStatus.created,
    )
    current_node_ids: Mapped[dict | None] = mapped_column(JSONB, default=list)
    variables: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    initiated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    project = relationship("Project", backref="workflow_instances")
    task_instances: Mapped[list["TaskInstance"]] = relationship(
        back_populates="workflow_instance", cascade="all, delete-orphan",
        order_by="TaskInstance.created_at",
    )


# ---------------------------------------------------------------------------
# TaskInstance — a task within a running workflow instance
# ---------------------------------------------------------------------------

class TaskInstance(Base):
    __tablename__ = "task_instances"
    __table_args__ = (
        Index("ix_ti_workflow_instance", "workflow_instance_id"),
        Index("ix_ti_status", "status"),
        Index("ix_ti_assignee", "assignee_id"),
        Index("ix_ti_node_id", "node_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workflow_instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    node_label: Mapped[str | None] = mapped_column(String(255))
    task_type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, name="task_type"), nullable=False,
    )
    status: Mapped[TaskInstanceStatus] = mapped_column(
        Enum(TaskInstanceStatus, name="task_instance_status"),
        default=TaskInstanceStatus.pending,
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    assignee_type: Mapped[str | None] = mapped_column(String(50))
    input_data: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    output_data: Mapped[dict | None] = mapped_column(JSONB, default=dict)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    workflow_instance: Mapped["WorkflowInstance"] = relationship(
        back_populates="task_instances"
    )
