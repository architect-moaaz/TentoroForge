"""State manager — manages workflow instance lifecycle and persistence."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.workflow_instance import (
    WorkflowInstance,
    WorkflowInstanceStatus,
    TaskInstance,
    TaskInstanceStatus,
    TaskType,
)


class StateManager:
    """Manages workflow instance state transitions and persistence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_instance(
        self,
        project_id: uuid.UUID,
        workflow_id: str,
        workflow_name: str,
        initiated_by: uuid.UUID | None = None,
        variables: dict | None = None,
    ) -> WorkflowInstance:
        instance = WorkflowInstance(
            project_id=project_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            status=WorkflowInstanceStatus.created,
            initiated_by=initiated_by,
            variables=variables or {},
            current_node_ids=[],
        )
        self.db.add(instance)
        await self.db.flush()
        return instance

    async def get_instance(self, instance_id: uuid.UUID) -> WorkflowInstance | None:
        result = await self.db.execute(
            select(WorkflowInstance).where(WorkflowInstance.id == instance_id)
        )
        return result.scalar_one_or_none()

    async def transition_instance(
        self,
        instance: WorkflowInstance,
        new_status: WorkflowInstanceStatus,
        error_message: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        instance.status = new_status
        instance.updated_at = now

        if new_status == WorkflowInstanceStatus.running and not instance.started_at:
            instance.started_at = now

        if new_status in (
            WorkflowInstanceStatus.completed,
            WorkflowInstanceStatus.failed,
            WorkflowInstanceStatus.cancelled,
        ):
            instance.completed_at = now

        if error_message:
            instance.error_message = error_message

        await self.db.flush()

    async def update_current_nodes(
        self, instance: WorkflowInstance, node_ids: list[str]
    ) -> None:
        instance.current_node_ids = node_ids
        await self.db.flush()

    async def set_variable(
        self, instance: WorkflowInstance, key: str, value: object
    ) -> None:
        variables = dict(instance.variables or {})
        variables[key] = value
        instance.variables = variables
        await self.db.flush()

    # -----------------------------------------------------------------------
    # Task instance management
    # -----------------------------------------------------------------------

    async def create_task(
        self,
        workflow_instance_id: uuid.UUID,
        node_id: str,
        node_label: str | None,
        task_type: TaskType,
        assignee_id: uuid.UUID | None = None,
        assignee_type: str | None = None,
        input_data: dict | None = None,
        due_at: datetime | None = None,
    ) -> TaskInstance:
        task = TaskInstance(
            workflow_instance_id=workflow_instance_id,
            node_id=node_id,
            node_label=node_label,
            task_type=task_type,
            status=TaskInstanceStatus.assigned if assignee_id else TaskInstanceStatus.pending,
            assignee_id=assignee_id,
            assignee_type=assignee_type,
            input_data=input_data or {},
            due_at=due_at,
        )
        self.db.add(task)
        await self.db.flush()
        return task

    async def get_task(self, task_id: uuid.UUID) -> TaskInstance | None:
        result = await self.db.execute(
            select(TaskInstance).where(TaskInstance.id == task_id)
        )
        return result.scalar_one_or_none()

    async def complete_task(
        self,
        task: TaskInstance,
        output_data: dict | None = None,
    ) -> None:
        task.status = TaskInstanceStatus.completed
        task.completed_at = datetime.now(timezone.utc)
        if output_data:
            task.output_data = output_data
        await self.db.flush()

    async def fail_task(
        self, task: TaskInstance, error_message: str
    ) -> None:
        task.status = TaskInstanceStatus.failed
        task.error_message = error_message
        task.completed_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def list_tasks_for_assignee(
        self,
        project_id: uuid.UUID,
        assignee_id: uuid.UUID,
        status_filter: list[TaskInstanceStatus] | None = None,
    ) -> list[TaskInstance]:
        q = (
            select(TaskInstance)
            .join(WorkflowInstance)
            .where(
                WorkflowInstance.project_id == project_id,
                TaskInstance.assignee_id == assignee_id,
            )
        )
        if status_filter:
            q = q.where(TaskInstance.status.in_(status_filter))

        q = q.order_by(TaskInstance.created_at.desc())
        result = await self.db.execute(q)
        return list(result.scalars().all())

    async def list_pending_tasks_for_instance(
        self, instance_id: uuid.UUID
    ) -> list[TaskInstance]:
        result = await self.db.execute(
            select(TaskInstance).where(
                TaskInstance.workflow_instance_id == instance_id,
                TaskInstance.status.in_([
                    TaskInstanceStatus.pending,
                    TaskInstanceStatus.assigned,
                    TaskInstanceStatus.active,
                ]),
            )
        )
        return list(result.scalars().all())

    async def cancel_pending_tasks(self, instance_id: uuid.UUID) -> None:
        await self.db.execute(
            update(TaskInstance)
            .where(
                TaskInstance.workflow_instance_id == instance_id,
                TaskInstance.status.in_([
                    TaskInstanceStatus.pending,
                    TaskInstanceStatus.assigned,
                    TaskInstanceStatus.active,
                ]),
            )
            .values(
                status=TaskInstanceStatus.cancelled,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await self.db.flush()
