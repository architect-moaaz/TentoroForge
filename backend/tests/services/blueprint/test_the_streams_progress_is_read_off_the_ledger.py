"""The Smith stream's progress comes from the run ledger, not from counting
executor calls.

Counting calls had three consequences a watcher saw at once: a fan-out node
was ticked at its first page, the nodes that are services rather than agent
calls never ticked, and the registry a reloaded page reads reported 23 of 19.
"""
from __future__ import annotations

from services import run_registry
from services.blueprint.run_progress import Progress


def _stream():
    events: list[tuple[str, dict]] = []
    return events, lambda event, data: events.append((event, data))


def test_a_fan_out_node_is_done_at_its_last_page_not_its_first():
    events, emit = _stream()
    progress = Progress(emit, total=2)

    progress({"event": "node:start", "node": "page_layouts", "subjects": 3})
    for i, page in enumerate(("PAGE-001", "PAGE-002", "PAGE-003"), start=1):
        progress({"event": "node:subject", "node": "page_layouts",
                  "subject": page, "index": i, "total": 3, "ok": True})
    assert [e for e, _ in events].count("node:done") == 0, "three pages, no node done yet"

    progress({"event": "node:done", "node": "page_layouts", "artifacts": 3})

    names = [e for e, _ in events]
    assert names == ["node:start", "node:subject", "node:subject", "node:subject", "node:done"]
    done = events[-1][1]
    assert done == {"node": "page_layouts", "nodesDone": 1, "nodesTotal": 2, "callsDone": 3}


def test_a_service_node_counts_like_any_other():
    """`apis` and `figma_design_system` are services: no executor call, so the
    old wrapper never saw them and the count could not reach the total."""
    events, emit = _stream()
    progress = Progress(emit, total=2)

    progress({"event": "node:start", "node": "apis", "subjects": 1})
    progress({"event": "node:done", "node": "apis", "artifacts": 1})

    assert events[-1] == ("node:done", {"node": "apis", "nodesDone": 1,
                                        "nodesTotal": 2, "callsDone": 1})


def test_the_ledgers_own_plan_line_is_not_forwarded():
    events, emit = _stream()
    Progress(emit, total=1)({"event": "plan", "nodes": ["apis"], "total": 1})
    assert events == []


def test_a_reloaded_page_gets_the_rows_and_the_ledgers_count():
    project = "proj-progress-test"
    run_registry.begin(project, phase="build")
    events, emit = _stream()
    progress = Progress(emit, total=2)

    run_registry.note(project, "plan", {"nodes": ["apis", "page_layouts"], "total": 2})
    progress({"event": "node:start", "node": "apis", "subjects": 1})
    progress({"event": "node:done", "node": "apis"})
    progress({"event": "node:start", "node": "page_layouts", "subjects": 15})
    for i in range(1, 5):
        progress({"event": "node:subject", "node": "page_layouts",
                  "subject": f"PAGE-{i:03d}", "index": i, "total": 15, "ok": True})
    for event, data in events:
        run_registry.note(project, event, data)

    snap = run_registry.snapshot(project)

    assert (snap["nodesDone"], snap["nodesTotal"], snap["callsDone"]) == (1, 2, 5)
    assert snap["nodes"] == [
        {"key": "apis", "state": "done", "calls": 0},
        {"key": "page_layouts", "state": "running", "calls": 4, "subject": "4 of 15"},
    ]
    run_registry.finish(project, "complete")
