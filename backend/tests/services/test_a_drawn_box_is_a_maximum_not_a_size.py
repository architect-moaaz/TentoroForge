"""A frame that flows reflows; a frame that is positioned scales.

Dev Mode exports every auto-layout frame at the pixel size it had on the
artboard, and a page assembled from those numbers is exactly as wide as the
artboard at every viewport. On a scaled canvas it shrinks as a picture, text
and all — which is right for a flattened design and wrong for one drawn with
auto-layout, where the numbers mean: this wide at most, this tall at least,
and the row wraps when it must.

Two decisions are pinned here. `frame_fit` reads the frame's top level: a
positioned top level is a picture (`scale`), a flowing one is a layout
(`fluid`). And on a fluid frame `_responsive_container_classes` rewrites
container sizes into maxima, converts a pixel grid to as-many-as-fit, and
leaves drawings (containers of positioned children) and leaves alone.
"""
from services.jsx_to_schema import (
    _responsive_container_classes, frame_fit, parse_jsx_tree,
    transform_jsx_to_schema,
)

FLOWING = '''
export default function F() {
  return (
    <div className="relative size-full" data-node-id="1:1">
      <div className="bg-[#f7f3eb] flex flex-col w-[1387px]" data-node-id="1:2">
        <div className="flex gap-[16px] w-[1097px] h-[85px] shrink-0" data-node-id="1:3">
          <div className="bg-white w-[355.66px] h-[85px] shrink-0 flex flex-col" data-node-id="1:4">
            <p className="text-[12px] w-[46px]">OPEN CASES</p>
          </div>
          <div className="bg-white w-[355.66px] h-[85px] shrink-0 flex flex-col" data-node-id="1:5">
            <p className="text-[12px]">PENDING</p>
          </div>
        </div>
        <div className="grid grid-cols-[___355.66px_355.66px_355.66px] gap-x-[16px]" data-node-id="1:6">
          <p>a</p><p>b</p><p>c</p>
        </div>
        <div className="relative w-[340px] h-[120px] shrink-0" data-node-id="1:7">
          <div className="absolute left-[10px] top-[20px] w-[30px] h-[85px] bg-[#c9a84c]" />
          <div className="absolute left-[50px] top-[40px] w-[30px] h-[65px] bg-[#c9a84c]" />
        </div>
      </div>
    </div>
  );
}
'''

FLATTENED = '''
export default function F() {
  return (
    <div className="bg-white relative size-full" data-node-id="1:1">
      <div className="absolute contents left-[10px] top-[10px]">
        <div className="absolute inset-[10%_50%_50%_10%] w-[600px]" data-node-id="1:10"><p>x</p></div>
      </div>
      <div className="absolute contents left-[10px] top-[400px]">
        <div className="absolute inset-[55%_50%_5%_10%] w-[600px]" data-node-id="1:20"><p>y</p></div>
      </div>
    </div>
  );
}
'''


def _find(node, node_id):
    if isinstance(node, dict):
        if (node.get("props") or {}).get("_figmaNodeId") == node_id:
            return node
        for c in node.get("children") or []:
            hit = _find(c, node_id)
            if hit:
                return hit
    return None


def _cn(root, node_id):
    return (_find(root, node_id)["props"].get("className") or "").split()


# ------------------------------------------------------------- the decision

def test_a_flowing_frame_is_fluid():
    assert frame_fit(parse_jsx_tree(FLOWING)) == "fluid"


def test_a_positioned_frame_scales():
    assert frame_fit(parse_jsx_tree(FLATTENED)) == "scale"


def test_the_fit_rides_on_the_schema():
    assert transform_jsx_to_schema(FLOWING, {}, canvas=(1387.0, 982.0))["canvasFit"] == "fluid"
    assert transform_jsx_to_schema(FLATTENED, {}, canvas=(4000.0, 2000.0))["canvasFit"] == "scale"
    assert "canvasFit" not in transform_jsx_to_schema(FLOWING, {})


# ------------------------------------------------- a drawn box is a maximum

def _fluid():
    return transform_jsx_to_schema(FLOWING, {}, canvas=(1387.0, 982.0))


def test_a_containers_width_becomes_its_maximum():
    cn = _cn(_fluid(), "1:4")
    assert "max-w-[355.66px]" in cn and "w-full" in cn
    assert "w-[355.66px]" not in cn


