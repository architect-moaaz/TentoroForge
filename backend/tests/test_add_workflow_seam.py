"""S5-T4 — `add_workflow` seam tests. Same shape as test_add_page_seam."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.add_workflow_seam import (
    AddWorkflowError,
    DETERMINISTIC_OPS,
    build_add_workflow_bundle,
)


def _seed_app(tmp_path: Path, entity: str = "Candidate") -> Path:
    (tmp_path / "contracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "workflows").mkdir(parents=True, exist_ok=True)
    (tmp_path / "contracts" / "resource-registry.json").write_text(
        json.dumps({
            "version": "1.0",
            "entities": [{
                "name":  entity,
                "table": entity.lower() + "s",
                "fields": [
                    {"name": "id",        "type": "uuid", "notNull": True},
                    {"name": "firstName", "type": "varchar", "notNull": True},
                    {"name": "email",     "type": "varchar", "notNull": True},
                ],
            }],
            "relationships": [], "roles": [], "interactions": [],
        })
    )
    return tmp_path


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #

def test_create_op_bundle_writes_correct_workflow_file(tmp_path):
    app = _seed_app(tmp_path, "Candidate")
    ops = build_add_workflow_bundle(str(app), op="create", entity="Candidate")
    assert len(ops) == 1
    assert ops[0].path == "workflows/CreateCandidate.json"
    wf = json.loads(ops[0].content)
    # crud_workflow_generator uses a slug-shaped id (create-candidate); the
    # human-facing basename is what we've asserted above.
    assert wf["id"], "workflow must have an id"
    assert wf["definition"]["nodes"], "generator should emit at least one node"


def test_op_and_entity_are_case_insensitive(tmp_path):
    app = _seed_app(tmp_path, "Candidate")
    ops = build_add_workflow_bundle(str(app), op="CREATE", entity="candidate")
    assert ops[0].path == "workflows/CreateCandidate.json"


def test_update_and_delete_ops_produce_distinct_files(tmp_path):
    app = _seed_app(tmp_path, "Candidate")
    for op, expected in (("update", "UpdateCandidate.json"),
                          ("delete", "DeleteCandidate.json")):
        ops = build_add_workflow_bundle(str(app), op=op, entity="Candidate")
        assert ops[0].path == f"workflows/{expected}"


def test_custom_name_wins(tmp_path):
    app = _seed_app(tmp_path, "Candidate")
    ops = build_add_workflow_bundle(
        str(app), op="create", entity="Candidate",
        name="BulkImportCandidate",
    )
    assert ops[0].path == "workflows/BulkImportCandidate.json"


# --------------------------------------------------------------------------- #
# Error paths
# --------------------------------------------------------------------------- #

def test_refuses_non_deterministic_op(tmp_path):
    app = _seed_app(tmp_path)
    with pytest.raises(AddWorkflowError, match=r"deterministic|Supported"):
        build_add_workflow_bundle(str(app), op="approve", entity="Candidate")


def test_refuses_unknown_entity(tmp_path):
    app = _seed_app(tmp_path, "Candidate")
    with pytest.raises(AddWorkflowError, match=r"entity 'NoSuch' not found"):
        build_add_workflow_bundle(str(app), op="create", entity="NoSuch")


def test_refuses_existing_workflow_file(tmp_path):
    app = _seed_app(tmp_path, "Candidate")
    (app / "workflows" / "CreateCandidate.json").write_text("{}")
    with pytest.raises(AddWorkflowError, match=r"already exists"):
        build_add_workflow_bundle(str(app), op="create", entity="Candidate")


def test_refuses_missing_output_dir(tmp_path):
    with pytest.raises(AddWorkflowError, match=r"output_dir missing"):
        build_add_workflow_bundle(
            str(tmp_path / "not-a-dir"),
            op="create", entity="Candidate",
        )


def test_deterministic_ops_are_lowercase_and_hyphen_free():
    assert DETERMINISTIC_OPS
    for op in DETERMINISTIC_OPS:
        assert op == op.lower() and "-" not in op and " " not in op
