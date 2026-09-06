"""§73 — would the application described actually work?"""

from services.blueprint.functional_completeness import functional_findings


def _doc(root, sources=None, workflows=("FLOW-001",)):
    return {
        "pages": [{"id": "PAGE-001", "route": "/plants"}],
        "workflows": [{"id": w, "name": w} for w in workflows],
        "pageLayouts": [{"page": "PAGE-001", "root": root,
                         "dataSources": [{"name": n} for n in (sources or [])]}],
    }


def _rules(doc):
    return sorted(f["rule"] for f in functional_findings(doc))


def test_a_control_with_no_action_is_a_defect():
    """Five buttons on one generated page carried a label and nothing else.
    They render, they are clickable, and nothing happens — indistinguishable
    from a broken application, with no error to diagnose from."""
    doc = _doc({"type": "Button", "props": {"label": "Mark Watered Today"}})
    assert _rules(doc) == ["control-without-action"]
    assert "would do nothing" in functional_findings(doc)[0]["detail"]


def test_a_control_that_acts_is_fine():
    for prop, value in (("workflow", "FLOW-001"), ("navigate", "/x"),
                        ("submit", True), ("opensDialog", "d")):
        button = {"type": "Button", "props": {"label": "Go", prop: value}}
        # A dialog target must exist on the page — five real buttons opened
        # dialogs by id that no node carried, and did nothing.
        node = ({"type": "Stack", "props": {}, "children": [
                    button, {"id": "d", "type": "Dialog", "props": {"title": "Go"}, "children": []}]}
                if prop == "opensDialog" else button)
        doc = _doc(node)
        assert _rules(doc) == [], prop


def test_a_workflow_that_does_not_exist_is_caught_at_any_depth():
    """`Table.rowActions[0].workflow` is where an invented id shipped; a check
    that reads one key walks past it."""
    doc = _doc({"type": "Table", "props": {
        "rows": "{{plants}}",
        "rowActions": [{"label": "Mark", "workflow": "markPlantWatered"}]}},
        sources=["plants"])
    assert _rules(doc) == ["workflow-not-defined"]


def test_a_binding_with_no_source_is_caught():
    """`{{overdue.value}}` with no `overdue` source renders the template text
    itself to whoever opens the page."""
    doc = _doc({"type": "Stat", "props": {"value": "{{overdue.value}}"}})
    assert _rules(doc) == ["binding-without-source"]


def test_a_bound_source_is_fine():
    doc = _doc({"type": "Table", "props": {"rows": "{{plants}}"}},
               sources=["plants"])
    assert _rules(doc) == []


def test_a_page_nothing_composed_is_caught():
    """The Blueprint still claims the page exists, and every consumer believes
    it — while the route 404s."""
    doc = _doc({"type": "Stack"})
    doc["pageLayouts"] = []
    assert _rules(doc) == ["page-not-composed"]


def test_findings_nest_through_children():
    doc = _doc({"type": "Stack", "children": [
        {"type": "Row", "children": [
            {"type": "Button", "props": {"label": "Deep"}}]}]})
    assert _rules(doc) == ["control-without-action"]


def test_the_action_list_comes_from_the_composer_contract():
    """Hand-listing them is how `opensDialog` came to be refused on a page
    whose create form was a modal — the list held four of the six offered."""
    from services.blueprint.functional_completeness import _action_props

    assert {"workflow", "navigate", "submit", "onClick",
            "opensDialog", "togglesSidebar"} <= _action_props()


# ---------------------------------------------------------------------------
# The findings are rejections, not a report.
# ---------------------------------------------------------------------------

def _proposal(root):
    from services.blueprint.executors import AgentResult, ArtifactProposal

    return AgentResult(
        task_id="t", agent="a2ui_pages", status="completed",
        proposals=[ArtifactProposal(
            section="pageLayouts", natural_key="PAGE-001",
            body={"page": "PAGE-001", "root": root})],
    )


def test_a_dead_control_is_refused_so_the_composer_is_asked_again():
    """§73 closes the loop: the orchestrator re-asks a node when its output is
    refused, so a button with no action is a page composed wrongly rather than
    a page to repair afterwards."""
    import pytest

    from services.blueprint.agent_contract import (
        InvalidPatternTemplate, check_pattern_templates,
    )

    result = _proposal({"type": "Stack", "props": {}, "children": [
        {"type": "Button", "props": {"label": "Cancel"}, "children": []}]})
    doc = {"pages": [{"id": "PAGE-001", "route": "/plants"}], "workflows": []}

    with pytest.raises(InvalidPatternTemplate) as exc:
        check_pattern_templates(result, doc)
    # The reason reaches the agent verbatim, so it can act on it.
    assert "declares no action" in str(exc.value)


def test_a_working_control_is_accepted():
    from services.blueprint.agent_contract import check_pattern_templates

    result = _proposal({"type": "Stack", "props": {}, "children": [
        {"type": "Button", "props": {"label": "Water", "workflow": "FLOW-001"},
         "children": []}]})
    check_pattern_templates(result, {
        "pages": [{"id": "PAGE-001", "route": "/plants"}],
        "workflows": [{"id": "FLOW-001", "name": "Record Watering"}]})


def test_without_a_doc_the_functional_check_is_skipped():
    """A caller that cannot say which workflows exist would otherwise reject
    every real binding as invented."""
    from services.blueprint.agent_contract import check_pattern_templates

    result = _proposal({"type": "Stack", "props": {}, "children": [
        {"type": "Button", "props": {"label": "Cancel"}, "children": []}]})
    check_pattern_templates(result)   # structure only — must not raise
