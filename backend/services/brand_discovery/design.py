"""The census, read as a design system. Deterministic, no model.

`site.py` counts what a page uses; this decides what those counts mean. It is
code rather than an agent for the same reason `services.figma.projection` is:
the numbers ARE the design language, and a model asked to extract them can
only paraphrase — round a hex, rename a role, pick the colour it expected a
company in that industry to have. Every paraphrase is a silent divergence from
the brand the user is holding us to, and they would never see which.

The output is `designSystem`-shaped — the same keys the Blueprint declares —
so projecting it into an application is a merge and not a translation. A
translation is exactly where `action_bg` quietly becomes `accent`.

WHAT IT REFUSES TO GUESS. A role the census cannot evidence is left out
rather than filled in. An absent `accent` lets the design agent's own choice
stand (the brand node merges over it, and a key that is not there does not
overwrite); an invented one replaces a considered decision with a hue nobody
picked. The one derivation this does make is the supporting scale around the
brand colour — `derive_palette` is the platform's existing colour theory and
it is honest about being derived, which the evidence records.
"""
from __future__ import annotations

import colorsys
import logging
import re
from collections import Counter

from services.brand_discovery.site import Reading

logger = logging.getLogger(__name__)

#: Saturation under this is a grey, a near-white or a near-black. Those are
#: the ground and the ink of a page, never its brand: a site whose most-used
#: colour is `#FFFFFF` has not told you it is a white company.
_NEUTRAL_SATURATION = 0.12

#: Lightness outside this band is a page's paper or its ink. The floor is
#: what keeps slate (`#0F172A` — saturated enough to pass the test above, and
#: body text on half the web) from being read as a second brand colour.
_BRAND_LIGHTNESS = (0.15, 0.88)

#: Near-white, for the one test that must not reject a dark colour. A button
#: whose background is black IS a brand statement — plenty of companies make
#: exactly that one — so the strongest signals are judged only against being
#: invisible: the same colour as the page's own ground, or white.
_NEAR_WHITE = 0.85

#: A role has to be used by more than a stray element before it counts. One
#: button on a page is a button; one element of a colour is a typo.
_MIN_USES = 2


