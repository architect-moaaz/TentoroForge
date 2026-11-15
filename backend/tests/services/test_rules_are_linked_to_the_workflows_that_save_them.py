"""A business rule is linked to every workflow that saves its record — by the
app, with no one connecting it — and a workflow's own copy of a rule is the
rule, not a second check that goes stale (services/rule_links.py).

The team's finding (2026-10-23): the Business Rules tab said a rule ran in no
workflow, while every workflow checked a copy of it (`check_amount: amount >
0`) that an edit of the rule never reached."""
from __future__ import annotations

import copy

import pytest

from services import rule_links as L
from tests.rule_lab_needed import needs_lab as needs_node  # node and esbuild


def _doc() -> dict:
    """Expense Desk as the build writes it: rules, and workflows that copy them."""
    refused = lambda key, msg: {"key": key, "type": "end", "config": {"refused": True, "message": msg}, "next": []}  # noqa: E731
    return {
        "data": {"entities": [{
            "id": "ENTITY-001", "name": "Expense", "table": "expenses",
            "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "title", "type": "string", "required": True},
                {"name": "amount", "type": "decimal", "required": True},
                {"name": "category", "type": "enum", "enumValues": ["travel", "meals", "office"], "required": True},
                {"name": "status", "type": "enum", "enumValues": ["submitted", "approved", "rejected"], "required": True},
                {"name": "managerNote", "type": "text"},
            ]}]},
        "businessRules": [
            {"id": "RULE-001", "name": "Positive amount", "kind": "condition_action", "entity": "ENTITY-001",
             "when": "amount <= 0", "then": [{"type": "show_error", "message": "The amount must be more than zero."}],
             "otherwise": []},
            {"id": "RULE-002", "name": "Manager note above 5000", "kind": "condition_action", "entity": "ENTITY-001",
             "when": "amount > 5000",
             "then": [{"type": "set_required", "field": "managerNote", "required": True,
                       "message": "A manager note is needed above 5000."}],
             "otherwise": [{"type": "set_required", "field": "managerNote", "required": False}]},
            {"id": "RULE-003", "name": "Rejected stays rejected", "kind": "condition_action", "entity": "ENTITY-001",
             "when": 'previous.status = "rejected" and status = "approved"',
             "then": [{"type": "show_error", "message": "A rejected expense can never be approved."}], "otherwise": []},
            {"id": "RULE-004", "name": "Starts as submitted", "kind": "condition_action", "entity": "ENTITY-001",
             "when": "status = null", "then": [{"type": "set_default", "field": "status", "value": "submitted"}],
             "otherwise": []},
        ],
        "workflows": [
            {"id": "FLOW-001", "name": "Log an expense", "steps": [
                {"key": "start", "type": "trigger", "next": ["check_amount"]},
                {"key": "check_amount", "type": "condition", "config": {"expression": "amount > 0"},
                 "next": ["check_note", "refuse_amount"]},
                refused("refuse_amount", "Enter what was spent."),
                {"key": "check_note", "type": "condition",
                 "config": {"expression": 'amount <= 5000 or (managerNote != null and managerNote != "")'},
                 "next": ["insert_expense", "refuse_note"]},
                refused("refuse_note", "Above 5000 a manager note is needed."),
                {"key": "insert_expense", "type": "action", "entity": "ENTITY-001",
                 "config": {"actionType": "db_insert", "table": "expenses",
                            "values": {"title": "{{title}}", "amount": "{{amount}}", "category": "{{category}}",
                                       "managerNote": '{{managerNote ?? ""}}', "status": "submitted"}},
                 "next": ["done"]},
                {"key": "done", "type": "end", "config": {"refused": False}, "next": []},
            ]},
            {"id": "FLOW-002", "name": "Approve", "steps": [
                {"key": "check_rejected", "type": "condition", "config": {"expression": 'expense.status = "rejected"'},
                 "next": ["end_refused", "update_status"]},
                {"key": "update_status", "type": "action",
                 "config": {"actionType": "db_update", "table": "expenses", "values": {"status": "approved"},
                            "where": {"id": "{{expense.id}}"}}, "next": ["end_ok"]},
                refused("end_refused", "This expense was rejected."),
                {"key": "end_ok", "type": "end", "config": {"refused": False}, "next": []},
            ]},
            {"id": "FLOW-003", "name": "List expenses", "steps": [
                {"key": "load", "type": "action", "entity": "ENTITY-001",
                 "config": {"actionType": "db_query", "table": "expenses"}, "next": ["done"]},
                {"key": "done", "type": "end", "config": {"refused": False}, "next": []},
            ]},
        ],
    }


