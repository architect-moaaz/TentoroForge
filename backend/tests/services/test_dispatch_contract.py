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
    assert f["page"] == "FLOW-C"        # every finding carries its artifact under `page` — the edge reads it
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
    assert r == {"files": ["src/contracts/dispatches.json", "src/lib/incident-map.ts"],
                 "dispatches": 3}
    data = json.loads((tmp_path / "src/contracts/dispatches.json").read_text())
    assert {e["workflow"] for e in data["dispatches"]} == {"FLOW-C", "FLOW-D"}


def test_the_run_time_reporter_gets_the_same_wires_the_dry_run_checks(tmp_path):
    """The build-time dry run names the route, the control and the workflow.
    When the same wire breaks in front of a customer the app has a workflow id
    and a browser path, so the projection hands it these two tables — written
    from the same manifest, never a second derivation that can disagree."""
    from services.blueprint.projection import project_dispatches
    project_dispatches(_doc(), tmp_path)
    emitted = (tmp_path / "src/lib/incident-map.ts").read_text()
    routes = json.loads(emitted.split("ROUTES: string[] = ")[1].split(";")[0])
    controls = json.loads(emitted.split("label: string }>> =\n")[1].rsplit(";", 1)[0])
    assert "/records/[id]" in routes
    # Keyed by the Blueprint id the control carries AND the slug the projected
    # definition is filed under, because the run sees whichever was dispatched.
    assert controls["FLOW-D"] == controls["delete-record"]
    # Both controls that run FLOW-D, so the reporter can tell them apart by the
    # route it was on — and, when it cannot, name neither rather than guess.
    assert {(c["route"], c["control"], c["label"]) for c in controls["FLOW-D"]} == {
        ("/records", "Table.rowActions[1]", "Delete"),
        ("/records/[id]", "Button", "Delete Record")}


def test_a_list_column_collected_by_a_text_field_is_refused():
    """`specialities: string[]` on the entity and the input, composed as a
    textarea with a "comma-separated" hint: the edit form showed the record's
    array as JSON and would have written a string back. A list is collected by
    a `tags` field, which submits an array."""
    from services.blueprint.dispatch_contract import field_kind_findings
    doc = _doc()
    doc["data"]["entities"][0]["fields"].append({"name": "specialities", "type": "string[]"})
    doc["workflows"][0]["inputs"].append({"name": "specialities", "kind": "field", "type": "string[]", "required": True})
    form = doc["pageLayouts"][2]["root"]["props"]
    form["fields"] = [{"name": "fullName", "kind": "text"}, {"name": "specialities", "kind": "textarea"}]
    found = field_kind_findings(doc)
    assert [f["rule"] for f in found] == ["form-field-kind-mismatch"]
    assert found[0]["page"] == "PAGE-ADD" and "specialities" in found[0]["detail"] and '"tags"' in found[0]["detail"]
    assert found[0] in page_findings(doc)                      # the composer's refusal, not advice
    form["fields"][1]["kind"] = "tags"
    assert field_kind_findings(doc) == []
    # the column's type alone is enough — the input may say only `field`
    doc["workflows"][0]["inputs"][-1].pop("type")
    form["fields"][1]["kind"] = "text"
    assert len(field_kind_findings(doc)) == 1