def test_a_containers_height_becomes_its_minimum():
    cn = _cn(_fluid(), "1:3")
    assert "min-h-[85px]" in cn and "h-[85px]" not in cn


def test_a_container_may_shrink():
    assert "shrink-0" not in _cn(_fluid(), "1:4")


def test_a_row_of_cards_wraps():
    assert "flex-wrap" in _cn(_fluid(), "1:3")


def test_a_pixel_grid_fits_as_many_columns_as_it_can():
    cn = _cn(_fluid(), "1:6")
    assert "grid-cols-[repeat(auto-fit,minmax(min(355.66px,100%),1fr))]" in cn
    assert _find(_fluid(), "1:6")["props"].get("columns") == 3, "the catalog count is kept"


def test_a_drawing_keeps_its_size_and_scrolls_sideways():
    """The chart's bars are positioned inside it; reflowing them breaks the
    chart, and cutting it hides it. Wider than the viewport, it scrolls."""
    cn = _cn(_fluid(), "1:7")
    assert "w-[340px]" in cn and "h-[120px]" in cn
    assert "max-w-full" in cn and "overflow-x-auto" in cn


def test_a_leaf_keeps_its_size():
    """A 46px axis label is 46px; only containers are rewritten."""
    root = _fluid()
    label = next(n for n in _walk(root) if (n.get("props") or {}).get("content") == "OPEN CASES")
    assert "w-[46px]" in (label["props"].get("className") or "")


def test_a_scaled_frame_is_not_rewritten():
    root = transform_jsx_to_schema(FLATTENED, {}, canvas=(4000.0, 2000.0))
    assert "w-[600px]" in _cn(root, "1:10")


def test_off_canvas_nothing_changes():
    """Reflow mode strips sizes its own way; this rewrite is canvas-only."""
    root = transform_jsx_to_schema(FLOWING, {})
    assert "max-w-[355.66px]" not in _cn(root, "1:4")


def _walk(node):
    if isinstance(node, dict):
        yield node
        for c in node.get("children") or []:
            yield from _walk(c)


def test_a_card_with_one_decoration_is_not_a_drawing():
    """Two flowing rows and one positioned outline make a card, not a chart."""
    jsx = FLOWING.replace(
        '<div className="bg-white w-[355.66px] h-[85px] shrink-0 flex flex-col" data-node-id="1:4">',
        '<div className="bg-white w-[355.66px] h-[85px] shrink-0 flex flex-col" data-node-id="1:4">'
        '<div className="absolute inset-0 border border-[#c9a84c] rounded-[8px]" />'
        '<div className="flex"><p>Active</p></div>')
    cn = _cn(transform_jsx_to_schema(jsx, {}, canvas=(1387.0, 982.0)), "1:4")
    assert "max-w-[355.66px]" in cn and "w-[355.66px]" not in cn



# ------------------------------------------ hand-placed stacks and drawings

HAND_PLACED = '''
export default function F() {
  return (
    <div className="relative size-full" data-node-id="1:1">
      <div className="flex flex-col w-[1387px]" data-node-id="1:2">
        <div data-name="Button" className="bg-white border rounded-[8px] h-[66px] w-[355.664px]" data-node-id="1:3">
          <div className="absolute flex justify-between left-[12px] top-[12px] w-[329px]" data-node-id="1:4">
            <p>Refund Policy</p><p>v3.2</p>
          </div>
          <div className="absolute flex gap-[8px] left-[12px] top-[36px] w-[329px]" data-node-id="1:5">
            <p>Active</p><p>All Brands</p>
          </div>
        </div>
        <div className="relative w-[340px] h-[120px]" data-node-id="1:6">
          <div className="absolute left-[10px] top-[20px] w-[30px] h-[85px]" data-node-id="1:7" />
          <div className="absolute left-[50px] top-[40px] w-[30px] h-[65px]" data-node-id="1:8" />
          <div className="absolute left-[0px] top-[110px] flex" data-node-id="1:9">
            <p className="absolute left-[10px] top-[0px]">Jul</p>
            <p className="absolute left-[50px] top-[0px]">Aug</p>
          </div>
        </div>
      </div>
    </div>
  );
}
'''


def _hand():
    with patch("services.jsx_to_schema._classify_button_action_with_llm",
               lambda *a, **k: {"navigate": "/policies/[id]"}):
        return transform_jsx_to_schema(HAND_PLACED, {}, canvas=(1387.0, 982.0))


