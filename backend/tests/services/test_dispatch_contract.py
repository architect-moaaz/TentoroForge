"""The wire between a control and its workflow — what the browser actually
POSTs against what the projected steps read. The Blueprint checks reason
about scope; these pin the POST body."""

import json

from services.blueprint.dispatch_contract import (
    control_dispatches, dispatches, dispatch_findings, workflow_ref_findings,
)
from services.blueprint.functional_completeness import authoring_findings, page_findings


def _wf(wid, name, op, inputs):
    return {"id": wid, "name": name, "trigger": {"kind": "manual"},
            "inputs": inputs,
            "steps": [{"key": "s", "name": "s", "type": "trigger", "config": {"type": "manual"}, "next": ["do"]},
                      {"key": "do", "name": "do", "type": "action", "entity": "E-REC",
                       "config": {"actionType": op, "table": "records",
                                  **({"where": {"id": "{{record.id}}"}} if op != "db_insert" else {}),
                                  **({"values": {"fullName": "{{fullName}}"}} if op != "db_delete" else {})},
                       "next": ["e"]},
                      {"key": "e", "name": "e", "type": "end", "next": []}]}


def _doc():
    return {
        "data": {"entities": [{"id": "E-REC", "name": "Record", "table": "records",
                               "fields": [{"name": "id", "type": "uuid"}, {"name": "fullName", "type": "string"}]}]},
        "pages": [
            {"id": "PAGE-LIST", "route": "/records", "actions": ["view", "delete"], "data": {"primaryEntity": "E-REC"}},
            {"id": "PAGE-DET", "route": "/records/[id]", "actions": ["delete"], "data": {"primaryEntity": "E-REC"}},
            {"id": "PAGE-ADD", "route": "/records/new", "actions": ["create"], "data": {"primaryEntity": "E-REC"}},
        ],
        "workflows": [
            _wf("FLOW-C", "Create Record", "db_insert", [{"name": "fullName", "kind": "field", "type": "string", "required": True}]),
            _wf("FLOW-D", "Delete Record", "db_delete", [{"name": "record", "kind": "record", "entity": "E-REC", "required": True}]),
        ],
        "pageLayouts": [
            {"page": "PAGE-LIST", "dataSources": [{"name": "records", "entity": "E-REC", "op": "list"}],
             "root": {"type": "Table", "props": {"data": "{{records}}", "columns": [{"key": "fullName", "label": "Name"}],
                                                 "rowActions": [{"label": "View", "navigate": "/records/{{id}}"},
                                                                {"label": "Delete", "workflow": "FLOW-D"}]}, "children": []}},
            {"page": "PAGE-DET", "dataSources": [{"name": "rec", "entity": "E-REC", "op": "get"}],
             "root": {"type": "Stack", "props": {}, "children": [
                 {"type": "Button", "props": {"label": "Delete Record", "workflow": "FLOW-D"}, "children": []}]}},
            {"page": "PAGE-ADD", "dataSources": [],
             "root": {"type": "Form", "props": {"submitLabel": "Create Record", "workflow": "FLOW-C",
                                                "fields": [{"name": "fullName"}]}, "children": []}},
        ],
    }


def test_each_control_puts_on_the_wire_what_the_library_dispatches():
    wires = {(d.route, d.control): d for d in control_dispatches(_doc())}
    assert wires[("/records", "Table.rowActions[1]")].keys == {"id"}          # Table.tsx: dispatch(wf, {id})
    assert wires[("/records/new", "Form")].keys == {"fullName"}               # Form.tsx: {...args, ...values}
    # The record page's Button sends nothing of its own; the projection carries
    # the page's record onto it (record_scope) — under the input's name and `id`.
    assert wires[("/records/[id]", "Button")].keys == {"id", "record"}
    assert wires[("/records/[id]", "Button")].bound == {"id", "record"}


def test_a_clean_app_has_no_wire_findings():
    doc = _doc()
    assert dispatch_findings(doc) == []
    assert workflow_ref_findings(doc) == []
    assert [f for f in page_findings(doc) if f["rule"] == "dispatch-payload-incomplete"] == []


def test_a_step_reading_what_nothing_declares_is_the_authors_refusal():
    """`{{age}}` in a Create step with no `age` input: the composer checks
    declared inputs and never collects it; the engine finds nothing; the column
    is written NULL. 18 such refs across 545 real workflows."""
    doc = _doc()
    doc["workflows"][0]["steps"][1]["config"]["values"]["age"] = "{{age}}"
    (f,) = workflow_ref_findings(doc)
    assert f["rule"] == "workflow-ref-unsupplied" and f["workflow"] == "FLOW-C"
    assert "{{age}}" in f["detail"] and "no input declares 'age'" in f["detail"]
    assert "workflow-ref-unsupplied" in {x["rule"] for x in authoring_findings(doc)}


def test_what_the_engine_and_earlier_steps_supply_is_not_flagged():
    doc = _doc()
    cfg = doc["workflows"][0]["steps"][1]["config"]
    cfg["values"].update({"createdBy": "{{user.id}}", "raw": "{{input.fullName}}", "prev": "{{s.something}}"})
    assert workflow_ref_findings(doc) == []


def test_a_wire_that_lacks_a_declared_input_is_one_finding_not_two():
    # A Delete button on the LIST page, outside any row: the record is not in
    # scope (unsatisfied_inputs says so) and not on the wire. One refusal.
    doc = _doc()
    doc["pageLayouts"][0]["root"] = {"type": "Stack", "props": {}, "children": [
        doc["pageLayouts"][0]["root"],
        {"type": "Button", "props": {"label": "Delete Record", "workflow": "FLOW-D"}, "children": []}]}
    rules = [f["rule"] for f in page_findings(doc) if f["page"] == "PAGE-LIST"]
    assert "workflow-inputs-unsatisfied" in rules
    assert "dispatch-payload-incomplete" not in rules


def test_the_manifest_samples_each_key_from_the_declared_input():
    m = {(e["route"], e["control"]): e for e in dispatches(_doc())}
    assert m[("/records", "Table.rowActions[1]")]["input"] == {"id": "00000000-0000-4000-8000-000000000001"}
    assert m[("/records/new", "Form")]["input"] == {"fullName": "sample fullName"}
    det = m[("/records/[id]", "Button")]["input"]
    assert set(det) == {"id", "record"} and all(v == "00000000-0000-4000-8000-000000000001" for v in det.values())
    assert m[("/records", "Table.rowActions[1]")]["workflow"] == "FLOW-D"


def test_the_projection_writes_the_manifest(tmp_path):
    from services.blueprint.projection import project_dispatches
    r = project_dispatches(_doc(), tmp_path)
    assert r == {"files": ["src/contracts/dispatches.json"], "dispatches": 3}
    data = json.loads((tmp_path / "src/contracts/dispatches.json").read_text())
    assert {e["workflow"] for e in data["dispatches"]} == {"FLOW-C", "FLOW-D"}
