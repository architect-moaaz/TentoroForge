"""Slice A Chart anatomy — dataclass + parser tests."""
from __future__ import annotations

from services.dashboard_maquette import (
    ChartEncodingSpec,
    ChartOverlaySpec,
    ChartSemanticColorSpec,
    ChartSpec,
    ChartViewToggle,
    DashboardMaquette,
)


def _chart(extra: dict) -> ChartSpec:
    raw = {"primary_chart": {"kind": "bar", "title": "T",
                              "entity": "payment", "group_by": "createdAt",
                              **extra}}
    m = DashboardMaquette.from_dict(raw)
    assert m.primary_chart is not None
    return m.primary_chart


class TestHelp:
    def test_help_parses(self):
        c = _chart({"help": "DTI above 40% is flagged risky"})
        assert c.help == "DTI above 40% is flagged risky"

    def test_help_strips_whitespace(self):
        c = _chart({"help": "  hello  "})
        assert c.help == "hello"

    def test_empty_help_dropped(self):
        c = _chart({"help": "   "})
        assert c.help is None


class TestOverlay:
    def test_line_overlay_parses(self):
        c = _chart({"overlay": {"kind": "line", "aggregate": "count",
                                "curve": "smooth"}})
        assert c.overlay is not None
        assert c.overlay.kind == "line"
        assert c.overlay.curve == "smooth"

    def test_unknown_overlay_kind_dropped(self):
        c = _chart({"overlay": {"kind": "donut"}})  # donut not in overlay set
        assert c.overlay is None

    def test_bad_curve_dropped(self):
        c = _chart({"overlay": {"kind": "line", "curve": "wobbly"}})
        assert c.overlay is not None
        assert c.overlay.curve is None

    def test_overlay_roundtrip(self):
        c = _chart({"overlay": {"kind": "line", "aggregate": "sum",
                                 "aggregate_field": "amount", "curve": "smooth"}})
        d = c.to_dict()
        assert d["overlay"] == {
            "kind": "line", "aggregate": "sum",
            "aggregate_field": "amount", "curve": "smooth",
        }


class TestViewToggles:
    def test_toggles_parse_in_order(self):
        c = _chart({"view_toggles": [
            {"label": "Time Trend", "modifier": {"window": "month"}},
            {"label": "Year Trend", "modifier": {"window": "year"}, "default": True},
        ]})
        assert [t.label for t in c.view_toggles] == ["Time Trend", "Year Trend"]
        assert c.view_toggles[1].default is True
        assert c.view_toggles[0].default is False

    def test_toggle_missing_label_dropped(self):
        c = _chart({"view_toggles": [
            {"modifier": {"window": "month"}},
            {"label": "OK"},
        ]})
        assert [t.label for t in c.view_toggles] == ["OK"]

    def test_non_dict_modifier_becomes_empty(self):
        c = _chart({"view_toggles": [
            {"label": "T", "modifier": "not-a-dict"},
        ]})
        assert c.view_toggles[0].modifier == {}


class TestEncoding:
    def test_leaderboard_and_sort(self):
        c = _chart({"encoding": {"leaderboard": True, "sorted": "desc",
                                  "top_n": 10, "value_labels": True}})
        assert c.encoding is not None
        assert c.encoding.leaderboard is True
        assert c.encoding.sorted == "desc"
        assert c.encoding.top_n == 10
        assert c.encoding.value_labels is True

    def test_stacked_only(self):
        c = _chart({"encoding": {"stacked": True}})
        assert c.encoding is not None
        assert c.encoding.stacked is True

    def test_empty_encoding_becomes_none(self):
        c = _chart({"encoding": {}})
        assert c.encoding is None

    def test_bad_sort_dropped(self):
        c = _chart({"encoding": {"sorted": "random"}})
        # sorted was the only flag → encoding drops to None
        assert c.encoding is None

    def test_top_n_negative_dropped(self):
        c = _chart({"encoding": {"top_n": -5}})
        assert c.encoding is None


class TestSemanticColor:
    def test_field_map_parses(self):
        c = _chart({"semantic_color": {
            "by": "field", "field": "gender",
            "map": {"M": "var(--male)", "F": "var(--female)"},
        }})
        assert c.semantic_color is not None
        assert c.semantic_color.field == "gender"
        assert c.semantic_color.map == {"M": "var(--male)", "F": "var(--female)"}

    def test_wrong_by_dropped(self):
        c = _chart({"semantic_color": {"by": "index", "field": "x",
                                        "map": {"a": "red"}}})
        assert c.semantic_color is None

    def test_empty_map_dropped(self):
        c = _chart({"semantic_color": {"by": "field", "field": "x", "map": {}}})
        assert c.semantic_color is None

    def test_non_string_map_entries_dropped(self):
        c = _chart({"semantic_color": {"by": "field", "field": "x",
                                        "map": {"a": "red", 1: "blue", "b": 42}}})
        assert c.semantic_color.map == {"a": "red"}


class TestBackCompat:
    def test_bare_chart_parses(self):
        c = _chart({})
        assert c.overlay is None
        assert c.view_toggles == []
        assert c.encoding is None
        assert c.semantic_color is None
        assert c.help is None

    def test_bare_chart_to_dict_no_anatomy_keys(self):
        c = _chart({})
        d = c.to_dict()
        for k in ("overlay", "view_toggles", "encoding", "semantic_color", "help"):
            assert k not in d
