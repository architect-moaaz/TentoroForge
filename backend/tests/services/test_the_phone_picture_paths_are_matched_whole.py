"""PR #28 review (2026-10-22): `"/phone/live" in path` let any route containing the text skip the rate limit and X-Frame-Options.
Anchored to the project route; and the live preview's `_expo/` rule is the static files only."""
import pytest

from middleware.phone_paths import is_phone_picture
from services.phone_live_proxy import allowed


@pytest.mark.parametrize("path", ["/api/projects/mjh7lfso/phone/live/", "/api/projects/mjh7lfso/phone/live", "/api/projects/a-b_c/phone/serve/index.html",
                                  "/api/projects/9f1/phone/live/hot"])
def test_the_picture_routes_are_matched(path):
    assert is_phone_picture(path)


@pytest.mark.parametrize("path", ["/api/projects/x/phone/livex", "/api/projects/x/phone/serveall", "/api/other/phone/live/", "/phone/live",
                                  "/api/projects/x/y/phone/live/", "/api/admin/projects/x/phone/live", "/api/x?next=/phone/live",
                                  "/api/projects/x/phone", "/api/projects//phone/live/"])
def test_a_route_that_only_contains_the_text_is_not(path):
    assert not is_phone_picture(path)


def test_only_the_static_files_under_expo_are_passed_to_the_page():
    assert allowed("/_expo/static/js/web/entry.js")
    assert not allowed("/_expo/") and not allowed("/_expo/anything") and not allowed("/_expo/symbolicate")


def test_websockets_is_declared_because_the_proxy_imports_it():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "requirements.txt").read_text(encoding="utf-8")
    assert "websockets>=13" in text


def _client(*middleware, **kw):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    for cls in middleware:
        app.add_middleware(cls, **kw.get(cls.__name__, {}))

    @app.get("/{path:path}")
    def _all(path: str):
        return {"ok": True}

    return TestClient(app)


def test_the_frame_header_is_dropped_for_the_picture_and_kept_for_a_look_alike():
    from middleware.security_headers import SecurityHeadersMiddleware

    client = _client(SecurityHeadersMiddleware)
    assert "x-frame-options" not in client.get("/api/projects/abc/phone/live/").headers
    assert client.get("/api/admin/phone/live/anything").headers["x-frame-options"] == "DENY"


def test_the_rate_limit_is_skipped_for_the_picture_and_not_for_a_look_alike():
    from middleware.rate_limit import RateLimitMiddleware

    client = _client(RateLimitMiddleware, RateLimitMiddleware=dict(requests_per_minute=1, burst=1))
    assert all(client.get("/api/projects/abc/phone/live/x").status_code == 200 for _ in range(5))
    codes = [client.get("/api/admin/phone/live/x").status_code for _ in range(4)]
    assert 429 in codes
