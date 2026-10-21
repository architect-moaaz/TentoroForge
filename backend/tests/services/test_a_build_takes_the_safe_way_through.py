"""A build that a check keeps refusing takes the check's safe way through
instead of stopping — after the author has been asked — says what it settled
for, and a refusal with no safe answer still stops it, as Forge's fault.

Four builds died on a refusal whose own message stated the safe answer
(Refund And Chargeback and three before it, 2026-10-20)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.blueprint import agent_contract as ac
from services.blueprint import orchestrator as orch
from services.blueprint.agent_contract import AgentResult, ArtifactProposal

ROLES = [{"id": "ROLE-001", "name": "Front Office Agent"}, {"id": "ROLE-008", "name": "System Admin"}]


def _pages(*routes: str, users: dict | None = None) -> AgentResult:
    users = users or {}
    return AgentResult(task_id="t", agent="page_design", proposals=[
        ArtifactProposal(section="pages", natural_key=r, body={
            "name": r, "route": r, "pattern": "list", "access": "role_restricted",
            **({"users": users[r]} if r in users else {}), "sections": [{"key": "main", "label": "Main"}]})
        for r in routes])


def _doc() -> dict:
    return {"roles": ROLES, "pages": [], "requirements": [{"id": "REQ-001"}],
            "security": {"signupRole": "Front Office Agent"}}


def test_a_restricted_page_nobody_was_named_for_becomes_the_administrators():
    result = _pages("/reports", "/cases", users={"/cases": ["ROLE-001"]})
    with pytest.raises(ac.InconsistentPageAccess) as refused:
        ac.check_page_access(result, _doc())
    said = refused.value.settle()
    assert result.proposals[0].body["users"] == ["ROLE-008"] and result.proposals[1].body["users"] == ["ROLE-001"]
    assert said and "/reports opens for the administrator (System Admin) only" in said[0]
    ac.check_page_access(result, _doc())  # settled: passes


def test_a_guess_is_not_a_safe_way_through():
    """Pages of one module that disagree on who may open them are not settled."""
    doc = _doc()
    doc["pages"] = [{"id": "PAGE-001", "route": "/a", "module": "M1", "access": "authenticated", "users": ["ROLE-001"]}]
    result = _pages("/b", users={"/b": ["ROLE-001"]})
    result.proposals[0].body["module"] = "M1"
    with pytest.raises(ac.InconsistentPageAccess) as refused:
        ac.check_page_access(result, doc)
    assert refused.value.settle is None


def test_an_audit_trail_nobody_may_read_is_the_administrators():
    result = AgentResult(task_id="t", agent="security", proposals=[ArtifactProposal(
        section="security", natural_key="security",
        body={"audit": {"level": "writes", "reviewers": [], "reasonRequired": ["refunds"]}})])
    with pytest.raises(ac.InvalidAudit) as refused:
        ac.check_audit(result, _doc())
    said = refused.value.settle()
    audit = result.proposals[0].body["audit"]
    assert audit["reviewers"] == ["ROLE-008"] and audit["reasonRequired"] == []
    assert any("administrator" in s for s in said)


def test_charts_short_of_the_standard_ship_as_written():
    doc = {**_doc(), "pages": [{"id": "PAGE-001", "route": "/", "pattern": "dashboard"}], "data": {"entities": []}}
    result = AgentResult(task_id="t", agent="analytics", proposals=[ArtifactProposal(
        section="widgets", natural_key="w1",
        body={"id": "W1", "page": "PAGE-001", "kind": "chart", "label": "Cases", "requirements": ["REQ-404"]})])
    with pytest.raises(ac.InvalidAnalytics) as refused:
        ac.check_analytics(result, doc)
    said = refused.value.settle()
    assert result.proposals[0].body["requirements"] == [] and said
    ac.check_analytics(result, doc)  # settled: passes


def test_a_record_field_that_cannot_work_is_taken_off_not_the_whole_data_model():
    result = AgentResult(task_id="t", agent="data_architect", proposals=[
        ArtifactProposal(section="data.entities", natural_key="Case", body={
            "name": "Case", "labelField": "title", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "reference", "type": "string"},
                {"name": "photo", "type": "image"},
                {"name": "look", "type": "vector", "embedding": {"of": ""}}]}),
        ArtifactProposal(section="data.entities", natural_key="Receipt", body={
            "name": "Receipt", "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True},
                {"name": "scan", "type": "image"},
                {"name": "look", "type": "vector", "embedding": {"of": "picture"}}]})])
    with pytest.raises(ac.InvalidEntityFields) as refused:
        ac.check_entity_fields(result, {"data": {"entities": []}})
    said = refused.value.settle()
    case, receipt = (p.body for p in result.proposals)
    assert case["labelField"] == "reference"
    # Two fields it could be taken of: not guessed, the vector field is left out and the choice said.
    assert "look" not in [f["name"] for f in case["fields"]]
    assert any("could be one of reference, photo" in s for s in said)
    # One field it could only be: taken of that.
    assert next(f for f in receipt["fields"] if f["name"] == "look")["embedding"]["of"] == "scan"
    ac.check_entity_fields(result, {"data": {"entities": []}})  # settled: passes


def test_journeys_that_name_nothing_are_left_out():
    result = AgentResult(task_id="t", agent="ux", proposals=[
        ArtifactProposal(section="flows", natural_key="f1", body={"name": "Refund", "steps": [{"page": "PAGE-404"}]})])
    try:
        ac.check_flows(result, {**_doc(), "pages": [{"id": "PAGE-001", "route": "/"}]})
    except ac.InvalidAppFlow as refused:
        said = refused.settle()
        assert [p.section for p in result.proposals] == [] and "left out" in said[0]


def _subject(monkeypatch, tmp_path, refusal: Exception, *, attempt: int, escalated: bool = True):
    svc = SimpleNamespace(output_dir=str(tmp_path), doc={})
    applied = SimpleNamespace(applied=True, artifacts=["PAGE-001"], change_requests=[],
                              needs_clarification=False)
    calls = {"n": 0}

    def apply(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise refusal
        return applied
    monkeypatch.setattr(orch, "apply_agent_result", apply)
    monkeypatch.setattr(orch, "record_refusal", lambda *a, **k: None, raising=False)
    import services.blueprint.refusals as refusals
    monkeypatch.setattr(refusals, "record_refusal", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_act_on", lambda *a, **k: [])
    monkeypatch.setattr(orch, "_proposed_identities", lambda *a, **k: set())
    monkeypatch.setattr(orch, "_landed", lambda *a, **k: None)
    recorded = []
    import services.incidents as incidents
    monkeypatch.setattr(incidents, "record", lambda *a, **k: recorded.append((a, k)) or {})
    state = orch._NodeRun(subjects=[""], pending=[""])
    if escalated:
        state.escalated.add("")
    report = orch.RunReport()
    outcome = AgentResult(task_id="t", agent="page_design")
    got = orch._apply_subject(svc, "page_contracts", state, "", outcome, attempt=attempt, max_attempts=2,
                              commit=True, user_request="", report=report)
    _subject.state = state
    return got, report, recorded


def test_the_author_is_asked_before_anything_is_settled(monkeypatch, tmp_path):
    refusal = ac.InconsistentPageAccess("/reports: names no role", settle=lambda: ["settled"])
    got, report, recorded = _subject(monkeypatch, tmp_path, refusal, attempt=1)
    assert got == "retry" and not report.settled and not recorded


def test_the_last_attempt_takes_the_safe_way_through_and_says_so(monkeypatch, tmp_path):
    refusal = ac.InconsistentPageAccess("/reports: names no role",
                                        settle=lambda: ["/reports opens for the administrator only"])
    got, report, recorded = _subject(monkeypatch, tmp_path, refusal, attempt=2)
    assert got == "applied" and not report.failed
    assert report.settled == {"page_contracts": ["/reports opens for the administrator only"]}
    assert orch.settled_for(tmp_path) == ["/reports opens for the administrator only"]
    assert json.loads((tmp_path / ".forge" / "settled.json").read_text())["page_contracts"]["settled"]
    assert not recorded


def test_a_refusal_with_no_safe_answer_stops_the_build_as_forges_fault(monkeypatch, tmp_path):
    refusal = ac.InvalidOwnershipRule("Case: the owner column is not a field")
    got, report, recorded = _subject(monkeypatch, tmp_path, refusal, attempt=2)
    assert got == "failed" and report.stuck and "page_contracts" in report.stuck
    (kind,), extra = recorded[0]
    assert kind == "build_stuck" and extra["node"] == "page_contracts"
    assert extra["signature"].startswith("build_stuck|page_contracts|")


def test_the_same_fault_in_a_second_app_is_marked_recurring(monkeypatch, tmp_path):
    import services.incidents as incidents
    monkeypatch.setattr(incidents, "_path", lambda: tmp_path / "incidents.jsonl")
    sig = incidents.signature("build_stuck", "page_contracts",
                              "InconsistentPageAccess: /cases: `access` names no role")
    assert sig == incidents.signature("build_stuck", "page_contracts",
                                      "InconsistentPageAccess: /orders/[id]: something else entirely")
    first = incidents.record("build_stuck", app="aaaa1111", detail="x", signature=sig)
    again = incidents.record("build_stuck", app="aaaa1111", detail="x", signature=sig)
    other = incidents.record("build_stuck", app="bbbb2222", detail="x", signature=sig)
    assert "recurring" not in first and "recurring" not in again
    assert other["recurring"] is True and other["apps"] == ["aaaa1111", "bbbb2222"]
    # Without an error name, the app's own words are taken out of the reason.
    assert incidents.signature("x", "n", "the page /cases/[id] for ROLE-004 has 3 tabs") == \
        incidents.signature("x", "n", "the page /orders for ROLE-001 has 7 tabs")


def test_a_refusal_is_put_to_the_strongest_model_before_anything_is_settled(monkeypatch, tmp_path):
    refusal = ac.InconsistentPageAccess("/reports: names no role", settle=lambda: ["settled"])
    got, report, recorded = _subject(monkeypatch, tmp_path, refusal, attempt=2, escalated=False)
    state = _subject.state
    assert got == "retry" and "" in state.escalated and not report.settled and not recorded
    assert "/reports: names no role" in state.feedback[""]


def test_the_last_try_runs_on_the_strongest_model_at_high_effort():
    from dataclasses import dataclass
    from services.blueprint import executors as ex

    @dataclass
    class Client:
        model: str = "claude-sonnet-5"
        effort: str = "medium"
    spec = SimpleNamespace(escalate=True)
    assert ex.escalated(Client(), spec) == Client(model=ex.ESCALATION_MODEL, effort="high")
    assert ex.escalated(Client(), SimpleNamespace(escalate=False)) == Client()


def test_a_scorecard_with_skipped_items_is_a_valid_document(tmp_path):
    """The card's `skipped` was written and never declared, so a card holding
    one refused every save of the document during the checks (pah7lhfz,
    2026-10-21)."""
    from services.blueprint import scorecard
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="T", domain="d")
    svc.doc.setdefault("runtime", {})["scorecard"] = {
        "status": "checking",
        "criteria": {"logic": scorecard._criterion(total=1, skipped=[scorecard.item("RULE-001", "A rule", "gates no process")])}}
    svc.validate()
