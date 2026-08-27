"""Workflow models — assignment policies for workflow steps."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class WorkflowAssignmentPolicy(Base):
    """Who handles which workflow tasks — maps workflow nodes to assignees."""

    __tablename__ = "workflow_assignment_policies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    workflow_id: Mapped[str] = mapped_column(String(255), nullable=False)
    node_id: Mapped[str] = mapped_column(String(255), nullable=False)
    assign_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # role, group, department, person, team, manager_of_requester, department_head, initiator, process_variable
    assign_target: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # entity ID or NULL for dynamic types like manager_of_requester, initiator
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    escalate_to: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # role name to escalate to
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    project = relationship("Project", backref="workflow_assignments")

    __table_args__ = (
        Index("idx_wf_assignment_project", "project_id"),
        Index("idx_wf_assignment_workflow", "project_id", "workflow_id"),
    )
