"""Blueprint backfill — Migration Step 5.

For projects that were generated BEFORE the Blueprint existed, we
need to seed an initial `.forge/blueprint.json` from whatever we can
read (registry, schemas, workflows). Best-effort — the resulting
blueprint has whatever detail the existing artifacts contain, and
Smith's future turns fill in `why` fields as they land.

The backfill is idempotent: re-running is safe and skips projects
that already have a blueprint (unless `force=True`).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.smith_blueprint import Blueprint
from services.blueprint_backfill import (
    backfill_project_blueprint,
    BackfillResult,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

def _make_project(tmp_path: Path) -> Path:
    """A minimal generated-app-shaped directory: a registry, one
    schema, one workflow."""
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps({
        "entities": [
            {"name": "Candidate", "table": "candidates",
             "columns": [{"name": "email"}, {"name": "firstName"}]},
            {"name": "Assessor", "table": "assessors",
             "columns": [{"name": "email"}]},
        ],
        "workflows": [
            {"id": "CreateCandidate", "name": "CreateCandidate"},
        ],
        "pages": [
            {"route": "/candidates", "schema_path": "src/schemas/candidates/index.json"},
            {"route": "/candidates/new", "schema_path": "src/schemas/candidates/new.json"},
        ],
    }))
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "CreateCandidate.json").write_text(json.dumps({
        "id": "CreateCandidate", "trigger": {"type": "form_submit"},
        "nodes": [], "edges": [],
    }))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "schemas").mkdir()
    return tmp_path


# --------------------------------------------------------------------------- #
# Backfill behaviour
# --------------------------------------------------------------------------- #

def test_backfill_creates_blueprint_from_registry_when_missing(tmp_path):
    _make_project(tmp_path)
    result = backfill_project_blueprint(project_id="p1", output_dir=str(tmp_path))
    assert result.created is True

    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    entity_names = {e["name"] for e in bp.entities}
    assert entity_names == {"Candidate", "Assessor"}
    workflow_names = {w["name"] for w in bp.workflows}
    assert "CreateCandidate" in workflow_names
    routes = {p["route"] for p in bp.pages}
    assert routes == {"/candidates", "/candidates/new"}


def test_backfill_is_idempotent_by_default(tmp_path):
    _make_project(tmp_path)
    r1 = backfill_project_blueprint(project_id="p1", output_dir=str(tmp_path))
    assert r1.created is True

    # Second run does nothing — a real blueprint exists now.
    r2 = backfill_project_blueprint(project_id="p1", output_dir=str(tmp_path))
    assert r2.created is False
    assert r2.reason == "blueprint already exists"


def test_backfill_force_rewrites_existing_blueprint(tmp_path):
    _make_project(tmp_path)
    backfill_project_blueprint(project_id="p1", output_dir=str(tmp_path))

    r = backfill_project_blueprint(
        project_id="p1", output_dir=str(tmp_path), force=True,
    )
    assert r.created is True


def test_backfill_records_external_change_log_entry(tmp_path):
    _make_project(tmp_path)
    backfill_project_blueprint(project_id="p1", output_dir=str(tmp_path))

    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert bp.change_log
    entry = bp.change_log[0]
    assert entry["source"] == "external"
    assert "backfill" in entry["smith_move"].lower()


def test_backfill_missing_registry_returns_result_with_reason(tmp_path):
    """A project with no registry can't be backfilled — report and skip."""
    result = backfill_project_blueprint(project_id="p1", output_dir=str(tmp_path))
    assert result.created is False
    assert "registry" in result.reason.lower()


def test_backfill_domain_left_none_when_unknown(tmp_path):
    """We can't infer a domain name from the registry alone. Domain
    stays None; the next Smith turn's discovery run fills it in
    (or a later slice adds a domain-heuristic pass)."""
    _make_project(tmp_path)
    backfill_project_blueprint(project_id="p1", output_dir=str(tmp_path))
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    assert bp.domain is None or (bp.domain and not bp.domain.get("name"))
