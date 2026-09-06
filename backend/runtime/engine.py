"""Workflow runtime engine — orchestrates workflow execution."""

import json
import uuid
import logging
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from models.workflow_instance import (
    WorkflowInstance,
    WorkflowInstanceStatus,
    TaskInstance,
    TaskInstanceStatus,
    TaskType,
)
from runtime.state_manager import StateManager
from runtime.gateway_controller import GatewayController
from runtime.task_executor import TaskExecutor
from runtime.assignment import AssignmentResolver
from runtime.execution_logger import ExecutionLogger
from runtime.variable_resolver import VariableResolver

logger = logging.getLogger(__name__)


class WorkflowRuntimeEngine:
    """Core workflow execution engine.

    Walks the node graph, creates task instances, handles gateways, and
    manages workflow lifecycle.

    State machine: created → running → waiting → completed/failed/cancelled
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.state = StateManager(db)
        self.gateway = GatewayController()
        self.assignment = AssignmentResolver(db)
        self.executor = TaskExecutor(db, self.state, self.assignment)
        self.exec_logger = ExecutionLogger(db)

    async def start_workflow(
        self,
        project_id: uuid.UUID,
        org_id: uuid.UUID,
        workflow_id: str,
        output_dir: str,
        initiated_by: uuid.UUID | None = None,
        variables: dict | None = None,
    ) -> WorkflowInstance:
        """Start a new workflow instance from a workflow definition."""
        definition = self._load_definition(output_dir, workflow_id)
        if not definition:
            raise ValueError(f"Workflow definition '{workflow_id}' not found")

        workflow_name = definition.get("name", workflow_id)
        nodes = definition.get("definition", {}).get("nodes", [])
        edges = definition.get("definition", {}).get("edges", [])

        if not nodes:
            raise ValueError(f"Workflow '{workflow_id}' has no nodes")

        # Create instance
        instance = await self.state.create_instance(
            project_id=project_id,
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            initiated_by=initiated_by,
            variables=variables,
        )

        # Transition to running
        await self.state.transition_instance(instance, WorkflowInstanceStatus.running)

        # Find start node(s)
        start_nodes = self._find_start_nodes(nodes, edges)
        if not start_nodes:
            await self.state.transition_instance(
                instance, WorkflowInstanceStatus.failed,
                error_message="No start node found in workflow definition",
            )
            await self.db.commit()
            return instance

        # Execute from start nodes
        await self._execute_nodes(
            instance=instance,
            node_ids=[n["id"] for n in start_nodes],
            nodes=nodes,
            edges=edges,
            project_id=project_id,
            org_id=org_id,
            workflow_id=workflow_id,
            initiator_person_id=initiated_by,
        )

        await self.db.commit()
        return instance

    async def complete_task(
        self,
        task_id: uuid.UUID,
        output_data: dict | None = None,
        output_dir: str | None = None,
    ) -> TaskInstance:
        """Complete a user task and advance the workflow."""
        task = await self.state.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        if task.status not in (TaskInstanceStatus.pending, TaskInstanceStatus.assigned, TaskInstanceStatus.active):
            raise ValueError(f"Task {task_id} is not in a completable state (status={task.status.value})")

        # Complete the task
        await self.state.complete_task(task, output_data)

        # Update workflow variables with task output
        instance = await self.state.get_instance(task.workflow_instance_id)
        if not instance:
            raise ValueError(f"Workflow instance for task {task_id} not found")

        if output_data:
            for key, value in output_data.items():
                await self.state.set_variable(instance, key, value)

        # Set previous variable for downstream nodes
        await self.state.set_variable(instance, "previous", {
            "node_id": task.node_id,
            "output": output_data,
        })

        # This node is no longer "active": drop it from current_node_ids. It was
        # only ever appended (when the blocking task was created) and never
        # removed, so every finished human-task node accumulated and stayed
        # painted amber/active in the simulator — including the final one after
        # the whole workflow completed.
        if task.node_id:
            remaining = [nid for nid in (instance.current_node_ids or []) if nid != task.node_id]
            await self.state.update_current_nodes(instance, remaining)

        # The blocking task parked the instance in `waiting`; completing it means
        # the run is moving again, so return it to `running` BEFORE advancing.
        # Otherwise the downstream drain reaches the completion guard while the
        # status is still the stale `waiting`, and the guard (which skips a
        # waiting instance so a genuinely-paused run isn't force-completed) would
        # leave a resumed human-task workflow stuck in `waiting` forever.
        if instance.status == WorkflowInstanceStatus.waiting:
            await self.state.transition_instance(instance, WorkflowInstanceStatus.running)

        # Try to advance the workflow
        if output_dir:
            definition = self._load_definition(output_dir, instance.workflow_id)
            if definition:
                nodes = definition.get("definition", {}).get("nodes", [])
                edges = definition.get("definition", {}).get("edges", [])

                # Find next nodes after this task's node
                next_node_ids = self._get_next_node_ids(task.node_id, edges)

                if next_node_ids:
                    await self._execute_nodes(
                        instance=instance,
                        node_ids=next_node_ids,
                        nodes=nodes,
                        edges=edges,
                        project_id=instance.project_id,
                        org_id=self._get_org_id_from_instance(instance),
                        workflow_id=instance.workflow_id,
                        initiator_person_id=instance.initiated_by,
                    )
                else:
                    # No next nodes — check if workflow is complete
                    await self._check_completion(instance)

        await self.db.commit()
        return task

    async def cancel_workflow(self, instance_id: uuid.UUID) -> WorkflowInstance:
        """Cancel a running workflow instance."""
        instance = await self.state.get_instance(instance_id)
        if not instance:
            raise ValueError(f"Workflow instance {instance_id} not found")

        if instance.status in (
            WorkflowInstanceStatus.completed,
            WorkflowInstanceStatus.cancelled,
        ):
            raise ValueError(f"Workflow is already {instance.status.value}")

        await self.state.cancel_pending_tasks(instance_id)
        await self.state.transition_instance(
            instance, WorkflowInstanceStatus.cancelled
        )
        await self.db.commit()
        return instance

    # -----------------------------------------------------------------------
    # Internal execution logic
    # -----------------------------------------------------------------------

    async def _execute_nodes(
        self,
        instance: WorkflowInstance,
        node_ids: list[str],
        nodes: list[dict],
        edges: list[dict],
        project_id: uuid.UUID,
        org_id: uuid.UUID,
        workflow_id: str,
        initiator_person_id: uuid.UUID | None = None,
    ) -> None:
        """Execute a set of nodes, handling gateways and task creation."""
        node_map = {n["id"]: n for n in nodes}
        completed_in_this_pass: set[str] = set()
        # Nodes we've already handled this pass. A node reached by two paths
        # (a `then`/`else` that reconverge, or two branches into a shared
        # "notify"/end node — present in 10 of the 12 vet workflows) MUST NOT
        # execute twice, and a loop-back edge must terminate rather than spin
        # forever. The one handler that legitimately re-enters — a parallel
        # join still waiting for a branch — discards itself below.
        processed: set[str] = set()
        to_process = list(node_ids)

        while to_process:
            current_id = to_process.pop(0)
            node = node_map.get(current_id)
            if not node:
                logger.warning("Node %s not found in definition", current_id)
                continue
            if current_id in processed:
                continue
            processed.add(current_id)

            node_type = node.get("type", "action")
            node_data = node.get("data", {})
            node_label = node_data.get("label", current_id)
            config = node_data.get("config", {})
            variables = instance.variables or {}

            # --- Execution logging: start ---
            log_entry = await self.exec_logger.log_start(
                instance_id=instance.id,
                node_id=current_id,
                node_type=node_type,
                node_label=node_label,
                input_snapshot={"variables_keys": list(variables.keys()), "config": config},
            )

            try:
                # Handle trigger nodes — seed trigger variables
                if node_type == "trigger":
                    await self.state.set_variable(instance, "trigger", variables.copy())
                    # Set previous for the next node
                    await self.state.set_variable(instance, "previous", {
                        "node_id": current_id,
                        "output": variables.copy(),
                    })
                    completed_in_this_pass.add(current_id)
                    await self.exec_logger.log_complete(log_entry, {"trigger_seeded": True})
                    next_ids = self._get_next_node_ids(current_id, edges)
                    to_process.extend(next_ids)
                    continue

                # Handle end nodes
                if node_type in ("end", "end_event"):
                    completed_in_this_pass.add(current_id)
                    await self.exec_logger.log_complete(log_entry, {"ended": True})
                    continue

                # Handle condition nodes — use then/else edge routing
                if node_type == "condition":
                    next_ids = self.gateway.resolve_condition_node(
                        node, edges, variables
                    )
                    completed_in_this_pass.add(current_id)
                    await self.exec_logger.log_complete(log_entry, {"branch_targets": next_ids})
                    to_process.extend(next_ids)
                    continue

                # Handle decision nodes — evaluate decision table and route
                if node_type == "decision":
                    config = node_data.get("config", {})
                    decision_table = config.get("decisionTable", {})

                    if decision_table:
                        from runtime.decision_evaluator import evaluate_decision_table

                        eval_result = evaluate_decision_table(decision_table, variables)

                        # Store outputs as workflow variables
                        outputs = eval_result.get("outputs")
                        if isinstance(outputs, dict):
                            for key, value in outputs.items():
                                await self.state.set_variable(instance, key, value)
                        await self.state.set_variable(instance, current_id, eval_result)
                        await self.state.set_variable(instance, "previous", {
                            "node_id": current_id,
                            "output": eval_result,
                        })

                        # Log the result
                        logger.info(
                            "Decision node %s: hit_policy=%s, matched=%d rules, outputs=%s",
                            current_id,
                            eval_result.get("hit_policy"),
                            len(eval_result.get("matched_rule_ids", [])),
                            outputs,
                        )

                    # Route via then/else edges based on whether rules matched
                    next_ids = self.gateway.resolve_decision_node(
                        node, edges, variables
                    )
                    completed_in_this_pass.add(current_id)
                    await self.exec_logger.log_complete(log_entry, {
                        "decision_result": eval_result if decision_table else None,
                        "branch_targets": next_ids,
                    })
                    to_process.extend(next_ids)
                    continue

                # Handle exclusive gateway (legacy format with edge.data.condition)
                if node_type == "exclusive_gateway":
                    next_ids = self.gateway.resolve_exclusive_gateway(
                        node, edges, variables
                    )
                    completed_in_this_pass.add(current_id)
                    await self.exec_logger.log_complete(log_entry, {"branch_targets": next_ids})
                    to_process.extend(next_ids)
                    continue

                # Handle AI decide nodes — execute AI, then route via then/else
                if node_type == "ai_decide":
                    from runtime.ai import get_ai_handler

                    handler = get_ai_handler("ai_decide", variables)
                    ai_output = await handler.execute(config)
                    decision = bool(ai_output.get("decision", True))

                    # Store AI output in variables
                    await self.state.set_variable(instance, current_id, ai_output)
                    await self.state.set_variable(instance, "previous", {
                        "node_id": current_id,
                        "output": ai_output,
                    })

                    # Route based on decision
                    next_ids = self.gateway.resolve_ai_decide_node(
                        node, edges, decision
                    )
                    completed_in_this_pass.add(current_id)
                    await self.exec_logger.log_complete(log_entry, ai_output)
                    to_process.extend(next_ids)
                    continue

                # Handle parallel gateway / fork / join
                if node_type in ("parallel_gateway", "fork", "join"):
                    # Check if this is a join (has multiple incoming edges)
                    incoming = [e for e in edges if e.get("target") == current_id]
                    if len(incoming) > 1:
                        # Join node — check if all incoming paths are complete
                        if not self.gateway.check_join_condition(
                            current_id, edges, completed_in_this_pass
                        ):
                            # Not all branches in yet — release the processed
                            # mark so the join is re-evaluated when the remaining
                            # branch re-queues it (otherwise the guard above would
                            # skip it forever and the join would never fire).
                            processed.discard(current_id)
                            await self.exec_logger.log_skip(
                                instance.id, current_id, node_type, node_label,
                                "Waiting for parallel paths to complete",
                            )
                            continue

                    next_ids = self.gateway.resolve_parallel_gateway(
                        node, edges, variables
                    )
                    completed_in_this_pass.add(current_id)
                    await self.exec_logger.log_complete(log_entry, {"parallel_targets": next_ids})
                    to_process.extend(next_ids)
                    continue

                if node_type == "event_gateway":
                    next_ids = self.gateway.resolve_event_gateway(
                        node, edges, variables
                    )
                    completed_in_this_pass.add(current_id)
                    await self.exec_logger.log_complete(log_entry, {"event_targets": next_ids})
                    to_process.extend(next_ids)
                    continue

                # Handle task nodes (user_task, service_task, action, ai_*, etc.)
                task = await self.executor.execute_node(
                    instance_id=instance.id,
                    project_id=project_id,
                    org_id=org_id,
                    workflow_id=workflow_id,
                    node=node,
                    variables=variables,
                    initiator_person_id=initiator_person_id,
                )

                if self.executor.is_blocking_task(task.task_type):
                    # Workflow waits for this task to be completed
                    await self.state.transition_instance(
                        instance, WorkflowInstanceStatus.waiting
                    )
                    # Track which nodes we're waiting at
                    current = list(instance.current_node_ids or [])
                    if current_id not in current:
                        current.append(current_id)
                    await self.state.update_current_nodes(instance, current)
                    await self.exec_logger.log_complete(log_entry, {
                        "task_id": str(task.id),
                        "task_type": task.task_type.value,
                        "blocking": True,
                    })
                else:
                    # Non-blocking task (service_task already completed)
                    # Store output as previous and node-specific variable
                    if task.output_data:
                        await self.state.set_variable(instance, current_id, task.output_data)
                        await self.state.set_variable(instance, "previous", {
                            "node_id": current_id,
                            "output": task.output_data,
                        })

                    completed_in_this_pass.add(current_id)
                    await self.exec_logger.log_complete(log_entry, {
                        "task_id": str(task.id),
                        "task_type": task.task_type.value,
                        "output": task.output_data,
                    })
                    next_ids = self._get_next_node_ids(current_id, edges)
                    to_process.extend(next_ids)

            except Exception as e:
                await self.exec_logger.log_failure(log_entry, str(e))
                logger.exception("Error executing node %s", current_id)
                # Per-node opt-in: continueOnError=true means downstream
                # nodes proceed as if this node produced null output. Fixes
                # the AC10-copy class where one failed extract kills the
                # whole workflow chain and mark_completed never runs. See
                # IRF-M4-T4 in docs/superpowers/plans/2026-08-11-intelligent-rich-forge.md.
                if node.get("continueOnError") or node_data.get("continueOnError"):
                    next_ids = self._get_next_node_ids(current_id, edges)
                    to_process.extend(next_ids)
                # Don't propagate — let other parallel paths continue
                continue

        # Completion: the pass drained with no pending tasks and nothing is
        # blocking. Complete regardless of whether an explicit end/end_event
        # node was hit — a fully-automated workflow (trigger → service action,
        # no end node) used to satisfy every completion precondition except the
        # end-node check and so stayed "running" forever, making the simulator
        # poll indefinitely. We still require that at least one node ran and the
        # instance isn't parked in `waiting` (a blocking task keeps a pending
        # task, so this branch isn't even entered in that case).
        if not await self.state.list_pending_tasks_for_instance(instance.id):
            if completed_in_this_pass and instance.status != WorkflowInstanceStatus.waiting:
                await self.state.transition_instance(
                    instance, WorkflowInstanceStatus.completed
                )
                return

    async def _check_completion(self, instance: WorkflowInstance) -> None:
        """Check if a workflow instance is complete (no pending tasks)."""
        pending = await self.state.list_pending_tasks_for_instance(instance.id)
        if not pending:
            await self.state.transition_instance(
                instance, WorkflowInstanceStatus.completed
            )

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _load_definition(self, output_dir: str, workflow_id: str) -> dict | None:
        # Load from the SAME place the list/editor/apply resolve by
        # (routers.workflows._workflows_path): the Blueprint projection writes
        # generated workflows to app/src/lib/workflows/definitions/<id>.json.
        # The engine previously only looked in the legacy <output_dir>/workflows
        # dir, so every simulate/start of a generated workflow failed with
        # "Workflow definition '<id>' not found". Prefer the projected dir; fall
        # back to the legacy dir for old projects.
        candidates = [
            Path(output_dir) / "app" / "src" / "lib" / "workflows"
                / "definitions" / f"{workflow_id}.json",
            Path(output_dir) / "workflows" / f"{workflow_id}.json",
        ]
        for wf_file in candidates:
            if wf_file.exists():
                try:
                    return json.loads(wf_file.read_text())
                except (json.JSONDecodeError, OSError):
                    return None
        return None

    def _find_start_nodes(self, nodes: list[dict], edges: list[dict]) -> list[dict]:
        """Find nodes with no incoming edges or type 'start'/'start_event'."""
        target_ids = {e.get("target") for e in edges}
        # A start node is an ENTRY point: it has no incoming edge. The trigger
        # TYPE alone is not sufficient — a workflow can have several trigger-typed
        # nodes chained (Start -> "form submitted" -> ...), and the old OR added
        # every trigger-typed node even when it had an incoming edge, so the graph
        # was entered twice and every downstream node executed (and logged) twice.
        start_nodes = [n for n in nodes if n.get("id") not in target_ids]
        return start_nodes or nodes[:1]

    def _get_next_node_ids(self, node_id: str, edges: list[dict]) -> list[str]:
        return [e["target"] for e in edges if e.get("source") == node_id]

    def _get_org_id_from_instance(self, instance: WorkflowInstance) -> uuid.UUID:
        """Get org_id from the project relationship.
        Falls back to a zero UUID if not loaded."""
        # Only read `project` when it is ALREADY loaded. Touching an unloaded
        # relationship here triggers a synchronous lazy-load in an async context
        # (MissingGreenlet). In the request path the project is eager-loaded, so
        # this returns the real org id; on any other path we fall back rather
        # than crash — which is exactly what the docstring already promises.
        from sqlalchemy import inspect as sa_inspect
        if "project" not in sa_inspect(instance).unloaded and instance.project:
            return instance.project.org_id
        return uuid.UUID(int=0)
