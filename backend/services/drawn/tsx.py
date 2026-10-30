"""A Figma node tree as React markup, with the drawn values.

Deterministic: the same frame always gives the same markup, and nothing here
judges what the frame means — `params` does that, over this output. Auto
layout becomes flex (direction, gap, padding, alignment, each child's FIXED /
HUG / FILL sizing); a frame without auto layout places its children where
they are drawn. Every value is the drawn one, as a Tailwind arbitrary value:
`gap-[12px]`, `text-[13px]`, `leading-[20px]`, `bg-[#0443fa]`,
`rounded-[10px]`, `shadow-[0_1px_2px_0_rgba(16,24,40,0.05)]`.

What markup cannot draw is exported from Figma instead: an icon or any
vector-only shape as an SVG, a photograph or image fill as a PNG. Each is
recorded in `Assets` and referenced from `/drawn/…`; the caller downloads
them (`assets.export`).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

#: Node types that draw a shape rather than hold content.
VECTOR_TYPES = frozenset({"VECTOR", "BOOLEAN_OPERATION", "LINE", "STAR", "POLYGON", "REGULAR_POLYGON"})
#: A vector-only subtree this size or smaller is an icon; larger is artwork
#: (a logo lockup, an illustration). Both are exported as SVG.
ICON_MAX = 64

_SAFE = re.compile(r"[^A-Za-z0-9_-]+")


def _px(value: Any) -> str:
    """A Figma length as a CSS one: whole pixels unless the drawing is finer."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "0px"
    n = round(n, 2)
    return f"{int(n)}px" if n == int(n) else f"{n}px"


def _hex(color: dict | None, opacity: float = 1.0) -> str:
    if not isinstance(color, dict):
        return ""
    try:
        r, g, b = (max(0, min(255, round(float(color[k]) * 255))) for k in ("r", "g", "b"))
        a = float(color.get("a", 1)) * float(opacity)
    except (KeyError, TypeError, ValueError):
        return ""
    if a >= 0.995:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r},{g},{b},{round(a, 3)})"


def _arb(prefix: str, value: str) -> str:
    """A Tailwind arbitrary-value class; spaces become underscores."""
    return f"{prefix}-[{value.replace(' ', '_')}]"


def _visible_paints(paints: Any) -> list[dict]:
    return [p for p in paints or [] if isinstance(p, dict) and p.get("visible") is not False]


@dataclass
class Assets:
    """What the markup refers to and Figma must render: ``{key: (node id, format)}``."""
    items: dict[str, tuple[str, str]] = field(default_factory=dict)

    def svg(self, node: dict) -> str:
        """The path an exported SVG of ``node`` is served at. An icon instance
        is exported once per component and colour, however often it is used."""
        colour = ""
        for n in _walk(node):
            paints = _visible_paints(n.get("fills")) + _visible_paints(n.get("strokes"))
            solid = next((p for p in paints if p.get("type") == "SOLID"), None)
            if solid:
                colour = _hex(solid.get("color"), float(solid.get("opacity", 1))).lstrip("#")
                break
        base = str(node.get("componentId") or node.get("id") or "")
        key = _SAFE.sub("-", f"{base}-{colour}" if node.get("componentId") else base).strip("-")
        self.items.setdefault(key + ".svg", (str(node.get("id") or ""), "svg"))
        return f"/drawn/{key}.svg"

    def png(self, node: dict) -> str:
        key = _SAFE.sub("-", str(node.get("id") or "")).strip("-")
        self.items.setdefault(key + ".png", (str(node.get("id") or ""), "png"))
        return f"/drawn/{key}.png"


def _walk(node: Any):
    if not isinstance(node, dict) or node.get("visible") is False:
        return
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def is_vector_only(node: dict) -> bool:
    """A subtree drawn only in shapes — no text and nothing laid out: an icon,
    a logo, an illustration. Markup cannot draw it; Figma can render it."""
    kinds = [str(n.get("type") or "") for n in _walk(node)]
    if not kinds or "TEXT" in kinds:
        return False
    if not any(k in VECTOR_TYPES for k in kinds):
        return False
    return all(k in VECTOR_TYPES or k in ("GROUP", "FRAME", "INSTANCE", "COMPONENT", "RECTANGLE", "ELLIPSE")
               for k in kinds)


