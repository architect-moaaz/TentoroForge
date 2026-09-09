"""Timer scheduler — background poller that completes expired wait tasks and checks SLAs."""

import asyncio
import re
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session
from models.workflow_instance import (
    WorkflowInstance,
    TaskInstance,
    TaskInstanceStatus,
    TaskType,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 15

# Duration parsing patterns
_DURATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(\d+)\s*(?:seconds?|s)\b", re.IGNORECASE), "seconds"),
    (re.compile(r"(\d+)\s*(?:minutes?|m)\b", re.IGNORECASE), "minutes"),
    (re.compile(r"(\d+)\s*(?:hours?|h)\b", re.IGNORECASE), "hours"),
    (re.compile(r"(\d+)\s*(?:days?|d)\b", re.IGNORECASE), "days"),
]


def parse_duration(duration_str: str) -> timedelta:
    """Parse a human-readable duration string into a timedelta.

    Supports: "30 seconds", "5 minutes", "1 hour", "2 days", "30s", "5m", "1h", "2d"
    """
    if not duration_str:
        return timedelta(hours=1)

    for pattern, unit in _DURATION_PATTERNS:
        match = pattern.search(duration_str)
        if match:
            value = int(match.group(1))
            return timedelta(**{unit: value})

    # Fallback: try to parse as a number of seconds
    try:
        return timedelta(seconds=int(duration_str))
    except (ValueError, TypeError):
        logger.warning("Could not parse duration '%s', defaulting to 1 hour", duration_str)
        return timedelta(hours=1)


class TimerScheduler:
    """Background scheduler that polls for expired timer tasks and SLA breaches."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background polling loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("TimerScheduler started (poll every %ds)", POLL_INTERVAL_SECONDS)

    async def stop(self) -> None:
        """Stop the background polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("TimerScheduler stopped")

    async def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                await self._check_expired_timers()
                await self._check_sla_breaches()
            except Exception:
                logger.exception("TimerScheduler poll error")
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _check_expired_timers(self) -> None:
        """Find timer tasks whose resume_at has passed and complete them."""
        async with async_session() as db:
            now = datetime.now(timezone.utc)

            result = await db.execute(
                select(TaskInstance).where(
                    TaskInstance.task_type == TaskType.timer_event,
                    TaskInstance.status.in_([
                        TaskInstanceStatus.pending,
                        TaskInstanceStatus.assigned,
                    ]),
                )
            )
            timer_tasks = list(result.scalars().all())

            for task in timer_tasks:
                resume_at_str = (task.input_data or {}).get("resume_at")
                if not resume_at_str:
                    continue

                try:
                    resume_at = datetime.fromisoformat(resume_at_str)
                except (ValueError, TypeError):
                    continue

                if now >= resume_at:
                    logger.info("Timer expired for task %s (node=%s), completing", task.id, task.node_id)
                    task.status = TaskInstanceStatus.completed
                    task.completed_at = now
                    task.output_data = {"timer_expired": True, "resume_at": resume_at_str}
                    await db.flush()

                    # Advance the workflow
                    await self._advance_workflow(db, task)

            await db.commit()

    async def _check_sla_breaches(self) -> None:
        """Find user tasks past their due_at and handle escalation."""
        async with async_session() as db:
            now = datetime.now(timezone.utc)

            result = await db.execute(
                select(TaskInstance).where(
                    TaskInstance.task_type == TaskType.user_task,
                    TaskInstance.status.in_([
                        TaskInstanceStatus.pending,
                        TaskInstanceStatus.assigned,
                        TaskInstanceStatus.active,
                    ]),
                    TaskInstance.due_at.isnot(None),
                    TaskInstance.due_at <= now,
                )
            )
            overdue_tasks = list(result.scalars().all())

            for task in overdue_tasks:
                escalation = (task.input_data or {}).get("config", {})
                escalate_to = escalation.get("escalateTo")

                if escalate_to:
                    logger.info(
                        "SLA breach for task %s (node=%s) — escalating to %s",
                        task.id, task.node_id, escalate_to,
                    )
                    # Mark escalation in input_data
                    input_data = dict(task.input_data or {})
                    input_data["sla_breached"] = True
                    input_data["escalated_to"] = escalate_to
                    task.input_data = input_data
                    await db.flush()

            await db.commit()

    async def _advance_workflow(self, db: AsyncSession, task: TaskInstance) -> None:
        """After completing a timer task, try to advance the workflow."""
        try:
            instance = await db.execute(
                select(WorkflowInstance).where(
                    WorkflowInstance.id == task.workflow_instance_id
                )
            )
            instance = instance.scalar_one_or_none()
            if not instance:
                return

            # Import here to avoid circular imports
            from runtime.engine import WorkflowRuntimeEngine
            from models.workflow_instance import WorkflowInstanceStatus

            engine = WorkflowRuntimeEngine(db)

            # Mirror complete_task on resume: the timer node is no longer active,
            # and a `waiting` instance must return to `running` before the drain
            # so the completion guard can fire (else the run stays waiting forever).
            if task.node_id:
                remaining = [nid for nid in (instance.current_node_ids or []) if nid != task.node_id]
                await engine.state.update_current_nodes(instance, remaining)
            if instance.status == WorkflowInstanceStatus.waiting:
                await engine.state.transition_instance(instance, WorkflowInstanceStatus.running)

            # Load definition to get edges
            # We need the output_dir from the project — use a helper query
            from models.project import Project
            project_result = await db.execute(
                select(Project).where(Project.id == instance.project_id)
            )
            project = project_result.scalar_one_or_none()
            if not project or not project.output_dir:
                return

            definition = engine._load_definition(project.output_dir, instance.workflow_id)
            if not definition:
                return

            nodes = definition.get("definition", {}).get("nodes", [])
            edges = definition.get("definition", {}).get("edges", [])

            next_node_ids = engine._get_next_node_ids(task.node_id, edges)
            if next_node_ids:
                await engine._execute_nodes(
                    instance=instance,
                    node_ids=next_node_ids,
                    nodes=nodes,
                    edges=edges,
                    project_id=instance.project_id,
                    org_id=engine._get_org_id_from_instance(instance),
                    workflow_id=instance.workflow_id,
                    initiator_person_id=instance.initiated_by,
                )
            else:
                await engine._check_completion(instance)

        except Exception:
            logger.exception("Failed to advance workflow after timer completion for task %s", task.id)
