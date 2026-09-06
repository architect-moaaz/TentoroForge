"""The rectangles a frame is made of, in the frame's own coordinates.

WHY THIS EXISTS. A flattened Figma export tells you nothing by name. On a real
dashboard every one of 274 `data-name` attributes was `Vector`, `Group`,
`Clip path group` or `Mask group`, and Figma's own metadata was no better —
`Group 3`, `clip2_568_17068`. The designer never named a layer, so there is no
string anywhere that says "this is the ticket volume chart".

What the export DOES carry is geometry: 248 positioned wrappers, each with a
`data-node-id` and a percentage inset. That is enough to say WHERE every piece
of the design is and how big it is, which is the input any further
understanding needs — a screenshot to look at, a node id to ask Figma about,
and an area to rank candidates by.

WHY PERCENTAGES RESOLVE AGAINST THE FRAME. Figma writes each card's inset
relative to the frame, and the wrappers between them carry `display: contents`
— no box, so no containing block of their own. `jsx_to_schema` dissolves those
wrappers on a canvas for exactly this reason, leaving the frame as the
reference. So a card's inset can be read directly as frame coordinates without
walking its ancestors.

This module measures and does not interpret. Deciding that a rectangle is a bar
chart is a judgement, and judgements belong to an agent that can be wrong
visibly (§49) — not to a regex over class names.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: `<div className="absolute inset-[T%_R%_B%_L%]" data-node-id="1:33">`.
#: Anchored on the two attributes together: a wrapper without an id cannot be
#: asked about later, and an id without an inset has no rectangle.
_CARD = re.compile(
    r'<div\s+className="[^"]*\binset-\[\s*'
    r'(-?[\d.]+)%[_\s]+(-?[\d.]+)%[_\s]+(-?[\d.]+)%[_\s]+(-?[\d.]+)%\s*\]'
    r'[^"]*"\s+data-node-id="([^"]+)"'
)


@dataclass(frozen=True)
class Region:
    """One rectangle of the design, in frame pixels."""

    node_id: str
    x: float
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def as_dict(self) -> dict:
        return {"nodeId": self.node_id, "x": round(self.x, 1),
                "y": round(self.y, 1), "width": round(self.width, 1),
                "height": round(self.height, 1)}


def regions(code: str, frame_width: float, frame_height: float) -> list[Region]:
    """Every positioned card in ``code``, largest first.

    Ordered by area because that is the order they matter in: a dashboard's
    charts and tables are its big rectangles, and its icons are the small ones.
    A caller that can only afford to look at twenty things should look at the
    twenty biggest.
    """
    if frame_width <= 0 or frame_height <= 0:
        return []

    out: list[Region] = []
    for top, right, bottom, left, node_id in _CARD.findall(code):
        t, r, b, l = (float(top) / 100, float(right) / 100,
                      float(bottom) / 100, float(left) / 100)
        width = frame_width * (1.0 - l - r)
        height = frame_height * (1.0 - t - b)
        # A negative or zero box is a mask artefact, not a piece of the design.
        if width <= 0 or height <= 0:
            continue
        out.append(Region(node_id=node_id, x=frame_width * l,
                          y=frame_height * t, width=width, height=height))

    out.sort(key=lambda reg: reg.area, reverse=True)
    return out


def _without_wrappers(boxes: list[dict]) -> list[dict]:
    def rect(b):
        return (float(b.get("x") or 0), float(b.get("y") or 0), float(b.get("width") or 0), float(b.get("height") or 0))

    def inside(inner, outer) -> bool:
        ix, iy, iw, ih = rect(inner); ox, oy, ow, oh = rect(outer)
        return ix >= ox - 0.5 and iy >= oy - 0.5 and ix + iw <= ox + ow + 0.5 and iy + ih <= oy + oh + 0.5 and (iw * ih) < (ow * oh)

    wrappers: set[int] = set()
    for i, a in enumerate(boxes):
        contained = [b for j, b in enumerate(boxes) if j != i and inside(b, a)]
        direct = [b for b in contained if not any(c is not b and inside(b, c) for c in contained)]
        if len(direct) == 1:
            _, _, w, h = rect(a); _, _, cw, ch = rect(direct[0])
            if w * h > 0 and (cw * ch) / (w * h) >= 0.9:
                wrappers.add(i)
    return [b for i, b in enumerate(boxes) if i not in wrappers]


def candidates(code: str, frame_width: float, frame_height: float, *,
               min_side: float = 120.0, limit: int = 32,
               boxes: list[dict] | None = None) -> list[Region]:
    """The regions worth looking at, and no more than ``limit`` of them.

    TWO FILTERS, BOTH ABOUT COST RATHER THAN CORRECTNESS. Looking at a region
    means a screenshot and a share of a vision call, and a frame has hundreds
    of them — 248 on the dashboard this was written against, of which the vast
    majority are icon-sized vectors that no amount of looking will turn into a
    chart.

    `min_side` drops those: a chart legible enough to have been drawn is at
    least a hundred-odd pixels on both sides. `limit` caps what remains, taking
    the largest, so a pathological frame cannot turn one page into hundreds of
    model calls.

    NESTED RECTANGLES ARE NOT DEDUPLICATED HERE. A card and the chart inside it
    are both real regions and both worth showing to something that can tell
    them apart; collapsing them by containment would be this module guessing
    which one is "the" region, which is precisely the judgement it must not
    make.
    """
    # A card is card-sized on its long side; its short side may be less — a
    # KPI tile is 172 by 110 — so the floor on the short side is two thirds.
    def _card_sized(w: float, h: float) -> bool:
        return max(w, h) >= min_side and min(w, h) >= min_side * 2 / 3

    found = [r for r in regions(code, frame_width, frame_height)
             if _card_sized(r.width, r.height)]
    # AN AUTO-LAYOUT EXPORT HAS NO INSETS. Dev Mode writes a percentage inset
    # only for absolutely positioned layers; a frame built with auto-layout
    # carries sizes instead — `w-[172px] h-[110px]`, or the parent's size for
    # a `w-full` child — and on such a frame this returned nothing, so no card
    # was ever looked at and every number on a dashboard stayed the drawn
    # text. Its cards are its filled boxes with a node id and a size; where
    # they sit is not known from the classes, which the crop does not need.
    seen = {r.node_id for r in found}
    # A WRAPPER IS ITS CHILD'S RECTANGLE TWICE. Auto-layout exports wrap a
    # card in a margin container a few pixels larger; ranked by area, the
    # twenty-four largest boxes on a dashboard were eleven cards and their
    # wrappers, and the KPI tiles fell below the cap. A box whose one directly
    # contained box covers nine tenths of it is the wrapper, not a region —
    # no kind is judged here, only that two rectangles are one.
    boxes = _without_wrappers(list(boxes or []))
    # THE FILE'S OWN GEOMETRY, WHEN THE EXTRACTION KEPT IT. `get_metadata`
    # answers with every element's box, auto-layout or not; a screen's
    # `structure.boxes` is that list in the frame's own coordinates and is the
    # honest source of where each card sits. Sizes read off classes are the
    # fallback for a reference extracted before boxes were kept.
    for box in boxes or []:
        nid = str(box.get("id") or box.get("node_id") or "")
        w, h = float(box.get("width") or 0), float(box.get("height") or 0)
        if not nid or nid in seen or not _card_sized(w, h):
            continue
        if w >= frame_width and h >= frame_height:
            continue
        # A BOX AS TALL AS THE FRAME IS A COLUMN — the rail, the content
        # column, the page's own scroll container — and a column is the
        # page's structure, not a card on it.
        if h >= 0.9 * frame_height:
            continue
        seen.add(nid)
        found.append(Region(node_id=nid, x=float(box.get("x") or 0), y=float(box.get("y") or 0),
                            width=w, height=h))
    from services.figma.palette import _surfaces
    for el in _surfaces(code, (frame_width, frame_height)):
        nid = el.get("node_id")
        w, h = el.get("w") or 0.0, el.get("h") or 0.0
        if not nid or nid in seen or not _card_sized(w, h):
            continue
        # The frame itself and its full-size wrappers are the page, not a card.
        if w >= frame_width and h >= frame_height:
            continue
        seen.add(nid)
        found.append(Region(node_id=nid, x=0.0, y=0.0, width=w, height=h))
    found.sort(key=lambda reg: reg.area, reverse=True)
    return found[:limit]
