"""A design connected as the specification is built as drawn, a page per job.

Three gaps stood between a large drawn file (D3 of one real file: 145 frames,
about sixty pages) and an app that looks like it:

* every frame became a page, so a job's "Pause" dialog, each step of the
  create-job wizard and each state of the search screen had routes of their
  own — the prototype's own links, which say what opens over what, were read
  file-wide and never per screen;
* the React page writer was told the frame was "the decision, not its
  numbers", saw no picture of it, and its look was held to taste, not to the
  drawing;
* the corners, spacing, body text and the file's named styles never reached
  the design system.

Now each frame records its prototype links; the page set places every frame
as a page or as a tab, panel, drawer, dialog, step or state of one
(`pages[].frames`); the writer is shown every frame of its page with the exact
values they are drawn with and told to reproduce them; the look puts the page
beside the drawing; and the drawn scales become tokens.
"""
from __future__ import annotations

import json

import pytest

from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidFramePlacement, check_frame_placement,
)
from services.figma import react_reference as fr
from services.figma import store
from services.figma.reference import DesignReference, ScreenRef, screen_links
from services.figma.url import FigmaTarget

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="


def _text(chars, size=14, weight=400, line=20, fill=(0.07, 0.09, 0.15), style_id=None):
    return {"type": "TEXT", "name": chars, "characters": chars,
            "style": {"fontFamily": "Inter", "fontSize": size, "fontWeight": weight, "lineHeightPx": line},
            "fills": [{"type": "SOLID", "color": dict(zip("rgb", fill))}],
            **({"styles": {"text": style_id}} if style_id else {})}


def _job(node="1:1"):
    """A job page whose "Pause" button opens 1:2 as an overlay and "Back" navigates to 1:3."""
    return {
        "id": node, "type": "FRAME", "name": "L-10 · Job workspace", "absoluteBoundingBox": {"width": 1440, "height": 1024},
        "layoutMode": "VERTICAL", "itemSpacing": 16, "paddingTop": 24, "paddingLeft": 24, "cornerRadius": 10,
        "fills": [{"type": "SOLID", "color": {"r": 0.97, "g": 0.98, "b": 0.99}}],
        "_styles": {"S:1": {"name": "Primary/600", "styleType": "FILL"}, "S:2": {"name": "Body/Regular", "styleType": "TEXT"}},
        "children": [
            _text("Senior Nurse ICU", 24, 700, 32),
            {"id": "9:1", "type": "INSTANCE", "name": "Button", "cornerRadius": 10, "layoutMode": "HORIZONTAL",
             "itemSpacing": 8, "paddingTop": 8, "paddingLeft": 16, "styles": {"fill": "S:1"},
             "fills": [{"type": "SOLID", "color": {"r": 0.06, "g": 0.46, "b": 0.43}}],
             "interactions": [{"trigger": {"type": "ON_CLICK"},
                               "actions": [{"type": "NODE", "destinationId": "1:2", "navigation": "OVERLAY"}]}],
             "children": [_text("Pause", style_id="S:2")]},
            {"id": "9:2", "type": "TEXT", "name": "back", "characters": "Back to jobs", "style": {"fontSize": 14},
             "interactions": [{"trigger": {"type": "ON_CLICK"},
                               "actions": [{"type": "NODE", "destinationId": "1:3", "navigation": "NAVIGATE"}]}]},
            *[{"type": "FRAME", "name": f"card {i}", "cornerRadius": 10, "layoutMode": "VERTICAL",
               "itemSpacing": 12, "paddingTop": 16, "paddingLeft": 16, "children": [_text(f"Row {i}")]}
              for i in range(3)],
        ],
    }


def _dialog():
    return {"id": "1:2", "type": "FRAME", "name": "L-06 · Pause a live job", "absoluteBoundingBox": {"width": 1440, "height": 1024},
            "children": [_text("Pause this job?", 18, 600, 24),
                         {"id": "9:3", "type": "TEXT", "name": "x", "characters": "Cancel",
                          "interactions": [{"actions": [{"destinationId": "1:1", "navigation": "SWAP"}]}]}]}


def _list():
    return {"id": "1:3", "type": "FRAME", "name": "L-12 · Jobs list", "absoluteBoundingBox": {"width": 1440, "height": 1024},
            "children": [_text("Jobs", 24, 700, 32)]}


