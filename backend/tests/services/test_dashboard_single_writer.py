"""The dashboard maquette composer is the sole writer for the landing route.

Why this test exists
--------------------
The composer used to yield to whatever had already written the page, on the
assumption that the maquette reaches the page AUTHOR as a design brief and the
author therefore builds the dashboard from it.

Measured across the 223-app corpus, it does not. Of the 125 apps carrying a
dashboard, 43 shipped with no chart, and of the 10 chartless ones that DID have
a maquette, **every single one declared a fully-specified primary_chart** —
entity, group_by, aggregate, window, help text. The deciding step ran, produced
real domain judgment ("Bills by Legislative Stage"), and the authored page
simply did not carry it. Two writers, and the one that did the thinking lost.

So the guard is now authority-aware. Two protections remain, and both are
pinned here: the idempotency marker still stops a second compose, and Smith /
user re-applies never reach this code at all (the post-gen caller gates the
whole block on ``not force`` — BUG-APPLY-1, "my edit never saved").
"""

import json
import os
from pathlib import Path

import pytest

from services.apply_dashboard_maquette import apply_maquette_to_dashboard

MAQUETTE = {
    "hero": {"title": "Operations"},
    # Shape copied from a real emitted maquette: KPI tiles use `op`, not
    # `aggregate` (the chart uses `aggregate`). Guessing that wrong is how a
    # fixture silently produces a KPI-less dashboard.
    "kpis": [
        {"label": "Open Bills", "entity": "Bill", "op": "count", "format": "number"},
        {"label": "Sessions", "entity": "Session", "op": "count", "format": "number"},
        {"label": "Votes", "entity": "VoteRecord", "op": "count", "format": "number"},
    ],
    # The decision that kept getting thrown away.
    "primary_chart": {
        "kind": "bar", "title": "Bills by Stage", "entity": "Bill",
        "group_by": "status", "aggregate": "count",
    },
    "activity": {"entity": "Session", "title": "Recent Sessions", "limit": 5},
}

AUTHORED_PAGE = {
    "schemaVersion": "2", "id": "home", "route": "/", "layout": "main",
    "dataSources": [{"name": "billStat", "entity": "Bill", "op": "aggregate",
                     "metrics": {"value": {"fn": "count"}}}],
    "root": {"type": "Stack", "props": {}, "children": [
        {"type": "Heading", "props": {"content": "Dashboard", "level": 1}},
        {"type": "MetricTile", "props": {"label": "Bills",
                                         "value": "{{billStat.value}}",
                                         "format": "number"}},
    ]},
}


def _app(tmp_path: Path, page: dict | None = MAQUETTE and AUTHORED_PAGE) -> Path:
    root = tmp_path / "app"
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "dashboard-maquette.json").write_text(
        json.dumps(MAQUETTE), encoding="utf-8")
    (root / "contracts" / "plan.json").write_text(
        json.dumps({"pages": [{"route": "/", "kind": "dashboard"}]}), encoding="utf-8")
    if page is not None:
        (root / "src" / "schemas" / "home.json").write_text(
            json.dumps(page), encoding="utf-8")
    return root


def _page(root: Path) -> dict:
    return json.loads((root / "src" / "schemas" / "home.json").read_text())


def _types(doc: dict) -> set[str]:
    out: set[str] = set()

    def walk(n):
        if isinstance(n, dict):
            out.add(n.get("type"))
            for c in n.get("children") or []:
                walk(c)

    walk(doc.get("root") or {})
    return out


@pytest.fixture(autouse=True)
def _authority_on(monkeypatch):
    monkeypatch.delenv("FORGE_DASHBOARD_AUTHORITY", raising=False)


def test_maquette_overwrites_an_authored_page(tmp_path):
    """The regression: an authored page used to win, and its chart was gone."""
    root = _app(tmp_path)
    assert "Chart" not in _types(_page(root)), "fixture must start chartless"

    res = apply_maquette_to_dashboard(str(root))

    assert res["applied"] is True, res.get("reason")
    assert "Chart" in _types(_page(root)), "the declared primary_chart must land"


def test_the_declared_chart_binds_to_a_real_series_source(tmp_path):
    root = _app(tmp_path)
    apply_maquette_to_dashboard(str(root))
    series = [s for s in _page(root).get("dataSources") or []
              if s.get("op") == "series"]
    assert series, "a chart with no series source plots nothing"
    assert series[0]["entity"] == "Bill"
    assert series[0]["groupBy"] == "status"


def test_opting_out_restores_the_old_yield_behaviour(tmp_path, monkeypatch):
    """FORGE_DASHBOARD_AUTHORITY=0 is the documented per-build escape."""
    monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")
    root = _app(tmp_path)
    res = apply_maquette_to_dashboard(str(root))
    assert res["applied"] is False
    assert "not overwriting" in res["reason"]
    assert "Chart" not in _types(_page(root))


def test_second_run_is_a_no_op(tmp_path):
    """Idempotency survives the change — the marker still short-circuits, so
    running post-gen twice does not recompose."""
    root = _app(tmp_path)
    assert apply_maquette_to_dashboard(str(root))["applied"] is True
    second = apply_maquette_to_dashboard(str(root))
    assert second["applied"] is False
    assert "already composed" in second["reason"]


def test_composes_a_dashboard_that_clears_the_substance_floor(tmp_path):
    """End to end against the gate that scores this — the whole point of the
    change is that the page it writes passes."""
    from services.dashboard_anatomy import dashboard_findings

    root = _app(tmp_path)
    apply_maquette_to_dashboard(str(root))
    findings = dashboard_findings("/", _page(root), {})
    assert findings == [], [f["rule"] for f in findings]


def test_never_raises_on_a_missing_maquette(tmp_path):
    root = tmp_path / "bare"
    (root / "src" / "schemas").mkdir(parents=True)
    res = apply_maquette_to_dashboard(str(root))
    assert res["applied"] is False and isinstance(res.get("reason"), str)