from unittest.mock import patch  # noqa: E402


def test_a_card_drawn_without_auto_layout_reflows_as_a_stack():
    """Two rows at left 12 / top 12 and 36 are a column the designer placed
    by hand; the card flows them and keeps the inset as padding."""
    card = _find(_hand(), "1:3")
    cn = card["props"]["className"].split()
    assert "flex" in cn and "flex-col" in cn
    assert "max-w-[355.664px]" in cn and "w-[355.664px]" not in cn
    assert "px-[12px]" in cn and "py-[12px]" in cn
    assert card["props"]["navigate"] == "/policies/[id]"


def test_the_reflowed_rows_lose_their_offsets():
    root = _hand()
    for node_id in ("1:4", "1:5"):
        cn = _cn(root, node_id)
        assert "absolute" not in cn and not any(t.startswith(("left-[", "top-[")) for t in cn), cn
        assert "max-w-[329px]" in cn


def test_a_two_dimensional_drawing_keeps_every_position():
    root = _hand()
    assert "w-[340px]" in _cn(root, "1:6")
    for node_id in ("1:7", "1:8"):
        assert "absolute" in _cn(root, node_id)


def test_nothing_inside_a_drawing_reflows():
    """The axis-label row inside the chart would read as a 'row' on its own;
    inside a drawing it stays exactly where it was drawn."""
    root = _hand()
    labels = _find(root, "1:9")
    assert "absolute" in (labels["props"].get("className") or "").split()
    assert "flex-wrap" not in (labels["props"].get("className") or "")


ROWS = '''
export default function F() {
  return (
    <div className="relative size-full" data-node-id="1:1">
      <div className="flex flex-col w-[1387px]" data-node-id="1:2">
        <div className="flex gap-[8px] items-end w-[320px]" data-node-id="2:1">
          <div className="bg-[#c9a84c] w-[46px] h-[60px]" /><div className="bg-[#c9a84c] w-[46px] h-[80px]" />
          <div className="bg-[#c9a84c] w-[46px] h-[40px]" /><div className="bg-[#c9a84c] w-[46px] h-[90px]" />
        </div>
        <div className="flex gap-[8px] w-[320px]" data-node-id="2:2">
          <p className="w-[46px]">Jul</p><p className="w-[46px]">Aug</p><p className="w-[46px]">Sep</p>
        </div>
        <div className="flex justify-between w-[300px]" data-node-id="2:3">
          <div className="flex flex-col w-[116px]"><p>OPEN CASES</p><p>4</p></div>
          <div className="flex flex-col w-[16px]"><img src="x" alt="" /></div>
        </div>
        <div className="flex gap-[8px] w-[500px]" data-node-id="2:5">
          <div className="flex px-[10px] rounded-full border"><p className="whitespace-nowrap">All</p></div>
          <div className="flex px-[10px] rounded-full border"><p className="whitespace-nowrap">Financial</p></div>
          <div className="flex px-[10px] rounded-full border"><p className="whitespace-nowrap">Legal &amp; Compliance</p></div>
        </div>
        <div className="flex gap-[16px] w-[1097px]" data-node-id="2:4">
          <div className="flex flex-col w-[355px]"><p>a</p></div>
          <div className="flex flex-col w-[355px]"><p>b</p></div>
          <div className="flex flex-col w-[355px]"><p>c</p></div>
        </div>
      </div>
    </div>
  );
}
'''


def test_a_row_of_bars_does_not_wrap():
    """A bar chart's sixth bar dropped under the legend; bars shrink instead."""
    assert "flex-wrap" not in _cn(transform_jsx_to_schema(ROWS, {}, canvas=(1387.0, 982.0)), "2:1")


def test_a_row_of_axis_labels_does_not_wrap():
    assert "flex-wrap" not in _cn(transform_jsx_to_schema(ROWS, {}, canvas=(1387.0, 982.0)), "2:2")


def test_a_text_block_beside_its_icon_does_not_wrap():
    """The icon stays beside the text; the text block shrinks and wraps its words."""
    assert "flex-wrap" not in _cn(transform_jsx_to_schema(ROWS, {}, canvas=(1387.0, 982.0)), "2:3")


def test_a_row_of_cards_still_wraps():
    assert "flex-wrap" in _cn(transform_jsx_to_schema(ROWS, {}, canvas=(1387.0, 982.0)), "2:4")


