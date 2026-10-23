"""PR #28 review, item 6 (2026-10-22). The phone picture is a generated app's code served from the platform's own address, and the platform keeps its
sign-in in `localStorage`. On that origin a screen's code (or a package's) could read a viewer's token, and the picture's link needs no sign-in, so
it can be sent to anyone signed in.

The responses now carry `Content-Security-Policy: sandbox allow-scripts` (no `allow-same-origin`): the page gets an origin of its own with no storage and
no cookies, whether it is framed or opened directly; only the platform's own pages may frame it; the Editor's iframe is sandboxed too.

Checked in a real browser (Chrome through Playwright, 2026-10-23): origin `null`, a decoy value in the platform's storage not readable, the editor's
messages and the live sockets still working, fonts and icons loading, a hot update arriving without a reload.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services import phone_sandbox
from services.phone_live_proxy import rewrite_bundle, rewrite_html


# ---- the headers -----------------------------------------------------------------------------------------------------------------

def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from middleware.security_headers import SecurityHeadersMiddleware

    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "OPTIONS"])
    def _all(path: str):
        return {"ok": True}

    return TestClient(app)


@pytest.mark.parametrize("path", ["/api/projects/abc/phone/live/", "/api/projects/abc/phone/live/assets?unstable_path=x", "/api/projects/abc/phone/serve/index.html",
                                  "/api/projects/abc/phone/serve"])
def test_a_phone_picture_is_sandboxed_and_only_the_platform_may_frame_it(path):
    r = _client().get(path)
    directives = [d.strip() for d in r.headers["content-security-policy"].split(";")]
    assert "sandbox allow-scripts" in directives, "its own origin, scripts allowed"
    assert not any("allow-same-origin" in d for d in directives), "never the platform's origin"
    assert "frame-ancestors 'self'" in directives and "frame-ancestors 'none'" not in directives
    assert r.headers["x-frame-options"] == "SAMEORIGIN"
    assert r.headers["access-control-allow-origin"] == "*", "a page with its own origin needs it for its fonts"


def test_cors_is_only_for_reading_a_picture_not_for_anything_that_changes_something():
    assert "access-control-allow-origin" not in _client().post("/api/projects/abc/phone/live/").headers
    assert "access-control-allow-origin" not in _client().get("/api/projects/abc/phone-preview/status").headers


@pytest.mark.parametrize("path", ["/api/projects", "/api/projects/abc/phone-preview/status", "/api/projects/abc/phone/live-notes", "/api/admin/phone/live/x",
                                  "/api/projects/abc/phone"])
def test_every_other_route_keeps_its_headers(path):
    r = _client().get(path)
    csp = r.headers["content-security-policy"]
    assert "sandbox" not in csp and "frame-ancestors 'none'" in csp
    assert r.headers["x-frame-options"] == "DENY" and "access-control-allow-origin" not in r.headers


def test_the_websites_own_preview_is_left_as_it_was():
    """`/preview/serve` is a different route with a different need (not part of this change)."""
    r = _client().get("/api/projects/abc/preview/serve/")
    assert "sandbox" not in r.headers["content-security-policy"] and "x-frame-options" not in r.headers


# ---- the editor's frame ----------------------------------------------------------------------------------------------------------

def test_the_editors_frame_is_sandboxed_and_never_given_the_platforms_origin():
    source = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "phone" / "PhonePreview.tsx").read_text(encoding="utf-8")
    assert 'sandbox="allow-scripts"' in source
    assert "allow-same-origin" not in source.replace("WITHOUT allow-same-origin", "")


def test_the_editor_talks_to_the_picture_by_message_and_checks_who_sent_it_not_where_from():
    """What a sandbox keeps and what it takes away: messages stay; reading the frame's page does not."""
    source = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "components" / "phone" / "PhonePreview.tsx").read_text(encoding="utf-8")
    assert "e.source !== frame.current?.contentWindow" in source
    assert "contentDocument" not in source and ".origin" not in source.replace("window.location.origin", "")


# ---- what the page needs to run in a sandbox -----------------------------------------------------------------------------------------

def test_the_live_page_starts_with_the_stand_in_before_any_script_of_the_app():
    html = rewrite_html('<html><head></head><body><script src="/x.bundle?platform=web"></script></body></html>', "/api/projects/abc/phone/live")
    assert html.index(phone_sandbox.MARK) < html.index("window.__FORGE_LIVE__") < html.index("x.bundle")


