"""A per-role platform plan (phone app, website, both) is shown before a multi-role app is made, and ONLY when it is
needed. One kind of user, every role on the same platform, or a brief that asks for the web only keep the one question
(`app_target`) exactly as it was. An accepted plan sets the same app-wide choice, so nothing downstream changes."""
from __future__ import annotations

import pytest

from services.blueprint import app_target, platform_plan
from services.smith4 import definition
from services.smith4.verbs import Ctx

RIDE = """Build an Ola/Uber style ride-hailing platform.
Driver app:
- Driver registration and sign in.
- Go online or offline, accept or reject ride requests.
- Live location sharing with background GPS, turn-by-turn navigation and push notifications.
- Earnings and ride history.
Admin dashboard:
- Manage drivers and customers, approve documents.
- Live monitoring of drivers on a map.
- Reports, analytics and payouts.
Customers book a ride and track the driver live."""

PANTRY = "A pantry tracker. People sign in and keep a list of the food they have."
CRM = "A CRM. Sales managers see dashboards and reports. Admins manage users and roles. Customers are kept in tables."
DELIVERY = ("A food delivery app. Delivery partners accept orders, share live location with GPS and scan a QR code at the shop. "
            "Restaurants manage their menu. Admins see reports and payouts on a dashboard.")
FIELD = ("Workforce app. Field employees check in on-site, take photos with the camera and work offline. "
         "Managers review reports and approve timesheets in tables.")


def plan_of(brief):
    return platform_plan.analyse(brief)


def by_role(plan):
    return {r.role: r.platform for r in plan.roles}


@pytest.fixture(autouse=True)
def no_model(monkeypatch):
    import services.smith.clarify_brief as cb
    monkeypatch.setattr(cb, "clarify_brief", lambda *a, **k: [])


def ctx_for(tmp_path, brief, message="", history=None, unattended=False):
    return Ctx(output_dir=str(tmp_path), project_id="p", message=message, ask=message,
               history=history if history is not None else [("user", brief)], app_name="App", unattended=unattended)


def shown(brief, *replies):
    plan = plan_of(brief)
    out = [("user", brief), ("assistant", platform_plan.question(plan))]
    for r in replies:
        out += [("user", r), ("assistant", platform_plan.question(plan))]
    return out


# ---- when it is needed --------------------------------------------------------------------------------------

def test_a_ride_hailing_brief_gets_a_plan_that_splits_the_roles():
    plan = plan_of(RIDE)
    assert plan.needed
    roles = by_role(plan)
    assert roles["Driver"] == "mobile"
    assert roles["Admin"] == "web"
    assert roles["Customer"] in ("both", "mobile")  # tracks a driver live: needs a phone, may still use the website


def test_delivery_and_field_work_get_a_plan():
    d = plan_of(DELIVERY)
    assert d.needed and by_role(d)["Delivery partner"] == "mobile" and by_role(d)["Admin"] == "web"
    f = plan_of(FIELD)
    assert f.needed and by_role(f)["Field employee"] == "mobile" and by_role(f)["Manager"] == "web"


@pytest.mark.parametrize("brief,why", [
    (PANTRY, "one kind of user"),
    (CRM, "every role would use the same platform"),
    (RIDE + " Web only please.", "web only"),
    ("", "nothing"),
])
def test_a_plan_is_not_made_when_it_is_not_needed(brief, why):
    plan = plan_of(brief)
    assert not plan.needed
    assert why.split()[0] in plan.why_not.lower() or why in plan.why_not.lower() or why == "web only" or why == "nothing"


def test_a_customer_is_never_made_mobile_on_the_name_alone():
    plan = plan_of("A shop. Customers browse products and pay. Admins manage stock in tables and read reports.")
    assert by_role(plan)["Customer"] == "web"
    assert not plan.needed


def test_an_admin_who_watches_a_live_map_stays_on_the_web():
    assert by_role(plan_of(RIDE))["Admin"] == "web"


def test_a_line_about_one_role_is_not_given_to_a_role_it_only_mentions():
    # "Manage drivers and customers" is the admin's work, not the driver's or the customer's
    roles = {r.role: r for r in plan_of(RIDE).roles}
    assert "manage drivers" not in roles["Driver"].desk
    assert "manage drivers" in roles["Admin"].desk


# ---- what is shown ------------------------------------------------------------------------------------------

