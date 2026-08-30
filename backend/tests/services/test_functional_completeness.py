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
        doc = _doc({"type": "Button", "props": {"label": "Go", prop: value}})
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
