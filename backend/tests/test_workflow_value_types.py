"""Tests for the workflow value↔column TYPE checker + corrector."""
import json
import os

import pytest

from services.workflow_value_types import (
    analyze_workflow_values,
    classify_value_kind,
    collect_trigger_inputs,
    columns_by_table_from_registry,
    repair_workflow_dict,
    repair_workflow_values,
)

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_MC2_WF = os.path.join(_REPO, "output", "mc2xgclv", "workflows",
                       "assessmentschedulingworkflow.json")
_MC2_REG = os.path.join(_REPO, "output", "mc2xgclv", "contracts",
                        "resource-registry.json")


# --- fixtures -------------------------------------------------------------- #

# The real assessments table column types (from mc2xgclv's resource-registry).
ASSESSMENTS_COLS = {
    "assessments": {
        "id": "uuid",
        "applicationId": "uuid",
        "candidateId": "uuid",
        "assessmentType": "varchar",
        "scheduledAt": "timestamp",
        "location": "varchar",
        "assignedAssessorId": "uuid",
        "status": "varchar",
        "notes": "text",
    }
}


def _create_node(values, label="Create Assessment Record"):
    return {
        "id": "create_assessment_record",
        "type": "action",
        "data": {
            "label": label,
            "config": {
                "table": "assessments",
                "actionType": "db_insert",
                "values": values,
            },
        },
    }


def _defn(*nodes):
    return {"nodes": list(nodes), "edges": []}


# --- Task 0-1: analyze ----------------------------------------------------- #

def test_real_assessment_shape_yields_two_findings():
    defn = _defn(_create_node({
        "applicationId": "{{applicationId}}",
        "candidateId": "CURRENT_TIMESTAMP",          # uuid <- timestamp: MISMATCH
        "assessmentType": "{{assessmentType}}",
        "scheduledAt": "CURRENT_TIMESTAMP",           # timestamp col: OK
        "location": "{{location}}",
        "assignedAssessorId": "{{assignedAssessorId}}",
        "status": "Create Assessment Record",         # enum/status <- node label: MISMATCH
    }))
    findings = analyze_workflow_values(defn, ASSESSMENTS_COLS)
    by_col = {f["column"]: f for f in findings}
    assert set(by_col) == {"candidateId", "status"}

    cand = by_col["candidateId"]
    assert cand["table"] == "assessments"
    assert cand["columnType"] == "uuid"
    assert cand["valueKind"] == "timestamp_literal"
    assert cand["reason"] == "timestamp-literal-into-uuid"

    st = by_col["status"]
    assert st["reason"] == "label-string-into-enum"
    assert st["value"] == "Create Assessment Record"

    # scheduledAt (timestamp column, timestamp literal) → NO finding.
    assert "scheduledAt" not in by_col


def test_correct_template_binding_into_uuid_yields_nothing():
    defn = _defn(_create_node({
        "candidateId": "{{candidateId}}",   # template → always OK
        "scheduledAt": "{{scheduledAt}}",
    }))
    assert analyze_workflow_values(defn, ASSESSMENTS_COLS) == []


def test_bare_identifier_into_uuid_is_valid_binding():
    # The deterministic-workflow convention: value == column name (process var).
    defn = _defn(_create_node({
        "candidateId": "candidateId",
        "applicationId": "applicationId",
    }))
    assert analyze_workflow_values(defn, ASSESSMENTS_COLS) == []


def test_bare_string_with_spaces_into_uuid_is_mismatch():
    defn = _defn(_create_node({"candidateId": "Some Candidate Name"}))
    findings = analyze_workflow_values(defn, ASSESSMENTS_COLS)
    assert len(findings) == 1
    assert findings[0]["reason"] == "bare-string-into-uuid"


def test_unknown_table_and_column_are_skipped():
    # Unknown table.
    n1 = _create_node({"candidateId": "CURRENT_TIMESTAMP"})
    n1["data"]["config"]["table"] = "ghosts"
    assert analyze_workflow_values(_defn(n1), ASSESSMENTS_COLS) == []
    # Unknown column on a known table.
    n2 = _create_node({"phantomCol": "CURRENT_TIMESTAMP"})
    assert analyze_workflow_values(_defn(n2), ASSESSMENTS_COLS) == []


def test_iso_date_into_uuid_is_mismatch():
    defn = _defn(_create_node({"candidateId": "2026-07-15"}))
    findings = analyze_workflow_values(defn, ASSESSMENTS_COLS)
    assert findings and findings[0]["reason"] == "iso-date-into-uuid"


