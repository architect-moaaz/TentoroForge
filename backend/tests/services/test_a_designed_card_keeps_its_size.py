"""A Figma card must keep its dimensions, and a card grid must wrap.

WHAT THE PAGE LOOKED LIKE. A 3902x1975 dashboard frame of roughly thirty cards
rendered as three: the header, one health ring and one chart, with the rest of
the page blank. The schema was not empty — 626 nodes, 249 images, every asset
on disk. The nodes had nothing to draw with.

TWO FUNCTIONS, ONE ASSUMPTION, POINTING OPPOSITE WAYS.

`_filter_position_classes` stripped `w-[Npx]`/`h-[Npx]` whenever the node also
carried `absolute`. `_infer_absolute_flow` returned no flow when children
spread on both axes, with the comment "treat as grid-ish, let className win".
By then the className had had `absolute`, `left-` and `top-` removed by the
first function — so there was nothing to win with. Figma writes every card as
`absolute left-[x] top-[y] w-[w] h-[h]`; taking the offsets AND the size leaves
an image layer with neither position nor dimensions.

WHAT IS KEPT AND WHAT IS RE-INFERRED. Offsets can be re-inferred as a flex
flow. Dimensions cannot be re-inferred from anything, because the content is
images with no intrinsic layout. So the size stays and the position goes, and
a 2D spread becomes a wrapping row — cards at their own size, filling rows in
reading order. That is the design's arrangement without its exact coordinates,
which is what a responsive reflow can honestly promise.
"""
import pytest

from services.jsx_to_schema import (
    JSXElement, _attach_style_passthrough, _filter_position_classes,
    _infer_absolute_flow,
)


def _El(cn):
    """A real JSXElement — `_infer_absolute_flow` isinstance-checks its
    children, so a duck-typed stub is silently skipped and every case reads as
    "nothing was laid out absolutely"."""
    return JSXElement(tag="div", attrs={"className": cn})


def _card(left, top, w=400, h=260):
    return _El(f"absolute left-[{left}px] top-[{top}px] w-[{w}px] h-[{h}px]")


# --------------------------------------------------------- the size survives

def test_a_card_keeps_its_width_and_height():
    out = _filter_position_classes(
        "absolute left-[120px] top-[340px] w-[420px] h-[260px] bg-white")
    assert "w-[420px]" in out and "h-[260px]" in out


def test_a_card_loses_its_position():
    """The offsets are the half a flex flow replaces."""
    out = _filter_position_classes(
        "absolute left-[120px] top-[340px] w-[420px] h-[260px]")
    for gone in ("absolute", "left-[120px]", "top-[340px]"):
        assert gone not in out.split()


def test_a_size_without_absolute_was_never_the_problem():
    """Unchanged behaviour — this case always kept its size."""
    assert "w-[420px]" in _filter_position_classes("w-[420px] flex")


@pytest.mark.parametrize("cn", [
    "absolute inset-[8.33%] w-[24px] h-[24px]",
    "absolute left-[0px] top-[0px] size-[16px]",
])
def test_decorative_svg_layers_are_still_composed_absolutely(cn):
    """An icon is layered vector shapes; its offsets ARE its meaning."""
    out = _filter_position_classes(cn, preserve_absolute=True)
    assert "absolute" in out.split()


# ------------------------------------------------- a kept width cannot overflow

def test_a_frame_width_is_capped_at_the_viewport():
    """Figma frames are authored wider than any screen — 3902px here. The size
    is the intent; the viewport is the limit."""
    props = {}
    _attach_style_passthrough(props, {"className": "absolute w-[3902px] h-[1975px]"})
    assert "w-[3902px]" in props["className"]
    assert "max-w-full" in props["className"]


def test_an_existing_max_width_is_not_doubled():
    props = {}
    _attach_style_passthrough(props, {"className": "w-[420px] max-w-[500px]"})
    assert props["className"].count("max-w-") == 1


def test_a_node_with_no_pixel_width_is_untouched():
    props = {}
    _attach_style_passthrough(props, {"className": "flex gap-2"})
    assert "max-w-full" not in props["className"]


# ------------------------------------------------------------- the grid wraps

def test_cards_spread_on_both_axes_wrap():
    """The dead branch. Four cards in a 2x2 grid spread on both axes, which
    used to return no flow at all."""
    flow, gap = _infer_absolute_flow(
        [_card(0, 0), _card(500, 0), _card(0, 300), _card(500, 300)])
    assert flow == "wrap"
    assert gap > 0


def test_a_single_row_is_still_a_row():
    flow, _ = _infer_absolute_flow([_card(0, 0), _card(500, 0), _card(1000, 0)])
    assert flow == "row"


def test_a_single_column_is_still_a_column():
    flow, _ = _infer_absolute_flow([_card(0, 0), _card(0, 300), _card(0, 600)])
    assert flow == "col"


def test_one_child_infers_nothing():
    assert _infer_absolute_flow([_card(0, 0)]) == (None, 0)


def test_children_that_are_not_absolute_infer_nothing():
    assert _infer_absolute_flow([_El("flex gap-2"), _El("block")]) == (None, 0)


def test_rounding_noise_is_not_a_grid():
    """Below the 8px threshold both axes are alignment, not layout — and a
    pair of near-identical offsets must not be promoted to a wrapping grid."""
    flow, _ = _infer_absolute_flow([_card(0, 0), _card(2, 3)])
    assert flow != "wrap"
