"""Smith in change mode: the problem report, reproduced through the screen
as the person who saw it; a platform fault reported, not patched around; a
requirement that is a requirement; a turn that picks up where it stopped.

E-commerce (forge-v3, 2026-10-09): "Add to cart is not functioning" was
tried as a signed-in Customer through the API — "the workflow works" — while
the shopper had pressed a button that never called it; about thirty of 95
requests were platform faults Smith could not change and patched around or
dropped; REQ-015 read "Change the post-sign-in landing route…"; and "carry
on" started from nothing after a turn died at 34 minutes.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.smith import reported
from services.smith4 import turn as T

ROLES = [{"id": "ROLE-001", "name": "Customer"}, {"id": "ROLE-002", "name": "Merchant"}]


def test_the_report_names_who_saw_it_and_where():
    r = reported.clean({"route": "/products?product=1", "role": "Customer", "signedIn": False,
                        "viewport": {"width": 390, "height": 844}, "device": "iPhone", "junk": 1})
    assert r == {"route": "/products?product=1", "role": "Customer", "signedIn": False,
                 "viewport": {"width": 390, "height": 844}, "device": "iPhone"}
    assert reported.who(r) == "guest", "signed out beats the role they once had"
    assert reported.who({"role": "Merchant", "signedIn": True}, ["Customer", "Merchant"]) == "Merchant"
    assert reported.who({"role": "Nobody", "signedIn": True}, ["Customer"]) == ""
    said = reported.block(r)
    assert said.startswith("WHO SAW IT: a signed-out visitor on /products?product=1, a phone (390×844) (iPhone).")
    assert "`open_page` as `guest` on `/products?product=1`" in said
    assert reported.block({}) == "" and reported.clean(None) == {}


def test_the_trials_are_the_reporters_when_a_report_names_them():
    from services.smith.trials import default_person
    doc = {"roles": ROLES, "pages": [{"id": "PAGE-002", "route": "/products", "access": "public"}], "workflows": []}
    assert default_person(doc, route="/products") != "guest"
    token = reported.REPORTED.set({"signedIn": False, "route": "/products"})
    try:
        assert default_person(doc, route="/products") == "guest"
    finally:
        reported.REPORTED.reset(token)
    token = reported.REPORTED.set({"role": "Merchant", "signedIn": True})
    try:
        assert default_person(doc, route="/products") == "Merchant"
    finally:
        reported.REPORTED.reset(token)


def test_a_change_waits_for_a_try_through_the_screen_they_named():
    api_only = [SimpleNamespace(tool="try_workflow", said="ran"), SimpleNamespace(tool="try_request", said="200")]
    report = {"route": "/products", "signedIn": False}
    said = T.untried_as_reported(report, api_only)
    assert "They saw this on /products as guest" in said and "`open_page`" in said
    assert T.untried_as_reported(report, api_only + [SimpleNamespace(tool="open_page", said="opened")]) == ""
    assert T.untried_as_reported({}, api_only) == "", "no screen named: any try counts, as before"
    assert T.untried_as_reported(report, []) == "", "nothing tried at all is REPRODUCE_FIRST's case"


def test_the_report_rides_from_the_request_to_the_turn(monkeypatch, tmp_path):
    import importlib

    from routers.blueprint_generate import SmithChatRequest
    from services import smith_chat_v2
    H = importlib.import_module("services.smith4.handle")
    assert "report" in SmithChatRequest.model_fields
    seen: dict = {}

    def fake_turn(ctx, **kw):
        seen["report"] = ctx.report
        from services.smith4.outcome import Outcome
        return Outcome(status="resolved", said="ok")
    monkeypatch.setattr(H, "turn", fake_turn)
    monkeypatch.setattr(H, "_engine_current", lambda od: [])
    monkeypatch.setattr(H, "_version", lambda od: 1)
    monkeypatch.setattr(H, "_in_step", lambda od, v, out: out)
    monkeypatch.setattr(H.plan_mod, "asked_of", lambda od: "")
    H._handle(project_id="p", output_dir=str(tmp_path), message="the button does nothing", unattended=True,
              report={"route": "/cart", "signedIn": False, "extra": "dropped"})
    assert seen["report"] == {"route": "/cart", "signedIn": False}
    req = smith_chat_v2.ChatV2Request(project_id="p", output_dir=str(tmp_path), message="m",
                                      report={"route": "/cart"})
    assert req.report == {"route": "/cart"}


def test_a_platform_fault_is_reported_not_patched_around(tmp_path):
    from services import incident_ledger
    from services.blueprint.service import BlueprintService
    from services.smith import writes
    BlueprintService.create(output_dir=tmp_path, app_id="shop", name="Shop", domain="retail")
    out = writes.run("report_platform_fault", {"detail": "the guest cart has no owner column, so every "
                                                         "signed-out Add to cart is refused", "where": "/products"},
                     output_dir=str(tmp_path))
    assert out["applied"] and "fault in the platform, not in your application" in out["said"]
    recorded = incident_ledger.read(str(tmp_path), kind="platform")
    assert len(recorded) == 1 and recorded[0]["message"].startswith("the guest cart has no owner column")
    assert recorded[0]["where"] == "/products" and recorded[0]["source"] == "smith"
    doc = BlueprintService.load(output_dir=tmp_path).doc
    issue = [i for i in doc["runtime"]["issues"] if i["kind"] == "platform"][0]
    assert issue["reported_by"] == "smith" and issue["where"] == "/products"
    assert not writes.run("report_platform_fault", {}, output_dir=str(tmp_path))["applied"]
    from services.smith import tools
    assert tools.is_write("report_platform_fault")


def test_a_requirement_says_what_the_product_must_do(tmp_path):
    from services.blueprint.service import BlueprintService
    from services.smith.definition_change import SectionChangeError, add_requirement, an_instruction
    assert an_instruction("Change the post-sign-in landing route for the Customer role from /account to /")
    assert an_instruction("make the cart page show the total")
    assert not an_instruction("A customer who signs in lands on the shop home")
    assert not an_instruction("The merchant can update an order's status")
    svc = BlueprintService.create(output_dir=tmp_path, app_id="shop", name="Shop", domain="retail")
    with pytest.raises(SectionChangeError, match="reads as an instruction"):
        add_requirement(svc, "Change the landing route to /")
    out = add_requirement(svc, "A customer who signs in lands on the shop home")
    assert out["applied"]


def test_a_turn_picks_up_where_the_last_one_stopped(tmp_path):
    from services.engineer.journal import Journal
    j = Journal(tmp_path)
    assert T._last_turn_unfinished(j) == []
    j.write("turn:start", message="add to cart is broken")
    j.write("turn:step", tool="read_page_code", status="read", said="the view calls run({product})")
    j.write("turn:step", tool="try_workflow", status="read", said="FLOW-001 completed")
    j.write("turn:end", status="no_op", said="ran out of steps")
    steps = T._last_turn_unfinished(j)
    assert [s["tool"] for s in steps] == ["read_page_code", "try_workflow"]
    j.write("turn:start", message="carry on")
    j.write("turn:step", tool="open_page", status="read", said="the button sent nothing")
    j.write("turn:end", status="resolved", said="fixed")
    assert T._last_turn_unfinished(j) == [], "a finished turn is not picked up"
    assert T.CARRY_ON.match("Carry on") and T.CARRY_ON.match("continue please") and not T.CARRY_ON.match("fix the cart")


def test_a_turn_has_a_clock_and_a_journal():
    import inspect
    src = inspect.getsource(T._run)
    assert "budget = Budget(TURN_MINUTES)" in src and "if budget.over():" in src
    assert 'journal.write("turn:step"' in src
    assert T.TURN_MINUTES > 0
    whole = inspect.getsource(T.turn)
    assert 'journal.write("turn:start"' in whole and 'journal.write("turn:end"' in whole
    assert "reported.REPORTED.set(dict(ctx.report or {}))" in whole
