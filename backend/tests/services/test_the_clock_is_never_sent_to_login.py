"""The routes machines call are open: the scheduler's tick and a signed
webhook authenticate themselves and can hold no session.

A built app's middleware matcher gated `/api/cron/tick`, so Vercel cron and
the app's own self-ping were answered with a 307 to `/login` and no
scheduled process ever ran in a published app (confirmed on
output/zo9k0ekd, 2026-10-11)."""
from __future__ import annotations

import re
from pathlib import Path

from services.blueprint.projection import _ALWAYS_OPEN, project_middleware

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}],
    "pages": [{"id": "PAGE-001", "name": "Home", "route": "/", "access": "authenticated"},
              {"id": "PAGE-002", "name": "Admin", "route": "/admin", "access": "role_restricted", "users": ["ROLE-001"]}],
    "navigation": {}, "security": {}, "data": {"entities": []}, "workflows": [],
}


def _matcher(app_root: Path) -> str:
    src = (app_root / "src" / "middleware.ts").read_text()
    return re.search(r'matcher:\s*\["(.+?)"\]', src).group(1)


def test_the_tick_and_the_webhooks_are_outside_the_gate(tmp_path):
    assert "api/cron" in _ALWAYS_OPEN and "api/webhooks" in _ALWAYS_OPEN
    project_middleware(DOC, tmp_path)
    matcher = _matcher(tmp_path)
    assert "api/cron" in matcher and "api/webhooks" in matcher
    gate = re.compile(matcher.replace("\\\\", "\\"))
    assert not gate.match("/api/cron/tick"), "the tick must not be answered with a redirect to sign in"
    assert not gate.match("/api/webhooks/stripe")
    assert gate.match("/admin"), "a page is still gated"
    assert gate.match("/api/data/orders"), "the data API is still gated"


def test_the_scaffold_agrees_before_any_projection():
    scaffold = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "middleware.ts"
    assert "api/cron(?:/|$)|api/webhooks(?:/|$)" in scaffold.read_text()
