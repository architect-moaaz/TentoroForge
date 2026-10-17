"""The Pages & Nav tab read `src/schemas`, `src/contracts` and `app-model.json`
at the project's root; a Blueprint app keeps its tree under `app/`, so the tab
drew an empty canvas for every one of them (Mark 8 on forge-v3, 2026-10-17).
It is drawn from the Blueprint now: live pages, where pages lead and how the
flows move between them, and the menu."""
from __future__ import annotations

from services.blueprint.ids import page_key
from services.blueprint.service import BlueprintService
from routers.navigation import _build_nav_from_app_model


def _app(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Mark 8", domain="tools")
    calc = s.upsert("pages", {"name": "Calculator", "route": "/", "pattern": "tool", "purpose": "Quick arithmetic.",
                              "primaryTasks": [], "entry": True}, natural_key=page_key("/"))
    tax = s.upsert("pages", {"name": "Tax", "route": "/tax", "pattern": "tool", "purpose": "Indian income tax.",
                             "primaryTasks": []}, natural_key=page_key("/tax"))
    gone = s.upsert("pages", {"name": "Old", "route": "/old", "pattern": "tool", "purpose": "Retired.", "primaryTasks": []},
                    natural_key=page_key("/old"))
    gone["status"] = "DEPRECATED"
    calc["navigatesTo"] = [tax["id"]]
    s.doc["flows"] = [{"id": "JOURNEY-001", "name": "Work Out Tax", "steps": [
        {"page": calc["id"], "does": "opens the tax screen"}, {"page": tax["id"], "does": "enters income"}]}]
    s.doc["navigation"] = {"initialRoute": {"default": "/"},
                           "tree": [{"label": "Calculator", "page": calc["id"]}, {"label": "Tax", "page": tax["id"]}]}
    s.save()
    return s


def test_a_blueprint_app_is_drawn_from_its_blueprint(tmp_path):
    _app(tmp_path)
    nav = _build_nav_from_app_model(str(tmp_path))
    assert [(x["data"]["label"], x["data"]["route"]) for x in nav["screens"]] == [("Calculator", "/"), ("Tax", "/tax")]
    assert nav["screens"][0]["data"]["isHome"] is True and nav["defaultScreen"] == "screen_0"
    # One arrow Calculator → Tax, however many places say so.
    assert [(e["source"], e["target"]) for e in nav["edges"]] == [("screen_0", "screen_1")]
    assert [(l["label"], l["route"]) for l in nav["sidebarLinks"]] == [("Calculator", "/"), ("Tax", "/tax")]


def test_a_project_with_no_blueprint_still_uses_the_old_readers(tmp_path):
    assert _build_nav_from_app_model(str(tmp_path)) == {"screens": [], "edges": [], "sidebarLinks": [], "topbarLinks": []}