def test_the_stand_in_is_added_once_and_to_a_page_with_or_without_a_head():
    once = phone_sandbox.with_shim("<html><head><title>x</title></head><body></body></html>")
    assert once.count(phone_sandbox.MARK) == 1 and once.index(phone_sandbox.MARK) < once.index("<title>")
    assert phone_sandbox.with_shim(once) == once
    assert phone_sandbox.with_shim("<p>no head</p>").startswith("<script>")


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to run the page's script")
def test_the_stand_in_replaces_storage_only_where_the_real_one_throws():
    script = phone_sandbox.SHIM.removeprefix("<script>").removesuffix("</script>")

    def run(storage_throws: bool, cookie_throws: bool) -> dict:
        program = f"""
        const window = globalThis; const real = {{ getItem: () => 'REAL', setItem() {{}}, removeItem() {{}}, key: () => null, length: 0 }};
        Object.defineProperty(window, 'localStorage', {{ configurable: true, get() {{ if ({str(storage_throws).lower()}) throw new Error('SecurityError'); return real; }} }});
        Object.defineProperty(window, 'sessionStorage', {{ configurable: true, get() {{ if ({str(storage_throws).lower()}) throw new Error('SecurityError'); return real; }} }});
        globalThis.document = {{}};
        Object.defineProperty(document, 'cookie', {{ configurable: true, get() {{ if ({str(cookie_throws).lower()}) throw new Error('SecurityError'); return 'a=1'; }}, set() {{}} }});
        {script}
        const out = {{}};
        out.getReal = localStorage.getItem('k');
        localStorage.setItem('k', 5); out.afterSet = localStorage.getItem('k'); out.len = localStorage.length; out.key0 = localStorage.key(0);
        localStorage.removeItem('k'); out.afterRemove = localStorage.getItem('k');
        out.cookie = document.cookie; sessionStorage.setItem('s', 'v'); out.session = sessionStorage.getItem('s');
        console.log(JSON.stringify(out));
        """
        done = subprocess.run(["node", "-e", program], capture_output=True, text=True, timeout=30)
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    sandboxed = run(True, True)
    assert sandboxed["getReal"] is None and sandboxed["afterSet"] == "5" and sandboxed["len"] == 1 and sandboxed["key0"] == "k"
    assert sandboxed["afterRemove"] is None and sandboxed["cookie"] == "" and sandboxed["session"] == "v", "in memory, and no error"
    open_page = run(False, False)
    assert open_page["getReal"] == "REAL" and open_page["cookie"] == "a=1", "where storage works nothing is replaced"


def test_the_built_picture_page_gets_the_stand_in_when_it_is_served(tmp_path, monkeypatch):
    """At serve time, so a picture built before this change has it too."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from routers import phone_preview as router_module
    from services import phone_preview

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><head></head><body>built</body></html>", encoding="utf-8")
    (dist / "app.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setattr(phone_preview, "dist_dir", lambda output_dir: dist)

    class _Result:
        def first(self):
            return ("out",)

    class _Db:
        async def execute(self, *_a, **_k):
            return _Result()

    app = FastAPI()
    app.include_router(router_module.router)

    async def fake_db():
        yield _Db()

    from database import get_db
    app.dependency_overrides[get_db] = fake_db
    client = TestClient(app)
    page = client.get("/api/projects/abc/phone/serve/")
    assert page.status_code == 200 and phone_sandbox.MARK in page.text and "built" in page.text
    assert phone_sandbox.MARK not in client.get("/api/projects/abc/phone/serve/app.js").text, "only pages, not scripts"


# ---- the asset address (found in a real browser) ----------------------------------------------------------------------------------------

def test_a_fonts_address_is_written_without_the_slash_that_makes_the_dev_web_server_redirect():
    """`/assets/?x` is answered by the dev web server in front of the backend with a redirect to `/assets?x`, and a redirect carries no CORS header; a
    page with its own origin must pass CORS on every hop, so its fonts failed on it. Metro serves both forms."""
    out = rewrite_bundle('x = {"httpServerLocation": "/assets/?unstable_path=.%2Fa"};', "/api/projects/abc/phone/live")
    assert '"/api/projects/abc/phone/live/assets?unstable_path=.%2Fa"' in out and "/assets/?" not in out
