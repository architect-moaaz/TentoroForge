"""Tests for the launcher↔workflow record-input contract (both halves).

Half 1 — plan_validator._rule_launcher_supplies_record_inputs: the plan
must declare, on every launcher of a record-scoped workflow, where the
record id comes from (requires_record or input_map). Feeds REVISE.

Half 2 — action_contract_guard.backfill_record_button_args: the
materializer completes bare workflow Buttons on record pages with
``args[var] = "{{<source>.id}}"`` derived from the workflow's own
where-clause bindings (the atb0m97x "Reprocess → WHERE id is empty"
class).
"""
from __future__ import annotations

import json
from pathlib import Path


# ─────────────────────── half 1: validator rule ─────────────────────────

def _record_workflow(name: str = "ReprocessDocumentWorkflow") -> dict:
    return {
        "name": name,
        "steps": [
            {"id": "t", "type": "trigger",
             "config": {"inputs": [{"name": "documentId"}]}},
            {"id": "reset", "type": "action",
             "config": {"actionType": "db_update", "table": "documents",
                        "where": {"id": "{{documentId}}"},
                        "values": {"status": "queued"}}},
        ],
    }


def _plan(action: dict) -> dict:
    return {
        "data_models": [{"name": "Document", "fields": []}],
        "workflows": [_record_workflow()],
        "pages": [{"name": "Document Detail", "route": "/documents/[id]",
                   "type": "detail", "entity": "Document",
                   "actions": [action]}],
    }


def test_bare_launcher_flagged():
    from services.plan_validator import validate_plan
    vs = validate_plan(_plan({"label": "Reprocess",
                              "workflow": "ReprocessDocumentWorkflow"}))
    hits = [v for v in vs if v["rule"] == "launcher_missing_record_input"]
    assert len(hits) == 1
    assert "documentId" in hits[0]["message"]
    assert "requires_record" in hits[0]["message"]


def test_requires_record_satisfies():
    from services.plan_validator import validate_plan
    vs = validate_plan(_plan({"label": "Reprocess",
                              "workflow": "ReprocessDocumentWorkflow",
                              "requires_record": True}))
    assert not any(v["rule"] == "launcher_missing_record_input" for v in vs)


def test_input_map_satisfies():
    from services.plan_validator import validate_plan
    vs = validate_plan(_plan({"label": "Reprocess",
                              "workflow": "ReprocessDocumentWorkflow",
                              "input_map": {"documentId": "record.id"}}))
    assert not any(v["rule"] == "launcher_missing_record_input" for v in vs)


def test_actor_fk_input_not_demanded():
    """uploadedById is a user FK, not the record's identity — the rule
    must not force requires_record for it."""
    from services.plan_validator import validate_plan
    wf = {
        "name": "NotifyUploader",
        "steps": [
            {"id": "t", "type": "trigger",
             "config": {"inputs": [{"name": "uploadedById"}]}},
            {"id": "n", "type": "action",
             "config": {"actionType": "send_notification",
                        "table": "documents"}},
        ],
    }
    plan = _plan({"label": "Notify", "workflow": "NotifyUploader"})
    plan["workflows"] = [wf]
    vs = validate_plan(plan)
    assert not any(v["rule"] == "launcher_missing_record_input" for v in vs)


def test_create_workflow_not_demanded():
    """A pure-create workflow has no record identity to supply."""
    from services.plan_validator import validate_plan
    wf = {
        "name": "CreateDocument",
        "steps": [
            {"id": "t", "type": "trigger", "config": {"inputs": []}},
            {"id": "i", "type": "action",
             "config": {"actionType": "db_insert", "table": "documents",
                        "values": {"status": "queued"}}},
        ],
    }
    plan = _plan({"label": "New", "workflow": "CreateDocument"})
    plan["workflows"] = [wf]
    vs = validate_plan(plan)
    assert not any(v["rule"] == "launcher_missing_record_input" for v in vs)


# ─────────────────────── half 2: args backfill ──────────────────────────

