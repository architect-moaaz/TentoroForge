"""DEFECT #6: button/manual-triggered mutations that NULL-wipe columns.

A `db_update` with self-referential `values` (`{"status":"{{status}}"}`) and no
trigger input backing `status` resolves to NULL at runtime and wipes the column, so
"Confirm Pickup"/"Process Return"/"Cancel" appear to do nothing. The healing pass
rewrites those values to real literals (status ← node label, *At ← now).
"""
import json

from services.workflow_mutation_guard import (
    heal_workflow_dict, heal_workflow_mutations, derive_status_literal,
    is_status_col, is_timestamp_col, has_explicit_literal, is_literal_value,
    NOW_LITERAL,
)


def _node(label, config):
    return {"id": "n", "type": "action",
            "data": {"label": label, "nodeType": "action", "config": config}}


def _wf(nodes, process_vars=None):
    return {
        "id": "w", "name": "W",
        "processVariables": process_vars or [],
        "definition": {
            "trigger": {"type": "manual"},
            "nodes": [{"id": "trigger", "type": "trigger",
                       "data": {"nodeType": "trigger", "config": {"nodeType": "trigger"}}},
                      *nodes,
                      {"id": "end", "type": "end"}],
            "edges": [],
        },
    }


def _pickup_config():
    return {
        "table": "rentals", "actionType": "db_update",
        "where": {"id": "{{id}}"},
        "values": {"status": "{{status}}", "pickedUpAt": "{{pickedUpAt}}"},
    }


# --- primary healing behaviour (the exact defect) -------------------------------
def test_status_from_label_and_timestamp_now():
    wf = _wf([_node("Set Picked Up", _pickup_config())])
    healed, unresolved = heal_workflow_dict(wf)
    assert healed == 2
    assert unresolved == []
    vals = wf["definition"]["nodes"][1]["data"]["config"]["values"]
    assert vals["status"] == "Picked Up"
    assert vals["pickedUpAt"] == NOW_LITERAL  # CURRENT_TIMESTAMP


def test_various_status_labels():
    for label, expected in [
        ("Set Returned", "Returned"),
        ("Mark as Cancelled", "Cancelled"),
        ("Mark Returned", "Returned"),
        ("Update Status to Approved", "Approved"),
    ]:
        wf = _wf([_node(label, {
            "table": "t", "actionType": "db_update",
            "where": {"id": "{{id}}"}, "values": {"status": "{{status}}"},
        })])
        heal_workflow_dict(wf)
        assert wf["definition"]["nodes"][1]["data"]["config"]["values"]["status"] == expected, label


def test_real_trigger_input_is_left_untouched():
    """A value backed by a declared trigger input is genuinely user-supplied — keep
    the {{var}}, never overwrite it with a label literal."""
    wf = _wf(
        [_node("Set Confirmed", {
            "table": "rentals", "actionType": "db_update",
            "where": {"id": "{{id}}"}, "values": {"notes": "{{notes}}", "status": "{{status}}"},
        })],
        process_vars=[{"name": "notes", "type": "string", "required": True}],
    )
    healed, unresolved = heal_workflow_dict(wf)
    vals = wf["definition"]["nodes"][1]["data"]["config"]["values"]
    assert vals["notes"] == "{{notes}}"      # backed input — untouched
    assert vals["status"] == "Confirmed"     # unbacked status — healed from label
    assert healed == 1


def test_unbacked_plain_field_is_flagged_not_wiped():
    """A non-status, non-timestamp unbacked field is left as {{var}} and flagged so a
    form/input can be added — never silently turned into a bad literal."""
    wf = _wf([_node("Assign Owner", {
        "table": "t", "actionType": "db_update",
        "where": {"id": "{{id}}"}, "values": {"ownerId": "{{ownerId}}"},
    })])
    healed, unresolved = heal_workflow_dict(wf)
    assert healed == 0
    assert unresolved == ["ownerId"]
    assert wf["definition"]["nodes"][1]["data"]["config"]["values"]["ownerId"] == "{{ownerId}}"


