"""The design system a file's frames are drawn with, when it publishes none.

`projection.design_system_from` takes a file's published variables as its
design system (§47), and `palette.from_screens` counts the colours and faces
the frames use when there are none. Neither said what the corners, the
spacing, the body text or the file's own named styles are, so a page held to
a drawing was written against the scaffold's radius and the Tailwind scale.

This reads them off the same frames: Figma's named styles (`Primary/600`, a
text style called `Body/Regular`) by the name the designer gave them, and the
radius, spacing and body size by how often each value is used. Counting, not
judging: a value used once is a one-off, and the scale is what recurs.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from services.figma.react_reference import _fill, _walk

#: A value must recur this often to be part of a scale rather than a one-off.
MIN_USES = 3


def _documents(screens: Iterable[Any]) -> list[dict]:
    out = []
    for screen in screens:
        structure = getattr(screen, "structure", None) or {}
        document = structure.get("document")
        if isinstance(document, dict):
            out.append(document)
    return out


def named_styles(documents: list[dict]) -> dict[str, dict[str, str]]:
    """``{"colors": {style name: hex}, "text": {style name: "family size/weight/line"}}``
    for every named style a frame applies."""
    names: dict[str, str] = {}
    for document in documents:
        for style_id, meta in (document.get("_styles") or {}).items():
            if isinstance(meta, dict) and meta.get("name"):
                names[str(style_id)] = str(meta["name"])
    colors: dict[str, str] = {}
    text: dict[str, str] = {}
    for document in documents:
        for node in _walk(document):
            refs = node.get("styles") if isinstance(node.get("styles"), dict) else {}
            fill = names.get(str(refs.get("fill") or refs.get("fills") or ""))
            if fill and fill not in colors:
                value = _fill(node)
                if value.startswith("#"):
                    colors[fill] = value.split("/", 1)[0]
            face = names.get(str(refs.get("text") or ""))
            style = node.get("style") if isinstance(node.get("style"), dict) else {}
            if face and face not in text and style.get("fontSize"):
                text[face] = " ".join(x for x in (
                    str(style.get("fontFamily") or ""), f"{int(round(float(style['fontSize'])))}px",
                    str(int(style["fontWeight"])) if style.get("fontWeight") else "",
                    f"/{int(round(float(style['lineHeightPx'])))}px" if style.get("lineHeightPx") else "") if x)
    return {"colors": colors, "text": text}


def _scale(counter: Counter, names: tuple[str, ...]) -> dict[str, str]:
    """The recurring values, smallest first, under ``names`` — as many names
    as there are values, spread across the range."""
    values = sorted(v for v, n in counter.items() if n >= MIN_USES and v > 0)
    if not values:
        return {}
    if len(values) > len(names):
        step = (len(values) - 1) / (len(names) - 1)
        values = [values[round(i * step)] for i in range(len(names))]
    picked = names if len(values) == len(names) else names[:len(values)]
    return {name: f"{value}px" for name, value in zip(picked, values)}


def scales(documents: list[dict]) -> dict[str, dict[str, str]]:
    """The radius and spacing scales and the body text the frames recur to."""
    radii: Counter = Counter()
    spacing: Counter = Counter()
    body: Counter = Counter()
    lines: Counter = Counter()
    for document in documents:
        for node in _walk(document):
            if node.get("cornerRadius"):
                radii[int(round(float(node["cornerRadius"])))] += 1
            if node.get("layoutMode") in ("HORIZONTAL", "VERTICAL"):
                for key in ("itemSpacing", "paddingTop", "paddingLeft"):
                    if node.get(key):
                        spacing[int(round(float(node[key])))] += 1
            if str(node.get("type") or "") == "TEXT":
                style = node.get("style") if isinstance(node.get("style"), dict) else {}
                if style.get("fontSize"):
                    size = int(round(float(style["fontSize"])))
                    body[size] += len(str(node.get("characters") or "")) or 1
                    if style.get("lineHeightPx"):
                        lines[(size, int(round(float(style["lineHeightPx"]))))] += 1
    out: dict[str, dict[str, str]] = {}
    radius = _scale(radii, ("sm", "md", "lg", "xl"))
    if radius:
        # `--radius` is the one components ask for: the corner drawn most.
        radius["md"] = f"{radii.most_common(1)[0][0]}px"
        out["radius"] = radius
    space = _scale(spacing, ("xs", "sm", "md", "lg", "xl", "2xl"))
    if space:
        out["spacing"] = space
    if body:
        # THE BODY IS THE SIZE MOST WORDS ARE SET IN, and its line height the
        # one that size is drawn with most.
        size = body.most_common(1)[0][0]
        line = max((n, h) for (sz, h), n in lines.items() if sz == size)[1] if any(
            sz == size for sz, _h in lines) else 0
        out["typography"] = {"baseSize": f"{size}px", **({"lineHeightBase": f"{line}px"} if line else {})}
    return out


def drawn_system(screens: Iterable[Any]) -> dict[str, dict[str, str]]:
    """The design-system buckets the frames state: named colours and text
    styles, and the radius, spacing and body-text scales."""
    documents = _documents(screens)
    if not documents:
        return {}
    named = named_styles(documents)
    out = scales(documents)
    if named["colors"]:
        out["namedColors"] = named["colors"]
    if named["text"]:
        out["textStyles"] = named["text"]
    return out