def _hsl(hex_value: str) -> tuple[float, float, float]:
    v = hex_value.lstrip("#")
    r, g, b = (int(v[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h, s, l


def _is_neutral(hex_value: str) -> bool:
    _, s, l = _hsl(hex_value)
    lo, hi = _BRAND_LIGHTNESS
    return s < _NEUTRAL_SATURATION or not (lo <= l <= hi)


def _luminance(hex_value: str) -> float:
    """Relative luminance, WCAG's definition — used to pick readable ink."""
    v = hex_value.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(v[i:i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def readable_on(background: str) -> str:
    """Black or white, whichever a person can actually read on `background`.

    Not a preference — the contrast edge that guards the token contract
    rejects a primary whose foreground fails AA, and a brand colour with
    white text baked in regardless would fail it on every light brand.
    """
    return "#0F172A" if _luminance(background) > 0.45 else "#FFFFFF"


def _by_role(reading: Reading, role: str) -> list[tuple[str, int]]:
    """Colours used for `role`, most used first, ties broken by hex.

    The tie-break is what makes this deterministic: two colours used the same
    number of times must not swap places between two reads of the same site,
    because the swap would rewrite the brand of every app built afterwards.
    """
    counted = [(c.hex, c.roles.get(role, 0)) for c in reading.colors.values()]
    return sorted([(h, n) for h, n in counted if n >= _MIN_USES],
                  key=lambda hn: (-hn[1], hn[0]))


def _brand_color(reading: Reading) -> tuple[str | None, str]:
    """The company's colour, and the evidence for calling it that.

    In order of how strongly each says "this is us":

    1. A button's background. A site puts its brand on the thing it wants
       clicked; that is the least ambiguous statement a page makes.
    2. A link's colour. Sites that style no buttons still colour their links.
    3. The most-used non-neutral anywhere. Weakest, and often a section
       background, but a coloured page is saying something.
    """
    grounds = {h for h, _ in _by_role(reading, "background")[:1]}
    for role, why in (("action_bg", "the background of its buttons"),
                      ("link", "the colour of its links"),
                      ("heading", "the colour of its headings")):
        for hex_value, count in _by_role(reading, role):
            # Not the stricter `_is_neutral`: this is the page stating its
            # brand outright, and rejecting a black button here would send a
            # monochrome brand down to the "most used colour" fallback, which
            # on those sites returns whichever hue their illustrations use.
            if hex_value in grounds or _hsl(hex_value)[2] > _NEAR_WHITE:
                continue
            return hex_value, f"{why} ({count} elements)"

    ranked = sorted(
        ((c.hex, c.total) for c in reading.colors.values()
         if not _is_neutral(c.hex) and c.total >= _MIN_USES),
        key=lambda hn: (-hn[1], hn[0]))
    if ranked:
        return ranked[0][0], f"the colour used most across the page ({ranked[0][1]} elements)"
    return None, "no colour on the page was distinct enough to read as a brand"


def _ground_and_ink(reading: Reading) -> tuple[str | None, str | None]:
    """The page's own paper and ink, when it states them clearly.

    Taken only from the dominant use — a site whose background is 90% white
    and 10% grey sections has a white ground, and reading the grey would make
    every generated app look like one of that site's inset panels.
    """
    backgrounds = _by_role(reading, "background")
    texts = _by_role(reading, "text")
    ground = backgrounds[0][0] if backgrounds else None
    ink = texts[0][0] if texts else None
    # Ink that is not readable on the ground is a mis-read, not a design.
    if ground and ink and abs(_luminance(ground) - _luminance(ink)) < 0.2:
        ink = None
    return ground, ink


_SYSTEM_FAMILIES = {
    "sans-serif", "serif", "monospace", "system-ui", "-apple-system",
    "ui-sans-serif", "ui-serif", "ui-monospace", "blinkmacsystemfont",
    "segoe ui", "roboto", "helvetica", "arial", "inherit", "initial",
}


def _family(counter: Counter) -> str | None:
    """The most-used real family, or None when the site sets no type of its own.

    A site that names only `sans-serif` has not chosen a typeface, and
    recording "sans-serif" as the company's font would override a design
    agent's considered choice with the absence of one.
    """
    for name, _count in counter.most_common():
        if name and name.lower() not in _SYSTEM_FAMILIES:
            return name
    return None


_PX = re.compile(r"^([\d.]+)px$")


def _radius(reading: Reading) -> dict[str, str] | None:
    """The corner the site rounds its controls to, as a small scale.

    One measurement, not a census of every corner: a page has one radius
    decision and a hundred elements inheriting it, so the mode is the
    decision. The scale around it is derived, because `--radius-sm` and
    `--radius-lg` are things components ask for and a site does not publish.
    """
    values = [v for v, _ in reading.radii.most_common() if _PX.match(v)]
    if not values:
        return None
    # The most common non-zero, since `0px` is every element that was never
    # styled and would outvote the decision on any page.
    for value in values:
        px = float(_PX.match(value).group(1))
        if px > 0:
            base = px
            break
    else:
        return {"sm": "0px", "md": "0px", "lg": "0px", "control": "0px", "card": "0px"}
    return {
        "sm": f"{max(2, round(base / 2))}px",
        "md": f"{round(base)}px",
        "lg": f"{round(base * 1.75)}px",
        "control": f"{round(base)}px",
        "card": f"{round(base * 1.5)}px",
    }


def _density(reading: Reading) -> str:
    """How much air the site leaves, in the Blueprint's three words.

    Read off the body type size, which is the one measurement that tracks it
    reliably: a 14px body is a dashboard, an 18px body is a marketing site
    that wants to be read slowly. Defaults to `comfortable` — the Blueprint's
    own default — when the page states nothing.
    """
    sizes = [float(m.group(1)) for v, _ in reading.font_sizes.most_common()
             if (m := _PX.match(v))]
    body = [s for s in sizes if 10 <= s <= 24]
    if not body:
        return "comfortable"
    typical = sorted(body)[len(body) // 2]
    if typical <= 14:
        return "compact"
    if typical >= 18:
        return "spacious"
    return "comfortable"


def _elevation(reading: Reading) -> dict[str, str] | None:
    """Whether this company's surfaces float, and how far.

    Only the fact and a scale derived from it. Copying the site's own shadow
    string would carry its colour into a palette that is no longer its
    palette, and a shadow tinted for one brand on another brand's ground is
    the kind of thing nobody can name but everybody sees.
    """
    shadows = [s for s, _ in reading.shadows.most_common() if s and s != "none"]
    if not shadows:
        return {"sm": "none", "md": "none", "lg": "none"}
    return {
        "sm": "0 1px 2px 0 rgb(0 0 0 / 0.05)",
        "md": "0 4px 6px -1px rgb(0 0 0 / 0.08)",
        "lg": "0 12px 24px -8px rgb(0 0 0 / 0.12)",
    }


def design_system_from(reading: Reading) -> tuple[dict, dict]:
    """`(design, evidence)` — the design language, and why each part of it.

    `design` is `designSystem`-shaped and carries only what the site
    evidenced. `evidence` is the same facts in the form a person can read in
    Settings, because a palette nobody can argue with is a palette nobody can
    correct.
    """
    from services.color_theory import derive_palette

    evidence: dict = {
        "rendered": reading.rendered,
        "title": reading.title,
        "colorsSeen": len(reading.colors),
    }
    design: dict = {}
    colors: dict[str, str] = {}

    brand, why = _brand_color(reading)
    evidence["brandFrom"] = why
    if brand:
        evidence["brand"] = brand
        colors.update({
            "primary": brand,
            "primaryForeground": readable_on(brand),
            "ring": brand,
        })
        # The supporting scale is only derivable from a colour that HAS a hue.
        # `derive_palette("#000000")` returns two greys, and writing those as
        # `accent` and `secondary` would overwrite a design agent's considered
        # choices with the arithmetic of black — a monochrome brand has said
        # what its brand is and nothing about its second voice.
        if _hsl(brand)[1] >= _NEUTRAL_SATURATION:
            derived = derive_palette(brand)
            colors["accent"] = derived.accent
            colors["secondary"] = derived.secondary

    ground, ink = _ground_and_ink(reading)
    if ground:
        colors["background"] = ground
        # `card`/`surface` is the ground unless the site says otherwise; a
        # white card on a white ground is what most sites actually are.
        colors["card"] = ground
        evidence["background"] = ground
    if ink:
        colors["foreground"] = ink
        evidence["foreground"] = ink

    borders = _by_role(reading, "border")
    if borders:
        colors["border"] = borders[0][0]
        colors["input"] = borders[0][0]

    # A second distinct non-neutral, used somewhere structural, is a real
    # accent. Only taken when it is genuinely a different hue from the brand
    # — a lighter tint of the same colour is the brand, not a second one.
    if brand:
        brand_hue = _hsl(brand)[0]
        for hex_value, _count in sorted(
                ((c.hex, c.total) for c in reading.colors.values()
                 if not _is_neutral(c.hex) and c.total >= _MIN_USES),
                key=lambda hn: (-hn[1], hn[0])):
            if hex_value == brand:
                continue
            gap = abs(_hsl(hex_value)[0] - brand_hue)
            if min(gap, 1 - gap) > 0.08:
                colors["accent"] = hex_value
                evidence["accent"] = hex_value
                break

    if colors:
        design["colors"] = colors

    typography: dict[str, str] = {}
    body_font = _family(reading.fonts)
    heading_font = _family(reading.heading_fonts) or body_font
    if body_font:
        typography["fontFamilyBase"] = body_font
    if heading_font:
        typography["fontFamilyHeading"] = heading_font
    if typography:
        design["typography"] = typography
        evidence["fonts"] = {k: v for k, v in typography.items()}

    radius = _radius(reading)
    if radius:
        design["radius"] = radius
        evidence["radius"] = radius.get("md")

    # Only when something was actually examined. "This company's surfaces are
    # flat" and "nothing could be read" are different statements, and the
    # first one written from the second is a design decision made by a failed
    # network request.
    if reading.colors:
        elevation = _elevation(reading)
        if elevation:
            design["elevation"] = elevation

    if reading.font_sizes:
        design["informationDensity"] = _density(reading)
        evidence["density"] = design["informationDensity"]
    return design, evidence
