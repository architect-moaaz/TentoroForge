"""A Form dropdown whose options come from a data resource chooses a record.

A dental app's booking form chose its clinic from `optionsFrom.source:
"clinics"` with no page data source declared. The running app filled the
dropdown — `fetchData("clinics")` is `/api/data/clinics`, and the data route
registers every table under its Drizzle export name — while the authoring
check looked the name up among the page's declared sources only and said
"nothing there names one" (UAT, 2026-09-18). The check now resolves the name
the way the data route does, with the projector's own export naming.
"""
from services.blueprint.functional_completeness import _entity_of_source, unsatisfied_inputs

DOC = {"data": {"entities": [
    {"id": "ENTITY-004", "name": "Clinic", "table": "clinics", "fields": []},
    {"id": "ENTITY-009", "name": "DentistSchedule", "table": "dentist_schedules", "fields": []},
]}}


def test_a_resource_name_resolves_to_its_entity_without_a_page_source():
    assert _entity_of_source(DOC, {"dataSources": []}, "clinics") == "ENTITY-004"
    assert _entity_of_source(DOC, {"dataSources": []}, "dentistSchedules") == "ENTITY-009"


def test_a_declared_page_source_still_wins():
    layout = {"dataSources": [{"name": "clinics", "entity": "ENTITY-009"}]}
    assert _entity_of_source(DOC, layout, "clinics") == "ENTITY-009"


def test_an_unknown_name_still_resolves_to_nothing():
    assert _entity_of_source(DOC, {"dataSources": []}, "nonsense") is None


def test_the_booking_form_is_satisfied_by_its_clinic_dropdown():
    doc = {**DOC,
           "pages": [{"id": "PAGE-020", "route": "/book-appointment"}],
           "security": {"ownershipRules": []},
           "workflows": [{"id": "FLOW-005", "name": "Book Appointment", "inputs": [
               {"name": "clinic", "kind": "record", "entity": "ENTITY-004", "required": False}],
               "steps": [{"key": "insert_appointment", "config": {
                   "actionType": "db_insert", "table": "appointments",
                   "values": {"clinicId": "{{clinic.id}}"}}}]}]}
    form = {"type": "Form", "props": {"workflow": "FLOW-005", "fields": [
        {"kind": "select", "name": "clinic", "label": "Clinic", "options": [],
         "interaction": {"optionsFrom": {"source": "clinics", "value": "id", "label": "name"}}}]}}
    layout = {"root": form, "dataSources": []}
    msgs = unsatisfied_inputs(doc, doc["pages"][0], layout, form, "FLOW-005")
    assert not [m for m in msgs if "clinic" in m], msgs
