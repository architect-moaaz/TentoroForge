"""Login/signup brand panel must use an industry-relevant Unsplash image, resolved from
the design-spec's loginBackground (preferred) or the per-domain default."""
import json
from pathlib import Path

from services.industry_design import get_login_background
from services.runtime_injector import _resolve_login_image, _substitute_auth_image


def test_get_login_background_per_domain_and_default():
    assert "images.unsplash.com" in get_login_background("Project Management")
    assert "images.unsplash.com" in get_login_background(None)          # falls back


def test_resolve_prefers_design_spec(tmp_path):
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts" / "design-spec.json").write_text(
        json.dumps({"imagery": {"loginBackground": "https://images.unsplash.com/photo-XYZ"}}), encoding="utf-8")
    assert _resolve_login_image(tmp_path, "Healthcare") == "https://images.unsplash.com/photo-XYZ"


def test_resolve_falls_back_to_domain_when_spec_null(tmp_path):
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts" / "design-spec.json").write_text(
        json.dumps({"imagery": {"loginBackground": None}}), encoding="utf-8")
    assert _resolve_login_image(tmp_path, "Healthcare") == get_login_background("Healthcare")


def test_substitutes_placeholder(tmp_path):
    (tmp_path / "src" / "app" / "login").mkdir(parents=True)
    (tmp_path / "src" / "app" / "login" / "page.tsx").write_text('<img src="__AUTH_IMAGE_URL__" />', encoding="utf-8")
    n = _substitute_auth_image(tmp_path, "Project Management")
    assert n == 1
    assert "__AUTH_IMAGE_URL__" not in (tmp_path / "src" / "app" / "login" / "page.tsx").read_text(encoding="utf-8")
    assert "images.unsplash.com" in (tmp_path / "src" / "app" / "login" / "page.tsx").read_text(encoding="utf-8")


# --- login brand-panel copy: app-specific, not generic corporate filler ---
from services.runtime_injector import _substitute_auth_copy


def test_auth_copy_uses_app_name(tmp_path):
    login = tmp_path / "src" / "app" / "login"
    login.mkdir(parents=True)
    (login / "page.tsx").write_text(
        '<h2>__AUTH_HEADLINE__</h2><p>__AUTH_SUBHEAD__</p>'
    )
    n = _substitute_auth_copy(tmp_path, "community_sports_club")
    assert n == 1
    out = (login / "page.tsx").read_text(encoding="utf-8")
    assert "Welcome to Community Sports Club" in out
    assert "Sign in to continue to Community Sports Club." in out
    assert "__AUTH_" not in out


def test_auth_copy_falls_back_without_name(tmp_path):
    login = tmp_path / "src" / "app" / "login"
    login.mkdir(parents=True)
    (login / "page.tsx").write_text('<h2>__AUTH_HEADLINE__</h2><p>__AUTH_SUBHEAD__</p>', encoding="utf-8")
    _substitute_auth_copy(tmp_path, None)
    out = (login / "page.tsx").read_text(encoding="utf-8")
    assert "Welcome back" in out and "Sign in to continue." in out