def test_idempotent():
    wf = _wf([_node("Set Picked Up", _pickup_config())])
    heal_workflow_dict(wf)
    snapshot = json.dumps(wf, sort_keys=True)
    healed2, _ = heal_workflow_dict(wf)
    assert healed2 == 0
    assert json.dumps(wf, sort_keys=True) == snapshot


def test_db_insert_healed_too():
    wf = _wf([_node("Set Approved", {
        "table": "requests", "actionType": "db_insert",
        "values": {"status": "{{status}}", "approvedAt": "{{approvedAt}}", "title": "{{title}}"},
    })], process_vars=[{"name": "title"}])
    heal_workflow_dict(wf)
    vals = wf["definition"]["nodes"][1]["data"]["config"]["values"]
    assert vals["status"] == "Approved"
    assert vals["approvedAt"] == NOW_LITERAL
    assert vals["title"] == "{{title}}"  # backed input untouched


# --- file-level pass ------------------------------------------------------------
def test_heal_workflow_mutations_writes_file(tmp_path):
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "pickup.json").write_text(json.dumps(_wf([_node("Set Picked Up", _pickup_config())])), encoding="utf-8")
    report = heal_workflow_mutations(tmp_path)
    assert report["workflows_scanned"] == 1
    assert report["values_healed"] == 2
    assert report["unresolved"] == 0
    reloaded = json.loads((wf_dir / "pickup.json").read_text(encoding="utf-8"))
    vals = reloaded["definition"]["nodes"][1]["data"]["config"]["values"]
    assert vals == {"status": "Picked Up", "pickedUpAt": NOW_LITERAL}


def test_pass_never_raises_on_missing_dir(tmp_path):
    report = heal_workflow_mutations(tmp_path / "nope")
    assert report == {"workflows_scanned": 0, "values_healed": 0, "unresolved": 0}


# --- classification helpers -----------------------------------------------------
def test_classification_helpers():
    assert is_status_col("status") and is_status_col("orderState") and is_status_col("stage")
    assert not is_status_col("ownerId")
    assert is_timestamp_col("pickedUpAt") and is_timestamp_col("returned_at")
    assert is_timestamp_col("completedDate")
    assert not is_timestamp_col("format")  # trailing "at" is not the *At suffix
    # Short timestamp signals match only on a word boundary — a uuid FK whose name
    # merely CONTAINS "date"/"time" must NOT be mistaken for a timestamp column.
    assert not is_timestamp_col("candidateId")  # "candi(date)Id" — regression
    assert not is_timestamp_col("runtimeId")     # "run(time)Id"
    assert derive_status_literal("Set Picked Up") == "Picked Up"
    assert derive_status_literal("Mark as Cancelled") == "Cancelled"
    assert derive_status_literal("Update Status") is None  # nothing meaningful left


# --- explicit-literal classification (A2: author supplies the target value) -------
def test_is_literal_value():
    assert is_literal_value("Approved")
    assert is_literal_value("CURRENT_TIMESTAMP")
    assert is_literal_value(True) and is_literal_value(42)
    assert not is_literal_value("{{status}}")
    assert not is_literal_value("")
    assert not is_literal_value("hello {{name}}")  # embedded template is not concrete


def test_has_explicit_literal():
    assert has_explicit_literal({"status": "Approved"})
    assert has_explicit_literal({"status": "Approved", "notes": "{{notes}}"})  # one is enough
    assert not has_explicit_literal({"status": "{{status}}"})
    assert not has_explicit_literal({})
    assert not has_explicit_literal(None)


def test_guard_is_pure_net_on_already_literal_workflow():
    # A2: once the author supplies literals, the guard heals ZERO (pure safety net).
    wf = _wf([_node("Restore Equipment Availability", {
        "table": "equipment", "actionType": "db_update", "where": {"id": "{{id}}"},
        "values": {"availabilityStatus": "Available", "restoredAt": NOW_LITERAL},
    })])
    healed, unresolved = heal_workflow_dict(wf)
    assert healed == 0
    assert unresolved == []
    vals = wf["definition"]["nodes"][1]["data"]["config"]["values"]
    assert vals == {"availabilityStatus": "Available", "restoredAt": NOW_LITERAL}
