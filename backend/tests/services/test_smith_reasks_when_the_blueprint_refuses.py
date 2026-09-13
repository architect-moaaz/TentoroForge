"""A plan the Blueprint refuses is re-asked once with the verdict, not reported.

A request for the case workflows drafted a condition `exists(approvals where
…)`; the engine cannot parse it, `apply_change` refused the plan, and Smith
answered "the Blueprint refused it" with the FEEL grammar printed only to a
log. `compose_route` and `make_executor` both re-ask with the refusal; the
conversation reached neither. Now it does, once, and the re-ask carries the
verdict and the workflow catalogue.
"""
import json

import pytest

from services.smith import smith as smith_module
from services.smith.smith import Smith
from services.smith.turn import interpret, TurnRejected
from services.blueprint.agent_contract import InvalidWorkflowStep
from tests.services.test_smith import FakeModel, plan_json


def test_interpret_seeded_with_a_verdict_asks_with_it_first():
    class _Model:
        enforces_schema = True
        prompts = []

        def __call__(self, *, system, user, schema=None):
            self.prompts.append(user)
            return plan_json()
    m = _Model()
    interpret(m, _ctx(), {"requirements": [], "pages": []},
              rejected="Approve Refund Stage, step 'gate': the engine cannot parse 'exists(x where y)'")
    assert len(m.prompts) == 1
    assert "Your previous reply was rejected" in m.prompts[0]
    assert "cannot parse" in m.prompts[0]
    assert "no subqueries" in m.prompts[0].lower() or "subqueries" in m.prompts[0]


def _ctx():
    from services.smith.turn import Context
    try:
        return Context(request="add the approve workflow")
    except TypeError:
        return Context.__new__(Context)


def test_a_refused_plan_is_re_asked_once_and_then_applied(ats, tmp_path, monkeypatch):
    model = FakeModel(plan_json(), plan_json())
    s = Smith.adopt(ats, tmp_path, model=model)
    calls = []

    def apply(*a, **kw):
        calls.append(kw.get("interpretation"))
        if len(calls) == 1:
            raise InvalidWorkflowStep("Approve Refund Stage, step 'gate': the engine cannot parse 'exists(approvals where x)'")
        return smith_module.ChangeResult.__new__(smith_module.ChangeResult)
    monkeypatch.setattr(smith_module, "apply_change", apply)
    plan_with_change = json.loads(plan_json())
    plan_with_change["intent"] = "change"
    plan_with_change["anchors"] = ["REQ-001"]
    model.replies = [json.dumps(plan_with_change), json.dumps(plan_with_change)]
    turn = s.turn("add an approve workflow")
    assert len(calls) == 2, "applied again after the re-ask"
    assert len(model.calls) == 2
    assert "cannot parse" in model.calls[1][1]
    assert not turn.rejected


def test_a_plan_refused_twice_is_reported_as_before(ats, tmp_path, monkeypatch):
    model = FakeModel(plan_json(), plan_json())
    s = Smith.adopt(ats, tmp_path, model=model)

    def apply(*a, **kw):
        raise InvalidWorkflowStep("step 'gate': the engine cannot parse 'exists(...)'")
    monkeypatch.setattr(smith_module, "apply_change", apply)
    plan_with_change = json.loads(plan_json())
    plan_with_change["intent"] = "change"
    plan_with_change["anchors"] = ["REQ-001"]
    model.replies = [json.dumps(plan_with_change), json.dumps(plan_with_change)]
    turn = s.turn("add an approve workflow")
    assert turn.rejected and "cannot parse" in turn.rejected
    assert "refused it" in turn.reply
    assert len(model.calls) == 2
