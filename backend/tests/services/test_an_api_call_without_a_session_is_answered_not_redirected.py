"""A call to the API without a session gets a 401 as JSON, not a redirect.

next-auth's `withAuth` redirects every unauthorised request to the sign-in
page. A client that is not a browser (a phone app, a script) cannot follow
that and reads a page of HTML where it expected JSON. The generated
middleware lets `/api/*` through `withAuth` and answers it itself: 401 with
no session, 403 for a session with the wrong role. Pages keep their redirect.

This proves the generated file says so; the answer on a running app is read
by the contract tests against a seeded copy."""
from __future__ import annotations

import re
from pathlib import Path

from services.blueprint.projection import project_middleware

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Admin"}],
    "pages": [{"id": "PAGE-001", "name": "Home", "route": "/", "access": "authenticated"},
              {"id": "PAGE-002", "name": "Admin", "route": "/admin", "access": "role_restricted", "users": ["ROLE-001"]}],
    "navigation": {}, "security": {}, "data": {"entities": []}, "workflows": [],
}


def _source(tmp_path: Path) -> str:
    project_middleware(DOC, tmp_path)
    return (tmp_path / "src" / "middleware.ts").read_text()


def test_an_api_call_without_a_session_is_answered_with_a_401(tmp_path):
    src = _source(tmp_path)
    assert 'isApi(path)' in src
    assert re.search(r'!token && isApi\(path\)\) return refuse\(401, "UNAUTHORIZED"', src)


def test_an_api_call_is_let_past_the_redirect_to_be_answered(tmp_path):
    src = _source(tmp_path)
    assert "authorized: ({ token, req }) => !!token || isApi(req.nextUrl.pathname)" in src


def test_a_role_restricted_api_answers_403_where_a_page_redirects(tmp_path):
    src = _source(tmp_path)
    assert 'refuse(403, "FORBIDDEN"' in src
    assert 'NextResponse.redirect(new URL("/403", req.url))' in src, "a page still redirects"


def test_pages_still_go_to_the_sign_in_page(tmp_path):
    src = _source(tmp_path)
    assert 'pages: { signIn: "/login" }' in src


def test_the_scaffold_agrees_before_any_projection():
    scaffold = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "middleware.ts"
    text = scaffold.read_text()
    assert 'status: 401' in text and "isApi(req.nextUrl.pathname)" in text
