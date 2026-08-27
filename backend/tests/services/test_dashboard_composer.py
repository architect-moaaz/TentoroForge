"""Tests for services.dashboard_composer — Spec C1.

Compiler + validator for the planner-emitted `dashboard_composition`
intent block. Pure module; no disk I/O; no LLM.
"""
from __future__ import annotations

import json
import pytest

from services.dashboard_composer import (
    KNOWN_CALCS,
    KNOWN_LAYOUTS,
    collect_violations,
    compose_dashboard,
)


def _entities() -> dict:
    return {
        "Unit": {"fields": {
            "id": {"type": "uuid"},
            "status": {"type": "varchar"},
            "propertyId": {"type": "uuid"},
        }},
        "RentPayment": {"fields": {
            "id": {"type": "uuid"},
            "amount": {"type": "numeric"},
            "status": {"type": "varchar"},
            "paidDate": {"type": "date"},
        }},
        "MaintenanceTicket": {"fields": {
            "id": {"type": "uuid"},
            "status": {"type": "varchar"},
        }},
    }


def _components() -> set:
    return {"Table", "Kanban", "Heatmap", "Chart", "Stat", "Card"}


# ────────────────────────────────────────────────────────────
# Vocabulary
# ────────────────────────────────────────────────────────────

class TestVocabulary:
    def test_known_calcs_include_the_six_advertised(self):
        for c in ("count", "sum", "ratio", "avg", "min", "max"):
            assert c in KNOWN_CALCS

    def test_known_layouts_include_default(self):
        assert "kpi_row_over_two_column_widgets" in KNOWN_LAYOUTS


# ────────────────────────────────────────────────────────────
# Compose — happy path
# ────────────────────────────────────────────────────────────

class TestComposeHappyPath:
    def test_compiles_valid_stat_tiles_to_stat_cards(self):
        page = compose_dashboard(
            {"tiles": [
                {"kind": "stat", "label": "Total Units",
                 "calc": "count", "entity": "unit"},
                {"kind": "stat", "label": "Rent Collected",
                 "calc": "sum", "entity": "rent_payment", "field": "amount"},
            ], "widgets": []},
            entities=_entities(),
            component_names=_components(),
        )
        # Root Stack → Grid of stat cards.
        assert page["type"] == "Stack"
        grid = page["children"][0]
        assert grid["type"] == "Grid"
        # Was `cols` — a prop Grid never read, so this pinned a two-up KPI
        # row that actually rendered stacked. Grid reads `columns`.
        assert grid["props"]["columns"] == 2
        assert "cols" not in grid["props"]
        # First tile: Card wrapping Stat bound to a REAL named source.
        first = grid["children"][0]
        assert first["type"] == "Card"
        stat = first["children"][0]
        assert stat["type"] == "Stat"
        assert stat["props"]["label"] == "Total Units"
        assert stat["props"]["value"].startswith("{{")

    def test_tiles_author_named_data_sources(self):
        sources: list = []
        compose_dashboard(
            {"tiles": [
                {"kind": "stat", "label": "Total Units",
                 "calc": "count", "entity": "unit"},
            ], "widgets": []},
            entities=_entities(),
            component_names=_components(),
            data_sources=sources,
        )
        assert len(sources) == 1
        assert sources[0]["entity"] == "Unit"  # canonical
        assert sources[0]["op"] == "count"
        assert sources[0]["name"]

    def test_compiles_widgets_below_kpi_row(self):
        page = compose_dashboard(
            {"tiles": [
                {"kind": "stat", "label": "N", "calc": "count", "entity": "Unit"},
            ], "widgets": [
                {"component": "Table", "title": "Recent Payments",
                 "bindsTo": "rent_payment", "sort": "paidDate desc", "limit": 5},
            ], "layout": "kpi_row_over_two_column_widgets"},
            entities=_entities(),
            component_names=_components(),
        )
        # Two rows in the Stack: KPI grid + widgets grid.
        assert page["children"][0]["type"] == "Grid"  # KPIs
        widgets_grid = page["children"][1]
        assert widgets_grid["type"] == "Grid"
        card = widgets_grid["children"][0]
        assert card["type"] == "Card"
        table = card["children"][-1]
        assert table["type"] == "Table"
        # Contract-complete: columns [{key,label}] + a rows binding.
        assert table["props"]["columns"]
        assert all("key" in c and "label" in c for c in table["props"]["columns"])
        assert table["props"]["rows"].startswith("{{")

    def test_table_widget_authors_list_data_source(self):
        sources: list = []
        compose_dashboard(
            {"tiles": [], "widgets": [
                {"component": "Table", "title": "Recent Payments",
                 "bindsTo": "rent_payment", "limit": 5},
            ], "layout": "widgets_only"},
            entities=_entities(),
            component_names=_components(),
            data_sources=sources,
        )
        assert len(sources) == 1
        assert sources[0]["entity"] == "RentPayment"
        assert sources[0]["op"] == "list"
        assert sources[0]["limit"] == 5

    def test_entity_folding_is_case_and_snake_case_tolerant(self):
        page = compose_dashboard(
            {"tiles": [
                {"kind": "stat", "label": "Tix", "calc": "count",
                 "entity": "maintenance_ticket"},
            ]},
            entities=_entities(),
            component_names=_components(),
        )
        sources: list = []
        page = compose_dashboard(
            {"tiles": [
                {"kind": "stat", "label": "Tix", "calc": "count",
                 "entity": "maintenance_ticket"},
            ]},
            entities=_entities(),
            component_names=_components(),
            data_sources=sources,
        )
        assert sources[0]["entity"] == "MaintenanceTicket"