def test_scheduledat_iso_date_ok():
    defn = _defn(_create_node({"scheduledAt": "2026-07-15T10:00:00Z"}))
    assert analyze_workflow_values(defn, ASSESSMENTS_COLS) == []


def test_number_into_uuid_is_mismatch():
    defn = _defn(_create_node({"candidateId": 42}))
    findings = analyze_workflow_values(defn, ASSESSMENTS_COLS)
    assert findings and findings[0]["reason"] == "number-into-uuid"


def test_analyze_never_raises_on_garbage():
    assert analyze_workflow_values({}, ASSESSMENTS_COLS) == []
    assert analyze_workflow_values({"nodes": "notalist"}, ASSESSMENTS_COLS) == []
    assert analyze_workflow_values(None, None) == []


def test_enum_values_known_invalid_value():
    cols = {"t": {"status": {"type": "varchar", "enum": ["Open", "Closed"]}}}
    node = {
        "id": "n", "type": "action",
        "data": {"label": "N", "config": {"table": "t", "actionType": "db_insert",
                                           "values": {"status": "Bogus"}}},
    }
    findings = analyze_workflow_values(_defn(node), cols)
    assert findings and findings[0]["reason"] == "invalid-enum-value"
    # A valid enum value → no finding.
    node["data"]["config"]["values"]["status"] = "Open"
    assert analyze_workflow_values(_defn(node), cols) == []


def test_classify_value_kind():
    assert classify_value_kind("{{x}}") == "template"
    assert classify_value_kind("CURRENT_TIMESTAMP") == "timestamp_literal"
    assert classify_value_kind("now()") == "timestamp_literal"
    assert classify_value_kind("2026-01-02") == "iso_date"
    assert classify_value_kind("42") == "number"
    assert classify_value_kind(7) == "number"
    assert classify_value_kind(True) == "bool"
    assert classify_value_kind("true") == "bool"
    assert classify_value_kind(None) == "null"
    assert classify_value_kind("hello world") == "bare_string"


def test_columns_by_table_from_registry():
    registry = {
        "entities": {
            "Assessment": {
                "table": "assessments",
                "columns": [
                    {"name": "candidateId", "type": "uuid", "enum": None},
                    {"name": "status", "type": "varchar", "enum": ["A", "B"]},
                ],
            }
        }
    }
    cbt = columns_by_table_from_registry(registry)
    assert cbt["assessments"]["candidateId"]["type"] == "uuid"
    assert cbt["assessments"]["status"]["enum"] == ["A", "B"]
    # Works end-to-end through analyze.
    node = _create_node({"candidateId": "CURRENT_TIMESTAMP"})
    findings = analyze_workflow_values(_defn(node), cbt)
    assert findings and findings[0]["reason"] == "timestamp-literal-into-uuid"


# --- Task 0-2: repair ------------------------------------------------------ #

def test_repair_rebinds_to_trigger_input():
    defn = _defn(_create_node({
        "candidateId": "CURRENT_TIMESTAMP",
        "scheduledAt": "CURRENT_TIMESTAMP",   # OK, untouched
        "status": "Create Assessment Record",
    }))
    repaired, changes = repair_workflow_values(
        defn, ASSESSMENTS_COLS, trigger_inputs={"candidateId"})
    vals = repaired["nodes"][0]["data"]["config"]["values"]
    assert vals["candidateId"] == "{{candidateId}}"
    assert vals["scheduledAt"] == "CURRENT_TIMESTAMP"   # untouched
    assert "status" not in vals                         # dropped (no input, no enum)

    by_col = {c["column"]: c for c in changes}
    assert by_col["candidateId"]["from"] == "CURRENT_TIMESTAMP"
    assert by_col["candidateId"]["to"] == "{{candidateId}}"
    assert by_col["status"]["to"] is None


def test_repair_drops_when_no_trigger_input():
    defn = _defn(_create_node({"candidateId": "CURRENT_TIMESTAMP"}))
    repaired, changes = repair_workflow_values(defn, ASSESSMENTS_COLS, trigger_inputs=set())
    vals = repaired["nodes"][0]["data"]["config"]["values"]
    assert "candidateId" not in vals
    assert changes == [{"node": "create_assessment_record", "column": "candidateId",
                        "from": "CURRENT_TIMESTAMP", "to": None}]


def test_repair_is_idempotent():
    defn = _defn(_create_node({
        "candidateId": "CURRENT_TIMESTAMP",
        "status": "Create Assessment Record",
    }))
    repaired, _ = repair_workflow_values(defn, ASSESSMENTS_COLS, trigger_inputs={"candidateId"})
    repaired2, changes2 = repair_workflow_values(repaired, ASSESSMENTS_COLS, trigger_inputs={"candidateId"})
    assert changes2 == []
    assert repaired2 == repaired
    # And the definition is now clean under analyze.
    assert analyze_workflow_values(repaired, ASSESSMENTS_COLS) == []


