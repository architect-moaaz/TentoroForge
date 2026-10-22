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


def test_two_tables_setting_the_same_field_are_two_rules(app):
    a = br.create(app, TABLE)["rule"]["rule"]
    other = json.loads(json.dumps(TABLE))
    other["name"] = "Location by type"
    other["table"]["inputs"] = [{"name": "employmentType"}]
    other["table"]["rules"] = [{"inputEntries": ["permanent"], "outputEntries": ["office"]}]
    b = br.create(app, other)["rule"]["rule"]
    assert a["id"] != b["id"] and a["statement"] != b["statement"]
    assert "Location by type" in b["statement"] and "employmentType" in b["statement"]


def test_a_rule_made_again_after_removal_keeps_nothing_of_the_removed_one(app):
    # Same wording -> same id; the removed record's `on` and scope must not come back.
    first = br.create(app, {**GATE, "statement": "Closed roles take no openings.", "on": ["create"],
                            "scope": "server"})["rule"]["rule"]
    br.remove(app, first["id"], expected=None)
    again = br.create(app, {**GATE, "statement": "Closed roles take no openings."})["rule"]["rule"]
    assert again["id"] == first["id"]
    assert "on" not in again and again.get("scope") != "server"
    assert again["status"] == "PROPOSED"
    rows = json.loads((app / "app" / "rules" / "blueprint-rules.json").read_text())
    assert "on" not in next(r for r in rows if r["id"] == again["id"])["config"]


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


def test_removing_a_rule_takes_it_out_of_every_workflow(app):
    rid = br.create(app, GATE)["rule"]["rule"]["id"]
    post, close = _flow(app, POST_ROLE)["steps"], _flow(app, CLOSE_ROLE)["steps"]
    br.attach(app, rid, workflow=POST_ROLE, after="validate_role_input")
    br.attach(app, rid, workflow=CLOSE_ROLE, after=None)
    out = br.remove(app, rid, expected=None)
    assert sorted(out["workflows"]) == sorted([POST_ROLE, CLOSE_ROLE])
    assert _flow(app, POST_ROLE)["steps"] == post and _flow(app, CLOSE_ROLE)["steps"] == close
    for f in (app / "app" / "src" / "lib" / "workflows" / "definitions").glob("*.json"):
        assert rid not in f.read_text(), f"{f.name} still runs the removed rule"


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


def test_a_second_rule_setting_the_same_field_is_warned_about(app):
    first = br.create(app, TABLE)["rule"]["rule"]
    other = {"name": "Remote when many", "kind": "condition_action", "entity": ROLE, "when": "openingsCount > 5",
             "then": [{"type": "set_field", "field": "location", "value": "remote"}]}
    said = br.try_rule(app, other)["advice"]
    assert any(first["id"] in a and "location" in a for a in said)
    # Not about itself, once saved.
    assert not any(first["id"] in a for a in br.try_rule(app, TABLE, rule_id=first["id"])["advice"])


def test_every_fault_is_said_at_once(app):
    said = br.try_rule(app, {**GATE, "when": "openingsCount >", "then": []})["problems"]
    assert any("Add what the rule does" in p for p in said) and any("cannot be read" in p for p in said)


# ---- what an attacker's requests found (adversarial API round, Oct 21) ---- #

def _said(app, rule) -> list[str]:
    return br.try_rule(app, rule)["problems"]


@pytest.mark.parametrize("when", ['"hello"', "42", "title", '"); process.exit(1); ("'])
def test_a_condition_is_a_yes_or_no_question(app, when):
    assert any("yes-or-no" in p for p in _said(app, {**GATE, "when": when})), when


@pytest.mark.parametrize("when, word", [
    ('status = "archived"', "not one of"),
    ('status in ["open", "archived"]', "not one of"),
    ("title > 5", "cannot be more or less"),
    ('openingsCount > "lots"', "is a number"),
    ("openingsCount > closedAt", "is a number"),
    ('matches(title, "(a+)+$")', "freeze"),
    ('matches(title, "([")', "not a valid pattern"),
])
def test_a_condition_the_engine_would_read_wrongly_is_refused(app, when, word):
    assert any(word in p for p in _said(app, {**GATE, "when": when})), (when, _said(app, {**GATE, "when": when}))


