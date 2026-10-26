"""The page an installed app (a PWA) shows with no network is open without a session.

The service worker keeps `/offline` at install and serves it when a page cannot be reached. The access gate redirected
`/offline` to the sign-in page, so the worker kept the sign-in page instead; a redirected answer cannot be used for a page
load, and "no network" showed the browser's own error (found on the published Habit Pal, 2026-10-21).

It is open as the exact route `/offline`, never as a word the path starts with: an app's own `/offline-orders` is gated like any other
page (PR #28 review, 2026-10-22; the platform's routes are declared in `services/blueprint/platform_routes.py`)."""
from __future__ import annotations

from services.blueprint.projection import project_middleware
from tests.services._middleware_gate import Gate

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}],
    "pages": [{"id": "PAGE-001", "name": "Home", "route": "/", "access": "authenticated"}],
    "navigation": {}, "security": {}, "data": {"entities": []}, "workflows": [],
}


def test_the_offline_page_is_open_and_a_real_page_is_not(tmp_path):
    project_middleware(DOC, tmp_path)
    gate = Gate(tmp_path)
    assert gate.is_public("/offline"), "a signed-out phone with no signal must be able to open it"
    assert not gate.is_public("/"), "a real page is still gated"
    assert not gate.is_public("/api/data/orders"), "the data API is still gated"


def test_a_route_that_only_starts_with_the_word_is_still_gated(tmp_path):
    project_middleware(DOC, tmp_path)
    gate = Gate(tmp_path)
    assert not gate.is_public("/offline-orders")
    assert not gate.is_public("/offline/x"), "the page itself, not what is under it"