def test_repair_does_not_mutate_input():
    defn = _defn(_create_node({"candidateId": "CURRENT_TIMESTAMP"}))
    repair_workflow_values(defn, ASSESSMENTS_COLS, trigger_inputs=set())
    assert defn["nodes"][0]["data"]["config"]["values"]["candidateId"] == "CURRENT_TIMESTAMP"


def test_repair_replaces_label_with_valid_enum():
    cols = {"assessments": {"status": {"type": "varchar", "enum": ["Scheduled", "Done"]}}}
    node = _create_node({"status": "Create Assessment Record"})
    repaired, changes = repair_workflow_values(_defn(node), cols, trigger_inputs=set())
    vals = repaired["nodes"][0]["data"]["config"]["values"]
    assert vals["status"] == "Scheduled"
    assert changes[0]["to"] == "Scheduled"


def test_collect_trigger_inputs():
    defn = {
        "nodes": [
            {"id": "n", "data": {"config": {
                "message": "hi {{candidateId}} at {{scheduledAt}}",
                "fields": ["applicationId", "location"],
            }}},
        ],
        "edges": [],
    }
    inputs = collect_trigger_inputs(defn)
    assert {"candidateId", "scheduledAt", "applicationId", "location"} <= inputs


# --- gate wiring ----------------------------------------------------------- #

def test_run_workflow_gate_repairs_values(tmp_path):
    from services.workflow_graph_gate import run_workflow_gate

    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps({
        "entities": {
            "Assessment": {
                "table": "assessments",
                "columns": [
                    {"name": "candidateId", "type": "uuid"},
                    {"name": "scheduledAt", "type": "timestamp"},
                    {"name": "status", "type": "varchar"},
                ],
            }
        }
    }))
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    # A fully reachable trigger→action→end graph so the gate keeps the action.
    create = _create_node({
        "candidateId": "CURRENT_TIMESTAMP",
        "scheduledAt": "CURRENT_TIMESTAMP",
        "status": "Create Assessment Record",
    })
    wf = {
        "id": "w", "name": "W",
        "definition": {
            "trigger": {"type": "manual"},
            "nodes": [
                {"id": "trigger", "type": "trigger",
                 "data": {"config": {"fields": ["candidateId", "scheduledAt", "status"]}}},
                create,
                {"id": "end", "type": "end", "data": {"config": {}}},
            ],
            "edges": [
                {"source": "trigger", "target": "create_assessment_record"},
                {"source": "create_assessment_record", "target": "end"},
            ],
        },
    }
    (wf_dir / "w.json").write_text(json.dumps(wf))

    summary = run_workflow_gate(str(tmp_path))
    assert summary["value_type_fixes"] >= 1

    out = json.loads((wf_dir / "w.json").read_text())
    create_out = next(n for n in out["definition"]["nodes"]
                      if n["id"] == "create_assessment_record")
    vals = create_out["data"]["config"]["values"]
    assert vals["candidateId"] == "{{candidateId}}"
    assert vals["scheduledAt"] == "CURRENT_TIMESTAMP"       # untouched
    # No residual mismatch.
    from services.workflow_value_types import columns_by_table_from_registry as _cbt
    reg = json.loads((tmp_path / "contracts" / "resource-registry.json").read_text())
    assert analyze_workflow_values(out["definition"], _cbt(reg)) == []


# --- Task 0-3: smoke on the real mc2xgclv artifact ------------------------- #

@pytest.mark.skipif(not (os.path.exists(_MC2_WF) and os.path.exists(_MC2_REG)),
                    reason="mc2xgclv sample artifact not present")
def test_smoke_real_assessment_scheduling_workflow():
    wf = json.loads(open(_MC2_WF, encoding="utf-8").read())
    reg = json.loads(open(_MC2_REG, encoding="utf-8").read())
    cbt = columns_by_table_from_registry(reg)

    findings = analyze_workflow_values(wf["definition"], cbt)
    by_col = {f["column"]: f for f in findings}
    # The two real bugs: candidateId (timestamp->uuid) and status (label->enum).
    assert by_col["candidateId"]["reason"] == "timestamp-literal-into-uuid"
    assert by_col["status"]["reason"] == "label-string-into-enum"

    _, changes = repair_workflow_dict(wf, cbt)
    changed_cols = {c["column"] for c in changes}
    assert {"candidateId", "status"} <= changed_cols
    # After the repair the workflow is type-clean.
    assert analyze_workflow_values(wf["definition"], cbt) == []
