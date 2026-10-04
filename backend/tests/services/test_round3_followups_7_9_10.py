"""Third tester round on tasks 7, 9, 10: legitimate questions about the pending removal
keep it, requests phrased as questions clear it, the order of two pending questions
does not depend on file times, an explicit native demand beats the word 'web', and
a dev server is not a built app."""
import json
import os
import sys

import pytest

from services.smith import clarify_brief as cb, confirm

TARGET = confirm.fingerprint("remove_field", "Medicine.preferredTime")

KEEP = ["what happens to the existing records?", "what happens to existing doses?", "what about the history?", "would I lose the history?",
        "how many records have a value?", "are you sure", "show me what it removes", "what happens to preferred time if I change it?",
        "does it filter anything?", "is it set on the dashboard?", "what will it take with it?", "will the data come back?"]
CLEAR = ["Can you make the header blue?", "can you add a delete button to the table?", "should I rename Orders to Sales?",
         "can you rename it instead?", "could you hide it instead", "why not just hide it?", "do not remove it", "how about we hide it instead",
         "when you are done, add a spice level", "who cares, rename it", "have it hidden instead", "may I rename it first"]


@pytest.mark.parametrize("msg", KEEP)
def test_a_real_question_about_the_removal_keeps_it(tmp_path, msg):
    confirm.remember(tmp_path, TARGET)
    assert confirm.decline_if_not_yes(tmp_path, msg) == "" and confirm.waiting(tmp_path), msg
    assert confirm.granted(tmp_path, "yes", "remove_field", "Medicine.preferredTime")


@pytest.mark.parametrize("msg", CLEAR)
def test_a_request_to_do_something_else_clears_it(tmp_path, msg):
    confirm.remember(tmp_path, TARGET)
    confirm.decline_if_not_yes(tmp_path, msg)
    assert not confirm.waiting(tmp_path), msg


def test_a_plan_with_the_same_file_time_still_wins_the_yes(tmp_path, monkeypatch):
    from services.smith import plan as plan_mod
    from services.smith4 import handle as handle_fn
    H = sys.modules["services.smith4.handle"]
    monkeypatch.setattr(H, "_in_step", lambda o, v, r: r, raising=False)
    monkeypatch.setattr(H, "_engine_current", lambda o: [], raising=False)
    confirm.remember(tmp_path, TARGET)
    plan_mod.remember(tmp_path, ["add a spice level", "show it on the form"], agreed=False)
    t = (tmp_path / confirm.PENDING_PATH).stat().st_mtime_ns
    for f in (confirm.PENDING_PATH, plan_mod.PENDING_PATH):
        os.utime(tmp_path / f, ns=(t, t))                                  # identical (or coarse) file times
    ran = []
    handle_fn(project_id="p", output_dir=str(tmp_path), message="Go ahead",
              choose=lambda ask, page, obs, hist: (ran.append(ask), {"tool": "answer", "args": {"text": "ok"}})[1], move=None)
    assert ran and "spice level" in ran[0]


def test_the_confirmation_asked_after_the_plan_still_gets_the_yes(tmp_path):
    from services.smith import plan as plan_mod
    from services.smith.ordering import asked_after
    plan_mod.remember(tmp_path, ["a", "b"], agreed=False)
    confirm.remember(tmp_path, TARGET)
    assert asked_after(tmp_path, confirm.PENDING_PATH, plan_mod.PENDING_PATH)
    assert not asked_after(tmp_path, plan_mod.PENDING_PATH, confirm.PENDING_PATH)


def test_files_without_a_sequence_fall_back_to_file_time(tmp_path):
    from services.smith import plan as plan_mod
    from services.smith.ordering import asked_after
    (tmp_path / ".forge").mkdir()
    (tmp_path / confirm.PENDING_PATH).write_text(json.dumps({"fingerprint": TARGET}))
    (tmp_path / plan_mod.PENDING_PATH).write_text(json.dumps({"steps": ["a"], "agreed": False}))
    os.utime(tmp_path / confirm.PENDING_PATH, ns=(1_000_000_000, 1_000_000_000))
    assert asked_after(tmp_path, plan_mod.PENDING_PATH, confirm.PENDING_PATH)


@pytest.mark.parametrize("word", ["sí", "oui", "ja", "はい", "हाँ", "نعم"])
def test_common_yes_words_in_other_languages_are_a_yes(tmp_path, word):
    assert confirm.is_yes(word)


@pytest.mark.parametrize("word", ["nein", "non", "नहीं", "لا", "いいえ"])
def test_common_no_words_in_other_languages_are_a_no(tmp_path, word):
    confirm.remember(tmp_path, "remove_field:a.b")
    assert confirm.decline_if_not_yes(tmp_path, word) == "no"


# --- 9 -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("brief", ["an ios app, not a website", "I need an iOS app, not a web app", "an Android app instead of a website",
                                   "a Kotlin app for my team", "build a swift app"])
def test_an_explicit_native_demand_beats_the_word_web(brief):
    assert cb.native_confirmation(brief) is not None, brief


@pytest.mark.parametrize("brief", ["an app for Kotlin developers", "Taylor Swift fan club app", "a responsive web app for Android and iOS",
                                   "a mobile app for a repair shop"])
def test_these_stay_unasked(brief):
    assert cb.native_confirmation(brief) is None, brief


def _p(*qs):
    return lambda prompt: json.dumps({"questions": [{"question": q, "options": ["a"]} for q in qs]})


BRIEF = "A clinic app where patients book visits with their doctor and see history over time."


@pytest.mark.parametrize("q", ["Which programming language?", "Which language should it be written in?", "Which framework should it be built with?"])
def test_language_and_framework_choices_are_dropped(q):
    assert cb.clarify_brief(BRIEF, provider=_p(q)) == []


def test_a_question_about_which_device_people_use_is_a_product_question():
    q = "Which platform should the nurses use to book - the ward screen or their phones?"
    assert [x["question"] for x in cb.clarify_brief(BRIEF, provider=_p(q))] == [q]
    assert cb.clarify_brief(BRIEF, provider=_p("Which platform: iOS, Android or web?")) == []


# --- 10 ------------------------------------------------------------------------------------------

def test_a_dev_server_and_an_early_shell_are_not_a_built_app(tmp_path):
    from services.smith4 import verbs
    (tmp_path / "app/.next/server").mkdir(parents=True)
    (tmp_path / "app/src/schemas").mkdir(parents=True)
    (tmp_path / "app/package.json").write_text("{}")
    (tmp_path / "app/src/schemas/shell.json").write_text("{}")
    assert not verbs._app_is_built(tmp_path)
    (tmp_path / "app/src/schemas/orders.json").write_text("{}")
    assert verbs._app_is_built(tmp_path)
