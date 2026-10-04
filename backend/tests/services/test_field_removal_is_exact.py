"""Task 6 re-test: a reference is only a dependent when it belongs to the removed
entity's field, branches are never made constant, code and unknown reads are
named, an empty filter is refused, the seed rows and screen conditions are
included, a failure rolls back, and a differently spelled yes still reaches
the confirmation."""
import json

import pytest

from services.blueprint.service import BlueprintService
from services.smith import confirm, field_change as fc, field_dependents as fd

from tests.services.test_removing_a_field_takes_everything_that_reads_it import _ent, _wf, svc  # noqa: F401


def _wf_named(s, name):
    return next(w for w in s.doc["workflows"] if w["name"] == name)


def test_another_entitys_same_named_field_is_left_alone(svc):
    s = svc
    s.doc["data"]["entities"].append({"id": "ENTITY-002", "name": "Patient", "table": "patients", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True}, {"name": "preferredTime", "type": "string"}]})
    wf = _wf_named(s, "Edit Medicine")
    wf["inputs"].append({"name": "patient", "kind": "record", "entity": "ENTITY-002", "required": True})
    wf["inputs"].append({"name": "medicine", "kind": "record", "entity": "ENTITY-001", "required": True})
    wf["steps"][1]["config"]["expression"] = "patient.preferredTime == 'Morning' and medicine.preferredTime != ''"
    fc.remove_field(s, "Medicine", "preferredTime")
    expr = _wf_named(s, "Edit Medicine")["steps"][1]["config"]["expression"]
    assert "patient.preferredTime == 'Morning'" in expr and "medicine.preferredTime" not in expr
    assert expr != "true"


def test_a_decision_row_is_never_dropped_or_made_always_true(svc):
    s = svc
    wf = _wf_named(s, "Edit Medicine")
    wf["steps"].insert(1, {"key": "route", "name": "Route", "type": "decision", "next": ["upd"],
                           "config": {"rules": [{"when": "preferredTime == 'Morning'", "then": "a"},
                                                {"when": "name == 'x'", "then": "b"}]}})
    deps = fd.scan(s.doc, _ent(s), "preferredTime")
    row = [d for d in deps if "decides between" in d["what"]]
    assert row and row[0]["class"] == "manual"
    out = fc.remove_field(s, "Medicine", "preferredTime")
    rules = _wf_named(s, "Edit Medicine")["steps"][1]["config"]["rules"]
    assert [r["when"] for r in rules] == ["preferredTime == 'Morning'", "name == 'x'"]        # nothing dropped, nothing constant
    assert any("decides between" in x for x in out["left"])


def test_code_is_named_not_claimed_gone_and_quoted_prose_is_not_a_reference(svc):
    s = svc
    wf = _wf_named(s, "Edit Medicine")
    wf["steps"][1]["config"]["script"] = "return ctx.preferredTime"
    wf["steps"][1]["config"]["note"] = "'preferredTime is set' is what the owner says"
    out = fc.remove_field(s, "Medicine", "preferredTime")
    assert any("code (script)" in x for x in out["left"])
    assert not any("owner says" in x for x in out["left"])
    assert "Nothing still refers to it" not in fc.summary_of("remove_field", out)


def test_a_filter_that_would_be_left_empty_is_never_applied(svc):
    s = svc
    wf = _wf_named(s, "Edit Medicine")
    cfg = wf["steps"][1]["config"]
    cfg["actionType"], cfg["where"] = "db_delete", {"preferredTime": "{{preferredTime}}"}
    out = fc.remove_field(s, "Medicine", "preferredTime")
    assert cfg["where"] == {"preferredTime": "{{preferredTime}}"}                        # never emptied
    assert any("EVERY record" in x or "finds its records only by" in x for x in out["left"])


def test_sample_rows_and_screen_conditions_are_included(svc, tmp_path):
    s = svc
    (tmp_path / "contracts").mkdir(exist_ok=True)
    (tmp_path / "contracts/seed-plan.json").write_text(json.dumps(
        {"tables": [{"name": "Medicine", "seed_data": [{"name": "A", "preferredTime": "08:00"}]}],
         "sample_data": {"Medicine": [{"name": "A", "preferredTime": "08:00"}]}}))
    s.upsert("pages", {"name": "Add", "route": "/add", "pattern": "form", "purpose": "Add.", "actions": [],
                       "data": {"primaryEntity": "ENTITY-001"}}, natural_key="/add")
    pid = next(p["id"] for p in s.doc["pages"] if p["route"] == "/add")
    s.upsert("pageLayouts", {"page": pid, "dataSources": [], "root": {"type": "Form", "props": {"workflow": "F", "fields": [
        {"name": "name", "kind": "text", "label": "N"},
        {"name": "reminder", "kind": "text", "label": "R", "interaction": {"visibleIf": "preferredTime == 'Morning'",
                                                                          "dependsOn": ["preferredTime", "name"]}}]}, "children": []}},
             natural_key=pid)
    s.save()
    what = " | ".join(d["what"] for d in fd.scan(s.doc, _ent(s), "preferredTime", output_dir=tmp_path))
    assert "sample records" in what and "visibleIf" in what and "waits on preferredTime" in what
    out = fc.remove_field(s, "Medicine", "preferredTime")
    assert out["left"] == []
    seed = json.loads((tmp_path / "contracts/seed-plan.json").read_text())
    assert "preferredTime" not in json.dumps(seed)


def test_the_confirmation_speaks_plainly_with_the_raw_text_second(svc):
    lines = fd.describe(fd.scan(svc.doc, _ent(svc), "preferredTime"))
    step = next(l for l in lines if "validate_input" in l)
    assert step.startswith("the step") and "(written as:" in step and step.index("it would") < step.index("(written as:")


def test_a_failure_rolls_the_blueprint_back(svc, monkeypatch):
    before = json.dumps(svc.doc, sort_keys=True)
    real = fd.apply

    def boom(deps):
        todo = [d for d in deps if not d.get("handled") and d["class"] != "manual"]
        todo[0]["apply"]()
        raise RuntimeError("halfway")
    monkeypatch.setattr(fd, "apply", boom)
    with pytest.raises(RuntimeError):
        fc.remove_field(svc, "Medicine", "preferredTime")
    assert json.dumps(svc.doc, sort_keys=True) == before
    svc.save()
    assert json.dumps(BlueprintService.load(output_dir=str(svc.output_dir)).doc, sort_keys=True) == before
    monkeypatch.setattr(fd, "apply", real)


def test_a_differently_spelled_yes_still_reaches_the_confirmation(tmp_path):
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Medicine.preferredTime"))
    assert confirm.granted(tmp_path, "Go ahead", "remove_field", "medicines.preferred_time")
