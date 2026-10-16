"""A prerequisite can ask for a role, and a record id that no account has is refused.

Data Collector 4 (60v142ju, 2026-10-12): "Submission data is admin-only" could
only be written as a record to look up, so it required an AdminUser whose id
was the signed-in account's id. No account ever had one, every staff process
refused every member of staff, and Smith could not rewrite the rule as a role
check because the contract had no way to say it.
"""
from services.blueprint.account_model import guard_workflow
from services.blueprint.agent_contract import prerequisite_findings
from services.smith.engine_blueprint_adapter import _checked_first


def _doc(requires: dict, *, admin_signs_in: bool = False) -> dict:
    return {
        "roles": [{"id": "ROLE-001", "name": "Officer"}, {"id": "ROLE-002", "name": "Supervisor"}],
        "data": {"entities": [
            {"id": "ENTITY-001", "name": "Submission", "table": "submissions", "fields": [{"name": "id", "primaryKey": True}]},
            {"id": "ENTITY-002", "name": "AdminUser", "table": "admin_users", "account": admin_signs_in,
             "fields": [{"name": "id", "primaryKey": True}, {"name": "userId"}, {"name": "status"}]},
        ]},
        "workflows": [{"id": "FLOW-002", "name": "Mark Submission Reviewed"}],
        "businessRules": [{"id": "RULE-003", "name": "Submission data is admin-only", "kind": "prerequisite",
                           "gates": ["FLOW-002"], "message": "Staff only.", "requires": requires}],
    }


def _rule(doc: dict) -> dict:
    return doc["businessRules"][0]


def test_a_record_whose_own_id_stands_for_the_account_is_refused_when_nobody_signs_in_as_it():
    doc = _doc({"entity": "ENTITY-002", "account": "id", "where": {}})
    found = prerequisite_findings(_rule(doc), doc)
    assert any("people do not sign in as AdminUser records" in f and "requires.roles" in f for f in found)


def test_the_same_shape_is_right_when_the_record_is_what_people_sign_in_as():
    doc = _doc({"entity": "ENTITY-002", "account": "id", "where": {}}, admin_signs_in=True)
    assert prerequisite_findings(_rule(doc), doc) == []


def test_a_field_holding_the_account_id_is_right():
    doc = _doc({"entity": "ENTITY-002", "account": "userId", "where": {"status": "active"}})
    assert prerequisite_findings(_rule(doc), doc) == []


def test_a_gate_on_roles_alone_is_right_and_an_unknown_role_is_not():
    doc = _doc({"roles": ["ROLE-001", "ROLE-002"]})
    assert prerequisite_findings(_rule(doc), doc) == []
    bad = _doc({"roles": ["ROLE-009"]})
    assert any("ROLE-009, which is not a role" in f for f in prerequisite_findings(_rule(bad), bad))


def test_a_gate_that_asks_for_nothing_is_refused():
    doc = _doc({})
    assert any("`roles` the signed-in person must hold" in f for f in prerequisite_findings(_rule(doc), doc))


def _write(doc: dict) -> tuple[list[dict], list[dict]]:
    nodes = [{"id": "trigger", "type": "trigger"}, {"id": "set_reviewed", "type": "action"}]
    edges = [{"id": "e1", "source": "trigger", "target": "set_reviewed"}]

    def make_node(nid, kind, config, label):
        return {"id": nid, "type": kind, "data": {"label": label, "config": config}}

    guard_workflow(doc, doc["workflows"][0], nodes, edges, make_node)
    return nodes, edges


def test_a_role_gate_is_one_condition_on_the_session_and_no_lookup():
    nodes, edges = _write(_doc({"roles": ["ROLE-001", "ROLE-002"]}))
    by_id = {n["id"]: n for n in nodes}
    assert by_id["prereq_rule_003"]["type"] == "condition"
    assert by_id["prereq_rule_003"]["data"]["config"]["expression"] == 'user.role in ["Officer", "Supervisor"]'
    assert not any(n["type"] == "action" and n["id"].startswith("prereq_") for n in nodes)
    assert {"source": "prereq_rule_003", "target": "prereq_rule_003_refused"}.items() <= next(
        e for e in edges if e["source"] == "prereq_rule_003" and e["target"] == "prereq_rule_003_refused").items()
    assert any(e["source"] == "prereq_rule_003" and e["target"] == "set_reviewed" for e in edges)


def test_a_role_and_a_record_are_both_checked():
    nodes, _ = _write(_doc({"roles": ["ROLE-001"], "entity": "ENTITY-002", "account": "userId", "where": {}}))
    ids = [n["id"] for n in nodes]
    assert "prereq_rule_003_role" in ids and "prereq_rule_003" in ids and "prereq_rule_003_met" in ids


def test_a_role_gate_is_not_written_twice():
    doc = _doc({"roles": ["ROLE-001"]})
    nodes, edges = _write(doc)
    count = len(nodes)
    guard_workflow(doc, doc["workflows"][0], nodes, edges,
                   lambda nid, kind, config, label: {"id": nid, "type": kind, "data": {"config": config}})
    assert len(nodes) == count


def test_smith_reads_the_role_the_gate_asks_for():
    doc = _doc({"roles": ["ROLE-001", "ROLE-002"]})
    said = _checked_first(doc, doc["workflows"][0])
    assert said and "must hold one of the roles Officer, Supervisor" in said[0] and "never the steps" in said[0]


def test_the_engine_reads_a_role_check():
    from runtime.feel_lite.evaluator import evaluate_expression
    assert evaluate_expression('user.role in ["Officer", "Supervisor"]', {"user": {"role": "Supervisor"}}) is True
    assert evaluate_expression('user.role in ["Officer", "Supervisor"]', {"user": {"role": "Public"}}) is False
