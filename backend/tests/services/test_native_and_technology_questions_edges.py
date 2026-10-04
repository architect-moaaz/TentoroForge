"""Task 9, second round: iOS/Android as the subject of a business or a responsive web
app is not a native demand; technology CHOICE questions are dropped and product
questions that share a word are kept; a bare .next is not a built app."""
import json

import pytest

from services.smith import clarify_brief as cb


@pytest.mark.parametrize("brief", ["a responsive web app for Android and iOS", "app for Android phone repair shop",
                                   "iOS app development agency website", "lightweight healthcare mobile app, responsive for Android and iOS",
                                   "A mobile-first app for tracking medicine"])
def test_these_are_not_native_demands(brief):
    assert cb.native_confirmation(brief) is None


@pytest.mark.parametrize("brief", ["Build me an iOS app for tracking pills", "I want an Android app for tasks", "a native app for my gym",
                                   "Build it in React Native", "write it with SwiftUI", "Build me a native app, not a web app"])
def test_these_still_are(brief):
    assert cb.native_confirmation(brief) is not None


def _p(*qs):
    return lambda prompt: json.dumps({"questions": [{"question": q, "options": ["a"]} for q in qs]})


BRIEF = "A clinic app where patients book visits with their doctor and see history over time."


@pytest.mark.parametrize("q", ["Do you want a mobile app or a website?", "Should it be built with Swift?", "Should it be a website or a mobile app?",
                               "Which platform should it run on?", "What stack do you prefer?", "Which database should it use?"])
def test_technology_choices_are_dropped(q):
    assert cb.clarify_brief(BRIEF, provider=_p(q)) == []


@pytest.mark.parametrize("q", ["Which database of patients should nurses see - only their ward or all?", "Which stack of vaccines is given first?",
                               "Which platform number does the train leave from?", "Who is the platform admin?"])
def test_product_questions_that_share_a_word_are_kept(q):
    assert [x["question"] for x in cb.clarify_brief(BRIEF, provider=_p(q))] == [q]


def test_a_bare_dot_next_is_not_a_built_app(tmp_path):
    from services.smith4 import verbs
    (tmp_path / "app/.next").mkdir(parents=True)
    (tmp_path / "app/package.json").write_text("{}")
    assert not verbs._app_is_built(tmp_path)
    (tmp_path / "app/.next/BUILD_ID").write_text("x")
    assert verbs._app_is_built(tmp_path)
