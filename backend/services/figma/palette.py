"""The design's scheme, read off the frames when the file publishes no tokens.

`design_system_from` projects a file's published variables onto `designSystem`
(§47). Most files publish none — the extraction records the gap as "tokens must
be derived from the frames themselves" — and then nothing derived them, so the
design system stayed the agent's generic palette and every surface painted
from it, the sign-in page first, looked like a different product from the
frames beside it.

The frames are not ambiguous about their scheme. Dev Mode writes every fill as
`bg-[#hex]`, every colour as `text-[#hex]`, every face as `font-['Name']`, and
a design uses its palette hundreds of times: on one real file the page ground
appeared 74 times, the accent 71, the rail 15, and the heading face was one
serif family against a body sans used a thousand times. Counting is the whole
method. Nothing here names a colour by what it is for except by where and how
often it is used, and every choice carries its count so the agent and the
reader can see the evidence rather than the verdict (§49).

WHAT IS NOT DONE. This never overrides a token the file DID publish — a
variable is the designer's statement; a frequency is an inference. And a file
with fewer than a handful of fills yields nothing, because three uses of a
colour is a screen, not a scheme.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

_BG = re.compile(r"\bbg-\[(#[0-9a-fA-F]{6})\]")
_TEXT = re.compile(r"\btext-\[(#[0-9a-fA-F]{6})\]")
_BORDER = re.compile(r"\bborder-\[(#[0-9a-fA-F]{6})\]")
_FONT = re.compile(r"\bfont-\['([^':\]]+)")

#: Fewer filled elements than this and the file is a sketch, not a scheme.
MIN_FILLS = 12


def _hex(value: str) -> str:
    return value.lower()


def _luminance(hex_colour: str) -> float:
    """Relative luminance, 0 (black) to 1 (white)."""
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _saturation(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hi, lo = max(r, g, b), min(r, g, b)
    return 0.0 if hi == 0 else (hi - lo) / hi


def _is_serif_or_display(family: str) -> bool:
    """A heading face is the one that is not the body face; when a file uses
    two, the less-used one that is not a mono is the display face."""
    return "mono" not in family.lower()


_TAG_RE = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9]*)([^>]*?)(/?)>")
_CLASS_RE = re.compile(r'className="([^"]*)"')
_PX_RE = {
    "w": re.compile(r"\bw-\[(\d+(?:\.\d+)?)px\]"),
    "h": re.compile(r"\bh-\[(\d+(?:\.\d+)?)px\]"),
    "size": re.compile(r"\bsize-\[(\d+(?:\.\d+)?)px\]"),
}
#: Tailwind's named fills Dev Mode still writes for pure black and white.
_NAMED = {"bg-white": "#ffffff", "bg-black": "#000000"}
# No trailing \b: after `]` there is no word boundary before a space, which is
# the same slip that once hid `left-0`.
_BG_ANY = re.compile(r"\bbg-(?:\[(#[0-9a-fA-F]{6})\]|(white|black))(?=\s|$|\")")


def _surfaces(code: str, size: tuple[float, float] | None = None) -> list[dict[str, Any]]:
    """Every filled element in a frame's code: fill, painted area, depth, and
    whether it carries a label of its own.

    Dev Mode writes each element's size as `w-[Npx] h-[Npx]` (or `*-full`,
    which is the parent's); walking the tags with a stack gives every fill
    the area it paints. Counting occurrences instead made a status bar's
    colour the page ground: on one real frame the green of eleven 6px bars
    outnumbered the light ground that one 1031x764 container painted.
    """
    out: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    pos = 0
    # THE ROOT IS THE FRAME. Its code says `size-full`, and the frame's own
    # width and height come from the screen record, so the root always has
    # the area it paints even when nothing inside is sized.
    frame = {"w": float(size[0]) if size else None, "h": float(size[1]) if size else None}
    for m in _TAG_RE.finditer(code):
        closing, tag, attrs, selfclose = m.group(1), m.group(2), m.group(3), m.group(4)
        # Text between the previous tag and this one belongs to the open element.
        between = code[pos:m.start()].strip()
        pos = m.end()
        if between and stack and any(ch.isalnum() for ch in between):
            # The label belongs to the nearest PAINTED ancestor: a button's
            # text sits in a <p> inside it, and the <p> has no fill.
            for el in reversed(stack):
                if el["fill"]:
                    el["label"] = True
                    break
        if closing:
            if stack:
                stack.pop()
            continue
        cls = (_CLASS_RE.search(attrs) or [None, ""])[1]
        parent = stack[-1] if stack else frame
        size = _PX_RE["size"].search(cls)
        w = float(size.group(1)) if size else None
        h = float(size.group(1)) if size else None
        mw, mh = _PX_RE["w"].search(cls), _PX_RE["h"].search(cls)
        if mw: w = float(mw.group(1))
        if mh: h = float(mh.group(1))
        # An axis is the parent's only when the element says so (`w-full`,
        # `size-full`, `flex-1`, `grow`, `self-stretch`); an axis nothing sets
        # is unknown, and an unknown area is no area. Giving every unsized
        # element its parent's size made a 6px-tall status chip the largest
        # surface on the page.
        fills_w = size is not None or bool(re.search(r"\b(w-full|flex-1|grow|self-stretch|basis-full)\b", cls))
        fills_h = size is not None or bool(re.search(r"\b(h-full|flex-1|grow|self-stretch)\b", cls))
        if w is None: w = parent["w"] if (fills_w or not stack) else None
        if h is None: h = parent["h"] if (fills_h or not stack) else None
        fill = None
        bg = _BG_ANY.search(cls)
        if bg:
            fill = _hex(bg.group(1)) if bg.group(1) else _NAMED["bg-" + bg.group(2)]
        nid = re.search(r'data-node-id="([^"]+)"', attrs)
        el = {"tag": tag, "w": w, "h": h, "fill": fill, "depth": len(stack), "label": False,
              "cls": cls, "node_id": nid.group(1) if nid else None}
        if fill:
            out.append(el)
        if not selfclose and tag not in ("img", "br", "input"):
            stack.append(el)
    for el in out:
        el["area"] = (el["w"] or 0.0) * (el["h"] or 0.0)
    return out


def from_code(codes: Iterable[str],
              sizes: Iterable[tuple[float, float] | None] | None = None) -> dict[str, Any]:
    """The scheme the frames use, with the evidence that justifies it.

    ``sizes`` gives each frame's width and height, so its root paints an area
    even when nothing inside is sized. Returns ``{"colors": {...},
    "typography": {...}, "evidence": {...}}`` or ``{}`` when the frames do
    not carry enough to say.
    """
    text: Counter = Counter()
    border: Counter = Counter()
    fonts: Counter = Counter()
    surfaces: list[dict[str, Any]] = []
    sizes = list(sizes or [])
    for i, code in enumerate(codes):
        code = code or ""
        text.update(_hex(c) for c in _TEXT.findall(code))
        border.update(_hex(c) for c in _BORDER.findall(code))
        fonts.update(_FONT.findall(code))
        surfaces.extend(_surfaces(code, sizes[i] if i < len(sizes) else None))

    if len(surfaces) < MIN_FILLS:
        return {}

    colors: dict[str, str] = {}
    evidence: dict[str, Any] = {}
    uses: Counter = Counter(el["fill"] for el in surfaces)

    # THE GROUND IS THE LARGEST SURFACE PAINTED. A tie goes to the deeper
    # element — it paints over the other. `bg-white` on the root behind a
    # full-size `#f3f3f1` app container is the app container.
    # When nothing is sized — a fixture, a file whose code carries no sizes —
    # the count stands in for the area, as it did before areas were read.
    sized = any(el["area"] > 0 for el in surfaces)
    largest = (max(surfaces, key=lambda el: (el["area"], el["depth"])) if sized
               else max(surfaces, key=lambda el: uses[el["fill"]]))
    background = largest["fill"]
    colors["background"] = background
    # Evidence is a number per key (the contract says so): the area painted
    # when sizes are known, else how often the fill is used.
    evidence["background"] = round(largest["area"]) if sized else uses[background]

    # THE RAIL IS THE LARGEST SURFACE THAT CONTRASTS WITH THE GROUND — a light
    # design has a dark sidebar (and vice versa), one per screen, tall.
    lum_bg = _luminance(background)
    contrasting = [el for el in surfaces
                   if el["fill"] != background and abs(_luminance(el["fill"]) - lum_bg) > 0.4]
    if contrasting:
        # Unsized, the rail is the fill that contrasts MOST, then the one used
        # most — a light design's dark sidebar, not its gold buttons.
        rail = (max(contrasting, key=lambda el: (el["area"], el["depth"])) if any(el["area"] > 0 for el in contrasting)
                else max(contrasting, key=lambda el: (abs(_luminance(el["fill"]) - lum_bg), uses[el["fill"]])))
        colors["sidebarBackground"] = rail["fill"]
        evidence["sidebarBackground"] = round(rail["area"]) if rail["area"] > 0 else uses[rail["fill"]]

    # THE ACCENT IS THE COLOUR OF THINGS YOU PRESS: the saturated fill used
    # most on elements that carry a label — a button, an active nav item, a
    # chip. A progress bar is saturated too and has no label, which is how
    # eleven green bars were once taken for the brand over two red buttons.
    excluded = {background, colors.get("sidebarBackground")}
    labelled: Counter = Counter(el["fill"] for el in surfaces
                                if el["label"] and el["fill"] not in excluded
                                and _saturation(el["fill"]) > 0.25)
    saturated: Counter = Counter(el["fill"] for el in surfaces
                                 if el["fill"] not in excluded and _saturation(el["fill"]) > 0.25)
    pick = labelled or saturated
    if pick:
        accent, n_acc = pick.most_common(1)[0]
        colors["primary"] = accent
        colors["accent"] = accent
        evidence["primary"] = labelled.get(accent, 0) or uses[accent]

    # FOREGROUND IS THE TEXT COLOUR THAT CONTRASTS MOST WITH THE GROUND among
    # those used substantially — a dashboard writes more captions than
    # headings, so "most used" named the muted grey-green over the black the
    # values and titles are set in. MUTED is the most-used other legible colour.
    legible = [(c, n) for c, n in text.items() if abs(_luminance(c) - lum_bg) > 0.3]
    if legible:
        top = max(n for _c, n in legible)
        substantial = [(c, n) for c, n in legible if n * 3 >= top]
        fg, n_fg = max(substantial, key=lambda cn: (abs(_luminance(cn[0]) - lum_bg), cn[1]))
        colors["foreground"] = fg
        evidence["foreground"] = n_fg
        muted = [(c, n) for c, n in legible if c != fg]
        if muted:
            colors["mutedForeground"] = max(muted, key=lambda cn: cn[1])[0]

    if border:
        colors["border"] = border.most_common(1)[0][0]
        evidence["border"] = border.most_common(1)[0][1]

    typography: dict[str, str] = {}
    if fonts:
        ranked = fonts.most_common()
        body = ranked[0][0]
        typography["fontFamilyBase"] = body.replace("_", " ")
        evidence["fontFamilyBase"] = ranked[0][1]
        display = next((f for f, _n in ranked[1:] if _is_serif_or_display(f)), None)
        if display:
            typography["fontFamilyHeading"] = display.replace("_", " ")
            evidence["fontFamilyHeading"] = fonts[display]
        mono = next((f for f, _n in ranked if "mono" in f.lower()), None)
        if mono:
            typography["fontFamilyNumeric"] = mono.replace("_", " ")

    out: dict[str, Any] = {"colors": colors, "evidence": evidence}
    if typography:
        out["typography"] = typography
    return out


def from_screens(screens: Iterable[Any]) -> dict[str, Any]:
    """`from_code` over a DesignReference's screens."""
    screens = list(screens)
    return from_code(
        [str((getattr(s, "structure", None) or {}).get("code") or "") for s in screens],
        [((getattr(s, "width", None) or 0), (getattr(s, "height", None) or 0))
         if getattr(s, "width", None) and getattr(s, "height", None) else None for s in screens],
    )
