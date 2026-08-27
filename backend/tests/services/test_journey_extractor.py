"""Unit tests for the archetype-aware journey extractor.

Cover per-archetype extractors + the page-shape fallback that picks a
route when the plan has no explicit app-level `archetype`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.journey_verifier.extractor import (
    _detect_archetype_from_pages,
    extract,
)


def _make_app(tmp_path: Path, plan: dict) -> Path:
    app = tmp_path / "app"
    app.mkdir()
    (app / "plan.json").write_text(json.dumps(plan))
    return app


def test_detect_kanban_from_page_archetype():
    plan = {"pages": [
        {"name": "Board", "route": "/board", "archetype": "kanban"},
    ]}
    assert _detect_archetype_from_pages(plan) == "kanban"


def test_detect_ecommerce_from_cart_entity():
    plan = {"entities": {"products": {}, "forge_cart": {}}}
    assert _detect_archetype_from_pages(plan) == "ecommerce"


def test_detect_recruitment_from_candidate_entity():
    plan = {"entities": {"candidates": {}}}
    assert _detect_archetype_from_pages(plan) == "recruitment"


def test_detect_crud_write_when_new_route_present():
    plan = {"pages": [
        {"route": "/orders", "archetype": "list"},
        {"route": "/orders/new", "archetype": "form"},
    ]}
    assert _detect_archetype_from_pages(plan) == "crud_write"


def test_detect_returns_none_when_bare_list_only():
    # Only a read-only list — no writable form, no domain hint. Fallback
    # to the generic smoke test kicks in downstream.
    plan = {"pages": [{"route": "/reports", "archetype": "list"}]}
    assert _detect_archetype_from_pages(plan) is None


def test_extract_kanban_journey(tmp_path):
    plan = {"pages": [
        {"name": "Board", "route": "/board", "archetype": "kanban"},
    ]}
    app = _make_app(tmp_path, plan)
    spec = extract(app)
    assert any("kanban" in j.slug for j in spec.journeys)
    board_j = next(j for j in spec.journeys if "kanban" in j.slug)
    routes = [s.route for s in board_j.steps if s.route]
    assert "/board" in routes


def test_extract_crud_write_synthesizes_field_fills(tmp_path):
    # crud_write should visit /orders/new and issue at least one fill step
    # for the varchar column, then click the form-submit CTA.
    plan = {
        "pages": [
            {"route": "/orders/new", "archetype": "form", "name": "New Order"},
        ],
        "entities": {"Order": {
            "fields": [
                {"name": "customer_name", "type": "varchar"},
                {"name": "quantity", "type": "int"},
                {"name": "created_at", "type": "timestamp"},
            ],
        }},
    }
    app = _make_app(tmp_path, plan)
    spec = extract(app)
    j = next((j for j in spec.journeys if "crud-write" in j.slug), None)
    assert j is not None, f"no crud-write journey emitted; got {[x.slug for x in spec.journeys]}"
    kinds = [s.kind for s in j.steps]
    assert "fill" in kinds
    # Submit step targets the form-submit slug so it survives label drift.
    submit = next(s for s in j.steps if s.kind == "click")
    assert submit.locator and submit.locator.journey_slug == "form-submit"


def test_extract_ecommerce_journey(tmp_path):
    plan = {"entities": {"products": {"fields": []}, "forge_cart": {"fields": []}}}
    app = _make_app(tmp_path, plan)
    spec = extract(app)
    assert any(j.slug == "ecommerce-add-to-cart" for j in spec.journeys)


def test_extract_recruitment_journey(tmp_path):
    plan = {"entities": {
        "candidates": {"fields": [{"name": "name", "type": "varchar"}]},
    }}
    app = _make_app(tmp_path, plan)
    spec = extract(app)
    assert any(j.slug == "recruitment-add-candidate" for j in spec.journeys)


def test_extract_falls_back_to_smoke_when_nothing_detectable(tmp_path):
    plan = {"pages": [], "entities": {}}
    app = _make_app(tmp_path, plan)
    spec = extract(app)
    assert len(spec.journeys) >= 1
    # Absolute floor: at least the smoke journey.
    assert any("smoke" in j.slug or "crud" in j.slug for j in spec.journeys)


def test_extract_still_prefers_declared_archetype(tmp_path):
    # An explicit `archetype: visual_product_search` at the app level wins
    # over any page-shape detection.
    plan = {
        "archetype": "visual_product_search",
        "pages": [{"route": "/board", "archetype": "kanban"}],
        "entities": {"scan_sessions": {}, "price_results": {}},
    }
    app = _make_app(tmp_path, plan)
    spec = extract(app)
    assert any(j.slug == "primary-scan" for j in spec.journeys)
