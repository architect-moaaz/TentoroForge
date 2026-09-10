"""Blueprint ↔ app-registry reconciliation.

Post-generate hook: after every build, sync what Smith *thinks* is
in the app with what actually landed on disk. Additive (adds new
things, logs orphans, never deletes)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint_backfill import (
    ReconcileResult,
    reconcile_blueprint_with_registry,
)
from services.smith_blueprint import Blueprint


def _write_registry(root: Path, data: dict) -> None:
    p = root / "contracts" / "resource-registry.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


def _seed_bp(tmp_path, entities=None, workflows=None, pages=None) -> Blueprint:
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    for e in (entities or []):
        bp.add_entity(name=e, table=e.lower(), purpose="", key_fields=[], why_shaped_this_way="")
    for w in (workflows or []):
        bp.add_workflow(name=w, purpose="", trigger="", why="")
    for p in (pages or []):
        bp.add_page(route=p, schema_path="", role="", notable_choices=[])
    bp.save()
    return bp


# --------------------------------------------------------------------------- #
# Additions
# --------------------------------------------------------------------------- #

def test_registry_has_new_entity_blueprint_learns_it(tmp_path):
    _seed_bp(tmp_path, entities=["Candidate"])
    _write_registry(tmp_path, {
        "entities": [
            {"name": "Candidate", "table": "candidates", "columns": [{"name": "email"}]},
            {"name": "User", "table": "users", "columns": [{"name": "email"}]},
        ],
    })

    r = reconcile_blueprint_with_registry(project_id="p1", output_dir=str(tmp_path))
    assert r.reconciled is True
    assert r.entities_added == 1
    assert r.entities_orphaned == []

    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    names = {e["name"] for e in bp.entities}
    assert names == {"Candidate", "User"}


def test_registry_workflows_and_pages_also_added(tmp_path):
    _seed_bp(tmp_path)
    _write_registry(tmp_path, {
        "entities": [],
        "workflows": [{"name": "CreateCandidate", "trigger": {"type": "form_submit"}}],
        "pages": [{"route": "/candidates", "schema_path": "src/schemas/candidates/index.json"}],
    })

    r = reconcile_blueprint_with_registry(project_id="p1", output_dir=str(tmp_path))
    assert r.workflows_added == 1
    assert r.pages_added == 1


# --------------------------------------------------------------------------- #
# Orphans — Blueprint has it, registry doesn't
# --------------------------------------------------------------------------- #

def test_blueprint_orphan_entity_reported_not_deleted(tmp_path):
    _seed_bp(tmp_path, entities=["Candidate", "GhostEntity"])
    _write_registry(tmp_path, {
        "entities": [{"name": "Candidate", "table": "candidates"}],
    })

    r = reconcile_blueprint_with_registry(project_id="p1", output_dir=str(tmp_path))
    assert r.entities_orphaned == ["GhostEntity"]

    # Still in blueprint — reconcile never deletes.
    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    names = {e["name"] for e in bp.entities}
    assert "GhostEntity" in names


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #

def test_reconcile_is_idempotent_when_already_in_sync(tmp_path):
    _seed_bp(tmp_path, entities=["Candidate"])
    _write_registry(tmp_path, {
        "entities": [{"name": "Candidate", "table": "candidates"}],
    })

    r1 = reconcile_blueprint_with_registry(project_id="p1", output_dir=str(tmp_path))
    assert r1.entities_added == 0
    assert r1.entities_orphaned == []
    # Second call should be a no-op with the "already in sync" reason.
    r2 = reconcile_blueprint_with_registry(project_id="p1", output_dir=str(tmp_path))
    assert r2.entities_added == 0
    assert "sync" in r2.reason.lower()


def test_reconcile_missing_registry_returns_error_not_raise(tmp_path):
    _seed_bp(tmp_path)  # no registry file written
    r = reconcile_blueprint_with_registry(project_id="p1", output_dir=str(tmp_path))
    assert r.reconciled is False
    assert "not found" in r.reason.lower()


def test_reconcile_malformed_registry_returns_error(tmp_path):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "resource-registry.json").write_text("{ not json", encoding="utf-8")
    _seed_bp(tmp_path)
    r = reconcile_blueprint_with_registry(project_id="p1", output_dir=str(tmp_path))
    assert r.reconciled is False
    assert "unreadable" in r.reason.lower()


# --------------------------------------------------------------------------- #
# Change-log entry
# --------------------------------------------------------------------------- #

def test_reconcile_records_change_log_entry_on_diff(tmp_path):
    _seed_bp(tmp_path, entities=["Candidate"])
    _write_registry(tmp_path, {
        "entities": [
            {"name": "Candidate", "table": "candidates"},
            {"name": "User", "table": "users"},
        ],
    })

    reconcile_blueprint_with_registry(project_id="p1", output_dir=str(tmp_path))

    bp = Blueprint.load(project_id="p1", output_dir=str(tmp_path))
    # There should be a change_log entry describing the reconcile.
    reconcile_entries = [
        e for e in bp.change_log
        if "reconcile" in e.get("smith_move", "").lower()
    ]
    assert len(reconcile_entries) >= 1
    assert "+1 entities" in reconcile_entries[-1]["diff_summary"]
