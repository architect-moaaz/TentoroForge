"""Where people will use the app is asked by Smith, first, in fixed words, and the answer is read exactly.

It used to be a question in the create dialog. Now Smith asks it once before the app is defined: five choices, the
limits of a PWA said in the question, the answer kept beside the Blueprint-to-be and written into `mobile.surface`."""
from __future__ import annotations

import json

import pytest

from services.blueprint import app_target
from services.blueprint.service import BlueprintService
from services.smith4 import definition
from services.smith4.verbs import Ctx

BRIEF = "A pantry tracker. People sign in and keep a list of the food they have. It also has a native phone app for iPhone and Android."
LABELS = [label for _s, label in app_target.OPTIONS]


def ctx_for(tmp_path, message="", history=None, unattended=False):
    return Ctx(output_dir=str(tmp_path), project_id="p", message=message, ask=message,
               history=history if history is not None else [("user", BRIEF)], app_name="Pantry Pal", unattended=unattended)


def asked_history(*replies):
    out = [("user", BRIEF), ("assistant", app_target.QUESTION)]
    for reply in replies:
        out += [("user", reply), ("assistant", app_target.QUESTION)]
    return out


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    """The clarifier is a model call: it says there is nothing more to ask, and counts how often it was asked."""
    calls = []
    import services.smith.clarify_brief as cb
    monkeypatch.setattr(cb, "clarify_brief", lambda *a, **k: calls.append(1) or [])
    return calls


# ---- the choices ------------------------------------------------------------------------------------------------

def test_there_are_five_choices_and_each_is_a_chip_the_question_names():
    assert [s for s, _l in app_target.OPTIONS] == list(app_target.SURFACES)
    assert LABELS == ["Web only", "Web + native app", "Web + PWA", "Native app only", "PWA only"]
    for label in LABELS:
        assert label.split(" ")[0].lower() in app_target.QUESTION.lower()


def test_the_question_says_what_a_pwa_cannot_do():
    q = app_target.QUESTION.lower()
    for limit in ("not in the app stores", "by hand", "bluetooth", "offline", "less like a downloaded app"):
        assert limit in q, limit


def test_the_question_is_one_short_point_per_line_in_words_a_customer_knows():
    points = [p for p in app_target.QUESTION.split("\n\n") if p.strip()]
    assert all("\n" not in p for p in points), "each point is on its own line"
    assert all(len(p) < 110 for p in points), "and short"
    said = app_target.QUESTION.lower()
    for jargon in ("backend", "api", "database", "webview", "service worker", "manifest"):
        assert jargon not in said, jargon


@pytest.mark.parametrize("said,surface", [
    ("Web only", "web"), ("web + native app", "web_native"), ("Web + PWA", "web_pwa"),
    ("Native app only", "native_only"), ("PWA only", "pwa_only"),
    ("just the website please", "web"), ("web and native", "web_native"), ("website and a pwa", "web_pwa"),
    ("only native", "native_only"), ("only pwa", "pwa_only"),
])
def test_an_answer_is_read_as_the_chip_or_the_same_thing_in_words(said, surface):
    assert app_target.parse_choice(said) == surface


@pytest.mark.parametrize("said", ["", "yes", "native", "pwa", "native and pwa", "something with phones", BRIEF])
def test_an_answer_that_names_no_single_choice_is_not_an_answer(said):
    assert app_target.parse_choice(said) is None


def test_the_old_dialog_values_are_read_as_what_they_meant(tmp_path):
    assert app_target.write(tmp_path, "responsive") and app_target.read(tmp_path) == "web"
    assert app_target.write(tmp_path, "native") and app_target.read(tmp_path) == "web_native"
    assert app_target.write(tmp_path, "rubbish") is False


# ---- what the choice sets in the Blueprint --------------------------------------------------------------------

@pytest.mark.parametrize("surface,native", [("web", False), ("web_native", True), ("web_pwa", False),
                                             ("native_only", True), ("pwa_only", False)])
def test_the_choice_is_written_into_the_blueprint(tmp_path, surface, native):
    app_target.write(tmp_path, surface)
    svc = BlueprintService.create(output_dir=tmp_path, app_id="x", name="Pantry Pal", domain="food", description="d")
    mobile = svc.doc["mobile"]
    assert mobile["surface"] == surface and mobile["native"]["enabled"] is native
    assert bool(mobile.get("store", {}).get("bundleId")) is native, "only a native app names a bundle id"
    saved = json.loads((tmp_path / ".forge/blueprint/current.json").read_text("utf-8"))
    assert saved["mobile"]["surface"] == surface


def test_only_the_native_only_choice_has_no_web_pages():
    assert [s for s in app_target.SURFACES if not app_target.has_web_pages(s)] == ["native_only"]
    assert [s for s in app_target.SURFACES if app_target.has_native(s)] == ["web_native", "native_only"]


