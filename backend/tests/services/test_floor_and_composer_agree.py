"""The floor's demands and what the composer is asked for are the same demands.

Two findings from one live compose turn, both the same shape: two answers to
one question, disagreeing.

    [a2ui] PAGE-002 declined (composed page failed the dashboard floor:
           dashboard_no_chart, binding 'item' has no declared data source)

Both cost the full composition — 140 seconds — before anything noticed.
"""
from __future__ import annotations

import re

from services.a2ui_authority import _JOB
from services.a2ui_to_forge import dangling_bindings

# ── the Repeat this codebase mints itself ───────────────────────────────

def _page(root: dict, sources=("votes",)) -> dict:
    return {"root": root,
            "dataSources": [{"name": n} for n in sources]}


def _repeat(source="votes", var="item", child_binding="{{item.titleAr}}"):
    """The node `a2ui_to_forge._repeat_from` emits, verbatim in shape."""
    return {"type": "Repeat", "props": {"source": source, "as": var},
            "children": [{"type": "Text", "props": {"content": child_binding}}]}


def test_a_repeat_binds_its_own_loop_variable():
    """`_repeat_from` emits `{"source": …, "as": "item"}` and children binding
    `{{item.x}}`. The checker looked for a `repeat` KEY, or `rows`/`items`/
    `data` holding `{{…}}` — a Repeat has neither, so this module refused a
    page over a variable it had introduced itself."""
    assert dangling_bindings(_page(_repeat())) == []


def test_the_variable_is_read_not_assumed():
    assert dangling_bindings(_page(_repeat(var="vote",
                                           child_binding="{{vote.title}}"))) == []
    # …and the old name is not silently still bound.
    assert dangling_bindings(_page(_repeat(var="vote",
                                           child_binding="{{item.title}}"))) == ["item"]


def test_a_repeat_over_an_invented_collection_does_not_launder_its_scope():
    """Only a source the page really declares opens the scope, so a Repeat
    over an invented collection still reports its variable rather than
    silencing it — which is what makes the rule safe to apply.

    `madeUp` itself is NOT reported: a Repeat carries its source as a bare
    prop, not a `{{binding}}`, and this function only reads bindings. That is a
    real gap and a separate one — a Repeat over a source nobody declares
    renders an empty list — but widening the check here would start refusing
    pages that pass today, which is its own decision.
    """
    assert dangling_bindings(_page(_repeat(source="madeUp"))) == ["item"]


def test_a_sibling_of_the_repeat_is_not_in_its_scope():
    """The binding is named, not blanket: everything else inside stays
    checked."""
    node = _repeat()
    node["children"].append(
        {"type": "Text", "props": {"content": "{{quorumPct}}"}})
    assert dangling_bindings(_page(node)) == ["quorumPct"]


# ── the chart, demanded in a word the composer's checker reads ──────────

#: `tools/a2ui-mcp/checks.py`, `_CAPABILITIES` — the chart row.
_CHART_WORDS = ("chart", "graph", "trend", "distribution", "histogram",
                "funnel", "sparkline", "plot", "over time", "by hour",
                "by week", "by stage")


def _demands_chart(text: str) -> bool:
    """A2UI's own rule: WHOLE WORDS. A substring test read "chart" inside
    "flowchart", so the server matches on word boundaries — which is why
    "worth charting" asked for nothing at all."""
    return any(re.search(rf"\b{re.escape(w)}\b", text, re.I) for w in _CHART_WORDS)


def test_the_dashboard_brief_asks_for_the_chart_the_floor_requires():
    """`dashboard_findings` raises `dashboard_no_chart` for any dashboard
    without one. If the brief does not ask in a word the composer's checker
    recognises, every dashboard is composed without a chart and then refused —
    which is what happened, at 140 seconds a time."""
    assert _demands_chart(_JOB["dashboard"]), (
        "the dashboard brief no longer names a chart in a word A2UI matches; "
        "the floor will refuse every dashboard it composes"
    )


def test_no_other_kind_asks_for_one():
    """A component named in a brief is read as mandatory. 'a trend' once put a
    bar chart on a two-entity plant tracker's create form; the floor asks
    nothing of these kinds and neither should the brief."""
    for kind in ("collection", "record", "form"):
        assert not _demands_chart(_JOB[kind]), f"{kind} demands a chart"


def test_the_floor_still_wants_a_chart_on_dashboards():
    """The other half of the agreement. If this is ever relaxed, the brief
    above is over-demanding and should be relaxed with it."""
    from services.dashboard_anatomy import _CHART_TYPES

    assert "Chart" in _CHART_TYPES
