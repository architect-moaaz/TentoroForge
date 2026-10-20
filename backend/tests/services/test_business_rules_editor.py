"""The Business Rules editor: rules are authored, tested and used in workflows.

Drools has guided rules, decision tables and business-rule tasks in its
processes; Forge's tab had a rule form, a table nobody could save, and no way
into a workflow. These hold the service behind the editor to what it now
promises — on the ATS fixture's Role record (status open/closed, openings) —
with the app's own engine (`rule_lab`) answering every "what would happen".
No model is called.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import business_rules as br
from services.blueprint.service import BlueprintService

FIXTURE = Path(__file__).resolve().parents[2] / "fleet" / "blueprints" / "ats-live.json"
ROLE = "ENTITY-002"
POST_ROLE = "FLOW-001"      # validate_role_input -> create_role -> land_on_role -> end
CLOSE_ROLE = "FLOW-003"


@pytest.fixture
def app(tmp_path) -> Path:
    out = tmp_path / "ats00002"
    (out / ".forge" / "blueprint").mkdir(parents=True)
    (out / "app").mkdir()
    doc = json.loads(FIXTURE.read_text())
    doc["application"]["id"] = "ats00002"
    (out / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc))
    return out


def _doc(out: Path) -> dict:
    return BlueprintService.load(output_dir=out).doc


def _flow(out: Path, wid: str) -> dict:
    return next(w for w in _doc(out)["workflows"] if w["id"] == wid)


TABLE = {
    "name": "Hiring priority", "kind": "decision_table", "entity": ROLE,
    "table": {"hitPolicy": "U",
              "inputs": [{"name": "openingsCount"}, {"name": "employmentType"}],
              "outputs": [{"name": "location"}],
              "rules": [{"inputEntries": ["[1..2]", "permanent"], "outputEntries": ["office"]},
                        {"inputEntries": ["> 2", "-"], "outputEntries": ["remote"]},
                        {"inputEntries": ["[1..2]", "contract, temporary, internship"], "outputEntries": ["hybrid"]}]},
}
GATE = {"name": "A closed role takes no openings", "kind": "condition_action", "entity": ROLE,
        "when": 'status = "closed" and openingsCount > 0',
        "then": [{"type": "show_error", "message": "A closed role cannot have openings."}]}


# ---- authoring ------------------------------------------------------------ #

def test_a_decision_table_with_ranges_and_alternatives_is_saved_and_projected(app):
    made = br.create(app, TABLE, actor="t")
    rule = made["rule"]["rule"]
    assert made["rule"]["runs"] == "save"
    t = rule["table"]
    assert t["hitPolicy"] == "U"
    assert [c["variableBinding"] for c in t["outputs"]] == ["location"], "an output keeps the field it writes"
    enum_col = t["inputs"][1]
    assert enum_col["type"] == "string" and enum_col["values"] == ["permanent", "contract", "temporary", "internship"]
    rows = json.loads((app / "app" / "rules" / "blueprint-rules.json").read_text())
    assert any(r["rule_type"] == "decision_table" and r["id"] == rule["id"] for r in rows)


def test_a_table_the_engine_cannot_run_is_refused_with_the_row_and_column(app):
    bad = json.loads(json.dumps(TABLE))
    bad["table"]["rules"][0]["inputEntries"][0] = "[9..1]"
    with pytest.raises(br.RuleError) as e:
        br.create(app, bad)
    assert "Row 1, openingsCount" in str(e.value) and "starts after it ends" in str(e.value)

    typo = json.loads(json.dumps(TABLE))
    typo["table"]["rules"][0]["inputEntries"][1] = "permenant"
    with pytest.raises(br.RuleError) as e:
        br.create(app, typo)
    assert "“permenant” is not one of permanent" in str(e.value)


def test_a_unique_table_with_overlapping_rows_is_refused_and_first_is_offered(app):
    overlap = json.loads(json.dumps(TABLE))
    overlap["table"]["rules"].append({"inputEntries": [">= 2", "permanent"], "outputEntries": ["office"]})
    with pytest.raises(br.RuleError) as e:
        br.create(app, overlap)
    assert "Unique" in str(e.value) and "use First" in str(e.value)
    overlap["table"]["hitPolicy"] = "F"
    assert br.create(app, overlap)["rule"]["rule"]["table"]["hitPolicy"] == "F"


def test_an_unreachable_row_is_said_not_refused(app):
    tbl = json.loads(json.dumps(TABLE))
    tbl["table"]["hitPolicy"] = "F"
    tbl["table"]["rules"].insert(0, {"inputEntries": ["-", "-"], "outputEntries": ["anywhere"]})
    checked = br.try_rule(app, tbl)
    assert checked["ok"], checked["problems"]
    assert any("can never be used" in a for a in checked["advice"])
    assert any(f["kind"] == "unreachable" and f["row"] == 2 for f in checked["findings"])


def test_a_table_setting_a_field_needs_one_value_per_field(app):
    for policy, agg, ok in (("C", None, False), ("R", None, False), ("C", "SUM", True)):
        tbl = json.loads(json.dumps(TABLE))
        tbl["name"] = f"Openings {policy}{agg}"
        tbl["table"] = {"hitPolicy": policy, **({"aggregation": agg} if agg else {}),
                        "inputs": [{"name": "status"}], "outputs": [{"name": "openingsCount"}],
                        "rules": [{"inputEntries": ["open"], "outputEntries": ["2"]},
                                  {"inputEntries": ["-"], "outputEntries": ["1"]}]}
        checked = br.try_rule(app, tbl)
        assert checked["ok"] is ok, (policy, agg, checked["problems"])


def test_a_rule_that_acts_only_otherwise_is_a_rule(app):
    otherwise_only = {"name": "Openings needed", "kind": "condition_action", "entity": ROLE,
                      "when": "openingsCount > 0", "then": [],
                      "otherwise": [{"type": "show_error", "message": "Give it at least one opening."}]}
    assert br.try_rule(app, otherwise_only)["ok"]
    nothing = {**otherwise_only, "otherwise": []}
    assert not br.try_rule(app, nothing)["ok"]


def test_when_it_fires_is_kept_and_projected(app):
    rule = {**GATE, "on": ["update", "create", "update"]}
    made = br.create(app, rule)["rule"]["rule"]
    assert "on" not in made, "both is the default and not stored"
    made = br.update(app, made["id"], {"on": ["update"]}, expected=None)["rule"]["rule"]
    assert made["on"] == ["update"]
    rows = json.loads((app / "app" / "rules" / "blueprint-rules.json").read_text())
    assert next(r for r in rows if r["id"] == made["id"])["config"]["on"] == ["update"]
    assert any("previous" in a for a in br.advice(_doc(app), {"on": ["create"], "when": "previous.status = 1"}))


# ---- test it -------------------------------------------------------------- #

def test_test_it_runs_the_draft_among_the_records_rules(app):
    r = br.test_rule(app, GATE, record={"status": "closed", "openingsCount": 3})
    assert r["refused"] and r["errors"] == ["A closed role cannot have openings."]
    assert r["focus"]["held"] is True and r["focus"]["fires"] is True
    r = br.test_rule(app, GATE, record={"status": "open", "openingsCount": 3})
    assert not r["refused"] and r["focus"]["held"] is False
    # On an update, with what the record was.
    on_update = {**GATE, "on": ["update"], "when": 'previous.status = "closed" and status = "open"',
                 "then": [{"type": "show_error", "message": "A closed role stays closed."}]}
    assert br.test_rule(app, on_update, record={"status": "open"})["refused"] is False, "quiet on create"
    r = br.test_rule(app, on_update, record={"status": "open"}, previous={"status": "closed"}, event="update")
    assert r["errors"] == ["A closed role stays closed."]


def test_test_it_shows_which_rows_matched_and_what_was_set(app):
    r = br.test_rule(app, TABLE, record={"openingsCount": 2, "employmentType": "contract"})
    assert r["patches"]["location"] == "hybrid"
    assert r["focus"]["matched"] == [3] and r["focus"]["used"] == [3]
    r = br.test_rule(app, TABLE, record={"openingsCount": 0, "employmentType": "permanent"})
    assert r["focus"]["matched"] == [] and "location" not in r["patches"]


def test_test_it_on_a_saved_rule_replaces_it_not_doubles_it(app):
    saved = br.create(app, GATE)["rule"]["rule"]
    softer = {**GATE, "then": [{"type": "set_field", "field": "openingsCount", "valueMode": "literal", "value": "0"}]}
    r = br.test_rule(app, softer, rule_id=saved["id"], record={"status": "closed", "openingsCount": 3})
    assert not r["refused"] and r["patches"]["openingsCount"] == 0, "the draft stands in for the saved rule"


def test_a_written_rule_and_a_rule_without_a_record_say_why_they_cannot_be_tested(app):
    r = br.test_rule(app, {"kind": "statement", "name": "Be kind", "statement": "Be kind to candidates."})
    assert not r["ok"] and "written rule" in r["problems"][0]
    r = br.test_rule(app, {**GATE, "entity": None})
    assert not r["ok"]


# ---- in workflows --------------------------------------------------------- #

def test_a_gate_runs_as_a_step_and_its_refusal_stops_the_workflow(app):
    rid = br.create(app, GATE)["rule"]["rule"]["id"]
    out = br.attach(app, rid, workflow=POST_ROLE, after="validate_role_input", on_refusal="stop")
    flow = _flow(app, POST_ROLE)
    key = br._step_key(rid)
    steps = {s["key"]: s for s in flow["steps"]}
    assert steps["validate_role_input"]["next"][0] == key, "the step comes after the one chosen, on its then-path"
    assert steps["validate_role_input"]["next"][1] == "show_role_validation_errors", "its else-path is kept"
    assert steps[key]["type"] == "decision" and steps[key]["config"] == {"rule": rid}
    assert steps[key]["next"] == ["create_role", f"{key}_refused"]
    assert steps[f"{key}_refused"]["config"] == {"refused": True, "message": "A closed role cannot have openings."}
    assert out["rule"]["usages"]["steps"] == [{"workflow": POST_ROLE, "name": "Post a Role", "step": key,
                                                "stepName": "Check: A closed role takes no openings", "stops": True}]
    graph = json.loads(next((app / "app" / "src" / "lib" / "workflows" / "definitions").glob("*post*role*.json")).read_text())
    nodes = {n["id"]: n for n in graph["definition"]["nodes"]}
    assert nodes[key]["type"] == "decision" and nodes[key]["data"]["config"]["rule"] == rid
    kinds = {(e["source"], e["target"]): e["data"]["edgeType"] for e in graph["definition"]["edges"]}
    assert kinds[(key, "create_role")] == "then" and kinds[(key, f"{key}_refused")] == "else"


def test_placing_it_again_moves_it_and_detaching_restores_the_workflow(app):
    rid = br.create(app, GATE)["rule"]["rule"]["id"]
    original = _flow(app, POST_ROLE)["steps"]
    br.attach(app, rid, workflow=POST_ROLE, after="validate_role_input")
    br.attach(app, rid, workflow=POST_ROLE, after="create_role", on_refusal="continue")
    steps = {s["key"]: s for s in _flow(app, POST_ROLE)["steps"]}
    key = br._step_key(rid)
    assert sum(1 for k in steps if k == key) == 1 and f"{key}_refused" not in steps, "moved, not doubled"
    assert steps["validate_role_input"]["next"][0] == "create_role"
    assert steps["create_role"]["next"] == [key] and steps[key]["next"] == ["land_on_role"]
    br.detach(app, rid, workflow=POST_ROLE)
    assert _flow(app, POST_ROLE)["steps"] == original
    with pytest.raises(br.RuleError) as e:
        br.detach(app, rid, workflow=POST_ROLE)
    assert e.value.status == 404


def test_at_the_start_and_before_an_end(app):
    rid = br.create(app, TABLE)["rule"]["rule"]["id"]
    br.attach(app, rid, workflow=CLOSE_ROLE, after=None)
    steps = _flow(app, CLOSE_ROLE)["steps"]
    assert steps[0]["key"] == br._step_key(rid) and steps[0]["next"] == ["confirm_close"]
    with pytest.raises(br.RuleError) as e:
        br.attach(app, rid, workflow=CLOSE_ROLE, after="end")
    assert "end of the workflow" in str(e.value)
    with pytest.raises(br.RuleError):
        br.attach(app, rid, workflow=CLOSE_ROLE, after="nope")
    with pytest.raises(br.RuleError):
        br.attach(app, rid, workflow="FLOW-999", after=None)


def test_only_a_rule_the_app_checks_can_be_a_step(app):
    stated = next(r for r in _doc(app)["businessRules"] if r.get("kind", "statement") == "statement")
    with pytest.raises(br.RuleError) as e:
        br.attach(app, stated["id"], workflow=POST_ROLE, after=None)
    assert "enforceable" in str(e.value)
    rid = br.create(app, GATE)["rule"]["rule"]["id"]
    br.set_enabled(app, rid, False, expected=None)
    with pytest.raises(br.RuleError) as e:
        br.attach(app, rid, workflow=POST_ROLE, after=None)
    assert "switched off" in str(e.value)


def test_a_rule_lists_the_workflows_that_save_its_record(app):
    made = br.create(app, GATE)["rule"]
    saves = {u["workflow"] for u in made["usages"]["saves"]}
    assert {"FLOW-001", "FLOW-002", "FLOW-003"} <= saves
    assert "FLOW-004" not in saves, "adding a candidate does not save a role"


def test_the_catalogue_lists_each_workflows_steps(app):
    flows = br.read(app)["catalogue"]["workflows"]
    post = next(w for w in flows if w["id"] == POST_ROLE)
    assert [s["key"] for s in post["steps"]][:3] == ["validate_role_input", "show_role_validation_errors", "create_role"]