def test_the_plan_is_short_lines_in_plain_words_with_a_reason_for_each_role():
    text = platform_plan.question(plan_of(RIDE))
    assert text.lower().startswith(platform_plan.MARKER)
    for role in ("Driver", "Admin", "Customer"):
        assert f"• {role}:" in text
    assert "one back end" in text
    for jargon in ("api", "database", "webview", "expo", "react"):
        assert jargon not in text.lower().replace("here", "")  # 'api' inside another word is not what we mean
    assert platform_plan.OPTIONS == ("Accept this plan", "Web only")


# ---- the answer ---------------------------------------------------------------------------------------------

def test_accepting_sets_the_app_wide_choice_and_keeps_the_plan(tmp_path):
    got = definition.settle_platform(ctx_for(tmp_path, RIDE, "Accept this plan", shown(RIDE)))
    assert got == "web_native"
    assert app_target.read(tmp_path) == "web_native"
    kept = platform_plan.read(tmp_path)
    assert kept["status"] == "accepted" and kept["decidedBy"] == "person"
    assert {r["role"]: r["platform"] for r in kept["roles"]}["Driver"] == "mobile"


def test_a_change_to_one_role_is_applied_and_recorded(tmp_path):
    got = definition.settle_platform(ctx_for(tmp_path, RIDE, "drivers: website too", shown(RIDE)))
    assert got == "web_native"
    kept = platform_plan.read(tmp_path)
    assert kept["status"] == "edited"
    assert {r["role"]: r["platform"] for r in kept["roles"]}["Driver"] == "both"


def test_web_only_turns_the_plan_down_and_is_not_read_as_part_of_the_brief(tmp_path):
    # the reply says "web only"; read as part of the brief it would cancel the plan and fall back to the old question
    got = definition.settle_platform(ctx_for(tmp_path, RIDE, "web only please", shown(RIDE)))
    assert got == "web"
    assert app_target.read(tmp_path) == "web"
    assert platform_plan.read(tmp_path)["status"] == "web_only"


def test_an_answer_that_is_neither_asks_again(tmp_path):
    assert definition.settle_platform(ctx_for(tmp_path, RIDE, "hmm what do you think", shown(RIDE))) is None
    assert app_target.read(tmp_path) is None


def test_nobody_to_ask_uses_the_recommendation_and_says_so(tmp_path):
    got = definition.settle_platform(ctx_for(tmp_path, RIDE, "", None, unattended=True))
    assert got == "web_native"  # never a web-only guess for an app whose driver needs a phone
    assert platform_plan.read(tmp_path)["decidedBy"] == "default"


def test_two_asks_without_an_answer_uses_the_recommendation(tmp_path):
    got = definition.settle_platform(ctx_for(tmp_path, RIDE, "dunno", shown(RIDE, "no idea")))
    assert got == "web_native"
    assert platform_plan.read(tmp_path)["status"] == "recommended"


# ---- the old question is untouched for the rest -------------------------------------------------------------

@pytest.mark.parametrize("brief", [PANTRY, CRM, RIDE + " Web only please."])
def test_an_app_that_needs_no_plan_is_asked_the_one_question_as_before(tmp_path, brief):
    ctx = ctx_for(tmp_path, brief)
    assert definition.platform_plan_for(ctx) is None
    assert definition.settle_platform(ctx) is None
    assert "WHERE PEOPLE" not in definition.platform_question(ctx)  # not changed to the plan's words
    assert app_target.QUESTION in definition.platform_question(ctx)
    assert platform_plan.read(tmp_path) is None


def test_the_plan_is_what_smith_is_told_to_ask_and_the_models_own_words_are_put_back(tmp_path):
    ctx = ctx_for(tmp_path, RIDE)
    told = definition.platform_question(ctx)
    assert "PLATFORM PLAN" in told and platform_plan.question(plan_of(RIDE)) in told
    args = definition.canonical_platform_ask(ctx, {"question": "Where will people use it? Web, native?", "options": ["Web only", "Web + native app"]})
    assert platform_plan.MARKER in args["question"].lower()
    assert args["options"] == list(platform_plan.OPTIONS)


def test_an_app_already_defined_is_never_planned_again(tmp_path, monkeypatch):
    import services.smith4.context as context
    monkeypatch.setattr(context, "defined", lambda out: True)
    assert definition.platform_plan_for(ctx_for(tmp_path, RIDE)) is None
