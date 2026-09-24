"""More than one ask in a message becomes a plan, whatever the number.

`understand_ask` returns ONE verb, so everything else in the message was
dropped: the biggest ask happened and the person found out later that the rest
had not. Two asks or six, the shape is the same — the number three is only
what the example happens to have.
"""

from __future__ import annotations

import pytest

from services.blueprint.service import BlueprintService
from services.smith import plan
from tests.services._front_door import SmithSession, TurnResult

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


def _session(project, done: list[str], asks=()) -> SmithSession:
    def _understand(message, ctx, **kw):
        # EVERY ask, first one included — the plan's first step was the raw
        # message, so a four-step plan opened with the whole sentence.
        return {"verb": "add_field", "entity": "Nurse", "field": {"name": "phone"},
                "asks": list(asks) if message.strip() == STEPS[0] else []}

    from services.smith4 import verbs as v4
    from services.smith4.outcome import Outcome
    v4.PERFORM["add_field"] = lambda ctx, u: (                            # noqa: ARG005
        done.append("did it") or Outcome(status="resolved", said="Done."))
    return SmithSession(
        project_id="p1", output_dir=str(project.output_dir), guards_fn=lambda *a, **kw: [],
        understand_ask_fn=_understand, iteration_move_fn=lambda *a, **kw: None)


@pytest.fixture(autouse=True)
def _restore_add_field():
    from services.smith4 import verbs as v4
    original = v4.PERFORM["add_field"]
    yield
    v4.PERFORM["add_field"] = original


def test_the_plan_is_shown_and_nothing_is_done_before_the_yes(project):
    done: list[str] = []
    result = _session(project, done, STEPS).run_iteration(user_message=STEPS[0])
    # The first step is the first ASK, not the whole message.
    assert "1. " + STEPS[0] in result.answer
    assert result.status == "asked" and done == []
    assert "That is more than one change" in result.answer
    for i, step in enumerate(STEPS, start=1):
        assert f"{i}. {step}" in result.answer
    assert result.options == [plan.ALL_LABEL, plan.FIRST_LABEL, plan.REWORD_LABEL]
    assert plan.peek(project.output_dir) == STEPS


def test_agreeing_does_the_first_one_now_and_says_what_is_left(project):
    done: list[str] = []
    _session(project, done, STEPS).run_iteration(user_message=STEPS[0])
    result = _session(project, done).run_iteration(user_message=plan.ALL_LABEL)
    assert result.status == "resolved" and done == ["did it"]
    assert "Still to do:" in result.answer
    assert STEPS[1] in result.answer and STEPS[2] in result.answer
    assert plan.peek(project.output_dir) == STEPS[1:]


def test_next_works_through_the_rest_one_at_a_time(project):
    done: list[str] = []
    _session(project, done, STEPS).run_iteration(user_message=STEPS[0])
    _session(project, done).run_iteration(user_message=plan.ALL_LABEL)
    second = _session(project, done).run_iteration(user_message="next")
    assert len(done) == 2 and plan.peek(project.output_dir) == [STEPS[2]]
    assert f"Still to do: **{STEPS[2]}**" in second.answer
    third = _session(project, done).run_iteration(user_message="next")
    assert len(done) == 3 and plan.peek(project.output_dir) == []
    assert "Still to do" not in third.answer


def test_just_the_first_one_drops_the_rest(project):
    done: list[str] = []
    _session(project, done, STEPS).run_iteration(user_message=STEPS[0])
    result = _session(project, done).run_iteration(user_message=plan.FIRST_LABEL)
    assert done == ["did it"] and plan.peek(project.output_dir) == []
    assert "Still to do" not in result.answer


def test_saying_it_differently_forgets_the_plan(project):
    done: list[str] = []
    _session(project, done, STEPS).run_iteration(user_message=STEPS[0])
    result = _session(project, done).run_iteration(user_message=plan.REWORD_LABEL)
    assert result.status == "asked" and "tell me the one thing you want first" in result.answer
    assert plan.peek(project.output_dir) == [] and done == []


def test_one_ask_is_not_turned_into_a_plan(project):
    done: list[str] = []
    result = _session(project, done).run_iteration(user_message=STEPS[0])
    assert result.status == "resolved" and done == ["did it"]
    assert plan.peek(project.output_dir) == []


def test_two_asks_are_a_plan_as_much_as_three(project):
    """Nothing about this is about the number three."""
    done: list[str] = []
    result = _session(project, done, [STEPS[0], "make the phone number required"]).run_iteration(
        user_message=STEPS[0])
    assert result.status == "asked" and done == []
    assert "1. " + STEPS[0] in result.answer
    assert "2. make the phone number required" in result.answer
    assert plan.peek(project.output_dir) == [STEPS[0], "make the phone number required"]


def test_what_does_not_fit_in_one_yes_is_said_rather_than_dropped(project):
    """Silently keeping six of nine is the same silence this exists to end,
    at a different number."""
    many = [f"ask number {i}" for i in range(1, 10)]
    planned, over = plan.split(many)
    assert len(planned) == plan.MAX_STEPS and len(over) == 3
    said = plan.as_question(planned, over)
    assert f"{plan.MAX_STEPS}. ask number {plan.MAX_STEPS}" in said
    assert "You asked for 3 more than I can plan in one go" in said
    for late in over:
        assert late in said
    # And the ones that fit are what is kept to work through.
    plan.remember(project.output_dir, planned)
    assert plan.peek(project.output_dir) == planned
    plan.remember(project.output_dir, ["  ", ""])
    assert plan.peek(project.output_dir) == []


def test_carrying_on_is_a_whole_message():
    assert plan.wants_next("next") and plan.wants_next("go on") and plan.wants_next("Continue.")
    for said in ("next week it should email them", "go on the dashboard", "", "nope"):
        assert not plan.wants_next(said), said
