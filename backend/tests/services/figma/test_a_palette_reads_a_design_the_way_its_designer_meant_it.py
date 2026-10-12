"""The scheme read off a light design with a white sidebar, a green brand and an orange accent.

The first live Figma build (ToolShare) came out cream and green where the design is cream, white, green and
orange: a 10% orange wash on one card was read as a solid and became the "sidebar", the green took both brand
roles, and nothing recorded the white of the cards and header."""
from __future__ import annotations

from services.figma import palette


def rgb(h):
    h = h.lstrip("#")
    return {"r": int(h[0:2], 16) / 255, "g": int(h[2:4], 16) / 255, "b": int(h[4:6], 16) / 255}


def box(name, x, y, w, h, fill=None, alpha=1.0, stroke=None, kids=(), typ="FRAME"):
    node = {"id": name, "type": typ, "name": name, "absoluteBoundingBox": {"x": x, "y": y, "width": w, "height": h},
            "children": list(kids)}
    if fill:
        node["fills"] = [{"type": "SOLID", "color": rgb(fill), "opacity": alpha}]
    if stroke:
        node["strokes"] = [{"type": "SOLID", "color": rgb(stroke)}]
    return node


def text(chars, colour, x=0, y=0):
    return {"id": chars, "type": "TEXT", "characters": chars, "absoluteBoundingBox": {"x": x, "y": y, "width": 80, "height": 16},
            "fills": [{"type": "SOLID", "color": rgb(colour)}]}


def frame():
    nav = [box(f"nav{i}", 12, 100 + i * 44, 215, 40, "#1c3828" if i == 0 else None, kids=[text("Browse", "#f2ede3")])
           for i in range(3)]
    cards = [box(f"card{i}", 300 + (i % 2) * 380, 200 + (i // 2) * 320, 364, 310, "#ffffff", stroke="#d6d0c4",
                 kids=[text("DeWalt Drill", "#18130e"), text("Add tool", "#d96f32"), text("View details", "#d96f32")])
             for i in range(4)]
    rail = box("rail", 0, 0, 240, 982, "#ffffff", stroke="#d6d0c4", kids=[
        *nav,
        box("active", 12, 800, 215, 88, "#d96f32", alpha=0.1, kids=[text("Active borrow", "#d96f32")]),   # a TINT
        box("avatar", 16, 900, 32, 32, "#d96f32", kids=[text("SM", "#ffffff")]),
    ])
    return box("root", 0, 0, 1257, 982, "#f2ede3", kids=[rail, *cards,
               box("btn", 1000, 40, 115, 36, "#1c3828", kids=[text("List a tool", "#f2ede3")])])


def derive():
    from types import SimpleNamespace

    doc = frame()
    screens = [SimpleNamespace(structure={"source": "rest_node_document", "document": doc}, width=1257, height=982)
               for _ in range(2)]
    return palette.from_screens(screens)


def test_a_tint_is_not_a_colour_of_the_scheme():
    out = derive()
    assert out["colors"].get("sidebarBackground") != "#d96f32", "a 10% wash became the sidebar"
    assert "sidebarBackground" not in out["colors"], "a white sidebar on a cream page is not a contrasting rail"


def test_the_white_of_the_cards_and_header_is_the_surface():
    out = derive()
    assert out["colors"]["background"] == "#f2ede3" and out["colors"]["surface"] == "#ffffff"


def test_a_second_hue_the_design_uses_is_the_accent_and_the_brand_stays_the_primary():
    out = derive()
    assert out["colors"]["primary"] == "#1c3828"
    assert out["colors"]["accent"] == "#d96f32" and out["evidence"]["accent"] >= 4


def test_a_stroke_is_the_border():
    assert derive()["colors"]["border"] == "#d6d0c4"


def test_a_design_with_one_brand_colour_keeps_it_as_both_primary_and_accent():
    """Few stray uses of another hue are not a second colour."""
    code = ('<div className="bg-[#f3f3f1] h-[764px] w-[1031px]">'
            + "".join('<div className="bg-[#ce1126] h-[32px] w-[120px]"><p className="text-[#ffffff]">Go</p></div>' for _ in range(4))
            + "".join('<div className="bg-[#ffffff] h-[100px] w-[100px]"><p className="text-[#0d0d0d]">12</p></div>' for _ in range(10))
            + '<p className="text-[#007a3d]">once</p></div>')
    out = palette.from_code([code])
    assert out["colors"]["primary"] == "#ce1126" and out["colors"]["accent"] == "#ce1126"


def test_a_near_black_ink_is_ink_not_an_accent():
    out = derive()
    assert out["colors"]["accent"] != out["colors"]["foreground"]


def test_a_real_dark_rail_is_still_a_rail():
    code = ('<div className="bg-[#f3f3f1] h-[764px] w-[1031px]">'
            '<div className="bg-[#0d0d0d] h-full w-[238px]"></div>'
            + "".join('<div className="bg-[#ffffff] h-[100px] w-[100px]"><p className="text-[#0d0d0d]">1</p></div>' for _ in range(12))
            + "</div>")
    assert palette.from_code([code])["colors"]["sidebarBackground"] == "#0d0d0d"
