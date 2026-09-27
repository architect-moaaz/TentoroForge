"""A page made public is served on the public side and listed on its menu.

Test2, 2026-09-28: "make Location Explorer public" set the page public and
re-projected the gate, and left its files inside `(dashboard)` — behind a
login the app does not have — and off the public menu every other page is
on. The access change now moves the page and lists it, as a build would.
"""
from pathlib import Path

from services.blueprint.app_sdk import project_code_pages
from services.blueprint.service import BlueprintService
from services.smith import access_change

VIEW = '"use client";\nexport default function View() { return <div />; }\n'
LOAD = 'import type { PageContext } from "@/sdk/server";\nexport async function load(ctx: PageContext) { return {}; }\n'


def test_a_coded_page_made_public_moves_out_of_the_signed_in_area(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Test2", domain="ops")
    svc.doc["security"] = {"authentication": "none"}
    svc.doc["pages"] = [
        {"id": "PAGE-001", "name": "Register", "route": "/register", "purpose": "x", "access": "public"},
        {"id": "PAGE-005", "name": "Location Explorer", "route": "/location-explorer", "purpose": "x"},
    ]
    svc.doc["pageCode"] = [{"page": p, "rationale": "", "load": LOAD, "view": VIEW}
                           for p in ("PAGE-001", "PAGE-005")]
    svc.save()
    app = tmp_path / "app"
    project_code_pages(svc.doc, app)
    inside = app / "src/app/(dashboard)/location-explorer/page.tsx"
    assert inside.is_file(), "signed-in by default: inside the group"

    svc.doc["pages"][1]["access"] = "public"
    files = access_change._project(svc, str(app))

    assert (app / "src/app/location-explorer/page.tsx").is_file()
    assert not inside.exists(), "one page per address — the old copy is swept"
    nav = (app / "src/contracts/public-nav.ts").read_text()
    assert "/location-explorer" in nav and "/register" in nav
    assert "src/contracts/public-nav.ts" in files


def test_smith_brings_an_app_that_drifted_back_in_step_with_its_definition(tmp_path):
    """The state Test2 was left in: the Blueprint says public, the files say
    signed-in. "Make it public" has nothing to change and "I still cannot see
    it" found the page in the menu file it read; `sync_app` writes the app out
    again and names what was out of step — and says so when nothing was."""
    from services.smith import sync_app

    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Test2", domain="ops")
    svc.doc["security"] = {"authentication": "none"}
    svc.doc["pages"] = [
        {"id": "PAGE-001", "name": "Register", "route": "/register", "purpose": "x", "access": "public"},
        {"id": "PAGE-005", "name": "Location Explorer", "route": "/location-explorer", "purpose": "x"},
    ]
    svc.doc["pageCode"] = [{"page": p, "rationale": "", "load": LOAD, "view": VIEW}
                           for p in ("PAGE-001", "PAGE-005")]
    svc.save()
    app = tmp_path / "app"
    project_code_pages(svc.doc, app)                  # written while it was signed-in
    (app / "package.json").write_text("{}")
    svc.doc["pages"][1]["access"] = "public"          # …then made public, files left behind
    svc.save()

    out = sync_app.run(str(tmp_path))

    assert out["applied"]
    assert (app / "src/app/location-explorer/page.tsx").is_file()
    assert not (app / "src/app/(dashboard)/location-explorer/page.tsx").exists()
    assert "/location-explorer" in (app / "src/contracts/public-nav.ts").read_text()
    assert "out of step" in out["diff_summary"] and "src/contracts/public-nav.ts" in out["edited_paths"]
    again = sync_app.run(str(tmp_path))
    assert again["edited_paths"] == [] and "already matches" in again["diff_summary"]


def test_an_app_not_yet_built_has_nothing_to_bring_in_step(tmp_path):
    from services.smith import sync_app
    BlueprintService.create(output_dir=tmp_path, app_id="t", name="T", domain="ops")
    out = sync_app.run(str(tmp_path))
    assert not out["applied"] and "not been built" in out["reason"]
