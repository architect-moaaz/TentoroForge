"""End-to-end runtime lifecycle: a human-task workflow must reach `completed`.

Regression guard for the completion bug where a workflow that pauses at a
blocking task (user_task/approval/...) was left in `waiting` forever after the
task was completed — the completion guard skipped the instance because
complete_task never returned it to `running`.
"""
import json
import uuid
from pathlib import Path

import pytest

from database import async_session
from models.workflow_instance import WorkflowInstanceStatus, TaskInstanceStatus
from runtime.engine import WorkflowRuntimeEngine


def _node(nid, ntype, config=None, label=None):
    return {"id": nid, "type": ntype,
            "data": {"label": label or nid, "nodeType": ntype, "config": config or {}}}


def _write_def(output_dir: Path, wf_id: str, nodes, edges):
    d = output_dir / "app" / "src" / "lib" / "workflows" / "definitions"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{wf_id}.json").write_text(json.dumps({
        "id": wf_id, "name": wf_id,
        "definition": {"nodes": nodes, "edges": edges, "trigger": {"type": "manual"}, "steps": []},
    }))


@pytest.mark.asyncio
async def test_human_task_workflow_completes(test_db, tmp_path):
    wf_id = "human-task-wf"
    nodes = [
        _node("trigger", "trigger"),
        _node("review", "user_task", label="Review"),
        _node("notify", "action", {"actionType": "set_variable", "variableName": "done", "expression": "1"}),
        _node("end", "end"),
    ]
    edges = [
        {"source": "trigger", "target": "review"},
        {"source": "review", "target": "notify"},
        {"source": "notify", "target": "end"},
    ]
    _write_def(tmp_path, wf_id, nodes, edges)
    project_id, org_id = uuid.uuid4(), uuid.uuid4()

    # A Project row so complete_task's org-id lookup resolves instance.project
    # (in the app the project is always eager-loaded in the request session).
    from models.project import Project
    async with async_session() as db:
        db.add(Project(id=project_id, org_id=org_id, name="T", owner_id=uuid.uuid4()))
        await db.commit()

    async with async_session() as db:
        engine = WorkflowRuntimeEngine(db)
        started = await engine.start_workflow(
            project_id=project_id, org_id=org_id, workflow_id=wf_id,
            output_dir=str(tmp_path), variables={})
        instance_id = started.id
        fresh = await engine.state.get_instance(instance_id)
        # Paused at the blocking human task.
        assert fresh.status == WorkflowInstanceStatus.waiting
        assert "review" in (fresh.current_node_ids or [])
        pending = await engine.state.list_pending_tasks_for_instance(instance_id)
        assert len(pending) == 1
        task_id = pending[0].id
        # The task carries a form hint so the UI can render the right form
        # (the ORIGINAL node type, since every human node collapses to user_task).
        assert (pending[0].input_data or {}).get("node_type") == "user_task"

    async with async_session() as db:
        # Load the project into the session (identity map) so instance.project
        # resolves without an async lazy-load — mirrors get_project_with_auth.
        await db.get(Project, project_id)
        engine = WorkflowRuntimeEngine(db)
        await engine.complete_task(task_id, output_data={"approved": True}, output_dir=str(tmp_path))
        refreshed = await engine.state.get_instance(instance_id)
        # The downstream action + end must run and the run must COMPLETE.
        final_status = refreshed.status
        final_nodes = list(refreshed.current_node_ids or [])
        assert final_status == WorkflowInstanceStatus.completed, \
            f"expected completed, got {final_status}"
        # The finished task node is no longer painted active.
        assert "review" not in final_nodes


@pytest.mark.asyncio
async def test_automated_workflow_with_end_completes(test_db, tmp_path):
    wf_id = "auto-wf"
    nodes = [
        _node("trigger", "trigger"),
        _node("act", "action", {"actionType": "set_variable", "variableName": "x", "expression": "1"}),
        _node("end", "end"),
    ]
    edges = [{"source": "trigger", "target": "act"}, {"source": "act", "target": "end"}]
    _write_def(tmp_path, wf_id, nodes, edges)

    async with async_session() as db:
        engine = WorkflowRuntimeEngine(db)
        instance = await engine.start_workflow(
            project_id=uuid.uuid4(), org_id=uuid.uuid4(), workflow_id=wf_id,
            output_dir=str(tmp_path), variables={})
        refreshed = await engine.state.get_instance(instance.id)
        assert refreshed.status == WorkflowInstanceStatus.completed


@pytest.mark.asyncio
async def test_parallel_join_with_blocking_task_completes(test_db, tmp_path):
    """A fork whose branches finish in DIFFERENT passes (one branch has a human
    task) must still join and complete — the join bookkeeping is durable across
    passes, and it must NOT fire early while the human branch is still pending."""
    wf_id = "parallel-wf"
    nodes = [
        _node("trigger", "trigger"),
        _node("fork", "parallel_gateway"),
        _node("A", "action", {"actionType": "set_variable", "variableName": "a", "expression": "1"}),
        _node("B", "user_task", label="Review"),
        _node("join", "join"),
        _node("end", "end"),
    ]
    edges = [
        {"source": "trigger", "target": "fork"},
        {"source": "fork", "target": "A"},
        {"source": "fork", "target": "B"},
        {"source": "A", "target": "join"},
        {"source": "B", "target": "join"},
        {"source": "join", "target": "end"},
    ]
    _write_def(tmp_path, wf_id, nodes, edges)

    async with async_session() as db:
        engine = WorkflowRuntimeEngine(db)
        started = await engine.start_workflow(
            project_id=uuid.uuid4(), org_id=uuid.uuid4(), workflow_id=wf_id,
            output_dir=str(tmp_path), variables={})
        instance_id = started.id
        fresh = await engine.state.get_instance(instance_id)
        # Branch A ran; branch B paused at the human task. The join has NOT fired.
        assert fresh.status == WorkflowInstanceStatus.waiting
        pending = await engine.state.list_pending_tasks_for_instance(instance_id)
        assert len(pending) == 1
        task_id = pending[0].id

    async with async_session() as db:
        engine = WorkflowRuntimeEngine(db)
        await engine.complete_task(task_id, output_data={"approved": True}, output_dir=str(tmp_path))
        refreshed = await engine.state.get_instance(instance_id)
        # Both branches are now in — the join fires and the run completes.
        assert refreshed.status == WorkflowInstanceStatus.completed, \
            f"expected completed, got {refreshed.status}"
