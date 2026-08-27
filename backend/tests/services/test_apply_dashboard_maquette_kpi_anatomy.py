"""Slice A composer emission — MetricTile carries anatomy props.

Given a KPI maquette dict with breakdown/threshold/extremes, the
composer must:

  * emit one Grid child (MetricTile) per top-level KPI
  * populate ``props.breakdown[]`` with {label, value:"{{source_name}}"}
    for each breakdown row + each extremes row
  * populate ``props.threshold`` with camelCase renderer keys
  * add one data source per breakdown row / extremes row so the
    runtime can resolve every mustache binding
"""
from __future__ import annotations

from services.apply_dashboard_maquette import _build_sections


def _grid(sections: list[dict]) -> dict:
    """Return the KPI Grid section (the one whose children are MetricTiles)."""
    for s in sections:
        if s.get("type") == "Grid":
            children = s.get("children") or []
            if any(c.get("type") == "MetricTile" for c in children):
                return s
    raise AssertionError("no KPI Grid emitted")


class TestBreakdownEmission:
    def test_breakdown_populates_metric_tile_prop(self):
        sections, sources = _build_sections({
            "kpis": [
                {"label": "Clients", "entity": "customer", "op": "count",
                 "breakdown": [
                     {"label": "Male",   "entity": "customer", "op": "count",
                      "filter": "gender=M"},
                     {"label": "Female", "entity": "customer", "op": "count",
                      "filter": "gender=F"},
                 ]},
            ],
        })
        tile = _grid(sections)["children"][0]
        bd = tile["props"].get("breakdown")
        assert bd and len(bd) == 2
        assert bd[0]["label"] == "Male"
        assert bd[1]["label"] == "Female"
        # values are mustache bindings to newly-authored sources
        assert bd[0]["value"].startswith("{{") and bd[0]["value"].endswith("}}")
        assert bd[1]["value"].startswith("{{") and bd[1]["value"].endswith("}}")

    def test_one_data_source_per_breakdown_row(self):
        sections, sources = _build_sections({
            "kpis": [
                {"label": "C", "entity": "customer", "op": "count",
                 "breakdown": [
                     {"label": "M", "entity": "customer", "op": "count",
                      "filter": "gender=M"},
                     {"label": "F", "entity": "customer", "op": "count",
                      "filter": "gender=F"},
                 ]},
            ],
        })
        # Primary KPI source + 2 breakdown sources.
        assert len(sources) == 3
        filters = [s.get("filter") for s in sources if s.get("filter")]
        assert "gender=M" in filters
        assert "gender=F" in filters

    def test_absent_breakdown_leaves_no_prop(self):
        sections, _ = _build_sections({
            "kpis": [
                {"label": "C", "entity": "customer", "op": "count"},
            ],
        })
        tile = _grid(sections)["children"][0]
        assert "breakdown" not in tile["props"]

    def test_breakdown_supports_sum_with_field(self):
        sections, sources = _build_sections({
            "kpis": [
                {"label": "Revenue", "entity": "payment", "op": "sum",
                 "field": "amount",
                 "breakdown": [
                     {"label": "Q4", "entity": "payment", "op": "sum",
                      "field": "amount", "filter": "quarter=Q4"},
                 ]},
            ],
        })
        # Primary sum source + Q4 sum source
        sum_sources = [s for s in sources if s.get("op") == "sum"]
        assert len(sum_sources) == 2
        assert all(s["field"] == "amount" for s in sum_sources)

    def test_row_missing_required_fields_dropped(self):
        sections, sources = _build_sections({
            "kpis": [
                {"label": "C", "entity": "customer", "op": "count",
                 "breakdown": [
                     {"entity": "customer", "op": "count"},           # no label
                     {"label": "OK", "entity": "customer", "op": "count"},
                 ]},
            ],
        })
        tile = _grid(sections)["children"][0]
        assert len(tile["props"]["breakdown"]) == 1
        assert tile["props"]["breakdown"][0]["label"] == "OK"


class TestThresholdEmission:
    def test_threshold_populates_camel_case_props(self):
        sections, _ = _build_sections({
            "kpis": [
                {"label": "DTI", "entity": "customer", "op": "avg", "field": "dti",
                 "threshold": {"warn_above": 50, "critical_above": 100,
                               "color_on_value": True}},
            ],
        })
        tile = _grid(sections)["children"][0]
        th = tile["props"].get("threshold")
        assert th == {
            "warnAbove": 50,
            "criticalAbove": 100,
            "colorOnValue": True,
        }

    def test_threshold_absent_leaves_no_prop(self):
        sections, _ = _build_sections({
            "kpis": [{"label": "X", "entity": "e", "op": "count"}],
        })
        assert "threshold" not in _grid(sections)["children"][0]["props"]

    def test_partial_threshold_only_emits_set_bounds(self):
        # When color_on_value isn't declared, the composer omits it
        # rather than writing a defaulted False — a smaller emitted
        # blob keeps downstream JSON diffs quieter.
        sections, _ = _build_sections({
            "kpis": [
                {"label": "X", "entity": "e", "op": "count",
                 "threshold": {"warn_above": 50}},
            ],
        })
        th = _grid(sections)["children"][0]["props"]["threshold"]
        assert th == {"warnAbove": 50}


class TestExtremesEmission:
    def test_extremes_add_max_min_rows_to_breakdown(self):
        sections, sources = _build_sections({
            "kpis": [
                {"label": "Debt", "entity": "loan", "op": "sum", "field": "principal",
                 "extremes": {"max_label": "Single Max", "min_label": "Single Min"}},
            ],
        })
        tile = _grid(sections)["children"][0]
        bd = tile["props"].get("breakdown")
        assert bd and len(bd) == 2
        labels = [row["label"] for row in bd]
        assert "Single Max" in labels
        assert "Single Min" in labels
        # Both derived data sources should exist against the same
        # entity + field as the parent KPI.
        ext_sources = [s for s in sources if s["entity"] == "loan"
                       and s.get("field") == "principal" and s["op"] == "max"]
        assert len(ext_sources) >= 2  # max source + min-approx source

    def test_extremes_skipped_when_kpi_has_no_field(self):
        # Bare count has no field to aggregate — extremes silently
        # skipped (a max/min over "rows" would be nonsense).
        sections, _ = _build_sections({
            "kpis": [
                {"label": "Total", "entity": "customer", "op": "count",
                 "extremes": {"max_label": "Peak"}},
            ],
        })
        tile = _grid(sections)["children"][0]
        assert "breakdown" not in tile["props"]

    def test_breakdown_and_extremes_combine(self):
        sections, _ = _build_sections({
            "kpis": [
                {"label": "Debt", "entity": "loan", "op": "sum", "field": "principal",
                 "breakdown": [
                     {"label": "Secured", "entity": "loan", "op": "sum",
                      "field": "principal", "filter": "type=secured"},
                 ],
                 "extremes": {"max_label": "Peak"}},
            ],
        })
        bd = _grid(sections)["children"][0]["props"]["breakdown"]
        labels = [row["label"] for row in bd]
        # Breakdown row first, then extremes.
        assert labels == ["Secured", "Peak"]


class TestBackCompat:
    def test_kpi_without_anatomy_emits_today_shape(self):
        sections, sources = _build_sections({
            "kpis": [
                {"label": "Total", "entity": "invoice", "op": "sum",
                 "field": "amount"},
            ],
        })
        tile = _grid(sections)["children"][0]
        # Exactly the same props keys as before Slice A shipped.
        assert set(tile["props"].keys()) == {"label", "value", "format"}
        # One primary data source, no derived rows.
        assert len(sources) == 1
