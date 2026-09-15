"""remove_entity / remove_workflow — the removal siblings of add_entity/add_workflow.

Source surgery only; the cascade (orphaned pages/workflows/relationships, controls
that named the gone workflow) is the completeness checks' job.
"""
import json
from pathlib import Path

import pytest

from services.remove_entity_seam import (
    build_remove_entity_bundle, RemoveEntityError, dependents,
)
from services.remove_workflow_seam import (
    build_remove_workflow_bundle, RemoveWorkflowError,
)


@pytest.fixture()
def app(tmp_path):
    (tmp_path / "contracts").mkdir()
    (tmp_path / "src" / "db" / "schema").mkdir(parents=True)
    (tmp_path / "workflows").mkdir()
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps({"entities": [
        {"name": "Draft", "slug": "drafts", "table": "drafts",
         "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]},
        {"name": "User", "slug": "users", "table": "users",
         "fields": [{"name": "id", "type": "uuid"}, {"name": "passwordHash", "type": "varchar"}]}]}))
    (tmp_path / "src" / "db" / "schema" / "drafts.ts").write_text("export const drafts = 1;\n")
    (tmp_path / "src" / "db" / "schema" / "index.ts").write_text(
        'export { draft } from "./drafts";\nexport { user } from "./users";\n')
    (tmp_path / "workflows" / "DeleteDraft.json").write_text(
        json.dumps({"id": "DeleteDraft", "name": "Delete Draft"}))
    return tmp_path


def _apply(app, ops):
    for op in ops:
        p = app / op.path
        if op.kind == "delete":
            if p.exists():
                p.unlink()
        else:
            p.write_text(op.content)


def test_remove_entity_drops_registry_module_and_barrel(app):
    _apply(app, build_remove_entity_bundle(str(app), entity="Draft"))
    reg = json.loads((app / "contracts" / "resource-registry.json").read_text())
    assert [e["name"] for e in reg["entities"]] == ["User"]
    assert not (app / "src" / "db" / "schema" / "drafts.ts").exists()
    assert "drafts" not in (app / "src" / "db" / "schema" / "index.ts").read_text()
    assert "users" in (app / "src" / "db" / "schema" / "index.ts").read_text()


def test_remove_entity_refuses_the_auth_entity(app):
    with pytest.raises(RemoveEntityError, match="auth-managed"):
        build_remove_entity_bundle(str(app), entity="User")


def test_remove_entity_unknown_is_refused(app):
    with pytest.raises(RemoveEntityError, match="not found"):
        build_remove_entity_bundle(str(app), entity="Nope")


def test_dependents_lists_the_cascade():
    doc = {
        "pages": [{"id": "P1", "route": "/drafts", "data": {"primaryEntity": "Draft"}}],
        "workflows": [{"id": "W1", "name": "Publish Draft",
                       "inputs": [{"entity": "Draft", "kind": "record"}]}],
        "data": {"relationships": [{"from": "Draft", "to": "Author"}]},
    }
    deps = dependents(doc, "Draft")
    assert any("page /drafts" in d for d in deps)
    assert any("Publish Draft" in d for d in deps)
    assert any("Draft" in d and "Author" in d for d in deps)


def test_remove_workflow_deletes_the_file(app):
    ops = build_remove_workflow_bundle(str(app), workflow_id="DeleteDraft")
    assert ops and ops[0].kind == "delete"
    _apply(app, ops)
    assert not (app / "workflows" / "DeleteDraft.json").exists()


def test_remove_workflow_unknown_is_refused(app):
    with pytest.raises(RemoveWorkflowError, match="not found"):
        build_remove_workflow_bundle(str(app), workflow_id="Ghost")
