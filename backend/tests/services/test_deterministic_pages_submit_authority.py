"""Tests for services.deterministic_pages.build_form_page honoring
page.submit.target when set.

Slice A T5. When submit.kind=workflow, the Form's props.workflow points
at the plan-declared workflow instead of the entity-derived CRUD name.
"""
from __future__ import annotations


def _find_form(node):
    if isinstance(node, dict):
        if (node.get("component") or node.get("type")) == "Form":
            return node
        for v in node.values():
            if isinstance(v, (dict, list)):
                r = _find_form(v)
                if r is not None:
                    return r
    elif isinstance(node, list):
        for i in node:
            r = _find_form(i)
            if r is not None:
                return r
    return None


def test_submit_target_workflow_overrides_crud_default():
    from services.deterministic_pages import build_form_page

    page = build_form_page(
        entity="Feedback", columns={"rating": {"type": "integer"}},
        route="/feedback/new", design_spec={},
        op="create",
        submit_target="SubmitFeedbackWorkflow",
    )
    form = _find_form(page)
    assert form["props"]["workflow"] == "SubmitFeedbackWorkflow"


def test_submit_target_omitted_falls_back_to_crud_default():
    from services.deterministic_pages import build_form_page

    page = build_form_page(
        entity="Feedback", columns={"rating": {"type": "integer"}},
        route="/feedback/new", design_spec={},
        op="create",   # no submit_target
    )
    form = _find_form(page)
    # Existing behaviour preserved — CreateFeedback CRUD workflow.
    assert form["props"]["workflow"] == "CreateFeedback"


def test_submit_target_works_on_edit():
    from services.deterministic_pages import build_form_page

    page = build_form_page(
        entity="Feedback", columns={"rating": {"type": "integer"}},
        route="/feedback/[id]/edit", design_spec={},
        op="edit",
        submit_target="EditFeedbackWorkflow",
    )
    form = _find_form(page)
    assert form["props"]["workflow"] == "EditFeedbackWorkflow"
