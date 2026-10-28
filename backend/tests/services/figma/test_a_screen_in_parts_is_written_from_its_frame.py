"""A screen written in parts is still written from the frame a person drew.

The first live Figma run showed it: Browse, My Borrows and Profile were each cut into parts (their template
layouts have sections), and `compose_page` handed them to `compose_screen`, which never received the reference.
So the writer asked for its own plan and the drawn frame was not shown to anyone."""
from __future__ import annotations

import json

from services.blueprint import ui_engineer as ue

REF = {"html": 'FRAME "Browse" 1257x982 row\n  TEXT "Find tools near you" 28/700', "format": "figma-outline",
       "frame": "Community Tool Sharing Platform", "tokens": "- colour brand/primary: #1f4d36",
       "size": [1257, 982], "previewUrl": "", "designId": "2:2", "reused": True}

DOC = {"application": {"name": "ToolShare"}, "pages": [{"id": "PAGE-001", "name": "Browse", "route": "/browse",
                                                         "pattern": "entity_list"}],
       "data": {"entities": []}, "workflows": []}
PAGE = DOC["pages"][0]
PART = {"key": "tools", "component": "ToolsPart", "label": "Tools", "sections": [], "workflows": []}


def test_the_frame_writer_is_shown_the_drawing_when_there_is_one():
    shown = ue.frame_prompt(DOC, PAGE, [PART], reference=REF)
    assert "A Figma frame drawn for this page" in shown and 'TEXT "Find tools near you"' in shown
    assert "THE FRAME IS THE DECISION" in shown
    bare = ue.frame_prompt(DOC, PAGE, [PART])
    assert "Figma frame" not in bare, "a screen with no drawing is asked for exactly as before"


def test_each_part_writer_is_shown_the_drawing_and_told_to_write_only_its_region():
    shown = ue.part_prompt(DOC, PAGE, PART, "export async function load() { return {}; }", reference=REF)
    assert "A Figma frame drawn for this page" in shown
    assert "Write ONLY the region that shows the sections above" in shown
    assert "Figma frame" not in ue.part_prompt(DOC, PAGE, PART, "export async function load() { return {}; }")


def test_a_ux_pilot_drawing_is_shown_to_a_screen_in_parts_the_same_way():
    ux = {"html": "<h1>Tasks</h1>", "previewUrl": "https://ux/p.png", "designId": "d1", "reused": False}
    shown = ue.frame_prompt(DOC, PAGE, [PART], reference=ux)
    assert "A design for this page, drawn by a designer" in shown and "<h1>Tasks</h1>" in shown


def test_compose_page_gives_the_reference_to_the_screen_written_in_parts(monkeypatch, tmp_path):
    import services.blueprint.screen_parts as sp

    seen = {}
    monkeypatch.setattr(sp, "screen_parts", lambda doc, page: [PART])
    monkeypatch.setattr(ue, "compose_screen", lambda *a, **k: (seen.update(k) or ({}, [])))
    ue.compose_page(DOC, PAGE, tmp_path, lambda **_: "{}", reference=REF)
    assert seen["reference"] is REF
    seen.clear()
    ue.compose_page(DOC, PAGE, tmp_path, lambda **_: "{}", reference=REF, relayout_of={"view": "x", "load": "y"})
    assert seen["reference"] is None, "a re-layout of a page that exists is not a first write from a drawing"


def test_a_screen_in_parts_with_a_drawing_skips_the_planning_call(monkeypatch, tmp_path):
    asked = []

    def planner(*a, **k):
        asked.append("plan")
        return {"state": "x"}

    monkeypatch.setattr(ue, "_page_plan", planner)
    monkeypatch.setattr(ue, "typecheck", lambda *a, **k: ["stop here"])        # end the run at the first compile
    prompts = []

    def client(*, system, user, schema=None, **_):
        prompts.append(user)
        return json.dumps({"load": "x", "view": "y"})

    for ref in (REF, None):
        asked.clear()
        prompts.clear()
        try:
            ue.compose_screen(DOC, PAGE, tmp_path, client, [PART], reference=ref)
        except ue.CompileError:
            pass
        assert (asked == []) is (ref is not None), "the drawing is the plan: no planning call with one, one without"
        assert any("A Figma frame drawn" in p for p in prompts) is (ref is not None)
