"""Every installable app has a public `/install` page: the link or QR code that puts it on a phone.

It is public because it is where someone who has not signed in is sent; it shows what installing is and nothing of theirs."""
from __future__ import annotations

import re
from pathlib import Path

from services.blueprint.projection import _ALWAYS_OPEN, project_middleware, project_pwa

DOC = {
    "application": {"name": "Habit Pal", "description": "A habit tracker."},
    "mobile": {"installable": True, "display": "standalone", "surface": "pwa_only"},
    "designSystem": {"colors": {"primary": "#C96A3B"}},
    "roles": [{"id": "ROLE-001", "name": "Member"}],
    "pages": [{"id": "PAGE-001", "name": "Today", "route": "/today", "access": "authenticated"}],
    "navigation": {}, "security": {}, "data": {"entities": []}, "workflows": [],
}


def test_an_installable_app_gets_the_install_page(tmp_path):
    out = project_pwa(DOC, tmp_path)
    page = tmp_path / "src" / "app" / "install" / "page.tsx"
    assert page.is_file() and "src/app/install/page.tsx" in out["files"]
    text = page.read_text(encoding="utf-8")
    for need in ("InstallButton", "isIOS", "Add to Home Screen", "QRCode", "MOBILE.installable"):
        assert need in text, need


def test_an_app_that_is_not_installable_loses_the_page(tmp_path):
    project_pwa(DOC, tmp_path)
    off = {**DOC, "mobile": {"installable": False}}
    project_pwa(off, tmp_path)
    assert not (tmp_path / "src" / "app" / "install" / "page.tsx").exists()


def test_the_install_page_is_open_to_someone_who_has_not_signed_in(tmp_path):
    assert "install" in _ALWAYS_OPEN
    project_middleware(DOC, tmp_path)
    src = (tmp_path / "src" / "middleware.ts").read_text(encoding="utf-8")
    matcher = re.search(r'matcher:\s*\["(.+?)"\]', src).group(1)
    gate = re.compile(matcher.replace("\\\\", "\\"))
    assert not gate.match("/install")
    assert gate.match("/today"), "a real page is still gated"


def test_the_scaffold_agrees_before_any_projection():
    scaffold = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "middleware.ts"
    assert "offline(?:/|$)|install(?:/|$)|api/auth(?:/|$)" in scaffold.read_text(encoding="utf-8")
