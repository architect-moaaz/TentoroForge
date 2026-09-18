"""A value a set_variable step sets is supplied — the engine says so, and the
refusal recommends it.

UAT, 2026-09-18: a dental app's Book Appointment read `{{resolvedClinicId}}`.
Told "declare it as an input, or set it from a step", the author set it from
two set_variable steps — and the reference check, which counted inputs and
step keys but not variable names, refused it again. After two identical
refusals the workflow shipped with no steps. The engine stores a set_variable
result under `variableName` (templates/runtime/workflows/engine.ts), and the
dry run now seeds those names too, so the two checks agree with the engine.
"""
from services.blueprint.dispatch_contract import set_variables, workflow_ref_findings


def _wf(*steps, inputs=({"name": "clinic", "kind": "record"},)):
    return {"id": "FLOW-005", "name": "Book Appointment", "inputs": list(inputs),
            "steps": list(steps)}


INSERT = {"key": "insert_appointment", "type": "action", "config": {
    "actionType": "db_insert", "table": "appointments",
    "values": {"clinicId": "{{resolvedClinicId}}"}}}
SET = {"key": "set_clinic", "type": "action", "config": {
    "actionType": "set_variable", "variableName": "resolvedClinicId", "value": "{{clinic.id}}"}}


def test_a_name_nothing_supplies_is_still_refused():
    [f] = workflow_ref_findings({"workflows": [_wf(INSERT)]})
    assert "resolvedClinicId" in f["detail"]


def test_setting_it_from_a_step_answers_the_refusal():
    assert workflow_ref_findings({"workflows": [_wf(SET, INSERT)]}) == []


def test_the_names_are_read_off_the_steps():
    assert set_variables(_wf(SET, INSERT)) == {"resolvedClinicId"}
    assert set_variables(_wf(INSERT)) == set()
