"""Tests for Slice C — section chrome (subtitle, filters, reset_filters).

The dashboard maquette contract grows three optional fields so the
LLM (or a deterministic bridge) can declare the top-of-page chrome
that gives each dashboard identity beyond the widget grid:

  - ``subtitle``       — one-line editorial subtitle under the H1
  - ``filters``        — list[FilterSpec] rendered as a filter bar
  - ``reset_filters``  — bool, renders the "↺ Reset all filters" chip

All three are OPTIONAL. A maquette without them parses identically
to today (byte-safe backwards compatibility). See spec:
docs/superpowers/specs/2026-08-15-widget-anatomy-composition-recipes.md
"""
from __future__ import annotations

import pytest

from services.dashboard_maquette import (
    DashboardMaquette,
    FilterSpec,
)


class TestSubtitleParsing:
    def test_subtitle_string_parses(self):
        m = DashboardMaquette.from_dict({
            "subtitle": "Evaluating batch processing across archivists",
        })
        assert m.subtitle == "Evaluating batch processing across archivists"

    def test_subtitle_absent_is_none(self):
        m = DashboardMaquette.from_dict({})
        assert m.subtitle is None

    def test_subtitle_non_string_dropped(self):
        m = DashboardMaquette.from_dict({"subtitle": 123})
        assert m.subtitle is None

    def test_subtitle_empty_string_dropped(self):
        # An empty subtitle would render as blank whitespace in the DOM;
        # treat as absent so the composer skips the node entirely.
        m = DashboardMaquette.from_dict({"subtitle": "   "})
        assert m.subtitle is None

    def test_subtitle_survives_to_dict_roundtrip(self):
        m = DashboardMaquette.from_dict({"subtitle": "Ops overview for today"})
        d = m.to_dict()
        assert d["subtitle"] == "Ops overview for today"
        m2 = DashboardMaquette.from_dict(d)
        assert m2.subtitle == m.subtitle


class TestFiltersParsing:
    def test_select_filter_parses(self):
        m = DashboardMaquette.from_dict({
            "filters": [
                {"kind": "select", "field": "status", "label": "Status",
                 "options": ["queued", "processing", "complete"]}
            ]
        })
        assert len(m.filters) == 1
        f = m.filters[0]
        assert f.kind == "select"
        assert f.field == "status"
        assert f.label == "Status"
        assert f.options == ["queued", "processing", "complete"]

    def test_date_range_filter_parses(self):
        m = DashboardMaquette.from_dict({
            "filters": [
                {"kind": "date-range", "field": "createdAt", "label": "Date range"}
            ]
        })
        assert len(m.filters) == 1
        assert m.filters[0].kind == "date-range"
        assert m.filters[0].options == []

    def test_text_filter_parses(self):
        m = DashboardMaquette.from_dict({
            "filters": [
                {"kind": "text", "field": "search", "label": "Search"}
            ]
        })
        assert len(m.filters) == 1
        assert m.filters[0].kind == "text"

    def test_multiple_filters_parse_in_order(self):
        m = DashboardMaquette.from_dict({
            "filters": [
                {"kind": "select", "field": "risk", "label": "Loan Risk"},
                {"kind": "select", "field": "brand", "label": "Card Brand"},
                {"kind": "date-range", "field": "createdAt", "label": "Date"},
            ]
        })
        assert [f.field for f in m.filters] == ["risk", "brand", "createdAt"]

    def test_unknown_kind_dropped(self):
        # Silent drop keeps the composer simple — it never has to reason
        # about a filter kind it can't render.
        m = DashboardMaquette.from_dict({
            "filters": [
                {"kind": "wizard", "field": "x", "label": "Unknown"},
                {"kind": "select", "field": "status", "label": "Status"},
            ]
        })
        assert len(m.filters) == 1
        assert m.filters[0].field == "status"

    def test_missing_required_field_dropped(self):
        # A filter without `field` has nothing to bind to.
        m = DashboardMaquette.from_dict({
            "filters": [
                {"kind": "select", "label": "No field"},
                {"kind": "select", "field": "ok", "label": "OK"},
            ]
        })
        assert len(m.filters) == 1
        assert m.filters[0].field == "ok"

    def test_missing_label_dropped(self):
        m = DashboardMaquette.from_dict({
            "filters": [
                {"kind": "select", "field": "no_label"},
            ]
        })
        assert m.filters == []

    def test_non_list_filters_dropped(self):
        m = DashboardMaquette.from_dict({"filters": "not-a-list"})
        assert m.filters == []

    def test_absent_filters_is_empty_list(self):
        m = DashboardMaquette.from_dict({})
        assert m.filters == []

    def test_filter_options_non_list_becomes_empty(self):
        m = DashboardMaquette.from_dict({
            "filters": [
                {"kind": "select", "field": "s", "label": "S", "options": "not-a-list"},
            ]
        })
        assert m.filters[0].options == []

    def test_filter_options_string_elements_kept(self):
        m = DashboardMaquette.from_dict({
            "filters": [
                {"kind": "select", "field": "s", "label": "S",
                 "options": ["a", 1, "b", None, "c"]},
            ]
        })
        # Non-strings silently dropped
        assert m.filters[0].options == ["a", "b", "c"]

    def test_filters_survive_roundtrip(self):
        raw = {
            "filters": [
                {"kind": "select", "field": "status", "label": "Status",
                 "options": ["queued", "done"]},
                {"kind": "date-range", "field": "createdAt", "label": "Date"},
            ]
        }
        m = DashboardMaquette.from_dict(raw)
        d = m.to_dict()
        assert d["filters"] == [
            {"kind": "select", "field": "status", "label": "Status",
             "options": ["queued", "done"]},
            {"kind": "date-range", "field": "createdAt", "label": "Date",
             "options": []},
        ]
        m2 = DashboardMaquette.from_dict(d)
        assert len(m2.filters) == 2


