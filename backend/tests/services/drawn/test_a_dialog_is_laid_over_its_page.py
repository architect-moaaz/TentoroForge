"""A dialog drawn over a page is the page with the dialog over it (DITANS, 2026-10-30/31).

A dialog's scrim covers the whole frame, so it is wider than the page column,
and the page was chosen as the widest layer beside the sidebar: 40 DITANS
dialogs and drawers were converted as nothing but their scrim. The page is
now the layout's own column; what floats over it is laid over it, kept within
it, and keeps its place as the page changes size — a scrim stretched, a drawer
pinned right, a dialog centred.
"""
from __future__ import annotations

from services.drawn.shell import read_screen
from services.drawn.tsx import Emitter


def _box(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def _text(nid, x, y, words):
    return {"id": nid, "type": "TEXT", "name": words, "characters": words, "absoluteBoundingBox": _box(x, y, 200, 20),
            "style": {"fontSize": 14}}


def _frame(*extra, layout="HORIZONTAL"):
    sidebar = {"id": "1:1", "type": "FRAME", "name": "Sidebar", "absoluteBoundingBox": _box(0, 0, 248, 900),
               "layoutMode": "VERTICAL", "children": [_text("1:2", 16, 16, "Home")]}
    page = {"id": "2:1", "type": "FRAME", "name": "Main", "absoluteBoundingBox": _box(248, 0, 1192, 900),
            "layoutMode": "VERTICAL", "children": [_text("2:2", 280, 32, "My offers")]}
    return {"id": "0:1", "type": "FRAME", "name": "Offer — decline (modal)", "absoluteBoundingBox": _box(0, 0, 1440, 900),
            "layoutMode": layout, "children": [sidebar, page, *extra]}


SCRIM = {"id": "3:1", "type": "RECTANGLE", "name": "Scrim", "layoutPositioning": "ABSOLUTE",
         "absoluteBoundingBox": _box(0, 0, 1440, 900), "fills": [{"type": "SOLID", "color": {"r": 0, "g": 0, "b": 0, "a": 0.4}}]}
DIALOG = {"id": "4:1", "type": "FRAME", "name": "Decline offer dialog", "layoutPositioning": "ABSOLUTE",
          "absoluteBoundingBox": _box(604, 250, 480, 400), "layoutMode": "VERTICAL",
          "children": [_text("4:2", 628, 274, "Decline this offer?")]}
DRAWER = {"id": "5:1", "type": "FRAME", "name": "Edit job drawer", "layoutPositioning": "ABSOLUTE",
          "absoluteBoundingBox": _box(1020, 0, 420, 900), "layoutMode": "VERTICAL",
          "children": [_text("5:2", 1044, 24, "Edit job")]}


def test_the_page_is_the_column_and_not_the_scrim():
    s = read_screen(_frame(SCRIM, DIALOG))
    assert s.page_root["id"] == "2:1", "the scrim is wider than the page; it is not the page"
    names = [c["name"] for c in s.page_root["children"]]
    assert names == ["My offers", "Scrim", "Decline offer dialog"], "the page, then what floats over it"
    scrim = s.page_root["children"][1]
    assert scrim["absoluteBoundingBox"]["x"] == 248 and scrim["absoluteBoundingBox"]["width"] == 1192, \
        "kept within the page: the sidebar beside it is the app's"
    assert scrim["constraints"] == {"horizontal": "LEFT_RIGHT", "vertical": "TOP_BOTTOM"}
    assert s.page_root["children"][2]["constraints"] == {"horizontal": "CENTER", "vertical": "CENTER"}


def test_a_drawer_stays_at_the_right_edge():
    s = read_screen(_frame(SCRIM, DRAWER))
    drawer = s.page_root["children"][2]
    assert drawer["constraints"] == {"horizontal": "RIGHT", "vertical": "TOP_BOTTOM"}


def test_a_panel_beside_the_page_in_auto_layout_is_not_laid_over_it():
    panel = {"id": "6:1", "type": "FRAME", "name": "Help panel", "absoluteBoundingBox": _box(1440, 0, 320, 900),
             "layoutMode": "VERTICAL", "children": []}
    s = read_screen(_frame(panel))
    assert [c["name"] for c in s.page_root["children"]] == ["My offers"], "the next column, not an overlay"


def test_in_a_free_frame_what_is_drawn_after_the_page_lies_over_it():
    loose_scrim = {**SCRIM, "layoutPositioning": None}
    loose_dialog = {**DIALOG, "layoutPositioning": None}
    s = read_screen(_frame(loose_scrim, loose_dialog, layout="NONE"))
    assert s.page_root["id"] == "2:1"
    assert [c["name"] for c in s.page_root["children"]] == ["My offers", "Scrim", "Decline offer dialog"]


def test_the_markup_keeps_each_layer_in_its_place_at_any_width():
    s = read_screen(_frame(SCRIM, DIALOG, DRAWER))
    out = Emitter(skip=s.skip).element(s.page_root)
    root = out.split(">", 1)[0]
    assert "relative" in root, "what floats in the page is placed against the page"
    scrim = next(line for line in out.splitlines() if 'data-layer="Scrim"' in line)
    assert "left-[0px]" in scrim and "right-[0px]" in scrim and "top-[0px]" in scrim and "bottom-[0px]" in scrim
    assert "w-[" not in scrim, "stretched, not the drawing's pixel width"
    dialog = next(line for line in out.splitlines() if 'data-layer="Decline offer dialog"' in line)
    assert "left-[calc(50%+0px)]" in dialog and "-translate-x-1/2" in dialog and "-translate-y-1/2" in dialog
    drawer = next(line for line in out.splitlines() if 'data-layer="Edit job drawer"' in line)
    assert "right-[0px]" in drawer and "left-[" not in drawer
    assert "Decline this offer?" in out and "Edit job" in out


def test_a_free_frame_keeps_its_pixels():
    free = {"id": "7:1", "type": "FRAME", "name": "Card", "absoluteBoundingBox": _box(0, 0, 400, 300),
            "children": [{"id": "7:2", "type": "RECTANGLE", "name": "Badge", "absoluteBoundingBox": _box(380, 0, 20, 20),
                          "constraints": {"horizontal": "RIGHT", "vertical": "TOP"}}]}
    out = Emitter().element(free)
    badge = next(line for line in out.splitlines() if 'data-layer="Badge"' in line)
    assert "left-[380px]" in badge and "right-[" not in badge


def test_a_dialog_centred_on_the_screen_stays_centred_on_the_page():
    """DITANS draws a dialog centred on the whole frame, sidebar included, and
    a little high: centred on the page it is, at any width."""
    on_screen = {**DIALOG, "absoluteBoundingBox": _box(460, 200, 520, 331)}
    s = read_screen(_frame(SCRIM, on_screen))
    assert s.page_root["children"][2]["constraints"] == {"horizontal": "CENTER", "vertical": "CENTER"}


def test_a_laid_over_frame_is_absolute_only():
    s = read_screen(_frame({**SCRIM, "type": "FRAME", "children": []}, DIALOG))
    scrim = next(line for line in Emitter(skip=s.skip).element(s.page_root).splitlines() if 'data-layer="Scrim"' in line)
    assert "absolute" in scrim.split('className="', 1)[1].split('"', 1)[0].split() and "relative" not in scrim
