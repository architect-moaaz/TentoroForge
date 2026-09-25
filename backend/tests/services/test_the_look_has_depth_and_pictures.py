"""A design has a harmony, a gradient and its photographs — and pages know where each goes.

Every generated app had a light neutral ground and flat surfaces: the design
agent was told "not white" and nothing about harmony, tinted neutrals, a dark
ground or depth, and no picture reached a page unless a template carried a
stock URL. Now the design agent names the harmony it uses, tints the
neutrals, may choose a dark ground, states a two-stop brand gradient, and
names the photographs by job; the `imagery` service finds and credits them
on Unsplash (with a key), the projection emits the gradient, the contrast
guard reads text at both stops, and the page author is told the three homes
of the gradient and how to show a photograph with its credit.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint.executors import NODE_TASKS
from services.blueprint.imagery import UNSPLASH_KEY_ENV, fill_imagery, find_photo, imagery_brief
from services.blueprint.orchestrator import DAG, SERVICE_HANDLERS, levels
from services.blueprint.projection import project_design_tokens, resolved_palette
from services.blueprint.ui_engineer import DESIGN_PRINCIPLES, _look
from services.blueprint.verification import (
    OPTIONAL_PALETTE_ROLES, PALETTE_ROLES, check_palette_contrast, check_palette_roles,
)

ROOT = Path(__file__).resolve().parents[2]

FOREST = {
    "background": "#F4F1EA", "surface": "#FFFFFF", "textPrimary": "#1F2A24", "textSecondary": "#5C6B63",
    "primary": "#1B4332", "accent": "#C97B3D", "accentSubtle": "#F6E7DA", "inverse": "#14261D",
}


def _doc(colors=None, imagery=None):
    return {"application": {"name": "Tool Share", "domain": "community"},
            "designSystem": {"colors": colors or dict(FOREST), "imagery": imagery or [],
                             "visualPersonality": "warm, practical"}, "pages": []}


# --- the design agent is asked for all three -----------------------------------

def test_the_designer_is_asked_for_a_harmony_a_gradient_and_pictures():
    task = NODE_TASKS["design_system"]
    for phrase in ("NAME THE HARMONY", "split-complementary", "NEUTRALS ARE TINTED", "60/30/10",
                   "THE GROUND CAN BE DARK", "`gradientStart`", "`gradientEnd`", "20-40°",
                   "`imagery`", "`auth`", "`hero`", "`empty`", "Leave `url` empty"):
        assert phrase in task, phrase


def test_the_gradient_roles_are_jobs_a_palette_may_leave_out():
    assert {"gradientStart", "gradientEnd"} <= set(PALETTE_ROLES)
    assert OPTIONAL_PALETTE_ROLES == {"gradientStart", "gradientEnd"}
    assert check_palette_roles(_doc()) == []                       # FOREST names no gradient


def test_the_contract_carries_imagery():
    schema = json.loads((ROOT / "contracts" / "blueprint.schema.json").read_text())
    imagery = schema["properties"]["designSystem"]["properties"]["imagery"]
    item = imagery["items"]
    assert item["properties"]["role"]["enum"] == ["auth", "hero", "empty"]
    assert set(item["properties"]) >= {"query", "alt", "url", "thumbUrl", "credit"}


# --- the gradient reaches the app, and is read at both ends --------------------

def test_the_gradient_is_projected_with_fallbacks(tmp_path):
    project_design_tokens(_doc(), tmp_path)
    css = (tmp_path / "src/app/tokens.css").read_text()
    assert ".bg-brand-gradient {" in css and ".text-brand-gradient {" in css
    assert "var(--gradient-start, var(--primary))" in css and "var(--gradient-end, var(--accent))" in css
    assert "--gradient-start:" not in css, "a design that states no gradient sets no stop"
    project_design_tokens(_doc(dict(FOREST, gradientStart="#1B4332", gradientEnd="#2D5A4A")), tmp_path)
    css = (tmp_path / "src/app/tokens.css").read_text()
    assert "--gradient-start:" in css and "--gradient-end:" in css and "--gradient-foreground:" in css
    tw = (ROOT / "templates/app-foundation/tailwind.config.ts").read_text()
    assert '"gradient-start": "hsl(var(--gradient-start, var(--primary)))"' in tw
    assert '"gradient-end": "hsl(var(--gradient-end, var(--accent)))"' in tw


def test_text_on_the_gradient_is_checked_at_both_stops():
    dark_pair = dict(FOREST, gradientStart="#1B4332", gradientEnd="#2D5A4A")
    assert [f for f in check_palette_contrast(_doc(dark_pair)) if "gradient" in f.artifact_id] == []
    pale_end = dict(FOREST, gradientStart="#1B4332", gradientEnd="#CFE8DA")   # light text vanishes here
    findings = [f for f in check_palette_contrast(_doc(pale_end)) if "gradient" in f.artifact_id]
    assert findings and "second stop" in findings[0].detail
    pal = resolved_palette(_doc(dark_pair))
    assert "gradient-foreground" in pal


# --- the pictures are found, credited, kept, and absent without a key ----------

PHOTO = {"results": [{"urls": {"raw": "https://images.unsplash.com/photo-1?ixid=abc", "small": "https://images.unsplash.com/photo-1?w=400"},
                      "user": {"name": "Ana Reyes", "links": {"html": "https://unsplash.com/@ana"}},
                      "links": {"download_location": "https://api.unsplash.com/photos/1/download?ixid=abc"}}]}


def _fake(calls):
    def get(path, params):
        calls.append((path, dict(params)))
        return PHOTO if path == "/search/photos" else {}
    return get


def test_a_photo_is_found_sized_and_credited_and_its_use_registered():
    calls: list = []
    photo = find_photo("neighbours sharing garden tools", _fake(calls))
    assert photo["url"].startswith("https://images.unsplash.com/photo-1?ixid=abc&w=1800")
    assert photo["credit"] == {"name": "Ana Reyes", "link": "https://unsplash.com/@ana?utm_source=tentoro_forge&utm_medium=referral"}
    assert calls[0] == ("/search/photos", {"query": "neighbours sharing garden tools", "per_page": "1",
                                           "orientation": "landscape", "content_filter": "high"})
    assert calls[1][0].startswith("/photos/1/download")             # the licence's courtesy call


def test_the_service_fills_what_is_empty_and_keeps_what_was_found():
    doc = _doc(imagery=[{"role": "auth", "query": "tools", "alt": "a shed"},
                        {"role": "hero", "query": "x", "url": "https://images.unsplash.com/kept", "credit": {"name": "K", "link": "l"}}])
    out = fill_imagery(doc, _fake([]))
    assert (out["found"], out["kept"], out["empty"]) == (1, 1, 0)
    auth, hero = doc["designSystem"]["imagery"]
    assert auth["url"].startswith("https://images.unsplash.com/photo-1") and auth["credit"]["name"] == "Ana Reyes"
    assert hero["url"] == "https://images.unsplash.com/kept", "a rebuild does not re-roll a picture"


def test_without_a_key_nothing_is_fetched_and_the_run_carries_on(monkeypatch):
    monkeypatch.delenv(UNSPLASH_KEY_ENV, raising=False)
    doc = _doc(imagery=[{"role": "auth", "query": "tools"}])
    out = fill_imagery(doc)
    assert out["found"] == 0 and out["empty"] == 1 and UNSPLASH_KEY_ENV in out["why"]
    assert doc["designSystem"]["imagery"][0].get("url", "") == ""
    assert "use the brand gradient" in imagery_brief(doc)


def test_a_failed_search_costs_one_picture_not_the_run():
    def boom(path, params):
        raise RuntimeError("503")
    doc = _doc(imagery=[{"role": "auth", "query": "tools"}, {"role": "hero", "query": "x"}])
    out = fill_imagery(doc, boom)
    assert out["empty"] == 2 and out["found"] == 0


# --- the node sits between the design and the page authors ----------------------

def test_the_imagery_node_runs_after_the_design_and_before_the_page_authors():
    node = DAG["imagery"]
    assert node.kind == "service" and node.depends_on == {"design_system"} and "designSystem" in node.produces
    assert "imagery" in DAG["ui_direction"].depends_on
    order = {k: i for i, lvl in enumerate(levels()) for k in lvl}
    assert order["design_system"] < order["imagery"] < order["ui_direction"] < order["page_code"]
    assert SERVICE_HANDLERS["imagery"].__name__ == "_find_imagery"


# --- the page author is told where each goes -----------------------------------

def test_the_page_author_knows_the_gradients_three_homes_and_how_to_credit_a_photo():
    for phrase in ("THE GRADIENT HAS THREE HOMES", "bg-brand-gradient", "sign-in\n  page's brand panel",
                   "Never behind body text", "PHOTOGRAPHS, WHERE THEY EARN THEIR PLACE", "object-cover",
                   "on Unsplash", "never one from another host"):
        assert phrase in DESIGN_PRINCIPLES, phrase


def test_the_look_carries_the_gradient_and_the_pictures_with_credits():
    doc = _doc(dict(FOREST, gradientStart="#1B4332", gradientEnd="#2D5A4A"),
               imagery=[{"role": "auth", "query": "tools", "alt": "A shared shed",
                         "url": "https://images.unsplash.com/p?w=1800", "credit": {"name": "Ana Reyes", "link": "https://unsplash.com/@ana"}}])
    look = _look(doc)
    assert "bg-brand-gradient (#1B4332 → #2D5A4A)" in look
    assert 'auth: src="https://images.unsplash.com/p?w=1800" alt="A shared shed" — Photo by Ana Reyes' in look
    assert "No photographs" in _look(_doc())


def test_the_app_may_load_pictures_from_unsplash():
    cfg = (ROOT / "templates/standalone-app/next.config.js").read_text()
    assert 'hostname: "images.unsplash.com"' in cfg and 'hostname: "localhost"' in cfg
