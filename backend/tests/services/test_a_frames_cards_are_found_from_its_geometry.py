"""An auto-layout export carries no percentage insets, so the region finder
saw nothing on a dashboard whose cards took their size from the layout, and
no number on it was ever looked at. The file's metadata carries every
element's box; kept on the screen, those boxes are the candidates."""
from services.figma.regions import candidates

CODE = '<div className="flex flex-col size-full" data-node-id="1:2"><div className="flex" data-node-id="1:5"></div></div>'
BOXES = [
    {"id": "1:2", "x": 0, "y": 0, "width": 1031, "height": 764},          # the frame itself
    {"id": "1:70", "x": 280, "y": 90, "width": 172, "height": 110},       # a KPI card
    {"id": "1:71", "x": 470, "y": 90, "width": 172, "height": 110},
    {"id": "1:90", "x": 280, "y": 230, "width": 480, "height": 400},      # the sessions list
    {"id": "1:42", "x": 20, "y": 20, "width": 20, "height": 20},          # an icon
]


def test_the_cards_come_from_the_boxes_largest_first_without_the_frame_or_icons():
    regs = candidates(CODE, 1031, 764, boxes=BOXES)
    assert [r.node_id for r in regs] == ["1:90", "1:70", "1:71"]
    assert regs[0].x == 280 and regs[0].width == 480


def test_without_boxes_an_auto_layout_frame_falls_back_to_sized_classes():
    code = ('<div className="flex flex-col size-full" data-node-id="1:2">'
            '<div className="bg-[#0d0d0d] flex h-[764px] w-[240px]" data-node-id="1:6"></div></div>')
    assert [r.node_id for r in candidates(code, 1031, 764)] == ["1:6"]


def test_the_extraction_keeps_each_screens_boxes_in_its_own_coordinates():
    from services.figma.reference import _screens_from_metadata
    markup = '''<canvas id="0:1" name="Page 1">
  <frame id="1:2" name="Platform" x="100" y="50" width="1031" height="764">
    <frame id="1:5" name="App" x="100" y="50" width="1031" height="764">
      <frame id="1:70" name="Card" x="380" y="140" width="172" height="110"><text id="1:71" name="132" x="390" y="150" width="60" height="30"/></frame>
    </frame>
  </frame>
</canvas>'''
    (screen,) = _screens_from_metadata([{"type": "text", "text": markup}], limit=10)
    boxes = screen.structure["boxes"]
    card = next(b for b in boxes if b["id"] == "1:70")
    assert (card["x"], card["y"], card["width"], card["height"]) == (280, 90, 172, 110)
    assert any(b["id"] == "1:5" for b in boxes)


def test_a_margin_wrapper_is_its_childs_rectangle_and_not_a_second_region():
    boxes = [
        {"id": "1:2", "x": 0, "y": 0, "width": 1031, "height": 764},
        {"id": "1:656", "x": 264, "y": 203, "width": 743, "height": 452},   # margin wrapper
        {"id": "1:273", "x": 264, "y": 227, "width": 743, "height": 428},   # the card inside it
        {"id": "1:70", "x": 280, "y": 90, "width": 172, "height": 110},     # a KPI tile
    ]
    ids = [r.node_id for r in candidates(CODE, 1031, 764, boxes=boxes, limit=2)]
    assert ids == ["1:273", "1:70"]


def test_a_frame_high_column_is_structure_not_a_card():
    boxes = [
        {"id": "1:6", "x": 0, "y": 0, "width": 240, "height": 764},        # the rail
        {"id": "1:177", "x": 240, "y": 0, "width": 791, "height": 764},    # the content column
        {"id": "1:205", "x": 833, "y": 89, "width": 173, "height": 114},   # a KPI tile
    ]
    assert [r.node_id for r in candidates(CODE, 1031, 764, boxes=boxes)] == ["1:205"]