def _connect(tmp_path, treat_as="specification"):
    from services.blueprint.service import BlueprintService
    from services.figma.reference import _attach_structure

    ref = DesignReference(target=FigmaTarget(file_key="zYxW9876VuTs", node_id=""))
    for doc in (_job(), _dialog(), _list()):
        ref.screens.append(ScreenRef(node_id=doc["id"], name=doc["name"], width=1440, height=1024, image=PNG))
        _attach_structure(ref, ref.screens[-1], [{"type": "structured", "data": doc}])
    svc = BlueprintService.create(output_dir=str(tmp_path), app_id="d3", name="Desk", domain="unknown",
                                  description="hire nurses")
    store.save(ref, tmp_path)
    store.connect(svc, ref, name="D3", treat_as=treat_as)
    svc.save()
    return svc


# -- the prototype's links, per frame -------------------------------------------

def test_a_screen_says_what_it_opens_and_from_which_button():
    links = screen_links(_job())
    assert {"to": "1:2", "kind": "overlay", "via": "Pause"} in links
    assert {"to": "1:3", "kind": "navigate", "via": "Back to jobs"} in links


def test_the_frame_record_keeps_links_to_the_designs_own_screens_only(tmp_path):
    frames = {f["nodeId"]: f for f in _connect(tmp_path).doc["designSources"][0]["frames"]}
    assert [l["kind"] for l in frames["1:1"]["links"]] == ["overlay", "navigate"]
    assert frames["1:2"]["links"] == [{"to": "1:1", "kind": "swap", "via": "Cancel"}]
    assert "links" not in frames["1:3"]


# -- the page set places frames ---------------------------------------------------

def test_a_slot_says_which_frames_open_it_and_the_prompt_asks_for_placement(tmp_path):
    from services.blueprint.page_planner import page_slot_prompt, page_slots

    doc = _connect(tmp_path).doc
    slots = {s["figmaFrame"]: s for s in page_slots(doc)}
    assert slots["1:2"]["openedFrom"] == [{"from": "1:1", "kind": "overlay", "via": "Pause"}]
    assert slots["1:1"]["links"][0] == {"to": "1:2", "kind": "overlay", "via": "Pause"}
    prompt = page_slot_prompt(doc)
    assert "PLACE EVERY DRAWN FRAME" in prompt and "`frames`" in prompt
    assert "One page per frame" not in prompt


def test_a_file_wired_only_with_navigation_still_says_what_leads_where(tmp_path):
    """One real file's 568 links were all `navigate`: the control that leads to
    a frame is its evidence then."""
    from services.blueprint.page_planner import REACHED_SHOWN, frame_slots

    slots = {s["figmaFrame"]: s for s in page_slots_of(_connect(tmp_path).doc)}
    assert slots["1:3"]["reachedFrom"] == [{"from": "1:1", "via": "Back to jobs"}]
    hub = [{"nodeId": f"{i}:9", "name": f"F{i}", "links": [{"to": "0:0", "kind": "navigate", "via": "Home"}]}
           for i in range(1, 8)] + [{"nodeId": "0:0", "name": "Home"}]
    home = next(s for s in frame_slots(hub) if s["figmaFrame"] == "0:0")
    assert len(home["reachedFrom"]) == REACHED_SHOWN and home["reachedFromCount"] == 7


def page_slots_of(doc):
    from services.blueprint.page_planner import page_slots
    return page_slots(doc)


def test_frames_the_prototype_ties_together_are_declared_in_one_part():
    from services.blueprint.page_planner import _packed

    slots = [{"figmaFrame": f"{i}:1", **({"links": [{"to": "44:1", "kind": "overlay"}]} if i == 1 else {})}
             for i in range(45)]
    parts = _packed(slots, 40)
    with_dialog = next(p for p in parts if any(s["figmaFrame"] == "44:1" for s in p))
    assert any(s["figmaFrame"] == "1:1" for s in with_dialog)
    assert sum(len(p) for p in parts) == 45 and all(len(p) <= 40 for p in parts)


def _pages(*bodies):
    return AgentResult(task_id="t", agent="page_design", proposals=[
        ArtifactProposal(section="pages", natural_key=b["route"], body=b) for b in bodies])