def _box(node: dict) -> dict:
    box = node.get("absoluteBoundingBox") or {}
    return box if isinstance(box, dict) else {}


@dataclass
class Emitter:
    """One conversion: the assets it found, what it was told to leave out,
    and how instances of shared components are written."""
    assets: Assets = field(default_factory=Assets)
    #: Node ids drawn elsewhere (the shell) or not part of the app (the
    #: prototype's own furniture) — left out wherever they occur.
    skip: set[str] = field(default_factory=set)
    #: ``node -> markup`` for an instance of a shared component, or None to
    #: draw it inline (`components.Library.use`).
    component: Callable[[dict, "Emitter"], str | None] | None = None
    #: Whether to mark each element with the designer's layer name.
    trace: bool = True
    #: …and with the Figma node id it came from (for debugging a conversion;
    #: off by default — a screen's ids are a fifth of its markup).
    trace_ids: bool = False
    #: ``text node -> prop key`` when a text is a prop of the component being
    #: drawn (`components`), else None to write its words.
    text_slot: Callable[[dict], str | None] | None = None

    def _own_size(self, node: dict) -> list[str]:
        """A component's root, sized by itself: its user's wrapper places it."""
        box = _box(node)
        out = []
        for mode, dim, size in ((node.get("layoutSizingHorizontal"), "w", box.get("width")),
                                (node.get("layoutSizingVertical"), "h", box.get("height"))):
            if mode == "FILL":
                out.append(f"{dim}-full")
            elif mode != "HUG" and size is not None:
                out.append(_arb(dim, _px(size)))
        return out

    # -- classes --------------------------------------------------------

    def _paint_classes(self, node: dict, style: dict) -> list[str]:
        out: list[str] = []
        fills = _visible_paints(node.get("fills"))
        for paint in reversed(fills):            # Figma lists bottom first; CSS draws one background
            kind = str(paint.get("type") or "")
            if kind == "SOLID":
                colour = _hex(paint.get("color"), float(paint.get("opacity", 1)))
                if colour:
                    out.append(_arb("bg", colour))
                break
            if kind.startswith("GRADIENT_"):
                gradient = _gradient(paint)
                if gradient:
                    style["backgroundImage"] = gradient
                break
            if kind == "IMAGE":
                style["backgroundImage"] = f"url({self.assets.png(node)})"
                style["backgroundSize"] = {"FILL": "cover", "FIT": "contain"}.get(str(paint.get("scaleMode") or "FILL"),
                                                                                   "cover")
                style["backgroundPosition"] = "center"
                break
        strokes = _visible_paints(node.get("strokes"))
        solid = next((p for p in strokes if p.get("type") == "SOLID"), None)
        if solid:
            colour = _hex(solid.get("color"), float(solid.get("opacity", 1)))
            weights = node.get("individualStrokeWeights")
            if isinstance(weights, dict):
                for side, cls in (("top", "border-t"), ("right", "border-r"), ("bottom", "border-b"),
                                  ("left", "border-l")):
                    if float(weights.get(side) or 0):
                        out.append(_arb(cls, _px(weights[side])))
            elif float(node.get("strokeWeight") or 0):
                out.append(_arb("border", _px(node["strokeWeight"])))
            if colour:
                out.append(_arb("border", colour))
            if node.get("strokeDashes"):
                out.append("border-dashed")
        radii = node.get("rectangleCornerRadii")
        if isinstance(radii, list) and len(radii) == 4 and len(set(radii)) > 1:
            for value, cls in zip(radii, ("rounded-tl", "rounded-tr", "rounded-br", "rounded-bl")):
                if value:
                    out.append(_arb(cls, _px(value)))
        elif node.get("cornerRadius"):
            out.append("rounded-full" if float(node["cornerRadius"]) >= 999 else _arb("rounded", _px(node["cornerRadius"])))
        shadows = []
        for effect in node.get("effects") or []:
            if not isinstance(effect, dict) or effect.get("visible") is False:
                continue
            kind = str(effect.get("type") or "")
            if kind in ("DROP_SHADOW", "INNER_SHADOW"):
                off = effect.get("offset") or {}
                shadows.append(("inset " if kind == "INNER_SHADOW" else "")
                               + f"{_px(off.get('x', 0))} {_px(off.get('y', 0))} {_px(effect.get('radius', 0))} "
                               f"{_px(effect.get('spread', 0))} {_hex(effect.get('color')) or 'rgba(0,0,0,0.1)'}")
            elif kind == "BACKGROUND_BLUR":
                out.append(_arb("backdrop-blur", _px(effect.get("radius", 0))))
        if shadows:
            out.append(_arb("shadow", ",".join(shadows)))
        if node.get("opacity") is not None and float(node["opacity"]) < 0.995:
            out.append(_arb("opacity", str(round(float(node["opacity"]), 3))))
        return out

    def _layout_classes(self, node: dict) -> list[str]:
        mode = str(node.get("layoutMode") or "")
        if mode not in ("HORIZONTAL", "VERTICAL"):
            return ["relative"]
        out = ["flex", "flex-row" if mode == "HORIZONTAL" else "flex-col"]
        if node.get("layoutWrap") == "WRAP":
            out.append("flex-wrap")
        main = str(node.get("primaryAxisAlignItems") or "MIN")
        out.append({"MIN": "justify-start", "CENTER": "justify-center", "MAX": "justify-end",
                    "SPACE_BETWEEN": "justify-between"}.get(main, "justify-start"))
        cross = str(node.get("counterAxisAlignItems") or "MIN")
        out.append({"MIN": "items-start", "CENTER": "items-center", "MAX": "items-end",
                    "BASELINE": "items-baseline"}.get(cross, "items-start"))
        if main != "SPACE_BETWEEN" and float(node.get("itemSpacing") or 0):
            out.append(_arb("gap-x" if mode == "HORIZONTAL" else "gap-y", _px(node["itemSpacing"])))
        if node.get("layoutWrap") == "WRAP" and float(node.get("counterAxisSpacing") or 0):
            out.append(_arb("gap-y" if mode == "HORIZONTAL" else "gap-x", _px(node["counterAxisSpacing"])))
        pads = [float(node.get(k) or 0) for k in ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft")]
        if len(set(pads)) == 1 and pads[0]:
            out.append(_arb("p", _px(pads[0])))
        else:
            for value, cls in zip(pads, ("pt", "pr", "pb", "pl")):
                if value:
                    out.append(_arb(cls, _px(value)))
        return out

    def _size_classes(self, node: dict, parent: dict | None) -> list[str]:
        """How big a node is, in its parent's terms."""
        box = _box(node)
        out: list[str] = []
        pmode = str((parent or {}).get("layoutMode") or "")
        absolute = parent is not None and (pmode not in ("HORIZONTAL", "VERTICAL")
                                           or node.get("layoutPositioning") == "ABSOLUTE")
        h_mode = str(node.get("layoutSizingHorizontal") or "FIXED")
        v_mode = str(node.get("layoutSizingVertical") or "FIXED")
        if absolute:
            pbox = _box(parent or {})
            out.append("absolute")
            try:
                out.append(_arb("left", _px(float(box["x"]) - float(pbox["x"]))))
                out.append(_arb("top", _px(float(box["y"]) - float(pbox["y"]))))
            except (KeyError, TypeError, ValueError):
                pass
            if box.get("width") is not None and h_mode != "HUG":
                out.append(_arb("w", _px(box["width"])))
            if box.get("height") is not None and v_mode != "HUG":
                out.append(_arb("h", _px(box["height"])))
            return out
        if parent is None:
            return ["w-full", "min-h-screen"]
        row = pmode == "HORIZONTAL"
        # The main axis is the parent's direction; FILL there is a share of
        # what is left, FILL across it is stretching to the parent's size.
        for mode, along, dim in ((h_mode, row, "w"), (v_mode, not row, "h")):
            size = box.get("width" if dim == "w" else "height")
            if mode == "FILL":
                out.extend(["flex-1", "basis-0", "min-w-0" if dim == "w" else "min-h-0"] if along else ["self-stretch"])
                continue
            if mode == "FIXED" and size is not None:
                out.append(_arb(dim, _px(size)))
            # A FIGMA CHILD NEVER SHRINKS BELOW ITS CONTENT. A CSS flex child
            # does, and one with overflow hidden shrinks to nothing: a card in
            # a column too short for it lost every row (A-05, 2026-10-28).
            if along:
                out.append("shrink-0")
        if node.get("layoutGrow") and "flex-1" not in out:
            out.append("flex-1")
        if node.get("layoutAlign") == "STRETCH" and "self-stretch" not in out:
            out.append("self-stretch")
        return out

    def _text_classes(self, style: dict, node: dict) -> list[str]:
        out = []
        family = str(style.get("fontFamily") or "")
        if family:
            out.append(f"font-['{family.replace(' ', '_')}']")
        if style.get("fontSize"):
            out.append(_arb("text", _px(style["fontSize"])))
        if style.get("fontWeight"):
            out.append(f"font-[{int(style['fontWeight'])}]")
        if style.get("lineHeightPx") and style.get("lineHeightUnit") != "INTRINSIC_%":
            out.append(_arb("leading", _px(style["lineHeightPx"])))
        if style.get("letterSpacing"):
            out.append(_arb("tracking", _px(style["letterSpacing"])))
        if style.get("italic"):
            out.append("italic")
        align = str(style.get("textAlignHorizontal") or "LEFT")
        if align in ("CENTER", "RIGHT", "JUSTIFIED"):
            out.append({"CENTER": "text-center", "RIGHT": "text-right", "JUSTIFIED": "text-justify"}[align])
        case = str(style.get("textCase") or "")
        if case in ("UPPER", "LOWER", "TITLE"):
            out.append({"UPPER": "uppercase", "LOWER": "lowercase", "TITLE": "capitalize"}[case])
        decoration = str(style.get("textDecoration") or "")
        if decoration in ("UNDERLINE", "STRIKETHROUGH"):
            out.append("underline" if decoration == "UNDERLINE" else "line-through")
        if style.get("textTruncation") == "ENDING":
            lines = int(style.get("maxLines") or 1)
            out.append("truncate" if lines <= 1 else f"line-clamp-{lines}")
        fills = _visible_paints(node.get("fills"))
        solid = next((p for p in fills if p.get("type") == "SOLID"), None)
        if solid:
            colour = _hex(solid.get("color"), float(solid.get("opacity", 1)))
            if colour:
                out.append(_arb("text", colour))
        if style.get("textAutoResize") in ("WIDTH_AND_HEIGHT",):
            out.append("whitespace-nowrap")
        return out

    # -- markup ---------------------------------------------------------

    def _attrs(self, node: dict, classes: list[str], style: dict) -> str:
        parts = [f'className="{" ".join(dict.fromkeys(c for c in classes if c))}"']
        if style:
            parts.append("style={" + json.dumps(style, separators=(", ", ": ")) + "}")
        if self.trace_ids and node.get("id"):
            parts.append(f'data-node="{node["id"]}"')
        name = str(node.get("name") or "").strip()
        if self.trace and name and not re.match(r"^(Frame|Group|Rectangle|Vector|Ellipse|Line)\b", name):
            # A JSX ATTRIBUTE STRING TAKES NO BACKSLASH ESCAPES: a layer named
            # with a double quote wrote `\"`, which ends the string, and 12
            # DITANS screens did not compile (2026-10-30). The name is a label.
            label = name[:60].replace("\\", "/").replace('"', "'")
            parts.append(f"data-layer={json.dumps(label, ensure_ascii=False)}")
        return " ".join(parts)

    def element(self, node: dict, parent: dict | None = None, depth: int = 0, *, own_size: bool = False) -> str:
        if not isinstance(node, dict) or node.get("visible") is False or str(node.get("id")) in self.skip:
            return ""
        kind = str(node.get("type") or "")
        pad = "  " * depth
        if parent is not None and self.component is not None and kind == "INSTANCE":
            used = self.component(node, self)
            if used is not None:
                size = " ".join(self._size_classes(node, parent))
                return f'{pad}<div className="{size}">{used}</div>\n' if size else f"{pad}{used}\n"
        style: dict[str, str] = {}
        sizing = self._own_size(node) if own_size else self._size_classes(node, parent)
        if (parent is not None or own_size) and is_vector_only(node):
            box = _box(node)
            src = self.assets.svg(node)
            w, h = _px(box.get("width", 0)), _px(box.get("height", 0))
            img = list(dict.fromkeys([*(c for c in sizing if not c.startswith(("w-[", "h-["))),
                                      _arb("w", w), _arb("h", h), "shrink-0"]))
            return (f'{pad}<img src="{src}" alt="" '
                    f'className="{" ".join(img)}" '
                    + (f'data-node="{node.get("id")}" ' if self.trace_ids else "") + "/>\n")
        if kind == "TEXT":
            return self._text(node, sizing, pad)
        classes = [*self._layout_classes(node), *sizing, *self._paint_classes(node, style)]
        if node.get("clipsContent"):
            classes.append("overflow-hidden")
        if kind == "ELLIPSE":
            classes.append("rounded-full")
        children = "".join(self.element(c, node, depth + 1) for c in node.get("children") or [])
        open_tag = f"{pad}<div {self._attrs(node, classes, style)}"
        return f"{open_tag}>\n{children}{pad}</div>\n" if children else f"{open_tag} />\n"

    def _text(self, node: dict, sizing: list[str], pad: str) -> str:
        style = node.get("style") if isinstance(node.get("style"), dict) else {}
        classes = [*sizing, *self._text_classes(style, node)]
        chars = str(node.get("characters") or "")
        overrides = node.get("characterStyleOverrides") or []
        table = node.get("styleOverrideTable") or {}
        slot = self.text_slot(node) if self.text_slot is not None else None
        if slot:
            body = "{props." + slot + "}"
        elif overrides and table and len(overrides) <= len(chars):
            body = _styled_runs(chars, overrides, table, node, self)
        else:
            body = _text_literal(chars)
        return f"{pad}<p {self._attrs(node, classes, {})}>{body}</p>\n"

    def frame(self, document: dict, component: str) -> str:
        """The whole frame as one component's markup (no imports, no props)."""
        inner = self.element(document)
        return f"export default function {component}() {{\n  return (\n{_indent(inner, 4)}  );\n}}\n"


def _styled_runs(chars: str, overrides: list, table: dict, node: dict, emitter: Emitter) -> str:
    """A text whose characters carry other styles: each run its own span."""
    runs: list[tuple[int, str]] = []
    for i, ch in enumerate(chars):
        key = int(overrides[i]) if i < len(overrides) else 0
        if runs and runs[-1][0] == key:
            runs[-1] = (key, runs[-1][1] + ch)
        else:
            runs.append((key, ch))
    out = []
    for key, text in runs:
        if not key or str(key) not in table:
            out.append(_text_literal(text))
            continue
        run = table[str(key)] or {}
        classes = emitter._text_classes({**run}, {"fills": run.get("fills") or node.get("fills")})
        out.append(f'<span className="{" ".join(classes)}">{_text_literal(text)}</span>')
    return "".join(out)


def _text_literal(text: str) -> str:
    """Characters as JSX children: braces and angle brackets escaped, line
    breaks kept."""
    lines = []
    for line in text.split("\n"):
        line = line.replace("{", "&#123;").replace("}", "&#125;").replace("<", "&lt;").replace(">", "&gt;")
        lines.append(line)
    return "<br />".join(lines)


def _gradient(paint: dict) -> str:
    stops = paint.get("gradientStops") or []
    if not stops:
        return ""
    handles = paint.get("gradientHandlePositions") or []
    angle = 180.0
    if len(handles) >= 2:
        import math
        dx = float(handles[1].get("x", 0)) - float(handles[0].get("x", 0))
        dy = float(handles[1].get("y", 0)) - float(handles[0].get("y", 0))
        angle = (math.degrees(math.atan2(dy, dx)) + 90) % 360
    colours = ", ".join(f"{_hex(s.get('color'))} {round(float(s.get('position', 0)) * 100)}%" for s in stops)
    kind = "radial-gradient(circle" if str(paint.get("type")) == "GRADIENT_RADIAL" else f"linear-gradient({round(angle)}deg"
    return f"{kind}, {colours})"


def _indent(text: str, n: int) -> str:
    return "".join(" " * n + line + "\n" if line.strip() else "\n" for line in text.splitlines())


def component_name(frame_name: str, suffix: str = "View") -> str:
    """`A-05 · Tenants & Entitlements — plans, seats` → `TenantsEntitlementsView`.
    The designer's id prefix and the description after a dash are left out."""
    name = re.sub(r"^[A-Z0-9]+(?:[-.][A-Z0-9]+)*\s*[·•:]\s*", "", frame_name.strip())
    name = re.split(r"\s+[—–-]\s+|\s*\(", name, maxsplit=1)[0]
    words = re.findall(r"[A-Za-z0-9]+", name)
    out = "".join(w[:1].upper() + w[1:] for w in words)[:48] or "Drawn"
    if out[0].isdigit():
        out = "Screen" + out
    return out + suffix
