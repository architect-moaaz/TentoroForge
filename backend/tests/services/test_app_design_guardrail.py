# backend/tests/services/test_app_design_guardrail.py
from services.app_design_guardrail import normalize_app_design


def _plan(pages):
    return {"pages": pages}


def test_unknown_archetype_falls_back_to_type():
    plan, report = normalize_app_design(_plan([
        {"route": "/x", "type": "list", "archetype": "hologram", "features": []},
    ]))
    p = plan["pages"][0]
    assert p["archetype"] == "list"                 # fell back to page type
    assert report["pages"][0]["substituted"] == ("hologram", "list")


def test_known_archetype_passes_through():
    plan, report = normalize_app_design(_plan([
        {"route": "/t", "type": "list", "archetype": "kanban", "features": []},
    ]))
    assert plan["pages"][0]["archetype"] == "kanban"
    assert report["pages"][0]["substituted"] is None


def test_drops_unsupported_and_sp2_features():
    plan, report = normalize_app_design(_plan([
        {"route": "/r", "type": "list", "archetype": "report",
         "features": ["approval", "sla-escalation", "ghost"]},
    ]))
    assert plan["pages"][0]["features"] == ["approval"]
    assert set(report["pages"][0]["dropped_features"]) == {"sla-escalation", "ghost"}


def test_missing_archetype_uses_type():
    plan, _ = normalize_app_design(_plan([{"route": "/q", "type": "detail"}]))
    assert plan["pages"][0]["archetype"] == "detail"


def test_failure_leaves_plan_unchanged():
    # non-dict pages → returned as-is, no crash
    plan, report = normalize_app_design({"pages": "nope"})
    assert plan == {"pages": "nope"} and report["pages"] == []


def test_alias_resolves_to_known_archetype():
    plan, report = normalize_app_design(_plan([
        {"route": "/b", "type": "list", "archetype": "board", "features": []},
    ]))
    assert plan["pages"][0]["archetype"] == "kanban"
    assert report["pages"][0]["substituted"] == ("board", "kanban")


def test_planner_choices_flow_to_renderable_template():
    from services.page_type_templates import template_for
    # A "help desk"-style plan the planner might emit
    plan = {"pages": [
        {"route": "/tickets", "type": "list", "archetype": "inbox", "features": ["status-pipeline","sla-escalation"]},
        {"route": "/reports", "type": "list", "archetype": "analytics", "features": []},   # alias → report
        {"route": "/board", "type": "list", "archetype": "kanban", "features": []},
    ]}
    plan, report = normalize_app_design(plan)
    archetypes = [p["archetype"] for p in plan["pages"]]
    assert archetypes == ["inbox", "report", "kanban"]            # alias normalized
    assert plan["pages"][0]["features"] == ["status-pipeline"]    # sla-escalation (SP2) dropped
    # every chosen archetype has a real template
    for a in archetypes:
        assert "DO NOT use" in template_for(a)
