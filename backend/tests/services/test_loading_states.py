"""A navigation shimmers the page area, not the whole window.

The root `loading.tsx` replaces the entire window — sidebar included — with a full-screen
card on every route change. The signed-in shell has its own, and each coded page ships one
shaped like itself."""
from pathlib import Path

import pytest

from services.blueprint import app_sdk

TEMPLATES = Path(app_sdk.__file__).resolve().parents[2] / "templates" / "app-foundation" / "src"


def _doc():
    pages = [
        {"id": "PAGE-001", "name": "Library", "route": "/library", "pattern": "entity_list", "status": "PROPOSED"},
        {"id": "PAGE-002", "name": "Stats", "route": "/stats", "pattern": "dashboard", "status": "PROPOSED"},
        {"id": "PAGE-003", "name": "Book", "route": "/books/[id]", "pattern": "record_workspace", "status": "PROPOSED"},
        {"id": "PAGE-004", "name": "Add", "route": "/books/new", "pattern": "form", "status": "PROPOSED"},
        {"id": "PAGE-005", "name": "Sign In", "route": "/login", "pattern": "auth", "status": "PROPOSED"},
        {"id": "PAGE-006", "name": "Home", "route": "/", "pattern": "dashboard", "status": "PROPOSED"},
    ]
    code = [{"page": p["id"], "load": "export async function load() { return {}; }\n",
             "view": '"use client";\nexport default function View() { return null; }\n'} for p in pages]
    return {"pages": pages, "pageCode": code, "data": {"entities": []}, "workflows": [], "application": {}}


@pytest.mark.parametrize("pattern,route,shape", [
    ("entity_list", "/a", "list"), ("dashboard", "/a", "dashboard"), ("record_workspace", "/a/[id]", "record"),
    ("form", "/a/new", "form"), ("something_new", "/a/[id]", "record"), ("something_new", "/a", "default"),
])
def test_a_page_is_drawn_as_its_pattern(pattern, route, shape):
    assert app_sdk.skeleton_for({"pattern": pattern, "route": route}) == shape


def test_a_coded_page_ships_a_loading_state_shaped_like_itself():
    doc = _doc()
    row = next(r for r in doc["pageCode"] if r["page"] == "PAGE-001")
    files = app_sdk.code_page_files(doc, row)
    loading = next(content for rel, content in files.items() if rel.endswith("/loading.tsx"))
    assert 'pattern="list"' in loading and "PageSkeleton" in loading
    assert loading.startswith(app_sdk.CODE_PAGE_MARKER)


def test_the_root_page_and_the_sign_in_pages_get_none():
    doc = _doc()
    for page_id in ("PAGE-005", "PAGE-006"):
        row = next(r for r in doc["pageCode"] if r["page"] == page_id)
        if page_id == "PAGE-006":
            doc["pages"][5]["route"] = "/"
        files = app_sdk.code_page_files(doc, row)
        assert not any(rel.endswith("/loading.tsx") for rel in files), page_id


def test_loading_files_are_written_and_removed_with_their_page(tmp_path):
    doc = _doc()
    app_sdk.project_code_pages(doc, tmp_path)
    loading = tmp_path / app_sdk.code_page_dir(doc["pages"][0]) / "loading.tsx"
    assert loading.is_file()
    doc["pageCode"] = [r for r in doc["pageCode"] if r["page"] != "PAGE-001"]
    app_sdk.project_code_pages(doc, tmp_path)
    assert not loading.exists(), "a removed page must not leave its loading state behind"


def test_the_scaffold_has_a_shell_level_loading_state():
    assert (TEMPLATES / "components" / "PageSkeleton.tsx").is_file()
    shell = (TEMPLATES / "app" / "(dashboard)" / "loading.tsx").read_text("utf-8")
    assert "PageSkeleton" in shell
    skeleton = (TEMPLATES / "components" / "PageSkeleton.tsx").read_text("utf-8")
    import re

    assert not re.search(r"#[0-9a-fA-F]{3,6}\b", skeleton), "token classes only: a hex colour here would be the design's"


def test_plain_anchors_in_the_shell_navigate_softly():
    """The rail and top bar are server-rendered `<a href>`. Unless the shell turns their clicks
    into router navigations every click is a full document load, and the root loading card
    covers the window until the signed-in layout has resolved again."""
    source = (TEMPLATES / "components" / "AppNavigator.tsx").read_text("utf-8")
    assert 'document.addEventListener("click"' in source
    assert "router.push(href)" in source
    assert "e.defaultPrevented" in source, "next/link already handles its own clicks"
    assert "(api|_next)" in source, "an API route or an asset is never a page"
