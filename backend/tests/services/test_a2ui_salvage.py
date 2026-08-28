"""A composition that fails on some widgets keeps the rest.

Why this exists
---------------
The A2UI floor was all-or-nothing. On a real build it produced a 95-node
dashboard, found 3 unreadable charts, returned `applied: False`, and the app
shipped the deterministic fallback instead: 13 nodes titled "Dashboard Page".
Three bad charts cost 92 good nodes, and the gate's failure mode was strictly
worse than letting the flawed page through.

The rule: drop what fails, keep what holds. A dashboard missing one chart is a
dashboard; a stub with a placeholder title is not. If pruning cannot make the
page pass — the failures are structural, not per-widget — the page is still
declined, because shipping something the floor rejects on its own terms is how
the gate stops meaning anything.
"""

import json
from services.a2ui_authority import _prune_failing_widgets


def _schema(*names):
    return {
        "schemaVersion": "2", "id": "home", "route": "/", "layout": "main",
        "dataSources": [{"name": n, "entity": "Product", "op": "series",
                         "groupBy": "id"} for n in names],
        "root": {"type": "Stack", "children": [
            {"type": "Card", "children": [
                {"type": "Chart", "props": {"data": f"{{{{{n}}}}}"}}]}
            for n in names
        ]},
    }


def _finding(ref):
    return {"rule": "dashboard_groupby_unreadable", "slot": "chart", "ref": ref}


def test_the_offending_datasource_is_removed():
    schema, pruned = _prune_failing_widgets(_schema("bad", "good"),
                                            [_finding("bad")])
    assert pruned == ["bad"]
    assert [s["name"] for s in schema["dataSources"]] == ["good"]


def test_the_widget_bound_to_it_goes_too():
    """Leaving the Chart behind means a component bound to nothing — the
    empty-widget bug this whole session has been about."""
    schema, _ = _prune_failing_widgets(_schema("bad", "good"), [_finding("bad")])
    assert "{{bad}}" not in __import__("json").dumps(schema)
    assert "{{good}}" in __import__("json").dumps(schema)


def test_everything_else_survives():
    schema, _ = _prune_failing_widgets(_schema("bad", "a", "b"),
                                       [_finding("bad")])
    assert [s["name"] for s in schema["dataSources"]] == ["a", "b"]


def test_a_finding_with_no_ref_prunes_nothing():
    """Structural failures name no dataSource. There is nothing to drop, so
    the caller must decline rather than silently ship."""
    schema, pruned = _prune_failing_widgets(
        _schema("a"), [{"rule": "dashboard_no_kpis", "slot": "kpi"}])
    assert pruned == []
    assert [s["name"] for s in schema["dataSources"]] == ["a"]


def test_pruning_does_not_mutate_the_input():
    original = _schema("bad", "good")
    _prune_failing_widgets(original, [_finding("bad")])
    assert [s["name"] for s in original["dataSources"]] == ["bad", "good"]


def test_emptied_containers_are_dropped():
    """A Card whose only child was the pruned chart is now an empty box."""
    schema, _ = _prune_failing_widgets(_schema("bad"), [_finding("bad")])
    kept = __import__("json").dumps(schema)
    assert "Chart" not in kept and "Card" not in kept


# ---------------------------------------------------------------------------
# Every binding needs a declared source.
#
# A composed /plants shipped four stat tiles reading {{plantstracked.value}},
# {{overdue.value}}, {{duetoday.value}} and {{neverwatered.value}} against a
# single declared source. A2UI invented a source name per metric; the binder
# passed names it had never seen straight through; the page rendered blanks.
# ---------------------------------------------------------------------------

def _page(sources, root):
    return {"id": "PAGE-001", "route": "/plants", "schemaVersion": "2",
            "dataSources": sources, "root": root}


def test_a_binding_with_no_source_is_dangling():
    from services.a2ui_to_forge import dangling_bindings

    page = _page(
        [{"name": "plants", "entity": "Plant", "op": "list"}],
        {"type": "Stack", "children": [
            {"type": "Stat", "props": {"label": "Tracked",
                                       "value": "{{plantstracked.value}}"}},
            {"type": "Table", "props": {"rows": "{{plants}}"}},
        ]},
    )
    assert dangling_bindings(page) == ["plantstracked"]


def test_a_binding_that_names_a_declared_source_is_not_dangling():
    from services.a2ui_to_forge import dangling_bindings

    # Both shapes resolve to the same source: whole, and dotted into a field.
    page = _page(
        [{"name": "plants", "entity": "Plant", "op": "list"}],
        {"type": "Stack", "children": [
            {"type": "Table", "props": {"rows": "{{plants}}"}},
            {"type": "Stat", "props": {"value": "{{plants.count}}"}},
        ]},
    )
    assert dangling_bindings(page) == []


def test_the_floor_reports_a_dangling_binding_and_names_the_source():
    from services.a2ui_authority import _floor_findings

    page = _page(
        [{"name": "plants", "entity": "Plant", "op": "list"}],
        {"type": "Stack", "children": [
            {"type": "Stat", "props": {"value": "{{overdue.value}}"}},
            {"type": "Table", "props": {"rows": "{{plants}}"}},
        ]},
    )
    findings = _floor_findings("entity_list", "/plants", page, {})
    dangling = [f for f in findings if f.get("ref") == "overdue"]
    assert dangling, findings
    # `ref` is what lets salvage drop the tile instead of declining the page.
    assert "no declared data source" in dangling[0]["rule"]


def test_salvage_drops_the_tile_that_reads_phantom_data():
    from services.a2ui_authority import _floor_findings, _prune_failing_widgets

    page = _page(
        [{"name": "plants", "entity": "Plant", "op": "list"}],
        {"type": "Stack", "children": [
            {"type": "Grid", "props": {"columns": 2}, "children": [
                {"type": "Stat", "props": {"value": "{{overdue.value}}"}},
            ]},
            {"type": "Table", "props": {"rows": "{{plants}}"}},
        ]},
    )
    findings = _floor_findings("entity_list", "/plants", page, {})
    candidate, pruned = _prune_failing_widgets(page, findings)

    # Reported as pruned even though it never was a dataSource — an empty
    # `pruned` makes the caller skip salvage and decline the whole page.
    assert "overdue" in pruned
    blob = json.dumps(candidate)
    assert "overdue" not in blob
    # The part of the page that was bound correctly survives.
    assert "{{plants}}" in blob
    assert not [f for f in _floor_findings("entity_list", "/plants",
                                           candidate, {})
                if f.get("ref") == "overdue"]
