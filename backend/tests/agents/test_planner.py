"""Tests for the planner agent's plan-shaping helpers. Focused on
deterministic post-processing (page-type annotation + entity inference);
LLM calls are not covered here.
"""
import pytest
from agents.planner import (
    _annotate_page_types,
    _infer_entity_for_page,
    _entity_summary_for_dashboard,
    run_planner_oneshot,
)


def test_annotates_routes_with_classifier_output():
    plan = {"pages": [
        {"route": "/", "name": "Home", "description": ""},
        {"route": "/login", "name": "Login", "description": ""},
        {"route": "/users/new", "name": "Create user", "description": "", "entity": "User"},
        {"route": "/users/[id]", "name": "User detail", "description": "", "entity": "User"},
        {"route": "/users", "name": "Users", "description": "Browse users", "entity": "User"},
    ]}
    out = _annotate_page_types(plan)
    types = [p["type"] for p in out["pages"]]
    assert types == ["dashboard", "auth", "form", "detail", "list"]


def test_preserves_explicit_type():
    """If a page already has a `type`, the annotator leaves it alone."""
    plan = {"pages": [{"route": "/x", "type": "custom"}]}
    out = _annotate_page_types(plan)
    assert out["pages"][0]["type"] == "custom"


def test_idempotent():
    """Running twice produces identical output."""
    plan = {"pages": [
        {"route": "/", "name": "Home"},
        {"route": "/login", "name": "Login"},
    ]}
    a = _annotate_page_types(plan)
    b = _annotate_page_types(dict(plan, pages=[dict(p) for p in plan["pages"]]))
    assert [p["type"] for p in a["pages"]] == [p["type"] for p in b["pages"]]


def test_handles_missing_pages_key():
    """No `pages` key — return plan unchanged."""
    plan = {"name": "Test"}
    out = _annotate_page_types(plan)
    assert out == plan


def test_handles_non_dict_input():
    """Defensive — never crash on weird inputs."""
    assert _annotate_page_types(None) is None
    assert _annotate_page_types([]) == []


def test_skips_malformed_page_entries():
    """Non-dict entries in pages list — skip them, don't crash."""
    plan = {"pages": [{"route": "/login"}, "garbage", None, 42]}
    out = _annotate_page_types(plan)
    assert out["pages"][0]["type"] == "auth"
    # malformed entries are left as-is (no crash)
    assert out["pages"][1] == "garbage"


# ── Entity inference helpers ────────────────────────────────────────────────

def test_infer_entity_from_route():
    """Route /leave-requests → LeaveRequest when that entity exists."""
    entities = ["LeaveRequest", "User", "LeaveBalance", "WorkflowTask"]
    page = {"route": "/leave-requests", "entity": "N/A"}
    assert _infer_entity_for_page(page, entities) == "LeaveRequest"


def test_infer_entity_exact_match_kept():
    """If entity is already a valid name, it is returned as-is."""
    entities = ["LeaveRequest", "User"]
    page = {"route": "/leave-requests", "entity": "LeaveRequest"}
    assert _infer_entity_for_page(page, entities) == "LeaveRequest"


def test_infer_entity_na_placeholder_cleared():
    """N/A / none / null entities return None when route doesn't match."""
    entities = ["LeaveRequest", "User"]
    for val in ["N/A", "none", "null", "unknown", "", "-"]:
        page = {"route": "/dashboard", "entity": val}
        assert _infer_entity_for_page(page, entities) is None, f"expected None for entity={val!r}"


def test_infer_entity_case_insensitive():
    """LLM sometimes capitalises differently — match case-insensitively."""
    entities = ["LeaveRequest"]
    page = {"route": "/x", "entity": "leaverequest"}
    assert _infer_entity_for_page(page, entities) == "LeaveRequest"


def test_entity_summary_for_dashboard():
    """Dashboard page with entity=None gets entity_summary = all entity names."""
    entities = ["LeaveRequest", "User", "LeaveBalance"]
    page = {"route": "/", "type": "dashboard", "entity": None}
    summary = _entity_summary_for_dashboard(page, entities)
    assert set(summary) == {"LeaveRequest", "User", "LeaveBalance"}


def test_entity_summary_empty_for_non_dashboard():
    """Non-dashboard entity-free pages should NOT get entity_summary."""
    entities = ["LeaveRequest", "User"]
    page = {"route": "/team", "type": "list", "entity": None}
    assert _entity_summary_for_dashboard(page, entities) == []


