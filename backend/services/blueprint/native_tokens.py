"""The design system's measures, as numbers a phone draws with.

The web reads the Blueprint's `designSystem` as CSS: radii in `px`, spacing in `rem`, shadows as
`box-shadow` strings, a base font size, a density. A native app has no CSS, and the kit used to carry
numbers of its own (one corner radius, a 4/8/12/16/24/32 scale, three fixed shadows), so the phone looked
like the app's colours and fonts on someone else's measures. This reads each measure from the design
system and falls back to the kit's own value only where the design is silent; `theme.generated.ts` carries
the result and the kit draws from nothing else.

* `radii`       sm / md / lg corner radii        (`designSystem.radius`)
* `spacing`     xs..xxl and the page margin      (`designSystem.spacing`, scaled by `informationDensity`)
* `shadows`     three levels                     (`designSystem.elevation`, one layer of each box-shadow)
* `type_scale`  the base size over the kit's 16  (`designSystem.typography.baseSize`)
* `border_width`                                 (`designSystem.borders`)
"""
from __future__ import annotations

import re
from typing import Any

#: What the kit used before the design system was read - the fallback, never the first choice.
DEFAULT_RADII = {"sm": 8, "md": 12, "lg": 16}
DEFAULT_SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
DEFAULT_SHADOWS = {
    1: {"shadowColor": "#0f172a", "shadowOpacity": 0.06, "shadowRadius": 6, "shadowOffset": {"width": 0, "height": 2}, "elevation": 1},
    2: {"shadowColor": "#0f172a", "shadowOpacity": 0.1, "shadowRadius": 12, "shadowOffset": {"width": 0, "height": 4}, "elevation": 3},
    3: {"shadowColor": "#0f172a", "shadowOpacity": 0.16, "shadowRadius": 20, "shadowOffset": {"width": 0, "height": 8}, "elevation": 8},
}

#: How much air `informationDensity` asks for, against "comfortable".
DENSITY = {"compact": 0.8, "dense": 0.8, "comfortable": 1.0, "cozy": 1.0, "spacious": 1.25, "airy": 1.25, "relaxed": 1.25}

#: The kit's slots, and the design's step each is: `space-1` is 0.25rem, so `xs` is `space-1`.
_SPACE_STEP = {"xs": 1, "sm": 2, "md": 3, "lg": 4, "xl": 6, "xxl": 8}

_NUMBER = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(px|rem|em|pt)?\s*$", re.I)


def px(value: Any, base: float = 16.0) -> float | None:
    """`12px` -> 12, `0.75rem` -> 12, `8` -> 8; anything else None."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    m = _NUMBER.match(str(value or ""))
    if not m:
        return None
    n = float(m.group(1))
    return n * base if (m.group(2) or "").lower() in ("rem", "em") else n


def _clean(n: float) -> int | float:
    return int(n) if float(n).is_integer() else round(n, 3)


def base_size(doc: dict) -> float:
    typo = (doc.get("designSystem") or {}).get("typography") or {}
    return px(typo.get("baseSize")) or 16.0


def type_scale(doc: dict) -> float:
    """The factor every size of the kit's type scale is multiplied by: a 18px base is 1.125."""
    return _clean(round(base_size(doc) / 16.0, 3))


#: A weight as the design may spell it -> the kit's four.
_WEIGHT_WORDS = {"regular": "regular", "normal": "regular", "light": "regular", "medium": "medium",
                 "semibold": "semibold", "bold": "bold", "bolder": "bold"}
#: Colours a heading may take, by the design's own words -> the theme's tone.
_HEADING_TONES = {"primary": "primary", "accent": "accent", "foreground": "default", "text": "default",
                  "textprimary": "default", "default": "default"}
DEFAULT_HEADING = {"weight": "bold", "tone": "default", "titleSize": None}


def heading(doc: dict) -> dict[str, Any]:
    """How the design's headings look: `typography.headingWeight` (400..700 or a word), `headingColor`
    (`primary` or the text colour) and `titleSize` (a page title, in px). The kit's own look where it is silent -
    the web draws a page title as whatever its screens ask for, and a design that says so makes both agree."""
    typo = (doc.get("designSystem") or {}).get("typography") or {}
    out = dict(DEFAULT_HEADING)
    w = str(typo.get("headingWeight") or "").strip().lower()
    if w.isdigit():
        out["weight"] = "regular" if int(w) < 450 else "medium" if int(w) < 550 else "semibold" if int(w) < 650 else "bold"
    elif w in _WEIGHT_WORDS:
        out["weight"] = _WEIGHT_WORDS[w]
    tone = _HEADING_TONES.get(re.sub(r"[^a-z]", "", str(typo.get("headingColor") or "").lower()))
    if tone:
        out["tone"] = tone
    size = px(typo.get("titleSize"))
    if size and 14 <= size <= 72:
        out["titleSize"] = _clean(size)
    return out


