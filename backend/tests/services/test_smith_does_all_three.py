"""Three asks in one message become a plan, not one change and two silences.

"Add a phone number, show it on the form, and make it required" is three
changes. `understand_ask` returns one verb, so the other two were dropped: the
biggest one happened and the person found out later that the rest had not.
"""

from __future__ import annotations

import pytest

from services.blueprint.service import BlueprintService
from services.smith import plan
from services.smith_session import SmithSession, TurnResult

STEPS = ["add a phone number to nurses",
         "show the phone number on the registration form",
         "make the phone number required"]


@pytest.fixture()
def project(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Roster", domain="health")
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
                                   "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]}]}
    s.save()
    return s


def _session(project, done: list[str], further=()) -> SmithSession:
    def _understand(message, ctx, **kw):
        return {"verb": "add_field", "entity": "Nurse", "field": {"name": "phone"},
                "further_asks": list(further) if message.strip() == STEPS[0] else []}

    session = SmithSession(
        project_id="p1", output_dir=str(project.output_dir), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=_understand, iteration_move_fn=lambda *a, **kw: None)
    session._add_field = lambda understanding: (                      # noqa: ARG005
        done.append("did it") or TurnResult(status="resolved", answer="Done."))
    return session


def test_the_plan_is_shown_and_nothing_is_done_before_the_yes(project):
    done: list[str] = []
    result = _session(project, done, STEPS[1:]).run_iteration(user_message=STEPS[0])
    assert result.status == "asked" and done == []
    assert "That is more than one change" in result.answer
    for i, step in enumerate(STEPS, start=1):
        assert f"{i}. {step}" in result.answer
    assert result.options == [plan.ALL_LABEL, plan.FIRST_LABEL, plan.REWORD_LABEL]
    assert plan.peek(project.output_dir) == STEPS


def test_agreeing_does_the_first_one_now_and_says_what_is_left(project):
    done: list[str] = []
    _session(project, done, STEPS[1:]).run_iteration(user_message=STEPS[0])
    result = _session(project, done).run_iteration(user_message=plan.ALL_LABEL)
    assert result.status == "resolved" and done == ["did it"]
    assert "Still to do:" in result.answer
    assert STEPS[1] in result.answer and STEPS[2] in result.answer
    assert plan.peek(project.output_dir) == STEPS[1:]


def test_next_works_through_the_rest_one_at_a_time(project):
    done: list[str] = []
    _session(project, done, STEPS[1:]).run_iteration(user_message=STEPS[0])
    _session(project, done).run_iteration(user_message=plan.ALL_LABEL)
    second = _session(project, done).run_iteration(user_message="next")
    assert len(done) == 2 and plan.peek(project.output_dir) == [STEPS[2]]
    assert f"Still to do: **{STEPS[2]}**" in second.answer
    third = _session(project, done).run_iteration(user_message="next")
    assert len(done) == 3 and plan.peek(project.output_dir) == []
    assert "Still to do" not in third.answer


def test_just_the_first_one_drops_the_rest(project):
    done: list[str] = []
    _session(project, done, STEPS[1:]).run_iteration(user_message=STEPS[0])
    result = _session(project, done).run_iteration(user_message=plan.FIRST_LABEL)
    assert done == ["did it"] and plan.peek(project.output_dir) == []
    assert "Still to do" not in result.answer


def test_saying_it_differently_forgets_the_plan(project):
    done: list[str] = []
    _session(project, done, STEPS[1:]).run_iteration(user_message=STEPS[0])
    result = _session(project, done).run_iteration(user_message=plan.REWORD_LABEL)
    assert result.status == "asked" and "tell me the one thing you want first" in result.answer
    assert plan.peek(project.output_dir) == [] and done == []


def test_one_ask_is_not_turned_into_a_plan(project):
    done: list[str] = []
    result = _session(project, done).run_iteration(user_message=STEPS[0])
    assert result.status == "resolved" and done == ["did it"]
    assert plan.peek(project.output_dir) == []


def test_a_plan_longer_than_the_screen_is_cut(project):
    plan.remember(project.output_dir, [f"step {i}" for i in range(20)])
    assert len(plan.peek(project.output_dir)) == plan.MAX_STEPS
    plan.remember(project.output_dir, ["  ", ""])
    assert plan.peek(project.output_dir) == []


def test_carrying_on_is_a_whole_message():
    assert plan.wants_next("next") and plan.wants_next("go on") and plan.wants_next("Continue.")
    for said in ("next week it should email them", "go on the dashboard", "", "nope"):
        assert not plan.wants_next(said), said