def test_conditions_that_are_fine_stay_fine(app):
    for when in ['status = "closed" and openingsCount > 0', "openingsCount >= 2", 'matches(title, "^[A-Z]")',
                 'employmentType in ["contract", "temporary"]', "previous.openingsCount > openingsCount",
                 'closedAt > date("2026-01-01")']:
        assert _said(app, {**GATE, "when": when}) == [], when


@pytest.mark.parametrize("act, word", [
    ({"type": "set_field", "field": "id", "value": "x"}, "identity"),
    ({"type": "set_field", "field": "openingsCount", "value": "lots"}, "is a number"),
    ({"type": "set_field", "field": "status", "value": "deleted"}, "not one of"),
    ({"type": "set_default", "field": "closedAt", "value": "soon"}, "is a date"),
    ({"type": "clear_field", "field": "createdAt"}, "identity"),
])
def test_a_value_a_rule_writes_fits_its_field(app, act, word):
    said = _said(app, {**GATE, "then": [act]})
    assert any(word in p for p in said), said
    assert _said(app, {**GATE, "then": [{"type": "set_field", "field": "openingsCount", "value": "0"}]}) == []


def test_a_table_writes_values_that_fit_and_reads_each_field_once(app):
    t = json.loads(json.dumps(TABLE))
    t["table"]["outputs"] = [{"name": "openingsCount"}]
    t["table"]["rules"] = [{"inputEntries": ["[1..2]", "permanent"], "outputEntries": ["lots"]}]
    assert any("is a number" in p for p in _said(app, t))
    t["table"]["outputs"] = [{"name": "id"}]
    assert any("identity" in p for p in _said(app, t))
    t = json.loads(json.dumps(TABLE))
    t["table"]["inputs"] = [{"name": "openingsCount"}, {"name": "openingsCount"}]
    assert any("one column" in p for p in _said(app, t))
    t = json.loads(json.dumps(TABLE))
    t["table"]["rules"][0]["inputEntries"][1] = "> permanent"
    assert any("cannot be more or less" in p for p in _said(app, t))


def test_what_a_payload_cannot_say(app):
    with pytest.raises(br.RuleError, match="created, changed"):
        br.create(app, {**GATE, "on": ["delete"]})
    with pytest.raises(br.RuleError, match="at most 1000"):
        br.create(app, {**GATE, "then": [{"type": "show_error", "message": "x" * 1001}]})
    with pytest.raises(br.RuleError, match="name, not"):
        br.create(app, {**GATE, "then": [{"type": "set_field", "field": ["a"], "value": "1"}]})
    with pytest.raises(br.RuleError, match="Priority"):
        br.create(app, {**GATE, "salience": 10 ** 30})
    with pytest.raises(br.RuleError, match="name"):     # invisible characters are no name
        br.create(app, {**GATE, "name": "​​\x00"})


def test_enabled_null_leaves_it_as_it_is(app):
    made = br.create(app, GATE)["rule"]["rule"]
    again = br.update(app, made["id"], {"enabled": None, "name": "Renamed"}, expected=None)["rule"]["rule"]
    assert again.get("enabled") is not False and again["name"] == "Renamed"


def test_a_generated_rule_without_a_kind_can_be_switched_off_and_renamed(app):
    rid = next(r["id"] for r in _doc(app)["businessRules"] if not r.get("kind"))
    br.set_enabled(app, rid, False, expected=None)
    renamed = br.update(app, rid, {"name": "Kept, renamed"}, expected=None)["rule"]["rule"]
    assert renamed["enabled"] is False and renamed["name"] == "Kept, renamed"


def test_a_rule_runs_only_in_a_workflow_that_works_with_its_record(app):
    rid = br.create(app, GATE)["rule"]["rule"]["id"]
    with pytest.raises(br.RuleError, match="does not work with a Role"):
        br.attach(app, rid, workflow="FLOW-004", after=None)     # Add a Candidate
    br.attach(app, rid, workflow="FLOW-002", after=None)          # Edit Role Details