# ────────────────────────────────────────────────────────────
# Repair — never silently drop
# ────────────────────────────────────────────────────────────

class TestRepair:
    def test_unknown_entity_becomes_missing_marker_not_dropped(self):
        page = compose_dashboard(
            {"tiles": [
                {"kind": "stat", "label": "Ghost", "calc": "count",
                 "entity": "ghost_entity"},
            ]},
            entities=_entities(),
            component_names=_components(),
        )
        stat = page["children"][0]["children"][0]["children"][0]
        assert stat["props"]["value"] == "—"
        assert "[missing]" in stat["props"]["hint"]
        assert "ghost_entity" in stat["props"]["hint"]

    def test_unknown_calc_becomes_missing_marker(self):
        page = compose_dashboard(
            {"tiles": [
                {"kind": "stat", "label": "X", "calc": "median",
                 "entity": "Unit"},
            ]},
            entities=_entities(),
            component_names=_components(),
        )
        stat = page["children"][0]["children"][0]["children"][0]
        assert "[missing]" in stat["props"]["hint"]
        assert "median" in stat["props"]["hint"]

    def test_unknown_widget_component_swapped_to_table(self):
        page = compose_dashboard(
            {"widgets": [
                {"component": "SankeyDiagram3D", "title": "Flow",
                 "bindsTo": "RentPayment"},
            ]},
            entities=_entities(),
            component_names=_components(),
        )
        w = page["children"][0]["children"][0]
        assert w["type"] == "Table"   # fallback
        assert "[missing]" in w["props"]["hint"]

    def test_field_reference_that_doesnt_exist_becomes_missing(self):
        page = compose_dashboard(
            {"tiles": [
                {"kind": "stat", "label": "Sum",
                 "calc": "sum", "entity": "Unit", "field": "nonexistent"},
            ]},
            entities=_entities(),
            component_names=_components(),
        )
        stat = page["children"][0]["children"][0]["children"][0]
        assert "[missing]" in stat["props"]["hint"]

    def test_empty_composition_returns_emptystate_page(self):
        page = compose_dashboard(
            {"tiles": [], "widgets": []},
            entities=_entities(),
            component_names=_components(),
        )
        assert page["children"][0]["type"] == "EmptyState"

    def test_all_broken_still_returns_a_page(self):
        page = compose_dashboard(
            {"tiles": [
                {"kind": "stat", "calc": "count", "entity": "ghost1"},
                {"kind": "stat", "calc": "count", "entity": "ghost2"},
            ]},
            entities=_entities(),
            component_names=_components(),
        )
        # Two [missing] cards, but the page renders.
        assert page["type"] == "Stack"
        assert len(page["children"][0]["children"]) == 2


