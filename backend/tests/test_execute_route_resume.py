"""Seam 3b (structural): the generated execute route must resolve a pending task
by entity and turn an Approve/Reject dispatch into a RESUME, and must NOT persist
the task inline (that now lives in triggerWorkflow, so persisting here too would
double-insert). We can't run the TS from this repo, so assert on the emitted text.
"""
from services.runtime_injector import _generate_workflow_api_route


def _route_text(tmp_path):
    _generate_workflow_api_route(tmp_path)
    return (tmp_path / "src" / "app" / "api" / "workflows" / "[id]" / "execute" / "route.ts").read_text(encoding="utf-8")


def test_route_resolves_pending_task_by_entity(tmp_path):
    t = _route_text(tmp_path)
    assert "__decision" in t
    assert "FROM workflow_tasks" in t and "status = 'pending'" in t
    assert "entity_id =" in t
    # builds the resume step markers from the resolved task's node_id
    assert "_completed`]" in t and "_decision`]" in t
    # merges the task's stored process variables
    assert "process_variables" in t


def test_route_no_longer_persists_task_inline(tmp_path):
    t = _route_text(tmp_path)
    # persistence moved into triggerWorkflow.persistPendingTask — the route must
    # not also INSERT (would double-persist on pause).
    assert "INSERT INTO workflow_tasks" not in t
    # still completes the resolved/explicit task
    assert "UPDATE workflow_tasks" in t and "status = 'completed'" in t