def test_a_frame_is_built_once_and_only_frames_the_design_has(tmp_path):
    doc = _connect(tmp_path).doc
    job = {"name": "Job", "route": "/jobs/[id]", "figmaFrame": "1:1",
           "frames": [{"frame": "1:2", "as": "dialog", "label": "Pause job"}]}
    check_frame_placement(_pages(job, {"name": "Jobs", "route": "/jobs", "figmaFrame": "1:3"}), doc)
    with pytest.raises(InvalidFramePlacement, match="placed on /jobs/\\[id\\] and again on /jobs"):
        check_frame_placement(_pages(job, {"name": "Jobs", "route": "/jobs", "figmaFrame": "1:3",
                                           "frames": [{"frame": "1:2", "as": "dialog"}]}), doc)
    with pytest.raises(InvalidFramePlacement, match="does not have"):
        check_frame_placement(_pages({**job, "frames": [{"frame": "7:7", "as": "tab"}]}), doc)
    # a page already saved holds its frames; restating it is not a clash
    doc["pages"] = [{"id": "PAGE-001", "route": "/jobs/[id]", **{k: job[k] for k in ("figmaFrame", "frames")}}]
    check_frame_placement(_pages(job), doc)
    with pytest.raises(InvalidFramePlacement):
        check_frame_placement(_pages({"name": "Pause", "route": "/pause", "figmaFrame": "1:2"}), doc)


def test_a_pages_main_frame_is_not_also_listed_as_its_part(tmp_path):
    from services.blueprint.executors import pin_page_set

    result = _pages({"name": "Job", "route": "/jobs/[id]", "figmaFrame": "1:1",
                     "frames": [{"frame": "1:1", "as": "state"}, {"frame": "1:2", "as": "dialog"}]})
    pin_page_set(result, _connect(tmp_path).doc)
    assert result.proposals[0].body["frames"] == [{"frame": "1:2", "as": "dialog"}]


def test_a_page_built_from_several_frames_belongs_to_the_part_that_drew_any_of_them():
    from services.blueprint.page_planner import page_frames

    page = {"figmaFrame": "1:1", "frames": [{"frame": "1:2", "as": "dialog"}]}
    assert page_frames(page) == {"1:1", "1:2"}


# -- 1. the writer sees every frame of its page -----------------------------------

def _job_page():
    return {"id": "PAGE-001", "name": "Job workspace", "route": "/jobs/[id]", "pattern": "record",
            "figmaFrame": "1:1", "frames": [{"frame": "1:2", "as": "dialog", "label": "Pause job"}]}


def test_a_specification_frame_is_reproduced_with_its_pictures_and_values(tmp_path):
    doc = _connect(tmp_path).doc
    ref, said = fr.reference_for(doc, _job_page(), tmp_path)
    assert ref["exact"] and "Reproducing Figma frame" in said and "1 other frame" in said
    assert len(ref["images"]) == 2 and all(p.endswith(".png") for p in ref["images"])
    assert ref["parts"][0]["as"] == "dialog" and "Pause this job?" in ref["parts"][0]["outline"]
    assert "#0f756e" in ref["values"] and "Inter 24px 700 /32px" in ref["values"]
    assert "corner radii px: 10" in ref["values"] and "Primary/600 #0f756e" in ref["values"]
    assert "Body/Regular = Inter 14px 400 /20px" in ref["values"]


def test_a_reference_design_is_still_adapted(tmp_path):
    doc = _connect(tmp_path, treat_as="evidence").doc
    ref, said = fr.reference_for(doc, _job_page(), tmp_path)
    assert not ref.get("exact") and "Adapting" in said


def test_the_writer_is_told_to_reproduce_the_drawing(tmp_path):
    from services.blueprint.ui_engineer import reference_block

    ref, _ = fr.reference_for(_connect(tmp_path).doc, _job_page(), tmp_path)
    block = reference_block(ref)
    assert "THE DRAWING IS THE SPECIFICATION" in block and "2. the page's dialog “Pause job”" in block
    assert "Never round a value" in block and "`bg-[#0f766e]`" in block
    assert "THE FRAME IS THE DECISION" not in block


def test_the_writer_is_shown_the_frames_only_when_it_reproduces_them():
    from services.blueprint.ui_engineer import _seeing

    seen = []

    class Client:
        accepts_images = True

        def __call__(self, **kwargs):
            seen.append(kwargs.get("images"))
            return "{}"

    client = Client()
    _seeing(client, {"exact": True, "images": ["a.png"]})(system="s", user="u", schema={})
    _seeing(client, {"images": ["a.png"]})(system="s", user="u", schema={})
    assert seen == [["a.png"], None]


