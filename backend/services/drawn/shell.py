"""What every frame shares, and what is not the application at all.

A design of a back office draws its sidebar and top bar on every screen. In
the app they are one frame around every page, so they are lifted out once —
the SHELL — and each screen is converted without them (its PAGE ROOT is
what is left). Found by geometry, the way `react_reference.content_box` cuts
the drawing for comparison: a column along the frame's left edge as tall as
the frame, a bar along the top of what is right of it.

The prototype's own furniture is left out of everything: a layer the designer
named as the prototype's ("Demo nav (prototype only)"), and any floating
layer drawn at the same place on most screens that is not the shell (a
chapter switcher, a "‹ Back · Next ›" bar). What was left out is reported, so
the person sees it in the flow document rather than missing it later.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

#: A floating layer on at least this share of screens is the prototype's.
REPEATED = 0.6
_PROTOTYPE_NAME = re.compile(r"prototype|demo nav|presenter|walkthrough", re.I)


def _box(node: dict) -> tuple[float, float, float, float] | None:
    box = node.get("absoluteBoundingBox") or {}
    try:
        return float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])
    except (KeyError, TypeError, ValueError):
        return None


def _children(node: dict) -> list[dict]:
    return [c for c in node.get("children") or [] if isinstance(c, dict) and c.get("visible") is not False]


@dataclass
class Screen:
    """One frame, read for its shell."""
    document: dict
    sidebar: dict | None = None
    topbar: dict | None = None
    #: The node the page is converted from: the frame less the shell.
    page_root: dict | None = None
    #: Node ids left out of the page (the shell, the prototype's furniture).
    skip: set[str] = field(default_factory=set)
    #: What was left out as not part of the application, by layer name.
    dropped: list[str] = field(default_factory=list)


def read_screen(document: dict) -> Screen:
    """A frame's sidebar, top bar and the page between them."""
    screen = Screen(document=document)
    frame = _box(document)
    if frame is None:
        screen.page_root = document
        return screen
    fx, fy, fw, fh = frame
    for child in _children(document):
        if _PROTOTYPE_NAME.search(str(child.get("name") or "")):
            screen.skip.add(str(child.get("id")))
            screen.dropped.append(str(child.get("name") or ""))
    left = None
    for child in _children(document):
        box = _box(child)
        if box and abs(box[0] - fx) < 2 and box[2] < fw * 0.3 and box[3] > fh * 0.8 \
                and str(child.get("id")) not in screen.skip:
            left = child
            break
    if left is not None:
        screen.sidebar = left
        screen.skip.add(str(left.get("id")))
        rest = [c for c in _children(document) if str(c.get("id")) not in screen.skip]
        # THE PAGE IS THE WIDE COLUMN BESIDE IT. Converted as the root, so
        # the page fills whatever width the app gives it. Chosen from the
        # layout's own columns: a dialog's scrim covers the whole frame, so it
        # is wider than the page, and 40 DITANS dialogs and drawers were
        # converted as nothing but their scrim (2026-10-30).
        # A frame without auto-layout marks nothing as floating: there the
        # page is the widest layer that starts beside the sidebar, and what is
        # drawn after it lies over it.
        sbox = _box(left)
        edge = sbox[0] + sbox[2] if sbox else fx
        flow = [c for c in rest if c.get("layoutPositioning") != "ABSOLUTE"
                and (_box(c) or (edge, 0, 0, 0))[0] >= edge - 2]
        column = max(flow or rest, key=lambda c: (_box(c) or (0, 0, 0, 0))[2], default=None)
        if column is not None:
            # In auto-layout a layer after the page is the next column (a side
            # panel), not something over it; only a free frame stacks by order.
            free = str(document.get("layoutMode") or "NONE") == "NONE"
            after = rest[rest.index(column) + 1:] if free else []
            screen.page_root = _with_overlays(column, [c for c in rest if c is not column and (
                c.get("layoutPositioning") == "ABSOLUTE" or c in after)], frame)
        else:
            screen.page_root = document
    else:
        screen.page_root = document
    # THE TOP BAR: along the top of the page, as wide as it, short.
    root = screen.page_root
    rbox = _box(root)
    if rbox:
        for child in _children(root):
            box = _box(child)
            if box and abs(box[1] - rbox[1]) < 2 and box[2] > rbox[2] * 0.6 and 24 < box[3] < min(140, rbox[3] * 0.2):
                screen.topbar = child
                screen.skip.add(str(child.get("id")))
                break
    return screen