def test_annotate_page_types_infers_entity_from_route():
    """Full annotator: N/A entity on a leave-requests page gets inferred."""
    plan = {
        "entities": {"LeaveRequest": {}, "User": {}},
        "pages": [
            {"route": "/leave-requests", "name": "LeaveRequestsListPage", "entity": "N/A"},
            {"route": "/users/[id]", "name": "UserDetailPage", "entity": "N/A"},
        ],
    }
    out = _annotate_page_types(plan)
    assert out["pages"][0]["entity"] == "LeaveRequest"
    assert out["pages"][1]["entity"] == "User"


def test_annotate_page_types_dashboard_gets_entity_summary():
    """Dashboard page gets entity=None and entity_summary=[all entities]."""
    plan = {
        "entities": {"LeaveRequest": {}, "User": {}, "LeaveBalance": {}},
        "pages": [
            {"route": "/", "name": "Dashboard", "entity": "N/A"},
        ],
    }
    out = _annotate_page_types(plan)
    page = out["pages"][0]
    assert page["entity"] is None
    assert set(page["entity_summary"]) == {"LeaveRequest", "User", "LeaveBalance"}


def test_annotate_page_types_valid_entity_unchanged():
    """Pages with a valid entity field are not touched by inference."""
    plan = {
        "entities": {"LeaveRequest": {}},
        "pages": [
            {"route": "/leave-requests", "entity": "LeaveRequest"},
        ],
    }
    out = _annotate_page_types(plan)
    assert out["pages"][0]["entity"] == "LeaveRequest"
    assert "entity_summary" not in out["pages"][0]


def test_annotate_page_types_idempotent_with_entity_inference():
    """Running twice on a plan with N/A entities produces identical output."""
    plan = {
        "entities": {"LeaveRequest": {}},
        "pages": [
            {"route": "/leave-requests", "name": "LR", "entity": "N/A"},
            {"route": "/", "name": "Dashboard", "entity": "N/A"},
        ],
    }
    import copy
    a = _annotate_page_types(copy.deepcopy(plan))
    b = _annotate_page_types(copy.deepcopy(plan))
    assert a["pages"][0]["entity"] == b["pages"][0]["entity"]
    assert a["pages"][1].get("entity_summary") == b["pages"][1].get("entity_summary")


# ── run_planner_oneshot short-circuit ───────────────────────────────────────

@pytest.mark.asyncio
async def test_run_planner_oneshot_short_circuits_on_figma_driven_plan():
    """When prior_plan is _figma_driven, no LLM call should happen."""
    prior = {
        "_figma_driven": True,
        "pages": [
            {"route": "/login", "name": "Login"},
            {"route": "/dashboard", "name": "Dashboard"},
        ],
        "figma_url": "https://figma.com/design/X/Y",
        "name": "Test",
    }
    # Note: no ANTHROPIC_API_KEY set, no mocking — if this calls the LLM it
    # would raise RuntimeError. The short-circuit must return BEFORE the
    # api-key check.
    result = await run_planner_oneshot(description="ignored", prior_plan=prior)
    # Plan returned with page types annotated
    assert result["_figma_driven"] is True
    assert result["pages"][0]["type"] == "auth"
    assert result["pages"][1]["type"] == "dashboard"


@pytest.mark.asyncio
async def test_run_planner_oneshot_no_short_circuit_when_no_prior_plan():
    """Without prior_plan, the function must still attempt LLM call → raises
    RuntimeError when no API key is set."""
    import os
    saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            await run_planner_oneshot(description="test app")
    finally:
        if saved_key:
            os.environ["ANTHROPIC_API_KEY"] = saved_key


@pytest.mark.asyncio
async def test_run_planner_oneshot_no_short_circuit_when_prior_plan_lacks_marker():
    """If a prior_plan is supplied but it's NOT marked _figma_driven, fall
    through to the normal LLM path."""
    import os
    saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        # plan dict without _figma_driven flag — should NOT short-circuit
        non_figma_plan = {"pages": [{"route": "/x"}], "name": "x"}
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            await run_planner_oneshot(description="test app", prior_plan=non_figma_plan)
    finally:
        if saved_key:
            os.environ["ANTHROPIC_API_KEY"] = saved_key
