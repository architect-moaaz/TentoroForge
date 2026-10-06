"""Ferry Booking (forge-v3, 2026-09-28): twelve of twenty-one pages shipped on
the plain fallback layout when the API account ran dry mid-build, and no later
run wrote them — page repair only looked at what failed in its own run."""
from types import SimpleNamespace

from services.blueprint.page_repair import unfinished_pages

PAGES = [{"id": "PAGE-001", "name": "Book", "route": "/book", "pattern": "wizard"},
         {"id": "PAGE-002", "name": "My bookings", "route": "/bookings", "pattern": "entity_list"},
         {"id": "PAGE-003", "name": "Sign in", "route": "/login", "pattern": "auth"},
         {"id": "PAGE-004", "name": "Old", "route": "/old", "pattern": "entity_list", "status": "DEPRECATED"}]
NOTHING_FAILED = SimpleNamespace(failed_because={}, degraded={}, failed=[])


def test_a_page_without_code_in_a_coded_app_is_unfinished():
    doc = {"pages": PAGES, "pageCode": [{"page": "PAGE-001", "view": "…"}]}
    todo = {t["page"]: t for t in unfinished_pages(doc, NOTHING_FAILED)}
    assert set(todo) == {"PAGE-002"}, "not the coded page, not sign-in, not a retired page"
    assert "plain layout the build falls back to" in todo["PAGE-002"]["reason"]


def test_an_app_with_no_page_code_is_not_rewritten_wholesale():
    assert unfinished_pages({"pages": PAGES, "pageCode": []}, NOTHING_FAILED) == []
