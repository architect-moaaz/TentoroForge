"""A2: when the planner/business-logic author supplies a CONCRETE literal `values`
map on a state-transition step, the workflow generator's db_update/db_insert path
must write it VERBATIM — ahead of label-derivation and self-refs — so the button
sets the correct value by construction (not a label guess).
"""
from services.workflow_generator import _build_step_config

_WF = {"name": "RestoreEquipment", "description": "Restore equipment availability"}
_MODELS = {"Equipment": {"name": "Equipment", "table": "equipment",
                         "fields": [{"name": "availabilityStatus", "type": "varchar"}]}}
_TABLES = {"equipment"}


def test_authored_literal_values_win_over_label_derivation():
    meta = {"name": "Restore Equipment Availability", "node_type": "action",
            "config": {"actionType": "db_update", "table": "equipment",
                       "values": {"availabilityStatus": "Available",
                                  "restoredAt": "CURRENT_TIMESTAMP"}}}
    cfg = _build_step_config("Restore Equipment Availability", "action", _WF,
                             _MODELS, _TABLES, meta=meta)
    assert cfg["actionType"] == "db_update"
    # VERBATIM — NOT the label "Restore Equipment Availability"
    assert cfg["values"] == {"availabilityStatus": "Available",
                             "restoredAt": "CURRENT_TIMESTAMP"}


def test_no_authored_values_still_label_derives():
    # #6 fallback intact when the author supplied nothing concrete.
    meta = {"name": "Mark as Retired", "node_type": "action"}
    cfg = _build_step_config("Mark as Retired", "action", _WF, _MODELS, _TABLES, meta=meta)
    assert cfg["actionType"] == "db_update"
    assert cfg["values"].get("availabilityStatus") == "Retired"


def test_authored_values_at_top_level_also_honored():
    # Defensive: a non-rich step dict may carry `values` at top level (no config).
    meta = {"name": "Set Available", "node_type": "action",
            "values": {"availabilityStatus": "Available"}}
    cfg = _build_step_config("Set Available", "action", _WF, _MODELS, _TABLES, meta=meta)
    assert cfg["values"] == {"availabilityStatus": "Available"}
