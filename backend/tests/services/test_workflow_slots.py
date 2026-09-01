"""Create pages get a workflow to submit to.

Measured on a fresh 53-page build: eleven pages whose entire job is to create
something, thirty-five workflows authored, and not one plain create among
them. Sixteen of twenty-seven refused pages were the two things left to the
composer — invent a name, or leave the button dead:

    /documents/new   targets workflow 'createDocument', which this application
                     does not define
    /committees/new  Form 'Form' declares no action — it would do nothing

The thirty-five are good workflows. They are the processes the requirements
describe, which is exactly what the agent was asked for. Nothing asked whether
the pages that exist can do anything.
"""
from __future__ import annotations

from services.blueprint.workflow_slots import (
    workflow_slot_prompt, workflow_slots,
)


def _doc(pages, workflows=()):
    return {"pages": list(pages), "workflows": list(workflows)}


def _page(route, pid="PAGE-001", pattern="form", **kw):
    return {"id": pid, "route": route, "name": route, "pattern": pattern, **kw}


def _flow(fid, pages, kind="manual"):
    return {"id": fid, "name": fid, "trigger": {"kind": kind},
            "launchedFrom": list(pages)}


def test_a_create_page_with_nothing_to_call_is_a_slot():
    slots = workflow_slots(_doc([_page("/committees/new", "PAGE-024")]))
    assert [s["route"] for s in slots] == ["/committees/new"]


def test_a_page_a_workflow_already_launches_from_is_not():
    """Six of the eleven were already served by a lifecycle workflow — "Raise a
    Motion" launches from /motions/new. Listing those would ask for a second
    workflow doing the same job."""
    doc = _doc([_page("/motions/new", "PAGE-011")],
               [_flow("FLOW-010", ["PAGE-011"])])
    assert workflow_slots(doc) == []


def test_the_route_serves_as_the_key_too():
    """`launchedFrom` is page ids in the contract, and prose elsewhere names
    routes. Either should count as served rather than asking twice."""
    doc = _doc([_page("/motions/new", "PAGE-011")],
               [_flow("FLOW-010", ["/motions/new"])])
    assert workflow_slots(doc) == []


def test_only_a_manual_workflow_serves_a_page():
    """A scheduled or event-driven workflow is not something a button starts,
    so a page whose only workflow is one of those still has a dead control."""
    doc = _doc([_page("/committees/new", "PAGE-024")],
               [_flow("FLOW-028", ["PAGE-024"], kind="schedule")])
    assert [s["route"] for s in workflow_slots(doc)] == ["/committees/new"]


def test_a_page_that_does_not_submit_is_never_a_slot():
    """An entity list has nothing to submit; asking for a workflow per page
    would author thirty of them nobody calls."""
    doc = _doc([_page("/committees", "PAGE-023", pattern="entity_list"),
                _page("/sittings/[id]", "PAGE-005", pattern="record_workspace")])
    assert workflow_slots(doc) == []


def test_a_wizard_submits_too():
    doc = _doc([_page("/committees/new", "PAGE-024", pattern="wizard")])
    assert len(workflow_slots(doc)) == 1


def test_a_deprecated_page_is_not_asked_for():
    doc = _doc([_page("/old/new", "PAGE-099", status="DEPRECATED")])
    assert workflow_slots(doc) == []


def test_nothing_is_said_when_every_page_is_served():
    """The prompt is empty rather than a paragraph explaining that there is
    nothing to do — an agent given a section about zero pages spends attention
    on it."""
    doc = _doc([_page("/motions/new", "PAGE-011")],
               [_flow("FLOW-010", ["PAGE-011"])])
    assert workflow_slot_prompt(doc) == ""


def test_declining_is_still_allowed():
    """A page can legitimately be a draft nobody submits. The slot makes the
    decision deliberate; it does not force a workflow into existence."""
    said = workflow_slot_prompt(_doc([_page("/committees/new", "PAGE-024")]))
    assert "leave it alone deliberately" in said
    assert "Decline it because you decided to" in said


def test_the_prompt_says_where_the_id_must_go():
    """`launchedFrom` is what `build_domain_context` filters on to tell the
    composer which workflows a page launches. A workflow authored without it
    serves nobody."""
    said = workflow_slot_prompt(_doc([_page("/committees/new", "PAGE-024")]))
    assert "launchedFrom" in said


def test_the_workflows_node_is_handed_the_slots():
    import inspect

    from services.blueprint import executors

    src = inspect.getsource(executors)
    assert 'if node == "workflows":' in src
    assert "workflow_slot_prompt(doc)" in src
