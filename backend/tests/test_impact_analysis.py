"""Impact / blast-radius analysis over a generated app.

Every test constructs a tiny fixture app on ``tmp_path`` with a small
registry + one or two schema/workflow files, then asserts the report
names exactly the artifacts the fixture wired up. False-positive bias:
missed hits are worse than double-counting."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services.impact_analysis import analyze_impact, ImpactReport


# =========================================================================
# Fixture helpers
# =========================================================================

def _write_app(tmp_path: Path) -> Path:
    """A small but realistic app: Candidate entity with a file-shaped
    FK, a create/detail page pair, one workflow that reads the field,
    one api route registered."""
    (tmp_path / "src" / "schemas" / "candidates").mkdir(parents=True)
    (tmp_path / "workflows").mkdir()
    (tmp_path / "contracts").mkdir()

    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "Candidate": {
                "fields": {
                    "id": {"type": "uuid"},
                    "firstName": {"type": "varchar"},
                    "latestCvAttachmentId": {"type": "uuid"},
                },
                "names": {
                    "entity": "Candidate", "tableSnake": "candidates",
                    "sourceName": "candidates", "routeSlug": "candidates",
                    "binding": "candidates", "label": "Candidates",
                    "labelSingular": "Candidate",
                },
            },
            "FileAttachment": {
                "fields": {"id": {"type": "uuid"}, "url": {"type": "varchar"}},
                "names": {
                    "entity": "FileAttachment", "tableSnake": "file_attachments",
                    "sourceName": "fileAttachments", "routeSlug": "file-attachments",
                    "binding": "fileAttachments", "label": "File Attachments",
                    "labelSingular": "File Attachment",
                },
            },
        },
        "relations": [
            {"from_entity": "Candidate", "to_entity": "FileAttachment",
             "type": "many-to-one", "foreignKey": "latestCvAttachmentId"},
        ],
        "api_routes": {
            "POST /api/data/candidates": {"entity": "Candidate", "method": "POST"},
            "GET /api/data/candidates":  {"entity": "Candidate", "method": "GET"},
        },
        "pages": {},
        "components": {},
        "workflow_bindings": {},
        "rules": {},
    }))

    # Create page — writes latestCvAttachmentId via a Select node.
    (tmp_path / "src" / "schemas" / "candidates" / "new.json").write_text(json.dumps({
        "route": "/candidates/new",
        "dataSources": [
            {"name": "fileAttachments", "entity": "FileAttachment", "op": "list"},
        ],
        "root": {
            "type": "Stack", "children": [
                {"type": "Form", "props": {}, "children": [
                    {"type": "Input",  "props": {"name": "firstName"}},
                    {"type": "Select", "props": {
                        "name": "latestCvAttachmentId",
                        "label": "Latest CV Attachment",
                        "optionsFrom": {"source": "fileAttachments", "value": "id", "label": "url"},
                    }},
                ]},
            ],
        },
    }))

    # Detail page — reads {{candidates[0].latestCvAttachmentId}}
    (tmp_path / "src" / "schemas" / "candidates" / "[id].json").write_text(json.dumps({
        "route": "/candidates/[id]",
        "dataSources": [
            {"name": "candidates", "entity": "Candidate", "op": "get"},
        ],
        "root": {
            "type": "Stack", "children": [
                {"type": "Text", "props": {
                    "content": "CV file id: {{candidates[0].latestCvAttachmentId}}",
                }},
                {"type": "Button", "props": {
                    "label": "Process CV", "actions": [
                        {"workflow": "process_cv", "label": "Process CV"},
                    ],
                }},
            ],
        },
    }))

    # Workflow — reads {{input.latestCvAttachmentId}} in a db_update.
    (tmp_path / "workflows" / "process_cv.json").write_text(json.dumps({
        "id": "process_cv",
        "nodes": [
            {"id": "trigger", "type": "trigger",
             "data": {"config": {"inputs": [{"name": "latestCvAttachmentId", "type": "uuid"}]}}},
            {"id": "update", "type": "action",
             "data": {"actionType": "db_update",
                      "config": {"table": "candidates",
                                 "where": {"id": "{{input.candidateId}}"},
                                 "values": {"cvProcessedAt": "{{now}}",
                                            "attachment": "{{input.latestCvAttachmentId}}"}}}},
        ],
    }))

    (tmp_path / "contracts" / "action-contract.json").write_text(json.dumps({
        "actions": [{"entity": "Candidate", "action": "create"}],
    }))
    return tmp_path


# =========================================================================
# entity + field target
# =========================================================================

def test_impact_of_entity_field_names_all_dependents(tmp_path):
    _write_app(tmp_path)
    r = analyze_impact(str(tmp_path), target={
        "entity": "Candidate", "field": "latestCvAttachmentId",
    })

    # Create page writes the field via a Form → Select with matching name.
    writers = [p["path"] for p in r.pages_writing]
    assert "src/schemas/candidates/new.json" in writers, writers

    # Detail page reads the field via {{candidates[0].latestCvAttachmentId}}.
    readers = [p["path"] for p in r.pages_reading]
    assert "src/schemas/candidates/[id].json" in readers, readers

    # Workflow reads the field via {{input.latestCvAttachmentId}}.
    wf_read_ids = {w["id"] for w in r.workflows_reading}
    assert "process_cv" in wf_read_ids, wf_read_ids

    # API routes on the entity are surfaced.
    assert any("/api/data/candidates" in a["route"] for a in r.api_routes_touching)

    # Contracts touched.
    assert "contracts/action-contract.json" in r.contracts_impacted

    # File-shaped name → env note.
    assert "FORGE_UPLOAD_DIR" in r.env_requirements


def test_impact_of_entity_only_no_field_lists_all_page_reads(tmp_path):
    """Without a `field`, every page reading ANY of the entity's data
    is listed — this is the coarser view for entity-level changes."""
    _write_app(tmp_path)
    r = analyze_impact(str(tmp_path), target={"entity": "Candidate"})
    readers = [p["path"] for p in r.pages_reading]
    assert "src/schemas/candidates/[id].json" in readers


def test_impact_of_unknown_entity_returns_empty_with_note(tmp_path):
    _write_app(tmp_path)
    r = analyze_impact(str(tmp_path), target={"entity": "NoSuchEntity"})
    assert r.pages_reading == [] and r.workflows_reading == []
    assert any("not in registry" in n for n in r.notes)


# =========================================================================
# page target
# =========================================================================

def test_impact_of_page_lists_workflows_it_fires(tmp_path):
    _write_app(tmp_path)
    r = analyze_impact(str(tmp_path), target={"page": "candidates/[id]"})
    fired = {w["id"] for w in r.workflows_writing}
    assert "process_cv" in fired


def test_impact_of_page_lists_entities_it_reads(tmp_path):
    _write_app(tmp_path)
    r = analyze_impact(str(tmp_path), target={"page": "candidates/[id]"})
    entities = {p["entity"] for p in r.pages_reading if "entity" in p}
    assert "Candidate" in entities


# =========================================================================
# workflow target
# =========================================================================

def test_impact_of_workflow_names_pages_that_fire_it(tmp_path):
    _write_app(tmp_path)
    r = analyze_impact(str(tmp_path), target={"workflow": "process_cv"})
    paths = {p["path"] for p in r.pages_writing}
    assert "src/schemas/candidates/[id].json" in paths


def test_impact_of_workflow_names_entities_it_writes(tmp_path):
    _write_app(tmp_path)
    r = analyze_impact(str(tmp_path), target={"workflow": "process_cv"})
    writes = [w for w in r.workflows_writing if w.get("action") == "db_update"]
    assert writes
    assert writes[0]["table"] == "candidates"


# =========================================================================
# Robustness
# =========================================================================

def test_missing_output_dir_returns_empty_with_note():
    r = analyze_impact("/nonexistent/path", target={"entity": "Candidate"})
    assert r.pages_reading == []
    assert any("not found" in n for n in r.notes)


def test_invalid_target_returns_empty_with_note(tmp_path):
    _write_app(tmp_path)
    r = analyze_impact(str(tmp_path), target={"foo": "bar"})
    assert any("target must contain" in n for n in r.notes)


def test_summary_names_at_least_one_dependent(tmp_path):
    _write_app(tmp_path)
    r = analyze_impact(str(tmp_path), target={
        "entity": "Candidate", "field": "latestCvAttachmentId",
    })
    s = r.summary()
    assert "candidates/new" in s or "candidates/[id]" in s
    assert "process_cv" in s
