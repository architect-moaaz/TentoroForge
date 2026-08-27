"""Slice A KPI anatomy — dataclass + parser tests.

Extends KPISpec with the fields that make a stat card tell a story:

  * breakdown  — sub-lines like "Male 984 / Female 1,016"
  * threshold  — warn/critical rules that colour the primary value
  * extremes   — max/min companion values ("Single Max $516K")

All fields optional. Missing = renders exactly like today. See spec:
docs/superpowers/specs/2026-08-15-widget-anatomy-composition-recipes.md
"""
from __future__ import annotations

import pytest

from services.dashboard_maquette import (
    DashboardMaquette,
    KPISpec,
    KPIBreakdownSpec,
    KPIThresholdSpec,
    KPIExtremesSpec,
)


# ─────────────────────────── breakdown ────────────────────────────────


class TestBreakdownParsing:
    def _kpi(self, extra: dict) -> KPISpec:
        raw = {"kpis": [{"label": "Clients", "entity": "customer", "op": "count", **extra}]}
        m = DashboardMaquette.from_dict(raw)
        assert len(m.kpis) == 1
        return m.kpis[0]

    def test_single_breakdown_row_parses(self):
        k = self._kpi({"breakdown": [
            {"label": "Male", "entity": "customer", "op": "count",
             "filter": "gender=M"},
        ]})
        assert len(k.breakdown) == 1
        b = k.breakdown[0]
        assert b.label == "Male"
        assert b.entity == "customer"
        assert b.op == "count"
        assert b.filter == "gender=M"

    def test_multiple_breakdown_rows_preserve_order(self):
        k = self._kpi({"breakdown": [
            {"label": "Male",   "entity": "customer", "op": "count", "filter": "gender=M"},
            {"label": "Female", "entity": "customer", "op": "count", "filter": "gender=F"},
        ]})
        assert [b.label for b in k.breakdown] == ["Male", "Female"]

    def test_sum_breakdown_with_field(self):
        k = self._kpi({"breakdown": [
            {"label": "Q4 Revenue", "entity": "payment", "op": "sum",
             "field": "amount", "filter": "quarter=Q4"},
        ]})
        b = k.breakdown[0]
        assert b.op == "sum"
        assert b.field == "amount"

    def test_missing_required_breakdown_field_drops_row(self):
        # A breakdown row must have label + entity + op — matches the
        # KPI itself's discipline.
        k = self._kpi({"breakdown": [
            {"entity": "customer", "op": "count"},          # no label
            {"label": "OK", "entity": "customer", "op": "count"},
        ]})
        assert len(k.breakdown) == 1
        assert k.breakdown[0].label == "OK"

    def test_unknown_op_drops_breakdown_row(self):
        # Match KPISpec op enum {count, sum, avg, max}. Unknown values
        # silently dropped so composer never emits an invalid data source.
        k = self._kpi({"breakdown": [
            {"label": "Weird", "entity": "customer", "op": "median"},
            {"label": "OK",    "entity": "customer", "op": "count"},
        ]})
        assert [b.label for b in k.breakdown] == ["OK"]

    def test_non_list_breakdown_dropped(self):
        k = self._kpi({"breakdown": "not-a-list"})
        assert k.breakdown == []

    def test_absent_breakdown_is_empty_list(self):
        k = self._kpi({})
        assert k.breakdown == []

    def test_breakdown_survives_roundtrip(self):
        k = self._kpi({"breakdown": [
            {"label": "Male", "entity": "customer", "op": "count", "filter": "gender=M"},
        ]})
        d = k.to_dict()
        assert d["breakdown"] == [
            {"label": "Male", "entity": "customer", "op": "count", "filter": "gender=M"},
        ]
        # Full-maquette roundtrip
        raw = {"kpis": [d]}
        m2 = DashboardMaquette.from_dict(raw)
        assert len(m2.kpis[0].breakdown) == 1


# ─────────────────────────── threshold ────────────────────────────────


class TestThresholdParsing:
    def _kpi(self, threshold: dict) -> KPISpec:
        raw = {"kpis": [{"label": "DTI", "entity": "customer", "op": "avg",
                         "field": "dti", "threshold": threshold}]}
        m = DashboardMaquette.from_dict(raw)
        return m.kpis[0]

    def test_warn_and_critical_parse(self):
        k = self._kpi({"warn_above": 50, "critical_above": 100})
        t = k.threshold
        assert t is not None
        assert t.warn_above == 50
        assert t.critical_above == 100
        assert t.color_on_value is False  # default

    def test_color_on_value_toggles(self):
        k = self._kpi({"critical_above": 100, "color_on_value": True})
        assert k.threshold.color_on_value is True

    def test_partial_threshold_ok(self):
        k = self._kpi({"warn_above": 50})
        assert k.threshold.warn_above == 50
        assert k.threshold.critical_above is None

    def test_non_numeric_bounds_dropped(self):
        k = self._kpi({"warn_above": "high", "critical_above": 100})
        assert k.threshold.warn_above is None
        assert k.threshold.critical_above == 100

    def test_empty_threshold_object_becomes_none(self):
        # An object with no useful bounds is functionally absent — drop
        # so the composer never emits a hollow shape.
        k = self._kpi({})
        assert k.threshold is None

    def test_threshold_roundtrip_carries_camel_and_snake(self):
        k = self._kpi({"warn_above": 50, "critical_above": 100, "color_on_value": True})
        d = k.to_dict()
        assert d["threshold"] == {
            "warn_above": 50, "critical_above": 100, "color_on_value": True,
        }


# ─────────────────────────── extremes ────────────────────────────────


class TestExtremesParsing:
    def _kpi(self, extremes: dict) -> KPISpec:
        raw = {"kpis": [{"label": "Debt", "entity": "loan", "op": "sum",
                         "field": "principal", "extremes": extremes}]}
        m = DashboardMaquette.from_dict(raw)
        return m.kpis[0]

    def test_max_and_min_parse(self):
        k = self._kpi({"max_label": "Single Max Debt", "min_label": "Single Min Debt"})
        e = k.extremes
        assert e is not None
        assert e.max_label == "Single Max Debt"
        assert e.min_label == "Single Min Debt"

    def test_only_max_ok(self):
        k = self._kpi({"max_label": "Peak"})
        assert k.extremes.max_label == "Peak"
        assert k.extremes.min_label is None

    def test_missing_both_labels_becomes_none(self):
        k = self._kpi({})
        assert k.extremes is None

    def test_non_string_labels_dropped(self):
        k = self._kpi({"max_label": 42, "min_label": "OK"})
        # 42 dropped, "OK" retained
        assert k.extremes.max_label is None
        assert k.extremes.min_label == "OK"


# ─────────────────────────── back-compat ────────────────────────────


class TestBackCompat:
    def test_kpi_without_anatomy_parses_unchanged(self):
        raw = {"kpis": [{"label": "Total", "entity": "invoice", "op": "sum",
                         "field": "amount"}]}
        m = DashboardMaquette.from_dict(raw)
        k = m.kpis[0]
        assert k.breakdown == []
        assert k.threshold is None
        assert k.extremes is None

    def test_legacy_to_dict_shape_only_grows_when_anatomy_present(self):
        # A KPI with no anatomy must not emit anatomy keys; downstream
        # JSON diffs stay clean when the LLM omits them.
        raw = {"kpis": [{"label": "T", "entity": "e", "op": "count"}]}
        d = DashboardMaquette.from_dict(raw).kpis[0].to_dict()
        assert "breakdown" not in d
        assert "threshold" not in d
        assert "extremes" not in d