def test_a_sample_record_is_a_record():
    from pydantic import ValidationError
    from routers.business_rules import TestPayload
    deep: dict = {}
    node = deep
    for _ in range(3000):
        node["a"] = {}
        node = node["a"]
    with pytest.raises(ValidationError, match="8 levels"):
        TestPayload(record=deep)
    with pytest.raises(ValidationError, match="finite"):
        TestPayload(record={"openingsCount": float("nan")})
    assert TestPayload(record={"title": "x", "tags": ["a"], "meta": {"k": 1}}).record["meta"] == {"k": 1}


def test_a_template_is_used_under_a_real_name():
    from pydantic import ValidationError
    from routers.project_templates import UseTemplateRequest
    with pytest.raises(ValidationError, match="name"):
        UseTemplateRequest(template_id="t", name="   ")
    assert UseTemplateRequest(template_id="t", name="  Desk  ").name == "Desk"


# ---- round 2 of the adversarial API run (Oct 21) ---------------------------- #

@pytest.mark.parametrize("when, word", [
    ("5 < title", "cannot be more or less"),
    ('"archived" = status', "not one of"),
    ("openingsCount = title", "is a number"),
    ("openingsCount = true", "is a number"),
    ('closedAt > "yesterday"', "is a date"),
    ('previous.status = "archived"', "not one of"),
    ('matches(title, "(a|aa)+$")', "freeze"),
    ('matches(title, "((a+))+$")', "freeze"),
    ("matches(title, description)", "written in the rule"),
    ('matches(title, "(?P<n>a)")', "does not read"),
])
def test_round_two_conditions_are_refused(app, when, word):
    said = _said(app, {**GATE, "when": when})
    assert any(word in p for p in said), (when, said)


@pytest.mark.parametrize("when", [
    'not(matches(location, "^[a-z]+(-[a-z]+)*$"))', 'matches(title, "^([a-z0-9]+\\\\.)+[a-z]{2,}$")',
    'closedAt > "2026-01-01"', "openingsCount = 3", 'status = "open"', '"open" = status',
    "closedAt > createdAt", "user.role = \"admin\"",
])
def test_round_two_fine_conditions_stay_fine(app, when):
    assert _said(app, {**GATE, "when": when}) == [], when


@pytest.mark.parametrize("act, word", [
    ({"type": "set_field", "field": "openingsCount", "valueMode": "formula", "value": '"lots"'}, "is a number"),
    ({"type": "set_field", "field": "openingsCount", "valueMode": "field", "value": "title"}, "different kinds"),
    ({"type": "set_field", "field": "openingsCount", "valueMode": "field", "value": "nope"}, "not a field"),
    ({"type": "set_field", "field": "openingsCount", "valueMode": "formula", "value": "((("}, "cannot be read"),
    ({"type": "set_field", "field": "status", "valueMode": "formula", "value": '"deleted"'}, "not one of"),
])
def test_a_copied_or_worked_out_value_fits_its_field_too(app, act, word):
    said = _said(app, {**GATE, "then": [act]})
    assert any(word in p for p in said), said


def test_formulas_and_copies_that_fit_are_fine(app):
    for act in ({"type": "set_field", "field": "openingsCount", "valueMode": "formula", "value": "openingsCount + 1"},
                {"type": "set_field", "field": "location", "valueMode": "field", "value": "clientOrDepartment"}):
        assert _said(app, {**GATE, "then": [act]}) == [], act


def test_round_two_payloads(app):
    with pytest.raises(br.RuleError, match="must be text"):
        br.create(app, {**GATE, "then": [{"type": "show_error", "message": 5}]})
    with pytest.raises(br.RuleError, match="formula"):
        br.create(app, {**GATE, "then": [{"type": "set_field", "field": "title", "valueMode": "magic", "value": "x"}]})
    t = json.loads(json.dumps(TABLE))
    t["table"]["rules"][1]["inputEntries"][0] = "> title"
    assert any("different kind" in p for p in _said(app, t))


def test_a_pattern_that_could_hang_the_engine_is_not_run_by_test_it(app):
    import time
    t0 = time.monotonic()
    r = br.test_rule(app, {**GATE, "when": 'matches(title, "(a+)+$")'}, record={"title": "a" * 34 + "!"})
    assert not r["ok"] and time.monotonic() - t0 < 5