# ────────────────────────────────────────────────────────────
# Layouts
# ────────────────────────────────────────────────────────────

class TestLayouts:
    def test_unknown_layout_falls_back_to_default(self):
        page = compose_dashboard(
            {"tiles": [
                {"kind": "stat", "label": "N", "calc": "count", "entity": "Unit"}],
             "widgets": [{"component": "Table", "bindsTo": "Unit"}],
             "layout": "bogus"},
            entities=_entities(),
            component_names=_components(),
        )
        # Default = KPI row over 2-col widgets grid; still emits both.
        assert page["children"][0]["type"] == "Grid"
        assert page["children"][1]["type"] == "Grid"

    def test_kpi_grid_only_omits_widgets(self):
        page = compose_dashboard(
            {"tiles": [
                {"kind": "stat", "label": "N", "calc": "count", "entity": "Unit"}],
             "widgets": [{"component": "Table", "bindsTo": "Unit"}],
             "layout": "kpi_grid_only"},
            entities=_entities(),
            component_names=_components(),
        )
        assert len(page["children"]) == 1  # KPI grid only

    def test_widgets_only_omits_kpis(self):
        page = compose_dashboard(
            {"tiles": [
                {"kind": "stat", "label": "N", "calc": "count", "entity": "Unit"}],
             "widgets": [{"component": "Table", "bindsTo": "Unit"}],
             "layout": "widgets_only"},
            entities=_entities(),
            component_names=_components(),
        )
        # KPI Stack shouldn't be present — just the widgets grid. Widgets
        # now wrap in titled Cards too, so detect KPIs by their Stat child.
        types = [c["type"] for c in page["children"]]
        assert "Grid" in types
        blob = json.dumps(page)
        assert '"Stat"' not in blob  # no KPI cards
        assert '"Table"' in blob     # the widget landed


# ────────────────────────────────────────────────────────────
# collect_violations — for the plan validator REVISE loop
# ────────────────────────────────────────────────────────────

class TestCollectViolations:
    def test_clean_composition_returns_empty(self):
        assert collect_violations(
            {"tiles": [
                {"kind": "stat", "label": "N", "calc": "count", "entity": "Unit"}]},
            entities=_entities(),
            component_names=_components(),
        ) == []

    def test_none_composition_is_clean(self):
        assert collect_violations(None, entities=_entities(), component_names=_components()) == []

    def test_reports_every_broken_ref(self):
        vs = collect_violations(
            {"tiles": [
                {"kind": "stat", "label": "A", "calc": "count", "entity": "ghost"},
                {"kind": "stat", "label": "B", "calc": "sum", "entity": "Unit", "field": "nope"},
             ],
             "widgets": [{"component": "Ghost", "bindsTo": "Unit"}],
             "layout": "bogus"},
            entities=_entities(),
            component_names=_components(),
        )
        assert any("ghost" in v for v in vs)
        assert any("nope" in v for v in vs)
        assert any("Ghost" in v for v in vs)
        assert any("bogus" in v for v in vs)

    def test_non_dict_composition_is_a_violation(self):
        vs = collect_violations("not-a-dict", entities=_entities(), component_names=_components())
        assert len(vs) == 1


# ────────────────────────────────────────────────────────────
# Determinism
# ────────────────────────────────────────────────────────────

class TestDeterministic:
    def test_same_input_same_output(self):
        comp = {"tiles": [
            {"kind": "stat", "label": "N", "calc": "count", "entity": "Unit"}]}
        a = compose_dashboard(comp, entities=_entities(), component_names=_components())
        b = compose_dashboard(comp, entities=_entities(), component_names=_components())
        assert a == b
