"""Tests for the post-generation action-contract reconciler (Slice 3)."""
from __future__ import annotations

import json
import os

from services.action_contract_guard import reconcile_action_contract


# ── fixtures ─────────────────────────────────────────────────────────────────

_SCHEMA_TS = """\
import { pgTable, uuid, varchar, integer, boolean, timestamp } from "drizzle-orm/pg-core";

export const applications = pgTable("applications", {
  id: uuid("id").primaryKey().defaultRandom(),
  candidateId: uuid("candidate_id"),
  status: varchar("status", { length: 50 }),
  stage: varchar("stage", { length: 50 }),
  notes: varchar("notes", { length: 255 }),
  createdAt: timestamp("created_at"),
});
"""

# A manual create workflow (db_insert only) — does NOT require a record.
_CREATE_WF = {
    "id": "create-application",
    "name": "CreateApplication",
    "definition": {
        "trigger": {"type": "manual"},
        "nodes": [
            {
                "id": "db_insert",
                "type": "action",
                "data": {
                    "config": {
                        "actionType": "db_insert",
                        "table": "applications",
                        "values": {
                            "candidateId": "candidateId",
                            "status": "status",
                            "stage": "stage",
                            "notes": "notes",
                        },
                    }
                },
            }
        ],
    },
}

# An event-driven workflow (db_change trigger) — REQUIRES a record.
_EVENT_WF = {
    "id": "shortlisting",
    "name": "ShortlistingWorkflow",
    "definition": {
        "trigger": {"type": "db_change"},
        "steps": [
            {
                "id": "mark",
                "type": "action",
                "config": {
                    "actionType": "db_update",
                    "table": "applications",
                    "where": {"id": "{{id}}"},
                    "values": {"status": "status", "stage": "stage"},
                },
                "next": "end",
            },
            {"id": "end", "type": "end"},
        ],
    },
}


def _mkapp(tmp_path, *, pages: dict, workflows: dict) -> str:
    out = os.path.join(str(tmp_path), "app")
    os.makedirs(os.path.join(out, "src", "db", "schema"), exist_ok=True)
    os.makedirs(os.path.join(out, "src", "schemas"), exist_ok=True)
    os.makedirs(os.path.join(out, "workflows"), exist_ok=True)
    with open(os.path.join(out, "src", "db", "schema", "applications.ts"), "w") as fh:
        fh.write(_SCHEMA_TS)
    for name, doc in workflows.items():
        with open(os.path.join(out, "workflows", name), "w") as fh:
            json.dump(doc, fh)
    for name, doc in pages.items():
        fp = os.path.join(out, "src", "schemas", name)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "w") as fh:
            json.dump(doc, fh)
    return out


def _load_contract(out: str) -> dict:
    with open(os.path.join(out, "contracts", "action-contract.json")) as fh:
        return json.load(fh)


# ── derivation ───────────────────────────────────────────────────────────────

def test_form_input_map_is_derived_from_matching_fields(tmp_path):
    page = {
        "route": "/applications/new",
        "root": {
            "type": "Form",
            "props": {"workflow": "CreateApplication", "submitLabel": "Create Application"},
            "children": [
                {"type": "Select", "props": {"name": "candidateId"}},
                {"type": "Input", "props": {"name": "status"}},
                {"type": "Input", "props": {"name": "stage"}},
                {"type": "Input", "props": {"name": "somethingElse"}},
            ],
        },
    }
    out = _mkapp(tmp_path, pages={"applications/new.json": page},
                 workflows={"CreateApplication.json": _CREATE_WF})
    res = reconcile_action_contract(out)
    assert res["resolved"] == 1 and res["unresolved"] == 0
    contract = _load_contract(out)
    action = contract["actions"][0]
    assert action["workflow_id"] == "create-application"
    assert action["kind"] == "form_submit"
    # Fields matching real input columns are mapped; the extra one is unmapped.
    assert action["input_map"] == {
        "candidateId": "candidateId", "status": "status", "stage": "stage"
    }
    assert action["unmapped_fields"] == ["somethingElse"]
    # A plain create does not require a record.
    assert action["requires_record"] is False


def test_bogus_declared_input_map_column_is_dropped(tmp_path):
    page = {
        "route": "/applications/new",
        "root": {
            "type": "Form",
            "props": {
                "workflow": "CreateApplication",
                "input_map": {"status": "status", "phantom": "nonexistentColumn"},
            },
            "children": [{"type": "Input", "props": {"name": "status"}}],
        },
    }
    out = _mkapp(tmp_path, pages={"applications/new.json": page},
                 workflows={"CreateApplication.json": _CREATE_WF})
    res = reconcile_action_contract(out)
    assert res["dropped_inputs"] == 1
    action = _load_contract(out)["actions"][0]
    # Valid declared column survives; bogus one is dropped and recorded.
    assert action["input_map"].get("status") == "status"
    assert "phantom" not in action["input_map"]
    assert action["dropped_inputs"] == [{"field": "phantom", "column": "nonexistentColumn"}]


def test_event_driven_workflow_requires_record(tmp_path):
    page = {
        "route": "/applications",
        "root": {
            "type": "Stack",
            "children": [
                {"type": "Button", "props": {"label": "Shortlist", "workflow": "ShortlistingWorkflow"}},
            ],
        },
    }
    out = _mkapp(tmp_path, pages={"applications.json": page},
                 workflows={"ShortlistingWorkflow.json": _EVENT_WF})
    reconcile_action_contract(out)
    action = _load_contract(out)["actions"][0]
    assert action["kind"] == "button"
    assert action["resolved"] is True
    assert action["requires_record"] is True


def test_unresolved_workflow_ref_is_reported_not_raised(tmp_path):
    page = {
        "route": "/applications/new",
        "root": {
            "type": "Form",
            "props": {"workflow": "NoSuchWorkflow"},
            "children": [{"type": "Input", "props": {"name": "status"}}],
        },
    }
    out = _mkapp(tmp_path, pages={"applications/new.json": page},
                 workflows={"CreateApplication.json": _CREATE_WF})
    res = reconcile_action_contract(out)
    assert res["unresolved"] == 1
    action = _load_contract(out)["actions"][0]
    assert action["resolved"] is False
    assert action["workflow_id"] is None
    # No columns to map against an unknown workflow.
    assert action["input_map"] == {}


def test_idempotent(tmp_path):
    page = {
        "route": "/applications/new",
        "root": {
            "type": "Form",
            "props": {"workflow": "CreateApplication"},
            "children": [
                {"type": "Input", "props": {"name": "status"}},
                {"type": "Input", "props": {"name": "stage"}},
            ],
        },
    }
    out = _mkapp(tmp_path, pages={"applications/new.json": page},
                 workflows={"CreateApplication.json": _CREATE_WF})
    reconcile_action_contract(out)
    with open(os.path.join(out, "contracts", "action-contract.json")) as fh:
        first = fh.read()
    reconcile_action_contract(out)
    with open(os.path.join(out, "contracts", "action-contract.json")) as fh:
        second = fh.read()
    assert first == second


def test_no_schemas_dir_is_noop(tmp_path):
    out = os.path.join(str(tmp_path), "empty")
    os.makedirs(out, exist_ok=True)
    res = reconcile_action_contract(out)  # must not raise
    assert res["actions"] == []
