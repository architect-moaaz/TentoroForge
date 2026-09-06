"""A workflow is offered to the classifier by name; the id stays the only
spelling a page may carry.

Offered as bare ids, "Approve" had nothing to match against FLOW-009, so
in one fifteen-screen build not a single button ran a workflow. Each
vocabulary entry now reads "FLOW-009 — Refund Approval Decision: <trigger>";
the model may answer with the entry or the id, and the binding's target is
the id either way. An answer naming nothing in the vocabulary is nothing.
"""
import json

from services.figma_action_llm import classify_figma_action_llm

WORKFLOWS = ["FLOW-009 — Refund Approval Decision: Manager approves or rejects a refund case",
             "FLOW-010 — Add Case Note: Anyone adds a note to a case"]


def _model(reply):
    return lambda _system, _user: json.dumps(reply)


def test_the_target_is_the_id_when_the_model_answers_with_the_entry():
    b = classify_figma_action_llm("Approve", available_routes=["/cases"], available_workflows=WORKFLOWS,
                                  query_fn=_model({"kind": "workflow", "target": WORKFLOWS[0], "confidence": 0.9}))
    assert (b.kind, b.target) == ("workflow", "FLOW-009")


def test_the_target_is_the_id_when_the_model_answers_with_the_id():
    b = classify_figma_action_llm("Approve", available_routes=["/cases"], available_workflows=WORKFLOWS,
                                  query_fn=_model({"kind": "workflow", "target": "FLOW-009", "confidence": 0.9}))
    assert (b.kind, b.target) == ("workflow", "FLOW-009")


def test_a_name_alone_is_not_a_spelling_a_page_may_carry():
    """The name is for matching; only the id resolves downstream."""
    b = classify_figma_action_llm("Approve", available_routes=["/cases"], available_workflows=WORKFLOWS,
                                  query_fn=_model({"kind": "workflow", "target": "Refund Approval Decision", "confidence": 0.9}))
    assert b.kind == "none"


def test_an_invented_workflow_is_nothing():
    b = classify_figma_action_llm("Approve", available_routes=["/cases"], available_workflows=WORKFLOWS,
                                  query_fn=_model({"kind": "workflow", "target": "FLOW-042", "confidence": 0.9}))
    assert b.kind == "none"


def test_the_model_is_shown_the_names():
    seen = {}
    def q(system, user):
        seen["user"] = user; return json.dumps({"kind": "none", "target": None, "confidence": 0})
    classify_figma_action_llm("Approve", available_routes=[], available_workflows=WORKFLOWS, query_fn=q)
    assert "Refund Approval Decision" in seen["user"]


def test_the_composer_offers_name_and_trigger_with_the_id():
    from services.blueprint import figma_layout
    from services.figma_llm_ctx import get_workflows, reset_figma_llm_context
    doc = {"pages": [{"route": "/cases"}], "workflows": [
        {"id": "FLOW-009", "name": "Refund Approval Decision", "trigger": {"kind": "manual", "detail": "Manager approves"}}]}
    figma_layout._set_action_vocabulary(doc)
    try:
        assert list(get_workflows()) == ["FLOW-009 — Refund Approval Decision: Manager approves"]
    finally:
        reset_figma_llm_context()