# -- 2. the look puts the page beside the drawing ---------------------------------

def _png(path, colour, size=(720, 500)):
    from PIL import Image
    Image.new("RGB", size, colour).save(path)
    return str(path)


def test_the_look_is_taken_at_the_pages_width_and_judged_on_one_labelled_picture(tmp_path):
    from services.blueprint import page_look

    drawing = {"exact": True, "size": [1440, 1024], "content": {"x": 0.25, "y": 0.0, "w": 0.75, "h": 1.0},
               "images": [_png(tmp_path / "f1.png", "#0443fa", (1440, 1024)), _png(tmp_path / "f2.png", "#ffffff")],
               "parts": [{"as": "dialog", "label": "Pause job"}]}
    assert page_look.drawing_viewports(drawing)["desktop"] == (1080, 1024), "the frame less its drawn sidebar"
    assert page_look.drawing_viewports(None) == page_look.VIEWPORTS
    asked = {}

    def critic(*, system, user, schema, images):
        asked.update(user=user, images=images)
        return json.dumps({"score": 9, "verdict": "pass", "strengths": [], "issues": []})

    look = {"shots": {"desktop": _png(tmp_path / "desktop.png", "#ff736a", (1080, 1024)),
                      "mobile": _png(tmp_path / "mobile.png", "#ffffff", (390, 844))},
            "errors": [], "viewports": {"desktop": (1080, 1024), "mobile": (390, 844)}}
    verdict, _ = page_look.judge({"pages": []}, {"id": "PAGE-001"}, look, critic,
                                 references=["mood.png"], drawing=drawing)
    assert asked["images"][0].endswith("side-by-side.png"), "one picture, both labelled"
    assert asked["images"][1:] == [look["shots"]["mobile"], drawing["images"][1]], "not the mood board"
    assert "drawing on the LEFT" in asked["user"] and "dialog “Pause job”" in asked["user"]
    assert "Measured: 0% of the page's colour blocks" in asked["user"]
    # the reviewer said 9 and pass; the blocks are another colour, so it goes back
    assert verdict["pixel"] == 0.0 and verdict["verdict"] == "revise" and verdict["likeness"] == 4.5
    assert page_look.rank(verdict) == (1, 45)


def test_the_same_picture_measures_as_a_match(tmp_path):
    from PIL import Image

    from services.blueprint.page_look import pixel_likeness
    a = Image.new("RGB", (1000, 800), "#f7fafb")
    assert pixel_likeness(a, a.resize((800, 640))) == 1.0


def test_a_page_that_does_not_look_like_its_drawing_goes_back_with_the_drawing(monkeypatch, tmp_path):
    from services.blueprint import page_look
    from services.blueprint import ui_engineer as ue

    monkeypatch.setattr(ue, "typecheck", lambda *a, **k: [])
    monkeypatch.setattr(ue, "system_prompt", lambda doc: "s")
    monkeypatch.setattr(ue, "_static_findings", lambda *a, **k: [])
    monkeypatch.setattr(ue, "_design_findings", lambda *a, **k: [])
    verdicts = iter([{"verdict": "revise", "score": 6, "issues": [
                         {"severity": "medium", "where": "header", "problem": "drawn 24px, built 16px", "fix": "p-[24px]"}]},
                     {"verdict": "pass", "score": 9, "issues": []}])
    looked = []

    def look_at(doc, page, app_root, load, view, critic, **kw):
        looked.append(kw.get("drawing"))
        return next(verdicts), (None, 0)
    monkeypatch.setattr(page_look, "look_at", look_at)
    calls = []

    class Client:
        accepts_images = True

        def __call__(self, *, system, user, schema, images=()):
            calls.append((user, list(images)))
            if "edits" in (schema.get("properties") or {}):
                return json.dumps({"rationale": "r", "load": "", "view": "", "edits": [
                    {"file": "view", "find": "p-[16px]", "replace": "p-[24px]"}]})
            return json.dumps({"rationale": "r", "load": "export async function load() { return {}; }",
                               "view": '"use client";\nexport default function View() { return <div className="p-[16px]">Senior Nurse ICU</div>; }'})

    reference = {"html": "FRAME", "exact": True, "images": ["f1.png", "f2.png"], "size": [1440, 1024], "parts": []}
    body, _ = ue.compose_page({"pages": []}, {"id": "PAGE-001", "route": "/x", "name": "X"}, tmp_path, Client(),
                              critic=object(), reference=reference)
    assert looked and all(d is reference for d in looked), "every look is beside the drawing"
    assert len(calls) == 2 and all(images == ["f1.png", "f2.png"] for _u, images in calls)
    assert "drawn 24px, built 16px" in calls[1][0]
    assert "p-[24px]" in body["view"]


