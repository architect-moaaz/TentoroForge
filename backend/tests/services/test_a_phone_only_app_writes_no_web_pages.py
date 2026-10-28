"""A phone-only app has no website: the frontend projection writes no content pages for it, and sweeps away any left over.

Cart Buddy's live address served a Shopping List table. Not writing the layouts was not enough: a page with no layout gets a
"not laid out yet" placeholder, and a schema composed on an earlier run is kept on purpose. And the count of "pages served"
reported the web pages it never meant to have as missing."""
from __future__ import annotations

import json
from pathlib import Path

from services.blueprint import assembly, projection

PAGES = [
    {"id": "PAGE-001", "name": "Shopping List", "route": "/", "pattern": "list", "access": "authenticated"},
    {"id": "PAGE-002", "name": "Bought", "route": "/bought", "pattern": "list", "access": "authenticated"},
]


def doc(surface=None):
    d = {"pages": [dict(p) for p in PAGES], "pageLayouts": [], "data": {"entities": []}, "workflows": []}
    if surface:
        d["mobile"] = {"surface": surface}
    return d


def schemas(root: Path) -> set[str]:
    return {p.name for p in (root / "src" / "schemas").glob("*.json")}


def test_a_phone_only_app_gets_no_content_page_and_the_old_ones_go(tmp_path):
    old = tmp_path / "src" / "schemas"
    old.mkdir(parents=True)
    (old / "home.json").write_text(json.dumps({"id": "PAGE-001", "meta": {}}), "utf-8")
    projection.project_frontend(doc("native_only"), tmp_path)
    assert schemas(tmp_path) == set()


def test_every_other_choice_still_gets_its_pages(tmp_path):
    projection.project_frontend(doc("web_native"), tmp_path)
    assert schemas(tmp_path)          # something was written for the pages


def test_a_phone_only_app_plans_no_web_routes(tmp_path):
    funnel = assembly.page_funnel(doc("native_only"), tmp_path)
    assert funnel["planned"] == 0 and funnel["missing"] == []


def test_a_web_app_still_counts_its_missing_pages(tmp_path):
    funnel = assembly.page_funnel(doc("web"), tmp_path)
    assert funnel["planned"] == 2 and set(funnel["missing"]) == {"/", "/bought"}


def test_a_phone_only_apps_front_door_is_the_sign_in_page():
    assert projection._entry_route(doc("native_only")) == "/login"
    assert projection._entry_route(doc("web")) == ""        # a web app has a page at "/", which the catch-all serves
