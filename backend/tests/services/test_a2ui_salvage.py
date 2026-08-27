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
