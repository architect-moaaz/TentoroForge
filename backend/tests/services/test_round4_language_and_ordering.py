"""Round 4: the spoken-language question is never dropped as a technology question, and the
ordering counter is safe under threads, a lost counter and a future-dated file."""
import json
import os
import threading

import pytest

from services.smith import clarify_brief as cb, confirm, plan as plan_mod
from services.smith.ordering import asked_after, next_seq

BRIEF = "Build an app for a clinic where nurses record medicine doses for each patient."


def _p(*qs):
    return lambda prompt: json.dumps({"questions": [{"question": q, "options": ["English", "Arabic"]} for q in qs]})


# the real first-question wordings from the UAT conversations, plus others
KEEP = ["Which language should the interface be in?", "Which language should the MediTrack interface be in?",
        "Which language should the app's interface be in?", "Which language should the app be in?",
        "Which language should the calculator interface be in?", "What language should the app use?",
        "Should the app support Arabic?", "Do you need multiple languages?", "Which language should the screens be shown in?",
        "Which framework of rules applies to vaccine stock?", "Which design language should this application use?",
        "Which market is the MVP launching in, and what language should the interface use?"]
DROP = ["Which programming language?", "Which language should it be written in?", "Which language and framework do you prefer?",
        "What language should the backend be coded in?", "Which framework should it be built with?",
        "Which framework should MediTrack be built in?"]


@pytest.mark.parametrize("q", KEEP)
def test_product_and_spoken_language_questions_are_kept(q):
    assert [x["question"] for x in cb.clarify_brief(BRIEF, provider=_p(q))] == [q]


@pytest.mark.parametrize("q", DROP)
def test_code_and_technology_questions_are_dropped(q):
    assert cb.clarify_brief(BRIEF, provider=_p(q)) == []


def test_the_clarifier_still_asks_the_language_when_the_brief_does_not_say(tmp_path):
    out = cb.clarify_brief(BRIEF, provider=_p("Which language should the interface be in?", "Which framework should it be built with?"))
    assert [x["question"] for x in out] == ["Which language should the interface be in?"]


# --- ordering ----------------------------------------------------------------------------------------

def test_the_sequence_is_unique_and_increasing_under_threads(tmp_path):
    got, lock = [], threading.Lock()

    def work():
        mine = [next_seq(tmp_path) for _ in range(50)]
        with lock:
            got.extend(mine)
    ts = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(got) == 200 and len(set(got)) == 200
    assert not (tmp_path / ".forge/seq.lock").exists()                     # the lock is released


def test_a_lost_counter_cannot_let_a_future_dated_confirmation_outrank_a_new_plan(tmp_path):
    (tmp_path / ".forge").mkdir()
    (tmp_path / confirm.PENDING_PATH).write_text(json.dumps({"fingerprint": "remove_field:a.b", "seq": 9_999_999_999_999_999_999}))
    assert not (tmp_path / ".forge/seq.json").exists()                     # the counter is gone
    plan_mod.remember(tmp_path, ["step a", "step b"], agreed=False)
    assert asked_after(tmp_path, plan_mod.PENDING_PATH, confirm.PENDING_PATH)
    assert next_seq(tmp_path) > 9_999_999_999_999_999_999


def test_a_stale_lock_file_is_taken_over(tmp_path):
    (tmp_path / ".forge").mkdir()
    lock = tmp_path / ".forge/seq.lock"
    lock.write_text("x")
    old = lock.stat().st_mtime - 60
    os.utime(lock, (old, old))
    assert next_seq(tmp_path) > 0


# --- task 7 residual: a typo-bearing request is still a request ----------------------------------------

@pytest.mark.parametrize("msg", ["cna you hide it insted?", "cn u rename it instaed?", "could u change it to optional?"])
def test_a_typo_bearing_request_clears_the_confirmation(tmp_path, msg):
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Medicine.preferredTime"))
    confirm.decline_if_not_yes(tmp_path, msg)
    assert not confirm.waiting(tmp_path), msg