def _rule(doc: dict, rid: str) -> dict:
    return next(r for r in doc["businessRules"] if r["id"] == rid)


def test_a_rule_is_linked_to_every_workflow_that_saves_its_record_on_the_saves_it_is_for():
    doc = _doc()
    links = {rid: [(x["name"], x["event"], x["touches"]) for x in L.links(doc, _rule(doc, rid))]
             for rid in ("RULE-001", "RULE-003", "RULE-004")}
    # A new expense and an approval both save an expense; a list never does.
    assert links["RULE-001"] == [("Log an expense", "create", True), ("Approve", "update", False)]
    # A rule about the value before a change is checked only on a change.
    assert links["RULE-003"] == [("Approve", "update", True)]
    # A rule that only fills in an empty value acts on every save, as the
    # app's engine runs it: a change with the value still empty is filled too.
    assert links["RULE-004"] == [("Log an expense", "create", True), ("Approve", "update", True)]
    # Unless it says which saves it is for.
    _rule(doc, "RULE-004")["on"] = ["create"]
    assert [x["name"] for x in L.links(doc, _rule(doc, "RULE-004"))] == ["Log an expense"]


def test_a_switched_off_rule_is_linked_nowhere():
    doc = _doc()
    _rule(doc, "RULE-001")["enabled"] = False
    assert L.links(doc, _rule(doc, "RULE-001")) == []


def test_the_workflow_screen_gets_the_rules_each_save_step_checks():
    by_flow = L.workflow_links(_doc())
    assert [c["rule"] for c in by_flow["FLOW-001"]["insert_expense"]] == ["RULE-001", "RULE-002", "RULE-004"]
    assert [c["rule"] for c in by_flow["FLOW-002"]["update_status"]] == ["RULE-001", "RULE-002", "RULE-003", "RULE-004"]
    assert "FLOW-003" not in by_flow


@needs_node
def test_a_workflow_check_that_says_what_a_rule_says_is_proven_the_rule_and_others_are_not():
    doc = _doc()
    verdict = {(c["rule"], c["workflow"], c["step"]): c["same"] for c in L.review_all(doc)}
    assert verdict[("RULE-001", "FLOW-001", "check_amount")] is True
    assert verdict[("RULE-002", "FLOW-001", "check_note")] is True
    # The rule about a change, against the loaded record and the change the step makes.
    assert verdict[("RULE-003", "FLOW-002", "check_rejected")] is True
    # A check on the same field that says something else is not that rule.
    assert verdict[("RULE-001", "FLOW-001", "check_note")] is False


@needs_node
def test_proven_copies_are_taken_out_and_the_workflow_still_reaches_its_save():
    doc = _doc()
    done = L.fold_copies(doc)
    assert {(d["workflow"], d["step"]) for d in done} == {
        ("FLOW-001", "check_amount"), ("FLOW-001", "check_note"), ("FLOW-002", "check_rejected")}
    log = {s["key"]: s.get("next") for s in doc["workflows"][0]["steps"]}
    assert log == {"start": ["insert_expense"], "insert_expense": ["done"], "done": []}
    approve = doc["workflows"][1]["steps"]
    # It began with the copy: what came after it begins it now; the stop went with it.
    assert [s["key"] for s in approve] == ["update_status", "end_ok"]
    assert L.review_all(doc) == []


@needs_node
def test_a_copy_left_behind_by_an_edit_is_kept_and_reported_not_taken_out():
    doc = _doc()
    _rule(doc, "RULE-002")["when"] = "amount > 7000"     # the rule was edited after the build
    assert not any(d["step"] == "check_note" for d in L.fold_copies(doc))
    left = [c for c in L.review(doc, _rule(doc, "RULE-002")) if c["step"] == "check_note"]
    assert left and left[0]["same"] is False and left[0]["differs"]


def test_a_fold_reads_where_the_step_goes_now_not_where_it_went_when_judged():
    doc = _doc()
    flow = doc["workflows"][0]
    first = {"step": "check_amount", "stop": "refuse_amount", "goOn": "check_note"}
    second = {"step": "check_note", "stop": "refuse_note", "goOn": "insert_expense"}
    assert L.fold(flow, second) and L.fold(flow, dict(first))
    assert {s["key"]: s.get("next") for s in flow["steps"]}["start"] == ["insert_expense"]