TRACKS = '''
export default function F() {
  return (
    <div className="relative size-full" data-node-id="1:1">
      <div className="flex flex-col w-[1387px]" data-node-id="1:2">
        <div className="grid grid-cols-[____262.75px_262.75px_262.75px_262.75px] grid-rows-[_112px] h-[112px]" data-node-id="3:1">
          <div className="flex flex-col w-[262px]"><p className="whitespace-nowrap">Approved policies governing refunds, operations, and compliance.</p></div>
          <div className="flex flex-col w-[262px]"><p>b</p></div>
        </div>
      </div>
    </div>
  );
}
'''


def test_a_drawn_row_height_is_the_least_a_row_may_be():
    """Fixed row tracks pinned every card to 112px; a card whose text wrapped
    at a narrow width then overflowed its own border."""
    cn = _cn(transform_jsx_to_schema(TRACKS, {}, canvas=(1387.0, 982.0)), "3:1")
    assert "auto-rows-[minmax(112px,auto)]" in cn
    assert not any(t.startswith("grid-rows-[") for t in cn)


def test_a_long_line_drawn_single_may_wrap_on_a_fluid_canvas():
    """A subtitle that cannot wrap is cut at the edge of the page."""
    root = transform_jsx_to_schema(TRACKS, {}, canvas=(1387.0, 982.0))
    label = next(n for n in _walk(root) if str((n.get("props") or {}).get("content") or "").startswith("Approved policies"))
    assert "whitespace-nowrap" not in (label["props"].get("className") or "")


def test_a_scaled_frame_keeps_its_single_lines():
    root = transform_jsx_to_schema(FLATTENED.replace("<p>x</p>", '<p className="whitespace-nowrap">x</p>'), {}, canvas=(4000.0, 2000.0))
    label = next(n for n in _walk(root) if (n.get("props") or {}).get("content") == "x")
    assert "whitespace-nowrap" in (label["props"].get("className") or "")


def test_a_row_of_chips_wraps():
    """Filter chips ran off the page into the next column; they wrap."""
    assert "flex-wrap" in _cn(transform_jsx_to_schema(ROWS, {}, canvas=(1387.0, 982.0)), "2:5")


def test_a_short_label_keeps_its_single_line():
    """A chip's label stays on one line; the chip moves to the next line instead."""
    root = transform_jsx_to_schema(ROWS, {}, canvas=(1387.0, 982.0))
    label = next(n for n in _walk(root) if (n.get("props") or {}).get("content") == "Financial")
    assert "whitespace-nowrap" in (label["props"].get("className") or "")


CHIPS = '''
export default function F() {
  return (
    <div className="relative size-full" data-node-id="1:1">
      <div className="flex flex-col w-[1387px]" data-node-id="1:2">
        <div className="h-[56px] relative shrink-0 w-[440px]" data-node-id="4:1">
          <div data-name="Button" className="absolute bg-white border left-[0px] top-[12px] w-[40px]"><p className="whitespace-nowrap">All</p></div>
          <div data-name="Button" className="absolute bg-white border left-[52px] top-[12px] w-[90px]"><p className="whitespace-nowrap">Financial</p></div>
          <div data-name="Button" className="absolute bg-white border left-[154px] top-[12px] w-[150px]"><p className="whitespace-nowrap">Legal &amp; Compliance</p></div>
        </div>
        <div className="flex justify-between w-[300px]" data-node-id="4:2">
          <div className="flex flex-col w-[116px]"><p>OPEN CASES</p><p>4</p></div>
          <div className="flex flex-col w-[16px]"><p>✓</p></div>
        </div>
      </div>
    </div>
  );
}
'''


def test_a_hand_placed_row_of_chips_shrinks_and_wraps():
    """The promotion rebuilt the row's class from the source and put the
    drawn width and `shrink-0` back; the chips ran into the next column."""
    with patch("services.jsx_to_schema._classify_button_action_with_llm", lambda *a, **k: {}):
        cn = _cn(transform_jsx_to_schema(CHIPS, {}, canvas=(1387.0, 982.0)), "4:1")
    assert "shrink-0" not in cn and "w-[440px]" not in cn
    assert "max-w-[440px]" in cn and "flex-wrap" in cn
    assert not any(t.startswith("py-[") for t in cn), "a chip's top offset is alignment, not a margin"
    assert "items-center" in cn