def _with_overlays(column: dict, overlays: list[dict], frame: tuple[float, float, float, float] | None = None) -> dict:
    """The page with what is drawn over it — a dialog, a drawer, their scrim —
    laid over it, each kept within the page: a scrim drawn across the whole
    frame covers the page, the shell beside it being the app's."""
    cbox = _box(column)
    if not overlays or cbox is None:
        return column
    cx, _cy, cw, _ch = cbox
    laid = []
    for node in overlays:
        box = dict(node.get("absoluteBoundingBox") or {})
        try:
            left, right = max(float(box["x"]), cx), min(float(box["x"]) + float(box["width"]), cx + cw)
        except (KeyError, TypeError, ValueError):
            continue
        if right <= left:
            continue
        held = _held(left, right, box, cbox, frame)
        placed = {**box, "x": left, "width": right - left}
        # CENTRED MEANS CENTRED ON THE PAGE: drawn centred on the whole frame,
        # it sat half a sidebar off the page's middle — and further off where
        # the sidebar folds away.
        if held["horizontal"] == "CENTER":
            placed["x"] = cx + (cw - placed["width"]) / 2
        if held["vertical"] == "CENTER" and placed.get("height") is not None:
            placed["y"] = cbox[1] + (cbox[3] - float(placed["height"])) / 2
        laid.append({**node, "layoutPositioning": "ABSOLUTE", "constraints": held, "absoluteBoundingBox": placed})
    return {**column, "children": [*(column.get("children") or []), *laid]} if laid else column


def _held(left: float, right: float, box: dict, page: tuple[float, float, float, float],
          frame: tuple[float, float, float, float] | None = None) -> dict:
    """How a layer laid over the page keeps its place as the page changes size,
    read from where it is drawn ON THE PAGE: its own constraints were the
    frame's, sidebar included. Across the page it stretches (a scrim); at an
    edge it stays there (a drawer); about the middle it stays centred (a
    dialog)."""
    px, py, pw, ph = page
    try:
        top, height = float(box["y"]), float(box["height"])
    except (KeyError, TypeError, ValueError):
        top, height = py, ph

    fx, fy, fw, fh = frame or page

    def along(start: float, length: float, origin: float, room: float, low: str, high: str, both: str,
              whole: tuple[float, float]) -> str:
        if length >= room * 0.95:
            return both
        if abs(start - origin) <= 4:
            return low
        if abs(start + length - origin - room) <= 4:
            return high
        # About the middle — of the page, or of the whole frame, as a dialog
        # is drawn: centred on the screen, sidebar included, a little high.
        centre = start + length / 2
        for o, r in ((origin, room), whole):
            if abs(centre - o - r / 2) <= max(24.0, r * 0.1):
                return "CENTER"
        return low

    return {"horizontal": along(left, right - left, px, pw, "LEFT", "RIGHT", "LEFT_RIGHT", (fx, fw)),
            "vertical": along(top, height, py, ph, "TOP", "BOTTOM", "TOP_BOTTOM", (fy, fh))}


def _floating(node: dict, depth: int = 0):
    """Layers drawn over the layout, not in it, within two levels of the frame."""
    for child in _children(node):
        if child.get("layoutPositioning") == "ABSOLUTE" or str(node.get("layoutMode") or "") not in ("HORIZONTAL", "VERTICAL"):
            yield child
        if depth < 1:
            yield from _floating(child, depth + 1)


