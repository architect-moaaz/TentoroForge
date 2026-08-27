"""Slice A composer emission — Chart carries anatomy props."""
from __future__ import annotations

from services.apply_dashboard_maquette import _build_sections


def _chart_node(sections: list[dict]) -> dict:
    for s in sections:
        if s.get("type") == "Chart":
            return s
    raise AssertionError("no Chart section emitted")


def _mq(chart_extra: dict) -> dict:
    return {"primary_chart": {"kind": "bar", "title": "Spend by Month",
                                "entity": "payment", "group_by": "month",
                                **chart_extra}}


class TestOverlayEmission:
    def test_overlay_authors_second_data_source(self):
        sections, sources = _build_sections(_mq({
            "overlay": {"kind": "line", "curve": "smooth",
                         "aggregate": "count"},
        }))
        # Primary series source + overlay series source.
        series_sources = [s for s in sources if s.get("op") == "series"]
        assert len(series_sources) == 2
        chart = _chart_node(sections)
        assert chart["props"].get("overlay") is not None
        assert chart["props"]["overlay"]["chartType"] == "line"
        assert chart["props"]["overlay"]["curve"] == "smooth"

    def test_absent_overlay_no_prop(self):
        sections, _ = _build_sections(_mq({}))
        assert "overlay" not in _chart_node(sections)["props"]


class TestViewTogglesEmission:
    def test_toggles_pass_through_camelcase(self):
        sections, _ = _build_sections(_mq({
            "view_toggles": [
                {"label": "Time Trend", "modifier": {"window": "month"}},
                {"label": "Year Trend", "modifier": {"window": "year"}, "default": True},
            ],
        }))
        vt = _chart_node(sections)["props"].get("viewToggles")
        assert vt and len(vt) == 2
        assert vt[0]["label"] == "Time Trend"
        assert vt[1]["default"] is True
        assert vt[0].get("default", False) is False


class TestEncodingEmission:
    def test_leaderboard_and_topN_camelcased(self):
        sections, _ = _build_sections(_mq({
            "encoding": {"leaderboard": True, "sorted": "desc",
                          "top_n": 10, "value_labels": True},
        }))
        enc = _chart_node(sections)["props"].get("encoding")
        assert enc == {"leaderboard": True, "sorted": "desc",
                        "topN": 10, "valueLabels": True}

    def test_empty_encoding_omitted(self):
        sections, _ = _build_sections(_mq({"encoding": {}}))
        assert "encoding" not in _chart_node(sections)["props"]


class TestSemanticColorEmission:
    def test_field_map_passed_through(self):
        sections, _ = _build_sections(_mq({
            "semantic_color": {"by": "field", "field": "gender",
                                "map": {"M": "var(--male)", "F": "var(--female)"}},
        }))
        sc = _chart_node(sections)["props"].get("semanticColor")
        assert sc == {"by": "field", "field": "gender",
                       "map": {"M": "var(--male)", "F": "var(--female)"}}


class TestHelpEmission:
    def test_help_populates_prop(self):
        sections, _ = _build_sections(_mq({
            "help": "DTI above 40% is flagged risky",
        }))
        assert _chart_node(sections)["props"]["help"] == \
            "DTI above 40% is flagged risky"


class TestBackCompat:
    def test_bare_chart_matches_pre_slice_shape(self):
        # No anatomy declared → Chart node keeps the exact prior keyset
        # (plus the new `title` prop, which was already the heading text).
        sections, sources = _build_sections(_mq({}))
        chart = _chart_node(sections)["props"]
        assert set(chart.keys()) == {"chartType", "data", "xKey", "series", "title"}
        # Exactly one series source (no overlay).
        assert len([s for s in sources if s.get("op") == "series"]) == 1
