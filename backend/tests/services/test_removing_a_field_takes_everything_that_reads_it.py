"""Med Tracker shape (egqkhylj): preferredTime read by step expressions in two
workflows, a template in a third, a rule and a form box. Removal must find all
(not preferredTimeZone), ask when anything is ambiguous, change nothing before
a yes, then rewrite everything and leave nothing referring to it."""
import json

import pytest

from services.blueprint.dispatch_contract import workflow_ref_findings
from services.blueprint.service import BlueprintService
from services.smith import field_change as fc, field_dependents as fd


def _wf(svc, name, inputs, steps):
    chain = [{"key": "start", "name": "Start", "type": "trigger", "config": {"type": "manual"}, "next": [steps[0]["key"]]}]
    for i, s in enumerate(steps):
        s.setdefault("name", s["key"])
        s["next"] = [steps[i + 1]["key"]] if i + 1 < len(steps) else ["end"]
        chain.append(s)
    chain.append({"key": "end", "name": "End", "type": "end", "next": []})
    return svc.upsert("workflows", {"name": name, "purpose": name, "trigger": {"kind": "manual"}, "launchedFrom": [],
                                    "inputs": inputs, "steps": chain}, natural_key=name)


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Med Tracker", domain="health")
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Medicine", "table": "medicines", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True}, {"name": "name", "type": "string", "required": True},
        {"name": "preferredTime", "type": "string"}, {"name": "preferredTimeZone", "type": "string"}]}], "relationships": []}
    ins = {"actionType": "db_insert", "table": "medicines", "values": {"name": "{{name}}", "preferredTime": "{{preferredTime}}"}}
    _wf(s, "Add Medicine",
        [{"name": "name", "kind": "field", "type": "string", "required": True},
         {"name": "preferredTime", "kind": "field", "type": "string", "required": False}],
        [{"key": "validate_input", "type": "condition", "config": {"expression": "preferredTime != null and preferredTime != ''"}},
         {"key": "compute_time_of_day", "type": "action", "config": {"actionType": "set_variable", "variableName": "slot",
                                                                     "value": "if preferredTime < '12:00' then 'Morning' else 'Evening'"}},
         {"key": "insert", "type": "action", "entity": "ENTITY-001", "config": ins}])
    _wf(s, "Edit Medicine", [{"name": "name", "kind": "field", "type": "string", "required": True},
                             {"name": "id", "kind": "field", "type": "uuid", "required": True}],
        [{"key": "validate_fields", "type": "condition", "config": {"expression": "name != '' and preferredTime != ''"}},
         {"key": "upd", "type": "action", "entity": "ENTITY-001",
          "config": {"actionType": "db_update", "table": "medicines", "values": {"name": "{{name}}"}, "where": {"id": "{{id}}"}}}])
    _wf(s, "Generate Dose Logs", [{"name": "name", "kind": "field", "type": "string", "required": True}],
        [{"key": "generate_dose_logs", "type": "action", "entity": "ENTITY-001",
          "config": {"actionType": "db_insert", "table": "medicines", "values": {"name": "{{name}}",
                                                                                 "note": "Take at {{medicine.preferredTime}} daily"}}}])
    s.upsert("businessRules", {"name": "Time Format", "statement": "Preferred time is HH:MM.", "kind": "condition_action",
                               "entity": "ENTITY-001", "when": "preferredTime == ''", "appliesTo": ["ENTITY-001"],
                               "then": [{"type": "show_error", "field": "preferredTime", "message": "Bad."}]}, natural_key="Time Format")
    s.upsert("businessRules", {"name": "Zone Rule", "statement": "Zone set.", "kind": "condition_action", "entity": "ENTITY-001",
                               "when": "preferredTimeZone == ''", "appliesTo": ["ENTITY-001"],
                               "then": [{"type": "show_error", "field": "preferredTimeZone", "message": "Zone."}]}, natural_key="Zone Rule")
    s.save()
    return s


def _ent(s):
    return s.doc["data"]["entities"][0]


def _blob(s):
    return json.dumps([s.doc["workflows"], s.doc["businessRules"]])


def test_the_scan_finds_every_reader_and_never_the_similarly_named_field(svc):
    deps = fd.scan(svc.doc, _ent(svc), "preferredTime")
    what = " | ".join(d["what"] for d in deps)
    for need in ("validate_input", "compute_time_of_day", "validate_fields", "generate_dose_logs", "Time Format"):
        assert need in what, need
    assert "preferredTimeZone" not in what and "Zone Rule" not in what
    assert any(d["class"] == "ask" for d in deps)                      # mixed expression / sentence template
    assert fd.needs_confirmation(deps)


def test_nothing_changes_before_the_person_confirms(svc):
    before = _blob(svc)
    out = fc.remove_field(svc, "Medicine", "preferredTime", confirmed=False)
    assert out["applied"] is False and out["needs_confirmation"] and len(out["would"]) >= 5
    assert _blob(svc) == before and any(f["name"] == "preferredTime" for f in _ent(svc)["fields"])


def test_after_a_yes_everything_is_rewritten_and_nothing_refers_to_it(svc):
    out = fc.remove_field(svc, "Medicine", "preferredTime", confirmed=True)
    assert out["applied"] and out["left"] == []
    assert fd.references_left(svc.doc, _ent(svc), "preferredTime") == []
    import re
    live = json.dumps([svc.doc["workflows"], [r for r in svc.doc["businessRules"] if r.get("status") != "DEPRECATED"]])
    assert not re.search(r"preferredTime(?![A-Za-z0-9_])", live)       # a retired rule's text is history
    assert "preferredTimeZone" in live                                  # the other field is untouched
    assert workflow_ref_findings(svc.doc) == []                         # steps read nothing undeclared
    said = fc.summary_of("remove_field", out)
    assert "Nothing still refers to it" in said and "Verify & Fix" not in said
    assert "not touched yet" in said


def test_a_stated_replacement_is_swapped_in(svc):
    svc.doc["data"]["entities"][0]["fields"].append({"name": "timeOfDay", "type": "string"})
    out = fc.remove_field(svc, "Medicine", "preferredTime", replacement="timeOfDay")
    wf = next(w for w in svc.doc["workflows"] if w["name"] == "Add Medicine")
    assert wf["steps"][1]["config"]["expression"] == "timeOfDay != null and timeOfDay != ''"
    assert out["left"] == []


def test_a_field_with_only_its_own_box_and_check_needs_no_question(svc):
    svc.doc["workflows"] = [w for w in svc.doc["workflows"] if w["name"] != "Generate Dose Logs"]
    wf = next(w for w in svc.doc["workflows"] if w["name"] == "Add Medicine")
    wf["steps"] = [s for s in wf["steps"] if s["key"] != "compute_time_of_day"]
    for w in svc.doc["workflows"]:
        for st in w["steps"]:
            if st["key"] == "validate_fields":
                st["config"]["expression"] = "preferredTime != ''"
    deps = fd.scan(svc.doc, _ent(svc), "preferredTime")
    assert deps and {d["class"] for d in deps} == {"retire"}
    assert not fd.needs_confirmation(deps)
    out = fc.remove_field(svc, "Medicine", "preferredTime", confirmed=False)       # no question: it just happens
    assert out["applied"] and out["left"] == []