def read_all(documents: dict[str, dict]) -> dict[str, Screen]:
    """Every frame read for its shell, with the floating layers repeated on
    most of them left out as the prototype's."""
    screens = {key: read_screen(doc) for key, doc in documents.items()}
    if len(screens) < 3:
        return screens
    seen: Counter = Counter()
    for screen in screens.values():
        names = set()
        for node in _floating(screen.document):
            box = _box(node)
            fb = _box(screen.document)
            if not box or not fb or str(node.get("id")) in screen.skip:
                continue
            names.add((str(node.get("name") or ""), round((box[0] - fb[0]) / 8), round((box[1] - fb[1]) / 8)))
        seen.update(names)
    repeated = {k for k, n in seen.items() if n >= REPEATED * len(screens) and k[0]}
    for screen in screens.values():
        fb = _box(screen.document)
        for node in _floating(screen.document):
            box = _box(node)
            if not box or not fb:
                continue
            key = (str(node.get("name") or ""), round((box[0] - fb[0]) / 8), round((box[1] - fb[1]) / 8))
            if key in repeated and str(node.get("id")) not in screen.skip \
                    and node is not screen.sidebar and node is not screen.topbar:
                screen.skip.add(str(node.get("id")))
                screen.dropped.append(key[0])
    return screens


def _words(node: dict | None) -> frozenset[str]:
    out: set[str] = set()

    def walk(n: dict) -> None:
        if str(n.get("type") or "") == "TEXT" and str(n.get("characters") or "").strip():
            out.add(str(n["characters"]).strip())
        for c in _children(n):
            walk(c)

    if node:
        walk(node)
    return frozenset(out)


def the_shell(screens: dict[str, Screen]) -> tuple[str, Screen] | None:
    """The screen whose sidebar and top bar stand for every screen's, when
    most screens draw one: the one whose sidebar says what most screens'
    sidebars say, with a top bar where one is drawn.

    THE TYPICAL SIDEBAR, NOT THE FIRST. Taken from the first screen, the
    recruiter's frame was the one drawn while the organisation awaits
    verification ("Verification pending" under its name) and the candidate's
    had its Profile group opened out (DITANS, 2026-10-29)."""
    with_side = [(k, s) for k, s in screens.items() if s.sidebar is not None]
    if len(with_side) < max(1, len(screens) // 2):
        return None
    both = [(k, s) for k, s in with_side if s.topbar is not None] or with_side
    seen = Counter(_words(s.sidebar) for _k, s in with_side)
    return max(both, key=lambda ks: seen[_words(ks[1].sidebar)])


def shell_markup(screen: Screen, emitter: Any, name: str = "DrawnShell") -> str:
    """The shell as one component: the drawn sidebar, the drawn top bar, and
    the page where the frames draw it (`children`)."""
    document = screen.document
    root_classes = " ".join(emitter._layout_classes(document) + ["w-full", "min-h-screen"]
                            + emitter._paint_classes(document, {}))
    side = emitter.element(screen.sidebar, document, 2) if screen.sidebar else ""
    page = screen.page_root if screen.page_root is not document else None
    column_classes = " ".join(emitter._layout_classes(page) + ["flex-1", "basis-0", "min-w-0", "self-stretch"]
                              + emitter._paint_classes(page, {})) if page else "flex flex-col flex-1 min-w-0"
    top = emitter.element(screen.topbar, page or document, 3) if screen.topbar else ""
    return (
        f"export default function {name}(props: {{ children?: React.ReactNode }}) {{\n"
        "  return (\n"
        f'    <div className="{root_classes}">\n'
        f"{side}"
        f'      <div className="{column_classes}">\n'
        f"{top}"
        '        <main className="flex-1 min-w-0 self-stretch">{props.children}</main>\n'
        "      </div>\n"
        "    </div>\n"
        "  );\n"
        "}\n"
    )