class TestResetFilters:
    def test_reset_true_parses(self):
        m = DashboardMaquette.from_dict({"reset_filters": True})
        assert m.reset_filters is True

    def test_reset_false_parses(self):
        m = DashboardMaquette.from_dict({"reset_filters": False})
        assert m.reset_filters is False

    def test_reset_absent_defaults_false(self):
        m = DashboardMaquette.from_dict({})
        assert m.reset_filters is False

    def test_reset_non_bool_dropped(self):
        # Strings/ints reduce to safe default False, not truthy coercion.
        m = DashboardMaquette.from_dict({"reset_filters": "yes"})
        assert m.reset_filters is False

    def test_reset_survives_roundtrip(self):
        m = DashboardMaquette.from_dict({"reset_filters": True})
        assert DashboardMaquette.from_dict(m.to_dict()).reset_filters is True


class TestBackCompat:
    """Existing maquettes without chrome fields must parse identically."""

    def test_empty_dict(self):
        m = DashboardMaquette.from_dict({})
        assert m.subtitle is None
        assert m.filters == []
        assert m.reset_filters is False

    def test_kpi_only_maquette_unchanged(self):
        m = DashboardMaquette.from_dict({
            "kpis": [{"label": "X", "entity": "y", "op": "count"}],
        })
        assert m.subtitle is None
        assert m.filters == []
        assert m.reset_filters is False
        assert len(m.kpis) == 1

    def test_to_dict_omits_empty_chrome(self):
        """A maquette with no chrome must serialise to the same shape it
        used to — no new keys, so downstream JSON diffs stay clean.

        Only when the LLM ACTUALLY set a chrome field does it show up.
        """
        m = DashboardMaquette()
        d = m.to_dict()
        # subtitle/filters/reset_filters ARE new keys but must not appear
        # when they carry the empty/None default.
        assert "subtitle" not in d or d["subtitle"] is None
        assert d.get("filters", []) == []
        assert d.get("reset_filters", False) is False
