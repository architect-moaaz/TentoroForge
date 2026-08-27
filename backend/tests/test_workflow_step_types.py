"""#4 — the planner's declared per-step node_type is authoritative (keyword
classifier is only the fallback)."""
from services.workflow_generator import _resolve_step_node_type, _generate_from_step_dicts


def test_runtime_node_type_is_trusted():
    assert _resolve_step_node_type({"node_type": "approval"}, "whatever") == ("approval", None)
    assert _resolve_step_node_type({"node_type": "condition"}, "whatever") == ("condition", None)
    assert _resolve_step_node_type({"node_type": "ai_extract"}, "whatever") == ("ai_extract", None)


def test_action_type_maps_to_action_node():
    assert _resolve_step_node_type({"node_type": "db_query"}, "x") == ("action", "db_query")
    assert _resolve_step_node_type({"node_type": "send_notification"}, "x") == ("action", "send_notification")
    assert _resolve_step_node_type({"node_type": "generate_document"}, "x") == ("action", "generate_document")


def test_planner_alias_maps_to_runtime():
    assert _resolve_step_node_type({"node_type": "assignment"}, "x") == ("user_task", None)
    assert _resolve_step_node_type({"node_type": "task_pool"}, "x") == ("user_task", None)
    assert _resolve_step_node_type({"node_type": "escalation"}, "x") == ("action", None)


def test_falls_back_to_classifier_when_absent_or_invalid():
    # no node_type → keyword classification ("approve" → approval)
    nt, forced = _resolve_step_node_type({}, "Manager approves the request")
    assert nt == "approval" and forced is None
    # invalid node_type → keyword fallback
    nt2, _ = _resolve_step_node_type({"node_type": "flurb"}, "Validate the fields")
    assert nt2 == "condition"


def test_declared_type_beats_misleading_name():
    """A step named like a notification but typed as a condition trusts the type."""
    d = _generate_from_step_dicts(
        {"name": "W", "description": ""},
        [{"name": "Send eligibility check", "node_type": "condition"}],
        {},
    )
    step = d["definition"]["nodes"][1]
    assert step["type"] == "condition"  # not "action"/send_notification from the keyword


def test_end_to_end_uses_declared_types():
    d = _generate_from_step_dicts(
        {"name": "Loan Origination", "description": ""},
        [
            {"name": "Capture financials", "node_type": "user_task"},
            {"name": "Assess credit risk", "node_type": "ai_decide"},
            {"name": "Route for approval", "node_type": "approval"},
            {"name": "Record decision", "node_type": "db_insert"},
            {"name": "Notify borrower", "node_type": "send_email"},
        ],
        {},
    )
    types = [n["type"] for n in d["definition"]["nodes"] if n["id"].startswith("step_")]
    assert types == ["user_task", "ai_decide", "approval", "action", "action"]
    acts = [(n.get("data") or {}).get("config", {}).get("actionType") for n in d["definition"]["nodes"] if n["id"] in ("step_3", "step_4")]
    assert acts == ["db_insert", "send_email"]
