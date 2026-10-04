"""Tester round on tasks 7, 9, 10, 11: a question keeps the confirmation, plurals
do not merge fields, the native question is asked once, technology questions
never reach the person, 'built' means built, and roles make an app bigger."""
import pytest

from services.smith import clarify_brief as cb, confirm


# --- 7 -------------------------------------------------------------------------------------------

def test_a_question_between_the_confirmation_and_the_yes_keeps_it_waiting(tmp_path):
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Medicine.preferredTime"))
    for q in ("what exactly will it take with it?", "Which screens use it?", "will the data come back?", "is that safe"):
        assert confirm.decline_if_not_yes(tmp_path, q) == "" and confirm.waiting(tmp_path), q
    assert confirm.granted(tmp_path, "yes", "remove_field", "Medicine.preferredTime")           # exactly once
    assert not confirm.granted(tmp_path, "yes", "remove_field", "Medicine.preferredTime")


def test_an_exact_no_and_a_different_request_still_clear_it(tmp_path):
    confirm.remember(tmp_path, "remove_field:a.b")
    assert confirm.decline_if_not_yes(tmp_path, "No, leave it") == "no" and not confirm.waiting(tmp_path)
    confirm.remember(tmp_path, "remove_field:a.b")
    assert confirm.decline_if_not_yes(tmp_path, "make the header blue") == "dropped" and not confirm.waiting(tmp_path)


def test_a_singular_yes_never_grants_the_plural_field(tmp_path):
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Order.item"))
    assert not confirm.granted(tmp_path, "yes", "remove_field", "Order.items")
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Order.item"))
    assert confirm.granted(tmp_path, "yes", "remove_field", "orders.item")                       # the entity may differ in plural
    confirm.remember(tmp_path, confirm.fingerprint("remove_field", "Medicine.preferredTime"))
    assert confirm.granted(tmp_path, "yes", "remove_field", "Medicine.preferred_time")


# --- 9 -------------------------------------------------------------------------------------------

NATIVE = "Build me a native React Native app for tracking medicine."


def _p(*qs):
    import json
    return lambda prompt: json.dumps({"questions": [{"question": q, "options": ["a"]} for q in qs]})


def test_either_answer_to_the_native_question_means_it_was_answered():
    assert cb.clarify_brief(NATIVE + "\n" + cb.NATIVE_CONFIRM_NO, provider=_p()) == []
    assert cb.native_declined(NATIVE + "\n" + cb.NATIVE_CONFIRM_NO)
    assert "native project is not something I build" in cb.NATIVE_DECLINED_SAY


@pytest.mark.parametrize("brief", ["Build me an iOS app for tracking pills", "I want an Android app for tasks",
                                   "an iPhone app to log meals", "Make a mobile app for my gym",
                                   "Build an app for iOS and Android"])
def test_native_phone_app_requests_are_caught(brief):
    assert cb.native_confirmation(brief) is not None


@pytest.mark.parametrize("brief", ["A mobile-first app for tracking medicine for patients", "A responsive web app that works on mobile",
                                   "A swift delivery tracking app", "Taylor Swift fan club app", "An app for Kotlin developers",
                                   "create app with one form and with field name and DOB to submit and save this"])
def test_ordinary_briefs_are_not_native_demands(brief):
    assert cb.native_confirmation(brief) is None


@pytest.mark.parametrize("q", ["What technology should it use?", "What stack do you prefer?", "Should this be a web app or a mobile app?",
                               "Which platform: iOS, Android or web?", "Which database should store the data?",
                               "Should it be a PWA?", "Do you need iOS and Android apps?", "Which framework should MediTrack be built in?"])
def test_technology_questions_never_reach_the_person(q):
    assert cb.clarify_brief("A clinic app where patients book visits with their doctor and see history over time.",
                            provider=_p(q)) == []


@pytest.mark.parametrize("q", ["Should orders be processed swiftly or in a batch?", "Is the kotlin team lead the approver?",
                               "Who can see patient records?", "Should customers be able to store their payment methods?"])
def test_business_questions_still_pass(q):
    assert [x["question"] for x in cb.clarify_brief("A clinic app where patients book visits with their doctor and see history over time.",
                                                    provider=_p(q))] == [q]


# --- 10 ------------------------------------------------------------------------------------------

def test_a_package_json_alone_is_not_a_built_app(tmp_path):
    from services.smith4 import verbs
    (tmp_path / "app").mkdir()
    (tmp_path / "app/package.json").write_text("{}")
    ctx = verbs.Ctx(output_dir=str(tmp_path), project_id="p", message="m", ask="m")
    ctx.applied = ["x"]
    said = verbs.rebuild(ctx, {}).said
    for banned in ("already in the application", "Publish carries them live", "Changes I make from chat"):
        assert banned not in said, banned


# --- 11 ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("brief", ["customers sign up, staff approve their requests and customers see the status",
                                   "sellers list handmade items and buyers browse and buy them",
                                   "A simple pharmacy app where the pharmacist records prescriptions and the patient sees when they are ready"])
def test_two_kinds_of_people_is_not_a_very_small_app(brief):
    assert not cb.is_very_small(brief)


def test_the_simpleapp_brief_stays_small():
    assert cb.is_very_small("create app with one form and with field name and DOB to submit and save this and "
                            "showing in another menu call master data")


@pytest.mark.parametrize("q", ["What mood should it have?", "Playful or serious?", "Which fonts do you like?", "Dark or light theme?"])
def test_style_questions_are_dropped_for_a_small_app(q):
    assert cb.clarify_brief("A simple form with a name and a date of birth that saves.", provider=_p(q)) == []
