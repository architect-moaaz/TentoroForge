"""Task executor — executes different task types within a workflow."""

import uuid
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from models.workflow_instance import TaskInstance, TaskInstanceStatus, TaskType
from runtime.state_manager import StateManager
from runtime.assignment import AssignmentResolver
from runtime.timer_scheduler import parse_duration

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Executes workflow tasks based on their type."""

    def __init__(
        self,
        db: AsyncSession,
        state_manager: StateManager,
        assignment_resolver: AssignmentResolver,
    ):
        self.db = db
        self.state = state_manager
        self.assignment = assignment_resolver

    async def execute_node(
        self,
        instance_id: uuid.UUID,
        project_id: uuid.UUID,
        org_id: uuid.UUID,
        workflow_id: str,
        node: dict,
        variables: dict,
        initiator_person_id: uuid.UUID | None = None,
    ) -> TaskInstance:
        """Execute a workflow node — creates a TaskInstance and processes it."""
        node_id = node["id"]
        node_data = node.get("data", {})
        node_type = node.get("type", "action")
        node_label = node_data.get("label", node_id)
        config = node_data.get("config", {})

        task_type = self._classify_task_type(node_type, config)

        # Resolve assignment (skip for service tasks and timer events)
        assignee_id = None
        assignee_type = None
        if task_type == TaskType.user_task:
            assign_type = config.get("assignType")

            # Task pool nodes: leave assignee_id as None, set assignee_type to "pool"
            if node_type == "task_pool":
                assignee_type = "pool"
            elif assign_type == "initiator":
                # Assign directly to the workflow initiator
                assignee_id = initiator_person_id
                assignee_type = "initiator"
            elif assign_type == "process_variable":
                # Resolve the variable path to a concrete person ID
                variable_path = config.get("assignVariablePath", "")
                if variable_path:
                    from runtime.variable_resolver import VariableResolver
                    resolver = VariableResolver(variables)
                    resolved = resolver.resolve_string(variable_path)
                    if resolved and resolved != variable_path:
                        try:
                            assignee_id = uuid.UUID(resolved)
                        except (ValueError, AttributeError):
                            logger.warning("process_variable resolved to non-UUID: %s", resolved)
                assignee_type = "process_variable"
            else:
                assignee_id, assignee_type = await self.assignment.resolve(
                    project_id=project_id,
                    org_id=org_id,
                    workflow_id=workflow_id,
                    node_id=node_id,
                    initiator_person_id=initiator_person_id,
                )

        # Calculate due date from SLA
        due_at = None
        sla_hours = config.get("slaHours")
        if sla_hours:
            due_at = datetime.now(timezone.utc) + timedelta(hours=int(sla_hours))

        input_data = {"variables": variables, "config": config}

        # Form hints for the task UI (simulator + inbox). Every human node
        # collapses to TaskType.user_task, so without the ORIGINAL node type the
        # UI cannot tell an approval (approve/reject) from a data-entry task and
        # falls back to a raw JSON box. Also surface the node's declared form
        # fields as `expectedOutputs` so a data-entry task renders typed fields.
        input_data["node_type"] = node_type
        form_fields = (config.get("formBinding") or {}).get("fields")
        if not isinstance(form_fields, list):
            form_fields = config.get("expectedOutputs")
        if isinstance(form_fields, list) and form_fields:
            declared = []
            for f in form_fields:
                if not isinstance(f, dict):
                    continue
                fname = f.get("name") or f.get("key") or f.get("label")
                if fname:
                    declared.append({"name": fname, "type": f.get("type") or "string"})
            if declared:
                input_data["expectedOutputs"] = declared

        # For timer events, compute resume_at
        if task_type == TaskType.timer_event:
            duration_str = config.get("duration", "1 hour")
            resume_at = datetime.now(timezone.utc) + parse_duration(duration_str)
            input_data["resume_at"] = resume_at.isoformat()

        task = await self.state.create_task(
            workflow_instance_id=instance_id,
            node_id=node_id,
            node_label=node_label,
            task_type=task_type,
            assignee_id=assignee_id,
            assignee_type=assignee_type,
            input_data=input_data,
            due_at=due_at,
        )

        logger.info(
            "Created task %s (type=%s) for node %s [%s], assigned to %s",
            task.id, task_type.value, node_id, node_type, assignee_id,
        )

        # Auto-execute service tasks immediately
        if task_type == TaskType.service_task:
            await self._execute_service_task(task, node_type, config, variables)

        return task

    async def _execute_service_task(
        self, task: TaskInstance, node_type: str, config: dict, variables: dict
    ) -> None:
        """Execute a service task automatically using action dispatchers."""
        try:
            # Check if this is an AI node type
            if node_type.startswith("ai_"):
                await self._execute_ai_task(task, node_type, config, variables)
                return

            action_type = config.get("actionType", "custom")
            logger.info("Auto-executing service task %s: %s", task.id, action_type)

            from runtime.actions import get_dispatcher

            dispatcher = get_dispatcher(action_type, self.db, variables)
            output = await dispatcher.execute(config)

            await self.state.complete_task(task, output_data=output)

        except Exception as e:
            logger.error("Service task %s failed: %s", task.id, e)
            await self.state.fail_task(task, str(e))

    async def _execute_ai_task(
        self, task: TaskInstance, node_type: str, config: dict, variables: dict
    ) -> None:
        """Execute an AI node task using AI handlers."""
        try:
            from runtime.ai import get_ai_handler

            handler = get_ai_handler(node_type, variables)
            output = await handler.execute(config)

            logger.info("AI task %s (%s) completed: %s", task.id, node_type, output.get("output"))

            await self.state.complete_task(task, output_data=output)

        except Exception as e:
            logger.error("AI task %s (%s) failed: %s", task.id, node_type, e)
            await self.state.fail_task(task, str(e))

    def _classify_task_type(self, node_type: str, config: dict) -> TaskType:
        """Map node type from workflow definition to TaskType enum."""
        # Trigger nodes act as service tasks (auto-complete)
        if node_type == "trigger":
            return TaskType.service_task

        # Human-in-loop task types
        if node_type in ("assignment", "approval", "user_task"):
            return TaskType.user_task

        # Task pool — user task but unassigned (claimable)
        if node_type == "task_pool":
            return TaskType.user_task

        # Escalation — creates a user task with escalation metadata
        if node_type == "escalation":
            return TaskType.user_task

        # AI node types — auto-execute as service tasks
        if node_type.startswith("ai_"):
            return TaskType.service_task

        # Action / automation nodes
        if node_type in ("action", "service_task", "automation"):
            return TaskType.service_task

        # Timer / wait nodes
        if node_type in ("wait", "timer", "timer_event"):
            return TaskType.timer_event

        # Gateway types
        if node_type in ("condition", "gateway", "exclusive_gateway", "parallel_gateway", "decision"):
            return TaskType.gateway

        return TaskType.user_task

    def is_blocking_task(self, task_type: TaskType) -> bool:
        """Whether a task type blocks workflow progression until completed."""
        return task_type in (TaskType.user_task, TaskType.timer_event)