def radii(doc: dict) -> dict[str, int | float]:
    given = (doc.get("designSystem") or {}).get("radius")
    out = dict(DEFAULT_RADII)
    if isinstance(given, dict):
        for key in out:
            n = px(given.get(key))
            if n is not None:
                out[key] = _clean(n)
    elif px(given) is not None:                      # one radius: the middle; the others keep their steps from it
        mid = px(given)
        out = {"sm": _clean(max(mid * 2 / 3, 2)), "md": _clean(mid), "lg": _clean(mid * 5 / 3)}
    return out


def density(doc: dict) -> float:
    word = str((doc.get("designSystem") or {}).get("informationDensity") or "comfortable").strip().lower()
    return DENSITY.get(word, 1.0)


def spacing(doc: dict) -> dict[str, int | float]:
    """The kit's six steps from the design's scale (`space-1`.. in rem), by the density asked for."""
    scale = (doc.get("designSystem") or {}).get("spacing") or {}
    factor = density(doc)
    out: dict[str, int | float] = {}
    for slot, step in _SPACE_STEP.items():
        n = px(scale.get(f"space-{step}")) if isinstance(scale, dict) else None
        out[slot] = _clean(round((n if n is not None else DEFAULT_SPACING[slot]) * factor))
    return out


def page_padding(doc: dict) -> int | float:
    """The margin around a screen's content: the design's `page-padding`, else the `lg` step."""
    scale = (doc.get("designSystem") or {}).get("spacing") or {}
    n = px(scale.get("page-padding")) if isinstance(scale, dict) else None
    return _clean(round(n)) if n is not None else spacing(doc)["lg"]


def border_width(doc: dict) -> int | float:
    borders = (doc.get("designSystem") or {}).get("borders") or {}
    n = px(borders.get("border-width")) if isinstance(borders, dict) else None
    return _clean(n) if n else 1


_LEN = r"(-?\d+(?:\.\d+)?)(?:px)?"
_LAYER = re.compile(_LEN + r"\s+" + _LEN + r"\s+(\d+(?:\.\d+)?)(?:px)?(?:\s+" + _LEN + r")?\s+rgba?\(([^)]+)\)", re.I)


def shadow(css: Any) -> dict[str, Any] | None:
    """One CSS `box-shadow` as React Native draws it. A phone draws ONE layer: the layers' opacity is summed
    (capped) so a two-layer web shadow keeps its weight. Android takes `elevation`, from the blur."""
    layers = _LAYER.findall(str(css or ""))
    if not layers:
        return None
    x, y, blur, _spread, color = layers[0]
    parts = [p.strip() for p in color.split(",")]
    try:
        r, g, b = (int(float(p)) for p in parts[:3])
    except ValueError:
        return None
    alpha = sum(float(c.split(",")[3]) for _, _, _, _, c in layers if len(c.split(",")) > 3)
    opacity = round(min(max(alpha, 0.04), 0.22), 3)
    return {"shadowColor": f"#{r:02x}{g:02x}{b:02x}", "shadowOpacity": opacity, "shadowRadius": _clean(float(blur) / 2),
            "shadowOffset": {"width": _clean(float(x)), "height": _clean(float(y))},
            "elevation": max(1, round(float(blur) / 2.5))}


def shadows(doc: dict) -> dict[int, dict[str, Any]]:
    """Levels 1-3 from `shadow-sm`, `shadow-md`, `shadow-lg` (a design with no `sm` starts at `md`)."""
    given = (doc.get("designSystem") or {}).get("elevation") or {}
    out = {n: dict(DEFAULT_SHADOWS[n]) for n in (1, 2, 3)}
    if isinstance(given, dict):
        for level, key in ((1, "shadow-sm"), (2, "shadow-md"), (3, "shadow-lg")):
            read = shadow(given.get(key))
            if read:
                out[level] = read
    return out
