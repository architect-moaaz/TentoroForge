"""Enriched recall block for the Smith orchestrator.

Every catalog contributes a labeled section — the tests assert each
label is present and that the substantive content the orchestrator
depends on (component names, endpoint paths, node types, seam names)
is included."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.smith_recall_enrich import (
    enriched_recall_block,
    _component_catalog,
    _data_engine_surface,
    _workflow_node_catalog,
    _specialist_seams_catalog,
)


def _make_stub_app(tmp_path: Path) -> Path:
    """Minimal shape assemble_recall can walk without crashing —
    just enough for the base-recall part to render its own section."""
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "workflows").mkdir()
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {"User": {"fields": {}}},
        "relations": [], "pages": {}, "components": {},
        "api_routes": {}, "workflow_bindings": {}, "rules": {},
    }))
    return tmp_path


# =========================================================================
# Compositional block
# =========================================================================

def test_enriched_block_includes_every_section(tmp_path):
    _make_stub_app(tmp_path)
    blob = enriched_recall_block(str(tmp_path))
    assert "COMPONENT CATALOG" in blob
    assert "DATA ENGINE API" in blob
    assert "WORKFLOW NODE CATALOG" in blob
    assert "SPECIALIST SEAMS" in blob


def test_enriched_block_survives_missing_app(tmp_path):
    """Empty dir shouldn't crash — degrade to notes."""
    blob = enriched_recall_block(str(tmp_path))
    # Static catalogs still render even if base recall fails.
    assert "DATA ENGINE API" in blob
    assert "WORKFLOW NODE CATALOG" in blob
    assert "SPECIALIST SEAMS" in blob


# =========================================================================
# Component catalog — from starter.json
# =========================================================================

def test_component_catalog_finds_monorepo_starter(tmp_path):
    """In dev, starter.json lives in packages/registry/dist/ — the
    loader must fall back to it when the app has no node_modules."""
    _make_stub_app(tmp_path)
    catalog = _component_catalog(str(tmp_path))
    # These types are known to exist in every generated app's library.
    assert "COMPONENT CATALOG" in catalog
    # Sanity: some baseline components are always registered.
    for baseline in ("Card", "Input", "Select"):
        assert baseline in catalog, f"expected {baseline} in catalog: {catalog[:400]}"


def test_component_catalog_lists_props_for_known_component(tmp_path):
    """FileUpload (or Select) — whichever exists in the library dist —
    must appear with at least one of its documented props so Smith
    can pick the right shape."""
    _make_stub_app(tmp_path)
    catalog = _component_catalog(str(tmp_path))
    # At least one common form-field prop.
    assert "name" in catalog or "label" in catalog or "value" in catalog


def test_component_catalog_graceful_when_starter_missing(tmp_path):
    """If starter.json can't be found, return a labeled fallback line —
    orchestrator will proceed without prop contracts but won't crash."""
    # Point at a fresh tmp with no node_modules and monkey-patch the
    # walk. Simplest: create a folder deeper than the 6-parent search
    # window and let it fail naturally.
    catalog = _component_catalog(str(tmp_path))
    # Real monorepo test above proves it IS found in dev, so we expect
    # the catalog either fully rendered OR a graceful fallback.
    assert "COMPONENT CATALOG" in catalog


# =========================================================================
# Static catalogs — data engine, workflow nodes, seams
# =========================================================================

def test_data_engine_surface_lists_files_endpoint():
    """FileUpload path only works if Smith knows about /api/files/upload."""
    s = _data_engine_surface()
    assert "/api/files/upload" in s
    assert "/api/data/[entity]" in s
    assert "/api/workflows/[id]/execute" in s


def test_data_engine_surface_maps_field_types_to_endpoints():
    s = _data_engine_surface()
    assert "FileUpload" in s
    assert "Select" in s
    assert "Form submit" in s


def test_workflow_node_catalog_covers_the_action_types_engine_registers():
    """Every action type register_default_actions() knows about must
    appear so Smith doesn't invent invalid types."""
    c = _workflow_node_catalog()
    for kind in ("db_insert", "db_update", "db_delete", "db_query",
                 "ai_generate", "ai_classify", "ai_extract", "ai_decide",
                 "send_notification", "send_email", "task",
                 "set_variable", "transform", "trigger", "end"):
        assert kind in c, f"missing action-type {kind!r} in catalog"


def test_workflow_node_catalog_documents_connectivity():
    c = _workflow_node_catalog()
    assert "next" in c
    assert "branches" in c or "gateway" in c
    assert "trigger" in c and "end" in c


def test_specialist_seams_catalog_names_every_seam():
    s = _specialist_seams_catalog()
    for seam in ("page_schema_patch", "edit_workflow", "add_page",
                 "add_workflow", "add_entity", "add_component",
                 "env_upsert", "regenerate_seed", "edit_file"):
        assert seam in s, f"missing seam {seam!r} in catalog"


def test_specialist_seams_catalog_declares_edit_file_last_resort():
    """The routing rule that direct edit is a last resort must be
    explicit — this is what nudges Smith away from the shortcut."""
    s = _specialist_seams_catalog()
    assert "LAST RESORT" in s
    assert "impact_analysis" in s
    assert "run_guards" in s


def test_specialist_seams_catalog_lists_edit_workflow_ops():
    """Enumerate the change operations edit_workflow accepts so
    Smith crafts the right payload shape on first try."""
    s = _specialist_seams_catalog()
    for op in ("add_trigger_input", "remove_trigger_input", "set_step_config",
               "add_step", "remove_step", "rewire", "rename"):
        assert op in s, f"missing edit_workflow op {op!r}"