def test_a_page_path_is_not_a_record(app):
    rid = br.create(app, GATE)["rule"]["rule"]["id"]
    with pytest.raises(br.RuleError, match="does not work with a Role"):
        br.attach(app, rid, workflow="FLOW-009", after=None)       # Reject Application: /roles/[id]/pipeline


# ---- round 3: the pattern check judges overlap, not shape ------------------- #

SAFE_PATTERNS = [
    "^[a-z0-9]+(-[a-z0-9]+)*$", "^([a-z0-9]+\\.)+[a-z]{2,}$", "^(ab|cd)*$", "^(\\w|-)+$", "^([a-z]|[0-9])+$",
    "^(\\s|\\w)+$", "^([A-Z][a-z]*)+$", "^\\d+(\\.\\d{2})?$", "^\\$?\\d{1,3}(,\\d{3})*(\\.\\d{2})?$",
    "^(draft|open|closed)$", "\\b(urgent|asap)\\b", "^(Mr|Mrs|Ms|Dr)\\.? [A-Z]", "^(?=.*[A-Z])(?=.*\\d).{8,}$",
    "^(?!test).*$", "^(\\d+,)*\\d+$", "^(\\d{1,3}\\.){3}\\d{1,3}$", "^#([0-9a-fA-F]{3}){1,2}$",
    "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", "^[^@\\s]+@[^@\\s]+\\.[a-z]{2,}$",
]
HANGING_PATTERNS = ["(a+)+$", "(a|aa)+$", "(a|a?)+$", "((a+))+$", "(\\w+\\s?)*$", "(.*a){12}", "^(\\d|\\d\\d)+$",
                    "^(x+x+)+y$", "^(.*?,){11}P", "(a*)*", "(([a-z])+)*"]


@pytest.mark.parametrize("pattern", SAFE_PATTERNS)
def test_patterns_people_use_are_accepted(pattern):
    assert br._pattern_problem(pattern) is None, pattern


@pytest.mark.parametrize("pattern", HANGING_PATTERNS)
def test_patterns_that_can_hang_are_refused(pattern):
    assert "freeze" in (br._pattern_problem(pattern) or ""), pattern


def test_inline_options_are_said_as_options():
    said = br._pattern_problem("(?i)^senior") or ""
    assert "options" in said and "named" not in said


def test_collect_totals_fill_numbers_and_any_rows_agree(app):
    t = json.loads(json.dumps(TABLE))
    t["table"].update(hitPolicy="C", aggregation="COUNT")       # location is text
    assert any("Collect totals fill number fields" in p for p in _said(app, t))
    t = json.loads(json.dumps(TABLE))
    t["table"]["outputs"] = [{"name": "openingsCount"}]
    t["table"].update(hitPolicy="C", aggregation="SUM")
    t["table"]["rules"] = [{"inputEntries": ["-", "-"], "outputEntries": ["1"]},
                           {"inputEntries": ["> 1", "-"], "outputEntries": ["2"]}]
    assert _said(app, t) == []
    t = json.loads(json.dumps(TABLE))
    t["table"]["hitPolicy"] = "A"
    t["table"]["rules"] = [{"inputEntries": ["-", "-"], "outputEntries": ["office"]},
                           {"inputEntries": ["> 1", "-"], "outputEntries": ["remote"]}]
    assert any("must agree" in p or "needs them to agree" in p for p in _said(app, t))
    t["table"]["rules"][1]["outputEntries"] = ["office"]
    assert _said(app, t) == []


def test_after_a_yes_no_step_the_check_goes_on_the_path_chosen(app):
    rid = br.create(app, GATE)["rule"]["rule"]["id"]
    key = br._step_key(rid)
    br.attach(app, rid, workflow=POST_ROLE, after="validate_role_input", path="else")
    steps = {s["key"]: s for s in _flow(app, POST_ROLE)["steps"]}
    assert steps["validate_role_input"]["next"] == ["create_role", key]
    assert steps[key]["next"][0] == "show_role_validation_errors"
    with pytest.raises(br.RuleError, match="yes or its no"):
        br.attach(app, rid, workflow=POST_ROLE, after="validate_role_input", path="maybe")
