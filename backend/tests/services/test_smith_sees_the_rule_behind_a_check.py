"""A check a rule writes into a process is shown with the rule that writes it.

Data Collector 4 (60v142ju, 2026-10-12): every staff process refused every
signed-in person, because the rule "Submission data is admin-only" required an
AdminUser record that no sign-in account had. Smith saw only the processes'
steps, removed the check from four of them twice, and the rule wrote it back
each time.
"""
from services.smith.engine_blueprint_adapter import _checked_first
from services.smith_blueprint_context import _render_workflows


def _doc() -> dict:
    return {
        "data": {"entities": [{"id": "ENTITY-002", "name": "AdminUser", "table": "admin_users"}]},
        "workflows": [{"id": "FLOW-002", "name": "Mark Submission Reviewed"},
                      {"id": "FLOW-001", "name": "Submit Personal Information"}],
        "businessRules": [{"id": "RULE-003", "name": "Submission data is admin-only", "kind": "prerequisite",
                           "gates": ["FLOW-002"], "message": "Please log in with an active administrator account.",
                           "requires": {"account": "id", "entity": "ENTITY-002", "where": {}}}],
    }


def test_a_gated_process_says_which_rule_checks_it_and_where_to_change_it():
    doc = _doc()
    checks = _checked_first(doc, doc["workflows"][0])
    assert len(checks) == 1
    said = checks[0]
    assert "AdminUser" in said and "`id` is their own account id" in said
    assert "Please log in with an active administrator account." in said
    assert "Submission data is admin-only" in said and "never the steps" in said


def test_a_process_no_rule_gates_has_nothing_checked_first():
    doc = _doc()
    assert _checked_first(doc, doc["workflows"][1]) == []


def test_the_check_is_on_the_page_smith_reads():
    from types import SimpleNamespace
    bp = SimpleNamespace(workflows=[{"name": "Mark Submission Reviewed", "purpose": "Review it",
                                     "checked_first": _checked_first(_doc(), _doc()["workflows"][0]),
                                     "steps": ["updates submissions (status=Reviewed)"]}])
    page = _render_workflows(bp)
    assert "checked before its steps:" in page
    assert page.index("checked before its steps") < page.index("updates submissions")


def test_an_app_already_built_gets_the_platforms_trail_and_sealing_on_its_next_turn():
    """Data Collector 4 kept its old audit.ts after the chain fix: the per-turn
    refresh did not list it, so Smith patched the old copy instead."""
    from services.smith.sync_app import RUNTIME_FILES
    for pair in (("audit.ts", "src/lib/audit.ts"), ("sensitive-crypto.ts", "src/lib/sensitive-crypto.ts"),
                 ("push.ts", "src/lib/push.ts"), ("tenancy.ts", "src/lib/tenancy.ts")):
        assert pair in RUNTIME_FILES