# -- 3. the drawn scales become tokens --------------------------------------------

def test_the_corners_spacing_and_body_text_the_frames_use_become_the_design_system(tmp_path):
    from services.figma.projection import design_system_from

    svc = _connect(tmp_path)
    ref = store.load("FIGMA-001", tmp_path)
    ds = design_system_from(ref)
    assert ds["radius"]["md"] == "10px"
    assert ds["typography"]["baseSize"] == "14px" and ds["typography"]["lineHeightBase"] == "20px"
    assert "16px" in ds["spacing"].values()
    assert svc.doc["designSources"][0]["treatAs"] == "specification"


def test_a_figma_node_response_keeps_its_style_names(monkeypatch):
    import asyncio

    from services import figma_client

    class Reply:
        status_code = 200

        def json(self):
            return {"nodes": {"1:1": {"document": {"id": "1:1"}, "styles": {"S:1": {"name": "Primary/600"}}}}}

    async def get(client, url, **kw):
        return Reply()
    monkeypatch.setattr(figma_client, "_get", get)
    out = asyncio.run(figma_client.fetch_figma_nodes("KEY", ["1:1"], "token"))
    assert out["1:1"]["_styles"] == {"S:1": {"name": "Primary/600"}}


def test_a_pill_is_not_the_corner_every_card_gets():
    from services.figma.styles import scales

    doc = {"type": "FRAME", "children": [{"type": "FRAME", "cornerRadius": 999} for _ in range(9)]
           + [{"type": "FRAME", "cornerRadius": 8} for _ in range(4)]}
    radius = scales([doc])["radius"]
    assert radius["md"] == "8px" and radius["full"] == "9999px"


def test_the_primary_is_what_buttons_are_painted_in_and_icons_draw_no_borders():
    from services.figma.palette import _document_to_pseudocode
    from services.figma.styles import action_colours

    blue = {"r": 0.016, "g": 0.263, "b": 0.98}
    doc = {"type": "FRAME", "children": [
        *[{"type": "INSTANCE", "name": "Button", "fills": [{"type": "SOLID", "color": blue}]} for _ in range(3)],
        *[{"type": "FRAME", "name": "badge", "fills": [{"type": "SOLID", "color": {"r": 1, "g": 0.45, "b": 0.42}}]}
          for _ in range(9)],
        {"type": "VECTOR", "name": "icon", "strokes": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0}}]},
    ]}
    assert action_colours([doc]).most_common(1)[0][0] == "#0443fa"
    assert "border-[#000000]" not in _document_to_pseudocode(doc)


def test_a_reproduced_page_is_painted_in_the_drawings_colours():
    from services.blueprint.ui_engineer import _drawn_findings

    ref = {"exact": True, "palette": ["#0443fa", "#ffffff"], "gradients": False}
    assert _drawn_findings('<div className="bg-[#0443fa] text-[#fffffe]" />', ref) == []
    found = _drawn_findings('<div className="bg-[#ff736a] bg-gradient-to-r from-primary" />', ref)
    assert "#ff736a" in found[0] and "gradient" in found[1]
    assert _drawn_findings('<div className="bg-[#ff736a]" />', {**ref, "exact": False}) == []


def test_the_page_is_the_frame_less_the_shell_it_draws():
    from services.figma.react_reference import content_box

    frame = {"absoluteBoundingBox": {"x": 0, "y": 0, "width": 1440, "height": 1024}, "children": [
        {"absoluteBoundingBox": {"x": 0, "y": 0, "width": 248, "height": 1024}},
        {"absoluteBoundingBox": {"x": 248, "y": 0, "width": 1192, "height": 1024}, "children": [
            {"absoluteBoundingBox": {"x": 248, "y": 0, "width": 1192, "height": 72}}]}]}
    assert content_box(frame) == {"x": 0.1722, "y": 0.0703, "w": 0.8278, "h": 0.9297}
    assert content_box({"absoluteBoundingBox": {"x": 0, "y": 0, "width": 800, "height": 600}, "children": []}) is None
