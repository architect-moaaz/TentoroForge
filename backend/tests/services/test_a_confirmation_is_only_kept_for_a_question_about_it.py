"""Task 7, second round: only a question ABOUT the pending operation keeps the
confirmation armed; a request phrased as a question, a negation, or anything in
doubt clears it, and a newer plan wins the yes."""
import os
import sys

import pytest

from services.smith import confirm

REQUESTS_AS_QUESTIONS = ["Can you make the header blue?", "can you add a delete button to the table?", "should I rename Orders to Sales?",
                         "can you rename it instead?", "could you hide it instead", "could you hide it instead?"]
NEGATIONS_AND_OTHERS = ["do not remove it", "do nothing", "Do not delete it, rename it", "how about we hide it instead",
                        "when you are done, add a spice level", "where possible add a filter", "who cares, rename it",
                        "which means no", "have it hidden instead", "may I rename it first", "stop", "wait", "hold on", "cancel",
                        "leave it", "keep it", "not now", "don't", "never mind"]


@pytest.mark.parametrize("msg", REQUESTS_AS_QUESTIONS + NEGATIONS_AND_OTHERS)
def test_anything_but_a_question_about_it_clears_the_confirmation(tmp_path, msg):
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Medicine.preferredTime"))
    confirm.decline_if_not_yes(tmp_path, msg)
    assert not confirm.waiting(tmp_path), msg


@pytest.mark.parametrize("msg", ["do not remove it", "do nothing", "stop", "wait", "hold on", "cancel", "leave it", "keep it", "not now",
                                 "don't", "never mind", "No, leave it"])
def test_a_whole_message_no_says_it_was_left(tmp_path, msg):
    confirm.remember(tmp_path, "remove_field:a.b")
    assert confirm.decline_if_not_yes(tmp_path, msg) == "no", msg


@pytest.mark.parametrize("msg", ["what will it take with it?", "will the data come back?", "is that safe?",
                                 "what happens to preferredTime on the other screens?", "Which screens use the preferred time field?"])
def test_a_question_about_the_pending_operation_keeps_it(tmp_path, msg):
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Medicine.preferredTime"))
    assert confirm.decline_if_not_yes(tmp_path, msg) == "" and confirm.waiting(tmp_path), msg


def test_a_plan_proposed_after_the_confirmation_wins_the_yes(tmp_path, monkeypatch):
    from services.smith import plan as plan_mod
    from services.smith4 import handle as handle_fn
    H = sys.modules["services.smith4.handle"]
    monkeypatch.setattr(H, "_in_step", lambda o, v, r: r, raising=False)
    monkeypatch.setattr(H, "_engine_current", lambda o: [], raising=False)
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Medicine.preferredTime"))
    old = (tmp_path / confirm.PENDING_PATH).stat().st_mtime_ns - 5_000_000_000
    os.utime(tmp_path / confirm.PENDING_PATH, ns=(old, old))               # the confirmation is older than the plan
    plan_mod.remember(tmp_path, ["add a spice level", "show it on the form"], agreed=False)
    ran = []
    handle_fn(project_id="p", output_dir=str(tmp_path), message="Go ahead",
              choose=lambda ask, page, obs, hist: (ran.append(ask), {"tool": "answer", "args": {"text": "ok"}})[1], move=None)
    assert ran and "spice level" in ran[0] and not confirm.waiting(tmp_path)
