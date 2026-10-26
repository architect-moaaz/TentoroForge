"""Every installable app has a public `/install` page: the link or QR code that puts it on a phone.

It is public because it is where someone who has not signed in is sent; it shows what installing is and nothing of theirs."""
from __future__ import annotations

from services.blueprint.projection import project_middleware, project_pwa
from tests.services._middleware_gate import Gate

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
    project_middleware(DOC, tmp_path)
    gate = Gate(tmp_path)
    assert gate.is_public("/install")
    assert not gate.is_public("/today"), "a real page is still gated"


def test_only_the_exact_route_is_open_never_a_page_that_starts_with_the_word(tmp_path):
    """PR #28 review: `install` as a word in the matcher's lookahead opened `/installments`, `/installers` and `/installations`."""
    project_middleware(DOC, tmp_path)
    gate = Gate(tmp_path)
    for look_alike in ("/installments", "/installers", "/installations", "/install-guide", "/install/x"):
        assert not gate.is_public(look_alike), look_alike


def test_an_app_that_is_not_installable_has_no_open_install_route(tmp_path):
    project_middleware({**DOC, "mobile": {"installable": False}}, tmp_path)
    assert not Gate(tmp_path).is_public("/install"), "an app with no install page does not leave the route open"


def _owns_install(access="authenticated"):
    return {**DOC, "pages": DOC["pages"] + [{"id": "PAGE-002", "name": "Installations", "route": "/install",
                                              "access": access}]}


def test_an_apps_own_install_page_wins_and_stays_behind_sign_in(tmp_path):
    """PR #28 review: the platform's page replaced an app's own `/install`
    (a field-service app's installations) and opened it to signed-out
    visitors. The app's page wins; the platform's stands aside."""
    project_pwa(DOC, tmp_path)                                   # the platform's page was there
    project_pwa(_owns_install(), tmp_path)
    assert not (tmp_path / "src" / "app" / "install" / "page.tsx").exists(), "the catch-all renders the app's page"
    project_middleware(_owns_install(), tmp_path)
    assert not Gate(tmp_path).is_public("/install"), "the app's page keeps its own access"
    project_middleware(_owns_install("public"), tmp_path)
    assert Gate(tmp_path).is_public("/install"), "…and is open when it says so"


def test_an_apps_own_file_at_the_path_is_never_removed(tmp_path):
    page = tmp_path / "src" / "app" / "install" / "page.tsx"
    page.parent.mkdir(parents=True)
    page.write_text("export default function Installations() { return null; }\n")
    project_pwa(_owns_install(), tmp_path)
    project_pwa({**DOC, "mobile": {"installable": False}}, tmp_path)
    assert page.read_text().startswith("export default function Installations"), "only the platform's page is removed"


def test_the_scaffolds_copy_is_removed_from_an_app_that_is_not_installable(tmp_path):
    from pathlib import Path
    scaffold = Path(__file__).resolve().parents[2] / "templates" / "app-foundation" / "src" / "app" / "install" / "page.tsx"
    page = tmp_path / "src" / "app" / "install" / "page.tsx"
    page.parent.mkdir(parents=True)
    page.write_text(scaffold.read_text())                        # what the scaffold copies into every app
    project_pwa({**DOC, "mobile": {"installable": False}}, tmp_path)
    assert not page.exists()
