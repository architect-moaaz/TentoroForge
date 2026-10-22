"""A phone-only app writes no web pages, so a page without a web tree is not a fault.

The build's App Flow review said "PAGE-004: no composed tree, so the page cannot be projected" for the sign-in pair of every
phone-only app, and sent App Flow back for a repair (a model call, and nothing to repair). The web app still has to compose a
tree for every page."""
from __future__ import annotations

from services.blueprint import functional_completeness, verification

PAGES = [
    {"id": "PAGE-001", "name": "Shopping List", "route": "/", "pattern": "list"},
    {"id": "PAGE-004", "name": "Sign in", "route": "/login", "pattern": "auth"},
    {"id": "PAGE-005", "name": "Create account", "route": "/signup", "pattern": "auth"},
]


def doc(surface=None, layouts=()):
    d = {"pages": [dict(p) for p in PAGES], "pageLayouts": list(layouts), "workflows": []}
    if surface:
        d["mobile"] = {"surface": surface}
    return d


def layout_findings(d):
    return [f for f in verification.check_page_layout(d) if "no composed tree" in str(getattr(f, "detail", f))]


def test_a_phone_only_app_is_not_asked_for_web_trees():
    assert layout_findings(doc("native_only")) == []


def test_every_other_choice_still_is_asked():
    for surface in (None, "web", "web_native", "web_pwa", "pwa_only"):
        found = layout_findings(doc(surface))
        assert len(found) == len(PAGES), surface


def test_the_completeness_check_agrees():
    phone = [f for f in functional_completeness.page_findings(doc("native_only")) if f["rule"] == "page-not-composed"]
    assert phone == []
    web = [f for f in functional_completeness.page_findings(doc("web")) if f["rule"] == "page-not-composed"]
    assert {f["page"] for f in web} == {"PAGE-001"}      # the sign-in pair is the template's own page on the web
