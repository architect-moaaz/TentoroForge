"""Documents written before the workflow node catalog still load — rewritten
into its vocabulary, once, with every rewrite reported."""
import json

from services.blueprint.migrations import migrate, migrate_workflow_vocabulary
from services.blueprint.service import BlueprintService


def _old_doc():
    return {"workflows": [{
        "id": "FLOW-001", "name": "Post a role",
        "trigger": {"kind": "event", "detail": "role.posted"},
        "steps": [
            {"key": "start", "name": "Start", "type": "start", "next": ["validate"]},
            {"key": "validate", "name": "Validate", "type": "condition",
             "config": {"expression": "title != ''", "trueBranch": "create", "falseBranch": "show_errors"},
             "next": ["show_errors", "create"]},
            {"key": "show_errors", "name": "Show errors", "type": "notification",
             "config": {"channel": "in_app"}, "next": ["start"]},
            {"key": "create", "name": "Create", "type": "action", "config": {"api": "API-001"}, "next": ["review"]},
            {"key": "review", "name": "Review", "type": "human_task", "next": ["wait"]},
            {"key": "wait", "name": "Cool off", "type": "timer", "next": ["sync"]},
            {"key": "sync", "name": "Sync", "type": "integration", "next": ["done"]},
            {"key": "done", "name": "Done", "type": "end"},
        ],
    }]}


def test_old_words_become_catalog_nodes_and_branches_become_next_order():
    doc = _old_doc()
    changed = migrate_workflow_vocabulary(doc)
    wf = doc["workflows"][0]
    by = {s["key"]: s for s in wf["steps"]}

    assert wf["trigger"]["kind"] == "api_event"
    assert "start" not in by
    assert by["review"]["type"] == "user_task"
    assert by["wait"]["type"] == "wait"
    assert by["show_errors"]["type"] == "action"
    assert by["show_errors"]["config"] == {"channel": "in_app", "actionType": "send_notification"}
    assert by["sync"]["config"]["actionType"] == "http_call"
    # then first, else second; the old keys are gone
    assert by["validate"]["next"] == ["create", "show_errors"]
    assert "trueBranch" not in by["validate"]["config"]
    # an edge back to the dropped start now points at what start pointed at
    assert by["show_errors"]["next"] == ["validate"]
    assert len(changed) >= 7


def test_migration_is_idempotent():
    doc = _old_doc()
    migrate(doc)
    once = json.dumps(doc, sort_keys=True)
    assert migrate(doc) == []
    assert json.dumps(doc, sort_keys=True) == once


def test_load_applies_migrations(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="R", domain="ATS")
    svc.doc["workflows"] = _old_doc()["workflows"]
    # Written raw — as a pre-catalog run would have left it.
    svc.current_path.write_text(json.dumps(svc.doc), "utf-8")

    loaded = BlueprintService.load(output_dir=tmp_path)
    types = {s["type"] for s in loaded.doc["workflows"][0]["steps"]}
    assert "human_task" not in types and "start" not in types
    loaded.validate()
