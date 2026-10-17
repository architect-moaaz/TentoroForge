"""A reference screen of kind `sign_in`/`sign_up` is answered by the
platform's own auth page of that kind: no author writes a `reference` on
a page the platform builds, so "Admin Login" stayed open and the journeys
step was sent back twice for it (60v142ju, 2026-10-12)."""
from __future__ import annotations

from services.blueprint.reference_coverage import coverage

DOC = {
    "domainReference": {"screens": [
        {"name": "Admin Login", "kind": "sign_in", "forRoles": ["Admin"]},
        {"name": "Create Account", "kind": "sign_up"},
        {"name": "Staff Login", "kind": "form"},
    ]},
    "pages": [{"id": "PAGE-008", "name": "Sign in", "route": "/login", "pattern": "auth", "auth": "login"},
              {"id": "PAGE-009", "name": "Create account", "route": "/signup", "pattern": "auth", "auth": "signup"}],
}


def test_auth_pages_answer_the_ways_in_by_kind_and_nothing_else():
    got = {c.name: c.covered_by for c in coverage(DOC, ("screen",))}
    assert got == {"Admin Login": "PAGE-008", "Create Account": "PAGE-009", "Staff Login": None}


def test_a_way_in_the_platform_has_not_built_yet_is_not_open():
    """The page set is checked BEFORE the `auth_pages` step adds /login and /signup: it was sent back twice for them."""
    early = {"domainReference": DOC["domainReference"], "pages": [], "security": {"authentication": "email_password"}}
    got = {c.name: c.covered_by for c in coverage(early, ("screen",))}
    assert got == {"Admin Login": "platform:auth_pages", "Create Account": "platform:auth_pages", "Staff Login": None}


def test_no_sign_in_means_nothing_is_promised():
    early = {"domainReference": DOC["domainReference"], "pages": [], "security": {"authentication": "none"}}
    got = {c.name: c.covered_by for c in coverage(early, ("screen",))}
    assert got == {"Admin Login": None, "Create Account": None, "Staff Login": None}


def test_a_sign_up_is_not_promised_where_nobody_holds_a_password():
    early = {"domainReference": DOC["domainReference"], "pages": [],
             "security": {"authentication": "email_password", "signIn": {"password": False, "magicLink": True}}}
    got = {c.name: c.covered_by for c in coverage(early, ("screen",))}
    assert got["Admin Login"] == "platform:auth_pages" and got["Create Account"] is None


def test_the_domain_agent_is_told_the_kinds():
    from services.blueprint.executors import NODE_TASKS
    assert "`sign_in` or `sign_up`" in NODE_TASKS["domain_reference"]
