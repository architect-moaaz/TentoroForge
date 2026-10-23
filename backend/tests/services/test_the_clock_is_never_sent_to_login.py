"""The routes machines call are open: the scheduler's tick and a signed
webhook authenticate themselves and can hold no session.

A built app's middleware matcher gated `/api/cron/tick`, so Vercel cron and
the app's own self-ping were answered with a 307 to `/login` and no
scheduled process ever ran in a published app (confirmed on
output/zo9k0ekd, 2026-10-11)."""
from __future__ import annotations

from pathlib import Path

from services.blueprint.platform_routes import PUBLIC
from services.blueprint.projection import project_middleware
from tests.services._middleware_gate import Gate

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}],
    "pages": [{"id": "PAGE-001", "name": "Home", "route": "/", "access": "authenticated"},
              {"id": "PAGE-002", "name": "Admin", "route": "/admin", "access": "role_restricted", "users": ["ROLE-001"]}],
    "navigation": {}, "security": {}, "data": {"entities": []}, "workflows": [],
}


def test_the_tick_and_the_webhooks_are_outside_the_gate(tmp_path):
    assert {"/api/cron", "/api/webhooks"} <= {r.route for r in PUBLIC if r.subtree}
    project_middleware(DOC, tmp_path)
    gate = Gate(tmp_path)
    assert gate.is_public("/api/cron/tick"), "the tick must not be answered with a redirect to sign in"
    assert gate.is_public("/api/webhooks/stripe")
    assert not gate.is_public("/admin"), "a page is still gated"
    assert not gate.is_public("/api/data/orders"), "the data API is still gated"
    assert not gate.is_public("/api/cronjobs"), "a route that only starts with the word is not the tick's"


def test_the_scaffold_agrees_before_any_projection():
    scaffold = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "middleware.ts"
    gate = Gate(scaffold)
    assert gate.is_public("/api/cron/tick") and gate.is_public("/api/webhooks/stripe")
    assert not gate.is_public("/api/data/orders")