# ---- Smith asks first ---------------------------------------------------------------------------------------------

def test_the_first_thing_asked_is_where_people_will_use_it_and_the_model_is_not_asked_for_anything_else(tmp_path, no_model):
    said = definition.open_decisions(ctx_for(tmp_path), {})
    assert "PLATFORM IS NOT CHOSEN" in said and app_target.QUESTION in said
    for label in LABELS:
        assert label in said
    assert not no_model, "the clarifier is not asked until the platform is settled"


def test_a_brief_that_says_native_is_not_an_answer(tmp_path):
    """The brief names a native phone app; that is a wish, and nobody was offered the five choices yet."""
    definition.open_decisions(ctx_for(tmp_path), {})
    assert app_target.read(tmp_path) is None


def test_a_reply_to_the_question_is_kept_and_the_clarifier_goes_on(tmp_path, no_model):
    said = definition.open_decisions(ctx_for(tmp_path, "Web + native app", asked_history()), {})
    assert app_target.read(tmp_path) == "web_native"
    assert "stands on its own" in said and no_model, "the clarifier ran and found nothing more to ask"


def test_a_chosen_platform_is_not_asked_again(tmp_path, no_model):
    app_target.write(tmp_path, "web_pwa")
    said = definition.open_decisions(ctx_for(tmp_path, "Teal please", asked_history("Web + PWA")), {})
    assert "PLATFORM IS NOT CHOSEN" not in said and app_target.read(tmp_path) == "web_pwa"


def test_a_reply_that_picks_none_is_asked_once_more_and_then_the_app_is_a_website(tmp_path):
    first = definition.open_decisions(ctx_for(tmp_path, "hmm, phones", asked_history()), {})
    assert "asked this already" in first and app_target.read(tmp_path) is None
    second = definition.open_decisions(ctx_for(tmp_path, "whatever", asked_history("hmm, phones")), {})
    assert "PLATFORM IS NOT CHOSEN" not in second and app_target.read(tmp_path) == "web"


def test_a_turn_with_nobody_to_ask_makes_a_website_and_says_so_in_the_file(tmp_path):
    definition.open_decisions(ctx_for(tmp_path, unattended=True), {})
    assert app_target.read(tmp_path) == "web"


def test_no_question_before_there_is_a_brief(tmp_path):
    said = definition.open_decisions(ctx_for(tmp_path, "", []), {})
    assert "Nothing has been asked for yet" in said and app_target.read(tmp_path) is None


def test_defining_before_the_question_was_answered_sends_Smith_back_to_ask(tmp_path):
    out = definition.define_application(ctx_for(tmp_path), {})
    assert out["applied"] is False and "PLATFORM IS NOT CHOSEN" in out["finding"]
    assert not (tmp_path / ".forge/blueprint/current.json").exists(), "no app was made on a guess"


# ---- the question's words are fixed, not the model's ----------------------------------------------------------------

def test_while_the_platform_is_open_the_question_is_put_back_to_its_own_words_and_chips(tmp_path):
    model_version = {"question": "Where will people use it? Web only, web and native... A PWA cannot do much.", "options": ["Web", "App"]}
    out = definition.canonical_platform_ask(ctx_for(tmp_path), model_version)
    assert out["question"] == app_target.QUESTION and out["options"] == LABELS


def test_a_question_about_something_else_is_left_as_the_model_asked_it(tmp_path):
    """A pre-app turn may ask about anything (a sign-in email, a colour): only the platform question is put back."""
    ask = {"question": "What email address would you sign in with?", "options": []}
    assert definition.canonical_platform_ask(ctx_for(tmp_path), ask) == ask


def test_a_platform_question_is_recognised_by_its_words_or_its_chips(tmp_path):
    by_words = {"question": "Where will people use it?", "options": []}
    by_chips = {"question": "How should this run?", "options": ["Web only", "PWA only", "Other"]}
    for ask in (by_words, by_chips):
        assert definition.canonical_platform_ask(ctx_for(tmp_path), ask)["question"] == app_target.QUESTION


def test_once_the_platform_is_chosen_the_models_questions_are_its_own(tmp_path):
    app_target.write(tmp_path, "pwa_only")
    ask = {"question": "Which colour?", "options": ["Teal"]}
    assert definition.canonical_platform_ask(ctx_for(tmp_path), ask) == ask


def test_an_app_that_already_exists_is_never_asked_the_platform_question(tmp_path, monkeypatch):
    import services.smith4.context as context
    monkeypatch.setattr(context, "defined", lambda _out: True)      # an app with requirements or pages
    ask = {"question": "Which field?", "options": ["a"]}
    assert definition.canonical_platform_ask(ctx_for(tmp_path), ask) == ask
