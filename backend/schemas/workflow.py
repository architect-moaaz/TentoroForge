"""Pydantic schemas for workflow endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Workflow Definitions (JSON stored in project files)
# ---------------------------------------------------------------------------

class WorkflowSave(BaseModel):
    """Save a workflow definition (JSON blob) to the project."""
    id: str
    name: str
    description: str | None = None
    processVariables: list[dict] | None = None  # Process variables flowing through workflow
    definition: dict  # Full workflow definition (nodes, edges, trigger, etc.)
    # Optimistic-concurrency token (register A15-1). The client echoes back the
    # `version` it last read; the server refuses the write if the file moved on
    # in between. Optional so existing callers keep working — but a caller that
    # omits it is explicitly choosing last-write-wins.
    version: str | None = None


class WorkflowListItem(BaseModel):
    id: str
    name: str
    description: str | None
    trigger_type: str | None
    step_count: int


# ---------------------------------------------------------------------------
# Workflow Assignment Policies
# ---------------------------------------------------------------------------

class AssignmentPolicyCreate(BaseModel):
    workflow_id: str
    node_id: str
    assign_type: str  # role, group, department, person, team, manager_of_requester, department_head, initiator, process_variable
    assign_target: str | None = None
    sla_hours: int | None = None
    escalate_to: str | None = None


class AssignmentPolicyUpdate(BaseModel):
    assign_type: str | None = None
    assign_target: str | None = None
    sla_hours: int | None = None
    escalate_to: str | None = None


class AssignmentPolicyResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    workflow_id: str
    node_id: str
    assign_type: str
    assign_target: str | None
    sla_hours: int | None
    escalate_to: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Workflow Runtime — Instances & Tasks
# ---------------------------------------------------------------------------

class WorkflowStartRequest(BaseModel):
    workflow_id: str
    variables: dict | None = None
    initiated_by: uuid.UUID | None = None


class TaskCompleteRequest(BaseModel):
    output_data: dict | None = None


class WorkflowInstanceResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    workflow_id: str
    workflow_name: str
    status: str
    current_node_ids: list[str] | None
    variables: dict | None
    initiated_by: uuid.UUID | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskInstanceResponse(BaseModel):
    id: uuid.UUID
    workflow_instance_id: uuid.UUID
    node_id: str
    node_label: str | None
    task_type: str
    status: str
    assignee_id: uuid.UUID | None
    assignee_type: str | None
    input_data: dict | None
    output_data: dict | None
    due_at: datetime | None
    completed_at: datetime | None
    error_message: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowInstanceDetailResponse(WorkflowInstanceResponse):
    tasks: list[TaskInstanceResponse] = []


class NodeExecutionLogResponse(BaseModel):
    id: uuid.UUID
    workflow_instance_id: uuid.UUID
    node_id: str
    node_type: str
    node_label: str | None
    status: str
    input_snapshot: dict | None
    output_snapshot: dict | None
    error_message: str | None
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None

    model_config = {"from_attributes": True}
