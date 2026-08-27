"""Tests for ``dashboard_page_composer`` — the deterministic sub-dashboard
composer that owns every dashboard-typed page beyond the landing one.

Root symptom this cures: on dz6jba0x, the LLM authored
``src/schemas/mrr-movement.json`` with an ``op:"aggregate"`` dataSource that
was missing its ``metrics`` block, and Chart nodes bound to unresolved
series dataSources. This module runs BEFORE the LLM's schema for those
routes ships (and post-hoc rewrites the file when it did), emitting
inline-dataSource nodes that can't have the drift class at all.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.dashboard_page_composer import (
    compose_sub_dashboards,
    plan_page_to_composition,
)


# ────────────────────────────────────────────────────────────
# Fixtures — the mrr-movement bug shape, verbatim to dz6jba0x
# ────────────────────────────────────────────────────────────

_REGISTRY = {
    "entities": {
        "MonthlyMrrSnapshot": {
            "fields": {
                "id": {"type": "uuid"},
                "year": {"type": "integer"},
                "month": {"type": "integer"},
                "totalMrr": {"type": "decimal"},
                "newMrr": {"type": "decimal"},
                "expansionMrr": {"type": "decimal"},
                "contractionMrr": {"type": "decimal"},
                "churnedMrr": {"type": "decimal"},
            }
        },
        "MrrEvent": {
            "fields": {
                "id": {"type": "uuid"},
                "kind": {"type": "varchar"},
                "amount": {"type": "decimal"},
                "occurredAt": {"type": "timestamp"},
            }
        },
    }
}


_PLAN_PAGE_MRR_MOVEMENT = {
    "name": "MrrMovementPage",
    "type": "dashboard",
    "archetype": "report",
    "route": "/mrr-movement",
    "entity": "MrrEvent",
    "widgets": [
        {
            "type": "chart",
            "entity": "MrrEvent",
            "title": "MRR Waterfall (12 months)",
            "groupBy": "occurredAt",
            "bucket": "month",
        },
        {
            "type": "chart",
            "entity": "MrrEvent",
            "title": "MRR Movement by Type",
            "groupBy": "kind",
        },
        {
            "type": "table",
            "entity": "MonthlyMrrSnapshot",
            "title": "Monthly Breakdown",
            "limit": 12,
            "columns": ["year", "month", "newMrr", "expansionMrr", "churnedMrr"],
        },
    ],
}


_PLAN = {
    "pages": [
        {"name": "Home", "type": "dashboard", "route": "/", "widgets": []},
        _PLAN_PAGE_MRR_MOVEMENT,
        {"name": "CustomersList", "type": "list", "route": "/customers", "entity": "MrrEvent"},
    ],
    "entities": [
        {"name": "MonthlyMrrSnapshot", "fields": [
            {"name": "newMrr"}, {"name": "expansionMrr"},
            {"name": "contractionMrr"}, {"name": "churnedMrr"}, {"name": "totalMrr"},
        ]},
        {"name": "MrrEvent", "fields": [
            {"name": "kind"}, {"name": "amount"}, {"name": "occurredAt"},
        ]},
    ],
}


_COMPONENT_NAMES = {"Chart", "Table", "Card", "Stack", "Grid", "Stat", "MetricTile", "EmptyState"}


# ────────────────────────────────────────────────────────────
# plan_page_to_composition — pure conversion
# ────────────────────────────────────────────────────────────

class TestPlanPageToComposition:
    def test_widgets_convert_type_to_component(self):
        comp = plan_page_to_composition(_PLAN_PAGE_MRR_MOVEMENT)
        widgets = comp.get("widgets", [])
        components = [w["component"] for w in widgets]
        # capitalises + maps: chart -> Chart, table -> Table
        assert components == ["Chart", "Chart", "Table"]

    def test_widgets_preserve_entity_as_bindsTo(self):
        comp = plan_page_to_composition(_PLAN_PAGE_MRR_MOVEMENT)
        assert all(w["bindsTo"] in {"MrrEvent", "MonthlyMrrSnapshot"} for w in comp["widgets"])

    def test_widgets_preserve_title_groupBy_limit(self):
        comp = plan_page_to_composition(_PLAN_PAGE_MRR_MOVEMENT)
        w0 = comp["widgets"][0]
        assert w0["title"] == "MRR Waterfall (12 months)"
        assert w0["groupBy"] == "occurredAt"
        assert w0.get("bucket") == "month"
        w2 = comp["widgets"][2]
        assert w2["limit"] == 12

    def test_no_tiles_by_default_when_plan_has_no_metrics_hint(self):
        comp = plan_page_to_composition(_PLAN_PAGE_MRR_MOVEMENT)
        assert comp.get("tiles", []) == []

    def test_tiles_emitted_when_plan_metrics_present(self):
        page = {
            **_PLAN_PAGE_MRR_MOVEMENT,
            "metrics": [
                {"label": "New MRR", "entity": "MonthlyMrrSnapshot",
                 "calc": "sum", "field": "newMrr"},
                {"label": "Churn", "entity": "MonthlyMrrSnapshot",
                 "calc": "sum", "field": "churnedMrr"},
            ],
        }
        comp = plan_page_to_composition(page)
        tiles = comp["tiles"]
        assert len(tiles) == 2
        assert tiles[0]["label"] == "New MRR"
        assert tiles[0]["calc"] == "sum"
        assert tiles[0]["field"] == "newMrr"

    def test_empty_widgets_returns_valid_composition_dict(self):
        comp = plan_page_to_composition({"type": "dashboard", "widgets": []})
        assert isinstance(comp, dict)
        assert comp.get("widgets", []) == []


# ────────────────────────────────────────────────────────────
# compose_sub_dashboards — end-to-end
# ────────────────────────────────────────────────────────────

def _write_project(tmp_path: Path, plan: dict, registry: dict = _REGISTRY,
                   existing_schemas: dict[str, dict] | None = None) -> Path:
    root = tmp_path
    contracts = root / "src" / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    (contracts / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    (contracts / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    if existing_schemas:
        sdir = root / "src" / "schemas"
        sdir.mkdir(parents=True, exist_ok=True)
        for name, schema in existing_schemas.items():
            (sdir / name).write_text(json.dumps(schema), encoding="utf-8")
    return root


class TestComposeSubDashboards:
    def test_writes_schema_for_mrr_movement(self, tmp_path):
        root = _write_project(tmp_path, _PLAN)
        res = compose_sub_dashboards(str(root), component_names=_COMPONENT_NAMES)
        assert res["composed"] >= 1
        out = root / "src" / "schemas" / "mrr-movement.json"
        assert out.is_file()

    def test_landing_dashboard_is_skipped(self, tmp_path):
        """/, /home, /dashboard, /overview go through the landing composer
        (apply_dashboard_maquette). This composer must NOT touch them."""
        root = _write_project(tmp_path, _PLAN)
        compose_sub_dashboards(str(root), component_names=_COMPONENT_NAMES)
        landing = root / "src" / "schemas" / "home.json"
        assert not landing.exists()  # never authored by this pass

    def test_non_dashboard_pages_are_skipped(self, tmp_path):
        root = _write_project(tmp_path, _PLAN)
        compose_sub_dashboards(str(root), component_names=_COMPONENT_NAMES)
        customers = root / "src" / "schemas" / "customers.json"
        assert not customers.exists()

    def test_composed_schema_has_no_aggregate_metrics_drift(self, tmp_path):
        """The whole point: emitted schemas must NOT contain an op:"aggregate"
        dataSource without a metrics block. Inline-dataSource style
        sidesteps the class entirely."""
        root = _write_project(tmp_path, _PLAN)
        compose_sub_dashboards(str(root), component_names=_COMPONENT_NAMES)
        schema = json.loads(
            (root / "src" / "schemas" / "mrr-movement.json").read_text(encoding="utf-8")
        )

        def _walk_aggregates(node):
            if isinstance(node, dict):
                ds = node.get("dataSource")
                if isinstance(ds, dict) and ds.get("op") == "aggregate":
                    yield ds
                for c in node.get("children") or []:
                    yield from _walk_aggregates(c)
            elif isinstance(node, list):
                for c in node:
                    yield from _walk_aggregates(c)

        # No top-level aggregate dataSources (composer uses inline scalar shape).
        for ds in schema.get("dataSources", []) or []:
            assert ds.get("op") != "aggregate", (
                "composer must not emit top-level aggregate dataSources — "
                "use inline {op:sum|max|avg, field} on Stat instead"
            )
        # Any inline aggregate must NOT reference dotted keys against undefined
        # metrics blocks — the inline shape has entity/op/field flat.
        for ds in _walk_aggregates(schema):
            assert "metrics" not in ds or ds["metrics"], (
                "inline aggregate must have metrics or none at all — not empty {}"
            )

    def test_composed_schema_uses_real_entities(self, tmp_path):
        root = _write_project(tmp_path, _PLAN)
        compose_sub_dashboards(str(root), component_names=_COMPONENT_NAMES)
        text = (root / "src" / "schemas" / "mrr-movement.json").read_text(encoding="utf-8")
        # Real entities from the plan are referenced.
        assert "MrrEvent" in text or "MonthlyMrrSnapshot" in text

    def test_idempotent_second_run(self, tmp_path):
        root = _write_project(tmp_path, _PLAN)
        r1 = compose_sub_dashboards(str(root), component_names=_COMPONENT_NAMES)
        path = root / "src" / "schemas" / "mrr-movement.json"
        first = path.read_text(encoding="utf-8")
        r2 = compose_sub_dashboards(str(root), component_names=_COMPONENT_NAMES)
        second = path.read_text(encoding="utf-8")
        assert first == second
        # Second run is a no-op — nothing to write, so composed=0.
        assert r2["composed"] == 0
        assert r1["composed"] >= 1

    def test_no_plan_no_crash(self, tmp_path):
        # empty project — no contracts dir at all.
        res = compose_sub_dashboards(str(tmp_path), component_names=_COMPONENT_NAMES)
        assert res["composed"] == 0
        assert "reason" in res

    def test_overwrites_llm_authored_schema_with_broken_aggregate(self, tmp_path):
        """When the LLM's mrr-movement.json is on disk with the exact
        aggregate-without-metrics bug, this composer overwrites it."""
        broken_schema = {
            "id": "MrrMovementPage",
            "route": "/mrr-movement",
            "root": {"type": "Stack", "children": []},
            "dataSources": [
                # The dz6jba0x bug shape verbatim: aggregate op, no metrics.
                {"name": "mrrSummary", "entity": "MonthlyMrrSnapshot",
                 "op": "aggregate"},
            ],
        }
        root = _write_project(
            tmp_path, _PLAN,
            existing_schemas={"mrr-movement.json": broken_schema},
        )
        compose_sub_dashboards(str(root), component_names=_COMPONENT_NAMES)
        composed = json.loads(
            (root / "src" / "schemas" / "mrr-movement.json").read_text(encoding="utf-8")
        )
        # Broken top-level aggregate is gone.
        for ds in composed.get("dataSources", []) or []:
            assert ds.get("op") != "aggregate"

    def test_preserves_shape_expected_by_renderer(self, tmp_path):
        root = _write_project(tmp_path, _PLAN)
        compose_sub_dashboards(str(root), component_names=_COMPONENT_NAMES)
        schema = json.loads(
            (root / "src" / "schemas" / "mrr-movement.json").read_text(encoding="utf-8")
        )
        # Renderer contract: id, route, root with type + children.
        assert schema.get("id")
        assert schema.get("route") == "/mrr-movement"
        assert schema["root"]["type"] in {"Stack", "Grid"}
        assert isinstance(schema["root"].get("children", []), list)
