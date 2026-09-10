"""nav-flow entry point + redirects derive from authGating."""
import json

from services.nav_flow_emitter import emit_nav_flow


def _emit(tmp_path, plan):
    emit_nav_flow(str(tmp_path), plan)
    return json.loads((tmp_path / "src" / "contracts" / "nav-flow.json").read_text(encoding="utf-8"))


def test_gated_app_enters_at_login(tmp_path):
    plan = {"authGated": True, "pages": [
        {"route": "/login", "name": "Login", "type": "auth"},
        {"route": "/signup", "name": "Sign Up", "type": "auth"},
        {"route": "/orders", "name": "Orders"},
    ]}
    nav = _emit(tmp_path, plan)
    assert nav["authGated"] is True
    assert nav["initialPage"] == "login"
    assert nav["post_logout_redirect"] == "/login"
    assert nav["post_login_redirect"] == "/orders"     # first shell page
    assert "/login" in nav["auth_routes"]


def test_public_app_enters_at_first_shell_page(tmp_path):
    plan = {"authGated": False, "pages": [
        {"route": "/", "name": "Home"},
        {"route": "/about", "name": "About"},
    ]}
    nav = _emit(tmp_path, plan)
    assert nav["authGated"] is False
    assert nav["post_logout_redirect"] is None
    assert nav["auth_routes"] == []
    # entry is the first shell page (home)
    assert nav["initialPage"] == nav["pages"][0]["id"]


def test_auth_gated_inferred_from_auth_pages_without_flag(tmp_path):
    # Even if the flag is absent, presence of auth routes gates the entry.
    plan = {"pages": [
        {"route": "/login", "name": "Login", "type": "auth"},
        {"route": "/dash", "name": "Dash"},
    ]}
    nav = _emit(tmp_path, plan)
    assert nav["authGated"] is True
    assert nav["initialPage"] == "login"
    assert nav["post_logout_redirect"] == "/login"
