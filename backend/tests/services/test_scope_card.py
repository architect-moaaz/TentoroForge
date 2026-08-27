"""Tests for services.scope_card — Layer 2 manifest derivation.

Pins the visual-product-search prompt to a small, expected manifest so any
regression that re-inflates page counts fails the test.
"""
from __future__ import annotations

import pytest

from services.locked_spec import build_locked_spec
from services.scope_card import (
    Manifest,
    Page,
    build_manifest,
    build_and_persist_from_spec,
    load_manifest,
    persist_manifest,
)


VISUAL_PRODUCT_SEARCH = (
    "Mobile-first app where a user scans a product with their phone camera "
    "or uploads an image. The app identifies the exact or similar-looking "
    "product using AI, then shows price comparison across retailers using "
    "the Firecrawl web-search MCP with tappable links to each seller. "
    "Admin can control the retailer allow-list (enable/disable, priority). "
    "Store scan history per user."
)


def test_manifest_visual_product_search_has_bounded_page_count():
    """Regression: nni3wjf6 generated 41 pages. The manifest must produce
    ~10-14 pages max (list+detail for events, full CRUD for managed entities,
    2 auth pages, custom action pages for scan/compare)."""
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    manifest = build_manifest(spec)
    # Anchor: never more than ~20 pages for this prompt. If this fails,
    # the extractor probably classified an actor as an entity or vice versa.
    assert len(manifest.pages) <= 20, \
        f"expected <=20 pages, got {len(manifest.pages)}: {[p.path for p in manifest.pages]}"
    # And at least the load-bearing pages must be there.
    paths = {p.path for p in manifest.pages}
    assert "/scans" in paths, "scan history list missing"
    assert "/scans/[id]" in paths, "scan detail missing"
    assert "/retailers" in paths, "retailer list missing"
    assert "/retailers/new" in paths, "retailer create missing"
    assert "/login" in paths, "login page missing (per-user scoping detected)"


def test_manifest_events_never_get_create_or_edit():
    """Scans are events — they're produced by the system (scan workflow),
    never authored by a user editing a form. The manifest must not include
    /scans/new or /scans/[id]/edit."""
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    manifest = build_manifest(spec)
    paths = {p.path for p in manifest.pages}
    assert "/scans/new" not in paths, \
        "events must not get create pages — scans are recorded, not authored"
    assert "/scans/[id]/edit" not in paths, \
        "events must not get edit pages"


def test_manifest_managed_entities_get_full_crud():
    """Retailer is a managed entity → full CRUD."""
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    manifest = build_manifest(spec)
    paths = {p.path for p in manifest.pages}
    assert "/retailers" in paths
    assert "/retailers/[id]" in paths
    assert "/retailers/new" in paths
    assert "/retailers/[id]/edit" in paths


def test_manifest_never_creates_pages_for_actors():
    """User/Admin are roles, not entities. No /users, /admins, etc."""
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    manifest = build_manifest(spec)
    paths = {p.path for p in manifest.pages}
    for bad in ("/users", "/admins", "/admin", "/customers"):
        assert bad not in paths, f"actor page {bad} leaked into manifest"


def test_manifest_tables_match_entity_kinds():
    """entities_with_tables must include managed + event entities only."""
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    manifest = build_manifest(spec)
    tables = set(manifest.entities_with_tables)
    assert "Retailer" in tables
    assert "Scan" in tables
    # Actors and externals stay out.
    assert "User" not in tables
    assert "Admin" not in tables
    assert "Firecrawl" not in tables


def test_manifest_workflows_only_for_managed_entities():
    """Events don't get Create/Update/Delete workflows — the recording is
    done by the app's own workflow (ScanProductWorkflow), not by a CRUD form."""
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    manifest = build_manifest(spec)
    workflows = set(manifest.workflows)
    assert "CreateRetailer" in workflows
    assert "UpdateRetailer" in workflows
    assert "DeleteRetailer" in workflows
    assert "CreateScan" not in workflows, \
        "scans are events — no CreateScan workflow"


def test_persist_and_load_manifest(tmp_path):
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    manifest = build_manifest(spec)
    persist_manifest(manifest, tmp_path)
    loaded = load_manifest(tmp_path)
    assert loaded is not None
    assert loaded.to_dict() == manifest.to_dict()


def test_build_and_persist_returns_none_without_spec(tmp_path):
    """When locked_spec.json doesn't exist, don't crash — just return None
    so callers can fall back to the legacy pipeline path."""
    result = build_and_persist_from_spec(tmp_path)
    assert result is None
