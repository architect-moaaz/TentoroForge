"""A page built FROM a Figma frame is drawn in the frame's coordinate space.

WHY A MODE AND NOT A DEFAULT. A flowed page has no fixed box, and every rule
here needs one. Reflowing is right for a page composed from the catalog; it is
wrong for a page that IS a drawing, because the drawing carries no flow to
recover. One real export: 626 nodes, 534 of them `absolute`, 251 `size-full`,
160 `inset-0` — and five pixel offsets in the whole file. There is nothing to
infer a flow from.

THE FOUR THINGS THAT HAD TO AGREE, each found by measuring the rendered DOM:

1. The root is the frame's size. `size-full` means "be my parent", and the
   parent is the page — so the root became the viewport, and children placed by
   percentage against 3902px landed somewhere else. It was substituting
   `min-h-screen w-full`, the one width the design was not drawn at.

2. Composition layers keep their positioning. On a sized canvas an absolute
   node has a box to resolve against, so it is composition, not flow abuse.

3. `contents` wrappers dissolve. Figma wraps each card in `absolute contents
   left-[x] top-[y]`; `display: contents` generates NO box, so it cannot be
   the containing block its percentage-inset children need. Measured: 625 of
   632 elements were 0x0 while the canvas itself was correctly 3902x1975.

4. A dissolved wrapper stays static. Making a parent of absolute children
   `relative` is right in a flowed page and wrong here — the percentages are
   in FRAME coordinates. As `relative` each wrapper became a 3902x48 box and
   `inset-[6.23%_93.93%_88%_3.08%]` computed to `0px 3902px 48px 0px`.

None of this shows up in a schema diff: the tree had 626 nodes and every asset
on disk in both the broken and working cases. It only shows up in a box model,
which is why these assertions are about classNames and geometry rather than
node counts.
"""
import pytest

from services.jsx_to_schema import transform_jsx_to_schema

FRAME = (3902.0, 1975.0)

JSX = """
export default function Frame() {
  return (
    <div className="bg-[#ededed] relative size-full" data-node-id="1:25">
      <div className="absolute contents left-[120px] top-[102px]">
        <div className="absolute inset-[6.23%_93.93%_88%_3.08%]">
          <img className="absolute block inset-0 max-w-none size-full" src="a.svg" alt="" />
        </div>
      </div>
    </div>
  );
}
"""


def _root(canvas):
    return transform_jsx_to_schema(JSX, {}, canvas=canvas)["children"][0]


def _find(node, needle):
    """Every node whose className contains `needle`."""
    out = []
    if isinstance(node, dict):
        if needle in ((node.get("props") or {}).get("className") or ""):
            out.append(node)
        for c in node.get("children") or []:
            out.extend(_find(c, needle))
    return out


# ------------------------------------------------------- 1. the root is a box

def test_the_root_carries_the_frames_size():
    style = (_root(FRAME).get("props") or {}).get("style") or {}
    assert style.get("width") == "3902px"
    assert style.get("height") == "1975px"
    assert style.get("position") == "relative"


def test_the_root_no_longer_claims_to_be_its_parent():
    """`size-full` on the root is what made the frame viewport-sized."""
    assert "size-full" not in ((_root(FRAME).get("props") or {}).get("className") or "")


def test_without_a_canvas_the_root_is_unchanged():
    """Every non-Figma page, and any frame whose size was never recorded, must
    keep the flowed behaviour exactly."""
    props = _root(None).get("props") or {}
    assert "style" not in props or "width" not in (props.get("style") or {})
    assert "min-h-screen" in (props.get("className") or "")


# --------------------------------------------- 2. composition layers survive

def test_a_percentage_inset_card_keeps_its_position_on_a_canvas():
    cards = _find(_root(FRAME), "inset-[6.23%")
    assert cards, "the card node vanished"
    assert "absolute" in (cards[0]["props"]["className"]).split()


def test_the_image_layer_keeps_its_fill():
    imgs = _find(_root(FRAME), "size-full")
    assert imgs, "the image layer lost its fill"
    assert "absolute" in imgs[0]["props"]["className"].split()


# ------------------------------------------------ 3. + 4. the wrapper dissolves

def test_a_contents_wrapper_is_dissolved():
    """`display: contents` generates no box, so it can never be the containing
    block — the class has to go, not be preserved."""
    assert not _find(_root(FRAME), "contents")


def test_a_dissolved_wrapper_is_not_positioned():
    """Neither its own `absolute` nor an injected `relative`: either one makes
    it the reference box for coordinates that mean the frame."""
    root = _root(FRAME)
    for node in root.get("children") or []:
        cn = ((node.get("props") or {}).get("className") or "").split()
        assert "absolute" not in cn
        assert "relative" not in cn


def test_the_wrappers_offsets_go_with_it():
    """`left-[120px] top-[102px]` was already inert under `display: contents`;
    applying it now would double-offset every child."""
    root = _root(FRAME)
    for node in root.get("children") or []:
        cn = (node.get("props") or {}).get("className") or ""
        assert "left-[120px]" not in cn and "top-[102px]" not in cn


# ------------------------------------------------------------- the mode resets

def test_canvas_mode_does_not_leak_between_transforms():
    """It is module state for the duration of one transform. A flowed page
    transformed after a canvas page must not inherit the canvas rules."""
    _root(FRAME)
    flowed = _root(None)
    assert "min-h-screen" in ((flowed.get("props") or {}).get("className") or "")


def test_the_marker_carries_the_size_to_the_renderer():
    """`FigmaCanvas` scales by (available width / frame width), so the frame
    width has to reach the page schema."""
    import asyncio
    import tempfile

    from services.figma_mcp_pipeline import build_schema_from_jsx

    with tempfile.TemporaryDirectory() as tmp:
        schema, _assets = asyncio.run(
            build_schema_from_jsx(JSX, tmp, canvas=FRAME))
    canvas = schema["_figmaCanvas"]

    assert {k: canvas[k] for k in ("width", "height")} == {"width": 3902.0, "height": 1975.0}

    assert canvas["fit"] in ("scale", "fluid"), "how the frame meets a narrower viewport travels with its size"
