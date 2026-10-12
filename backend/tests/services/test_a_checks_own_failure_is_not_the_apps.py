"""A check that failed is not a page that failed, and one cause is one repair (2026-10-09).

ToroCommerce's build sent six customer pages to Smith because the checker's
own screenshot step crashed, three more for React's development-only
attribute notice, and six processes one by one for a single seeding fault.
"""
from __future__ import annotations

from pathlib import Path

from services.blueprint import app_check
from services.blueprint.page_review import ReviewUnavailable, _what_failed
from services.blueprint.repair_groups import by_cause, cause_key, steps_for

DOC = {"roles": [{"id": "ROLE-001", "name": "Customer"}, {"id": "ROLE-002", "name": "Admin"}],
       "pages": [{"id": "PAGE-001", "name": "Shop", "route": "/shop", "users": ["ROLE-001"]}],
       "data": {"entities": []}}


def test_a_crash_of_the_checker_leaves_the_page_unchecked_not_failing(monkeypatch):
    calls = []

    def crash(*a, **k):
        calls.append(1)
        raise ReviewUnavailable("screenshots failed: TypeError: page.evaluate: Target closed")
    monkeypatch.setattr("services.blueprint.page_review.run_shots", crash)
    monkeypatch.setattr(app_check, "_entries", lambda app, doc, batch: [])
    monkeypatch.setattr(app_check, "arrival_findings", lambda *a: [])
    report = app_check.check_pages(object(), DOC, [{"page": "PAGE-001", "route": "/shop", "name": "Shop",
                                                     "entity": None, "as": "Customer"}], Path("/tmp/x"))
    page = report["PAGE-001"]
    assert page["findings"] == [], "nothing is sent to be repaired"
    assert page["unchecked"] and "Target closed" in page["unchecked"][0][1]
    assert len(calls) == 2, "tried once more before it is called unchecked"


def test_a_crashed_scripts_error_is_kept_from_its_first_line():
    stderr = ("file:///x/page_shots.mjs:154\n  await unclip(page);\n\nTypeError: page.evaluate: Target page, context "
              "or browser has been closed\n    at unclip (/x/page_shots.mjs:120:9)\n    at open (/x/page_shots.mjs:154:11)\n")
    said = _what_failed(stderr)
    assert said.startswith("TypeError: page.evaluate: Target page") and "unclip" in said


def test_failures_with_one_cause_are_one_repair():
    a = 'Refused twice — first {"cartItem": "552a435e-6a14-455c-965b-3829796c66a5"} as Customer: Your account has been disabled.'
    b = 'Refused twice — first {"customer": "b5091a1c-28ac-473b-9286-98c8fc4aaaaa", "phone": "+1-415"} as Customer: Your account has been disabled.'
    c = "Place Order (FLOW-004) failed: column \"total\" does not exist"
    assert cause_key(a) == cause_key(b) != cause_key(c)
    groups = by_cause([("FLOW-002", a), ("FLOW-005", b), ("FLOW-004", c)], lambda x: x[1])
    assert [[x[0] for x in g] for g in groups] == [["FLOW-002", "FLOW-005"], ["FLOW-004"]]
    assert steps_for(12, 1) == 12 and steps_for(12, 6) == 26, "more room for more failures, within a cap"


def test_a_page_that_names_no_process_it_could_start_keeps_its_details():
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal
    from services.blueprint.executors import drop_unknown_dispatches
    result = AgentResult(task_id="t", agent="page_design", proposals=[
        ArtifactProposal("pages", "/checkout", {"id": "PAGE-004", "route": "/checkout", "dispatches": "JOURNEY-006"}),
        ArtifactProposal("pages", "/cart", {"id": "PAGE-003", "route": "/cart", "dispatches": "FLOW-001"})])
    dropped = drop_unknown_dispatches(result, {"workflows": [{"id": "FLOW-001"}]})
    assert dropped == ["/checkout: JOURNEY-006"]
    assert "dispatches" not in result.proposals[0].body, "a guess at a process is left out, not fatal to the feature"
    assert result.proposals[1].body["dispatches"] == "FLOW-001"


def test_one_invented_page_state_costs_that_state_not_the_feature():
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal
    from services.blueprint.executors import drop_values_no_list_allows
    result = AgentResult(task_id="t", agent="page_design", proposals=[
        ArtifactProposal("pages", "/checkout", {"id": "PAGE-004", "route": "/checkout",
                                                "states": ["loading", "noSelection", "populated"]})])
    assert drop_values_no_list_allows(result) == ["/checkout: states ['noSelection']"]
    assert result.proposals[0].body["states"] == ["loading", "populated"]
