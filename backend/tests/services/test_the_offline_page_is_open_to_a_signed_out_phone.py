"""The page an installed app (a PWA) shows with no network is open without a session.

The service worker keeps `/offline` at install and serves it when a page cannot be reached. The access gate redirected
`/offline` to the sign-in page, so the worker kept the sign-in page instead; a redirected answer cannot be used for a page
load, and "no network" showed the browser's own error (found on the published Habit Pal, 2026-10-21)."""
from __future__ import annotations

import re
from pathlib import Path

from services.blueprint.projection import _ALWAYS_OPEN, project_middleware

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}],
    "pages": [{"id": "PAGE-001", "name": "Home", "route": "/", "access": "authenticated"}],
    "navigation": {}, "security": {}, "data": {"entities": []}, "workflows": [],
}


def _matcher(app_root: Path) -> str:
    src = (app_root / "src" / "middleware.ts").read_text()
    return re.search(r'matcher:\s*\["(.+?)"\]', src).group(1)


def test_the_offline_page_is_outside_the_gate(tmp_path):
    assert "offline" in _ALWAYS_OPEN
    project_middleware(DOC, tmp_path)
    gate = re.compile(_matcher(tmp_path).replace("\\\\", "\\"))
    assert not gate.match("/offline"), "a signed-out phone with no signal must be able to open it"
    assert gate.match("/"), "a real page is still gated"
    assert gate.match("/api/data/orders"), "the data API is still gated"


def test_a_route_that_only_starts_with_the_word_is_still_gated(tmp_path):
    project_middleware(DOC, tmp_path)
    gate = re.compile(_matcher(tmp_path).replace("\\\\", "\\"))
    # Each open entry ends where a piece of the path ends (PR #28 review, 2026-10-22): an app that names a page
    # /offline-orders is gated like any other.
    assert gate.match("/offline-orders")
    assert not gate.match("/offline") and not gate.match("/offline/x")


def test_the_scaffold_agrees_before_any_projection():
    scaffold = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "middleware.ts"
    assert "set-password(?:/|$)|offline(?:/|$)|install(?:/|$)|api/auth(?:/|$)" in scaffold.read_text()