def test_a_rule_that_only_fills_in_a_value_cannot_be_made_a_workflow_step(tmp_path, monkeypatch):
    from services import business_rules as rules
    from services.blueprint.service import BlueprintService

    doc = _doc()
    svc = type("S", (), {})()
    svc.doc = copy.deepcopy(doc)
    svc.output_dir = str(tmp_path)
    monkeypatch.setattr(rules, "_guard_writable", lambda *_a, **_k: None)
    monkeypatch.setattr(rules, "_refuse_if_building", lambda *_a, **_k: None)
    monkeypatch.setattr(BlueprintService, "load", classmethod(lambda cls, **_k: svc))
    with pytest.raises(rules.RuleError, match="only fills in or changes values"):
        rules.attach(tmp_path, "RULE-004", workflow="FLOW-002", after=None)


def test_smith_reads_where_each_rule_is_checked():
    from services.smith import reads
    said = reads.run("rule_links", {"rule": "rejected"}, output_dir="", doc=_doc())
    assert "RULE-003" in said and "Approve (FLOW-002)" in said and "Log an expense" not in said
    said = reads.run("rule_links", {"workflow": "List expenses", "rule": "positive"}, output_dir="", doc=_doc())
    assert "not checked in List expenses" in said
    assert "No business rule called" in reads.run("rule_links", {"rule": "nope"}, output_dir="", doc=_doc())


@needs_node
def test_smith_links_a_rule_says_already_linked_or_adds_an_extra_check(tmp_path, monkeypatch):
    from services import business_rules as rules
    from services.blueprint.service import BlueprintService
    from services.smith4.verbs import Ctx, perform

    svc = type("S", (), {})()
    svc.doc = _doc()
    svc.output_dir = str(tmp_path)
    monkeypatch.setattr(BlueprintService, "load", classmethod(lambda cls, **_k: svc))
    attached = []
    monkeypatch.setattr(rules, "attach", lambda out, rid, **k: attached.append((rid, k["workflow"])) or {"version": 9})
    ctx = Ctx(output_dir=str(tmp_path), project_id="p", message="", ask="")
    out = perform(ctx, "link_rule", {"verb": "link_rule", "rule": "positive amount", "workflow": "log an expense"})
    assert out.status == "resolved" and "already linked" in out.said and not attached
    out = perform(ctx, "link_rule", {"verb": "link_rule", "rule": "positive amount", "workflow": "approve"})
    assert out.status == "resolved" and attached == [("RULE-001", "FLOW-002")]
    out = perform(ctx, "link_rule", {"verb": "link_rule", "rule": "starts as submitted", "workflow": "approve"})
    assert out.status == "resolved" and "already linked" in out.said
    _rule(svc.doc, "RULE-004")["on"] = ["create"]
    out = perform(ctx, "link_rule", {"verb": "link_rule", "rule": "starts as submitted", "workflow": "approve"})
    assert out.status == "needs_user" and "only fills in values" in out.said and len(attached) == 1
    out = perform(ctx, "unlink_rule", {"verb": "unlink_rule", "rule": "positive amount", "workflow": "log an expense"})
    assert out.status == "needs_user" and "automatically" in out.said


@needs_node
def test_an_old_check_belongs_to_one_rule_never_to_one_that_only_shares_a_field():
    doc = _doc()
    assert L.stale(doc, L.review_all(doc)) == [], "every check matches its own rule"
    _rule(doc, "RULE-002")["when"] = "amount > 7000"
    assert [(c["rule"], c["step"]) for c in L.stale(doc, L.review_all(doc))] == [("RULE-002", "check_note")]


@needs_node
def test_a_field_one_rule_requires_is_required_whatever_another_rules_otherwise_says():
    from services.blueprint import rule_lab
    from services.blueprint.projection import business_rule_rows
    doc = _doc()
    doc["businessRules"].append({"id": "RULE-009", "name": "Travel note", "kind": "condition_action",
                                 "entity": "ENTITY-001", "when": 'category = "travel" and amount > 2000',
                                 "then": [{"type": "set_required", "field": "managerNote", "required": True,
                                           "message": "Travel above 2000 needs a note."}], "otherwise": []})
    rows = [r for r in business_rule_rows(doc) if r.get("model_name") == "Expense"]
    hints = rule_lab.simulate(model="Expense", rules=rows, record={"amount": 2500, "category": "travel"})["formHints"]
    note = [h for h in hints if h["field"] == "managerNote"]
    assert note and all(h.get("required") is True for h in note), note
    assert any(h.get("message") == "Travel above 2000 needs a note." for h in note)


def test_a_rule_made_without_a_sentence_reads_its_condition_in_words():
    from services.business_rules import _when_said
    assert _when_said('category = "meals" and amount > 500') == "category is meals and amount is more than 500"
    assert _when_said('previous.status = "rejected"') == "the old status is rejected"
    assert _when_said("managerNote = null") == "manager note is empty"
    assert _when_said('not(category in ["a"])') == 'not(category in ["a"])'