def _mk_app(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    (root / "workflows").mkdir(parents=True)
    (root / "src" / "schemas" / "documents").mkdir(parents=True)

    (root / "workflows" / "ReprocessDocumentWorkflow.json").write_text(json.dumps({
        "name": "ReprocessDocumentWorkflow",
        "definition": {"nodes": [
            {"id": "trigger", "type": "trigger",
             "data": {"nodeType": "trigger", "config": {}}},
            {"id": "reset", "type": "action",
             "data": {"nodeType": "action",
                      "config": {"actionType": "db_update",
                                 "table": "documents",
                                 "where": {"id": "{{documentId}}"},
                                 "values": {"status": "queued"}}}},
        ], "edges": []},
    }))

    (root / "src" / "schemas" / "documents" / "[id].json").write_text(json.dumps({
        "id": "documents-id", "route": "/documents/[id]",
        "dataSources": [{"name": "document", "entity": "Document",
                         "op": "get", "id": "{{route.id}}"}],
        "root": {"type": "Stack", "children": [
            {"type": "Button",
             "props": {"label": "Reprocess Document",
                       "workflow": "ReprocessDocumentWorkflow"}},
            {"type": "Button",
             "props": {"label": "Back", "navigate": "/documents"}},
        ]},
    }))
    return root


def _button(root: Path, label: str) -> dict:
    doc = json.loads(
        (root / "src" / "schemas" / "documents" / "[id].json").read_text())
    for c in doc["root"]["children"]:
        if c.get("props", {}).get("label") == label:
            return c
    raise AssertionError(f"button {label!r} not found")


def test_bare_button_gets_record_id_arg(tmp_path):
    from services.action_contract_guard import backfill_record_button_args
    root = _mk_app(tmp_path)
    rep = backfill_record_button_args(str(root))
    assert rep["summary"]["buttons_patched"] == 1
    btn = _button(root, "Reprocess Document")
    assert btn["props"]["args"] == {"documentId": "{{document.id}}"}


def test_nav_button_untouched(tmp_path):
    from services.action_contract_guard import backfill_record_button_args
    root = _mk_app(tmp_path)
    backfill_record_button_args(str(root))
    assert "args" not in _button(root, "Back")["props"]


def test_existing_args_not_overwritten(tmp_path):
    from services.action_contract_guard import backfill_record_button_args
    root = _mk_app(tmp_path)
    p = root / "src" / "schemas" / "documents" / "[id].json"
    doc = json.loads(p.read_text())
    doc["root"]["children"][0]["props"]["args"] = {"documentId": "{{custom}}"}
    p.write_text(json.dumps(doc))
    rep = backfill_record_button_args(str(root))
    assert rep["summary"]["buttons_patched"] == 0
    assert _button(root, "Reprocess Document")["props"]["args"] == \
        {"documentId": "{{custom}}"}


def test_list_page_without_get_source_skipped(tmp_path):
    from services.action_contract_guard import backfill_record_button_args
    root = _mk_app(tmp_path)
    (root / "src" / "schemas" / "documents.json").write_text(json.dumps({
        "id": "documents", "route": "/documents",
        "dataSources": [{"name": "documents", "entity": "Document",
                         "op": "list"}],
        "root": {"type": "Stack", "children": [
            {"type": "Button",
             "props": {"label": "Reprocess All",
                       "workflow": "ReprocessDocumentWorkflow"}},
        ]},
    }))
    rep = backfill_record_button_args(str(root))
    # only the detail-page button patched; the list-page one has no
    # record context to bind
    assert rep["summary"]["buttons_patched"] == 1
    lst = json.loads((root / "src" / "schemas" / "documents.json").read_text())
    assert "args" not in lst["root"]["children"][0]["props"]


def test_idempotent(tmp_path):
    from services.action_contract_guard import backfill_record_button_args
    root = _mk_app(tmp_path)
    backfill_record_button_args(str(root))
    rep2 = backfill_record_button_args(str(root))
    assert rep2["summary"]["buttons_patched"] == 0