def test_an_icon_drawn_as_a_glyph_does_not_make_a_row_wrap():
    assert "flex-wrap" not in _cn(transform_jsx_to_schema(CHIPS, {}, canvas=(1387.0, 982.0)), "4:2")



SPLIT = '''
export default function F() {
  return (
    <div className="relative size-full" data-node-id="1:1">
      <div className="flex flex-col w-[1387px]" data-node-id="1:2">
        <div className="gap-x-[16px] gap-y-[16px] grid grid-cols-[___355.66px_355.66px_355.66px] grid-rows-[_484px] h-[484px]" data-node-id="5:1">
          <div className="col-1 content-stretch flex flex-col items-start justify-self-stretch row-1 self-stretch" data-node-id="5:2"><p>list</p></div>
          <div className="col-[2/span_2] content-stretch flex flex-col items-start justify-self-stretch row-1 self-stretch" data-node-id="5:3"><p>panel</p></div>
        </div>
        <div className="h-[56px] relative w-[440px]" data-node-id="5:4">
          <div data-name="Button" className="absolute left-0 top-0 bg-white border"><p>All</p></div>
          <div data-name="Button" className="absolute left-[36px] top-0 bg-white border"><p>Financial</p></div>
          <div data-name="Button" className="absolute left-[108px] top-0 bg-white border"><p>Operations</p></div>
          <div data-name="Button" className="absolute left-0 top-[30px] bg-white border"><p>Guest Experience</p></div>
        </div>
      </div>
    </div>
  );
}
'''


def _split():
    with patch("services.jsx_to_schema._classify_button_action_with_llm", lambda *a, **k: {}):
        return transform_jsx_to_schema(SPLIT, {}, canvas=(1387.0, 982.0))


def test_a_grid_with_spans_becomes_a_row_that_keeps_its_proportions():
    """A one-to-two split drawn as tracks; the panel was cut off as auto-fit."""
    root = _split()
    grid = _find(root, "5:1")
    cn = grid["props"]["className"].split()
    assert grid["type"] == "Row" and "flex" in cn and "flex-wrap" in cn
    assert not any(t.startswith("grid") for t in cn)
    assert "flex-[1_1_355.66px]" in _cn(root, "5:2")
    assert "flex-[2_1_711.32px]" in _cn(root, "5:3")


def test_a_spanned_child_loses_its_placement():
    cn = _cn(_split(), "5:3")
    assert not any(t.startswith(("col-", "row-", "justify-self-", "self-")) for t in cn)
    assert "min-w-0" in cn


def test_chips_wrapped_by_hand_are_one_row_with_no_inset():
    """Four chips on one line and one below, the first at `left-0`."""
    cn = _cn(_split(), "5:4")
    assert "flex" in cn and "flex-wrap" in cn
    assert not any(t.startswith("px-[") for t in cn), cn


def test_a_drawn_rail_keeps_its_width_beside_the_content_column():
    """The pass-through capped `w-[240px]` with `max-w-full`; the responsive
    rewrite then added `max-w-[240px]` before it, and the later class won:
    a 240px rail filled the row and the content fell beneath it."""
    from services.jsx_to_schema import transform_jsx_to_schema
    code = '''<div className="bg-white flex flex-col size-full" data-node-id="1:2">
  <div className="bg-[#f3f3f1] flex h-[764px] items-start overflow-clip w-[1031px]" data-node-id="1:5">
    <div className="bg-[#0d0d0d] flex flex-col h-full items-start shrink-0 w-[240px]" data-node-id="1:6">
      <p className="text-[#ffffff]">Overview</p><p className="text-[#ffffff]">Sessions</p><p className="text-[#ffffff]">Committees</p>
    </div>
    <div className="flex flex-[791_0_0] flex-col h-full items-start" data-node-id="1:7">
      <p className="text-[#0d0d0d]">Dashboard</p>
    </div>
  </div>
</div>'''
    tree = transform_jsx_to_schema(code, {}, canvas=(1031, 764))["children"][0]
    def find(n):
        if isinstance(n, dict):
            cls = str((n.get("props") or {}).get("className") or "")
            if "bg-[#0d0d0d]" in cls:
                return cls
            for c in n.get("children") or []:
                r = find(c)
                if r:
                    return r
        return None
    cls = find(tree)
    assert cls and "max-w-[240px]" in cls and "max-w-full" not in cls, cls
