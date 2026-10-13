"""A native app is opt-in: `mobile.native.enabled` makes every page also a
React Native screen; nothing else does.

The `native_code` node sits beside `page_code` and fans out over the pages
only when the application asks for it. An application that does not ask has
no subjects, so the node completes without calling a model. The agent that
writes it may write `nativeCode` and nothing else, and a native app is refused
what the phone cannot do: sign in without a password, or ship without an id."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, CapabilityViolation, InvalidMobile, capability_for, check_capability, check_mobile,
)
from services.blueprint.orchestrator import DAG, native_page_subjects, pending_subjects, subjects_for

PAGES = [{"id": "PAGE-001", "route": "/"}, {"id": "PAGE-002", "route": "/orders"},
         {"id": "PAGE-003", "route": "/old", "status": "DEPRECATED"},
         {"id": "PAGE-004", "route": "/audit", "pattern": "audit_trail"}]


def _doc(**mobile):
    return {"pages": PAGES, "mobile": mobile, "security": {}}


def test_the_node_runs_beside_the_web_pages_not_after_them():
    node, web = DAG["native_code"], DAG["page_code"]
    assert node.agent == "native_engineer" and node.produces == frozenset({"nativeCode"})
    assert node.depends_on == web.depends_on, "the same inputs as the web page"
    assert "page_code" not in node.depends_on and "native_code" not in web.depends_on
    assert node.fanout == "native_pages" and node.optional


def test_an_application_that_does_not_ask_has_nothing_to_write():
    assert native_page_subjects(_doc()) == []
    assert native_page_subjects(_doc(native={"enabled": False})) == []
    assert native_page_subjects({"pages": PAGES}) == []
    assert subjects_for(DAG["native_code"], _doc()) == []


def test_an_application_that_asks_gets_a_screen_for_each_page_the_web_writes():
    doc = _doc(native={"enabled": True})
    assert native_page_subjects(doc) == ["PAGE-001", "PAGE-002"], "one-to-one with page_code's pages"
    assert native_page_subjects(doc) == subjects_for(DAG["page_code"], doc)


def test_a_page_with_a_screen_is_not_written_again():
    doc = _doc(native={"enabled": True})
    doc["nativeCode"] = [{"page": "PAGE-001", "screen": "x"}]
    assert pending_subjects(DAG["native_code"], doc) == ["PAGE-002"]


def test_the_agent_writes_native_code_and_nothing_else():
    assert capability_for("native_engineer").writes == {"nativeCode"}
    ok = AgentResult(task_id="T", agent="native_engineer", confidence=0.9,
                     proposals=[ArtifactProposal(section="nativeCode", natural_key="PAGE-001", body={"page": "PAGE-001"})])
    bad = AgentResult(task_id="T", agent="native_engineer", confidence=0.9,
                      proposals=[ArtifactProposal(section="pageCode", natural_key="PAGE-001", body={"page": "PAGE-001"})])
    check_capability(ok)
    with pytest.raises(CapabilityViolation):
        check_capability(bad)


def _result(section, body):
    return AgentResult(task_id="T", agent="product", confidence=0.9,
                       proposals=[ArtifactProposal(section=section, natural_key="", body=body)])


def test_a_native_app_names_its_bundle_id():
    with pytest.raises(InvalidMobile, match="bundle id"):
        check_mobile(_result("mobile", {"native": {"enabled": True}}), {})
    check_mobile(_result("mobile", {"native": {"enabled": True}, "store": {"bundleId": "com.acme.app"}}), {})


def test_a_native_app_needs_password_sign_in():
    doc = {"mobile": {"store": {"bundleId": "com.acme.app"}}, "security": {"signIn": {"password": False, "magicLink": True}}}
    with pytest.raises(InvalidMobile, match="password"):
        check_mobile(_result("mobile", {"native": {"enabled": True}}), doc)
    # …and a reply that turns password off under a native app is refused too.
    native = {"mobile": {"native": {"enabled": True}, "store": {"bundleId": "com.acme.app"}}}
    with pytest.raises(InvalidMobile, match="password"):
        check_mobile(_result("security", {"signIn": {"password": False, "magicLink": True}}), native)


def test_an_application_without_native_is_not_asked_for_either():
    check_mobile(_result("mobile", {"native": {"enabled": False}}), {"security": {"signIn": {"password": False, "magicLink": True}}})
