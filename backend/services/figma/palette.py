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

#: Fewer fills than this and the file is a sketch, not a scheme.
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


def from_code(codes: Iterable[str]) -> dict[str, Any]:
    """The scheme the frames use, with the counts that justify it.

    Returns ``{"colors": {...}, "typography": {...}, "evidence": {...}}`` or
    ``{}`` when the frames do not carry enough to say.
    """
    bg: Counter = Counter()
    text: Counter = Counter()
    border: Counter = Counter()
    fonts: Counter = Counter()
    for code in codes:
        code = code or ""
        bg.update(_hex(c) for c in _BG.findall(code))
        text.update(_hex(c) for c in _TEXT.findall(code))
        border.update(_hex(c) for c in _BORDER.findall(code))
        fonts.update(_FONT.findall(code))

    if sum(bg.values()) < MIN_FILLS:
        return {}

    colors: dict[str, str] = {}
    evidence: dict[str, Any] = {}

    # THE GROUND IS THE FILL USED MOST. Pages are mostly background.
    background, n_bg = bg.most_common(1)[0]
    colors["background"] = background
    evidence["background"] = n_bg

    # THE RAIL IS THE DARKEST FILL USED ON MORE THAN ONE SCREEN — a light design
    # has a dark sidebar (and vice versa), and it is used once per screen.
    lum_bg = _luminance(background)
    candidates = [(c, n) for c, n in bg.items() if n >= 2 and abs(_luminance(c) - lum_bg) > 0.4]
    if candidates:
        rail = max(candidates, key=lambda cn: (abs(_luminance(cn[0]) - lum_bg), cn[1]))
        colors["sidebarBackground"] = rail[0]
        evidence["sidebarBackground"] = rail[1]

    # THE ACCENT IS THE MOST-USED SATURATED FILL that is neither ground nor rail.
    # Status chips (green/amber/red) are saturated too, so the accent must also
    # out-count each of them — an accent is used everywhere, a chip in one place.
    saturated = [(c, n) for c, n in bg.items()
                 if c not in (background, colors.get("sidebarBackground")) and _saturation(c) > 0.25]
    if saturated:
        accent, n_acc = max(saturated, key=lambda cn: cn[1])
        colors["primary"] = accent
        colors["accent"] = accent
        evidence["primary"] = n_acc

    # FOREGROUND IS THE MOST-USED TEXT COLOUR THAT READS ON THE GROUND.
    legible = [(c, n) for c, n in text.items() if abs(_luminance(c) - lum_bg) > 0.3]
    if legible:
        fg, n_fg = max(legible, key=lambda cn: cn[1])
        colors["foreground"] = fg
        evidence["foreground"] = n_fg
        # Muted text: the next most-used legible colour, lighter than the foreground.
        muted = [(c, n) for c, n in legible if c != fg and _luminance(c) > _luminance(fg)]
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
    return from_code(
        str((getattr(s, "structure", None) or {}).get("code") or "") for s in screens
    )
