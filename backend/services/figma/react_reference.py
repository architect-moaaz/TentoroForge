"""A connected Figma frame as the reference the React page writer adapts.

The React path (`page_code` → `ui_engineer.compose_page`) takes a ``reference`` dict and ADAPTS the
drawing instead of deciding the page: the planning call is skipped, the house-style rules do not
apply, and the look reviewer only sends a page back for something broken. UX Pilot's drawing
arrives that way (`uxpilot.generate.reference_for`); this is the same seam for a frame a person
drew in Figma, read from the extraction `figma_connect` already stored under ``.forge/figma``.

WHAT THE WRITER IS GIVEN, AND WHY IT IS NOT JUST "THE JSX"
---------------------------------------------------------
* The hosted MCP's ``get_design_context`` answers with generated TSX (absolute pixel positions,
  arbitrary-value classes, a CDN url per image). That is a picture of the frame, not code to ship,
  so it is shown with its images folded to a stub and cut to a budget.
* The REST API answers with Figma's native node tree. A tree that deep is not something to hand a
  writer raw, so it is reduced to an indented outline: what each box is, its size, how it lays out,
  its fill, and the text it carries.
* The file's published variables (colours, type) are listed beside it, so the writer can pick the
  app's nearest token class rather than the frame's hex.

Nothing here raises and nothing here costs a call: a frame that is not stored, or has no structure
to read, yields no reference and a line saying why, and the page is written without one.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The outline is cut at this many characters (a page's structure fits in a fraction of it).
OUTLINE_CHARS = 14000
#: How deep the outline follows a frame. Past this a box is drawn as its name alone.
MAX_DEPTH = 14
#: At most this many palette / type tokens are listed.
MAX_TOKENS = 24

_ASSET_URL = re.compile(r"https?://[^\s\"'`)]*figma[^\s\"'`)]*", re.I)


def _hex(color: dict | None) -> str:
    """``#rrggbb`` for a Figma ``{r, g, b}`` colour (each 0..1), or "" when there is none."""
    if not isinstance(color, dict):
        return ""
    try:
        r, g, b = (max(0, min(255, round(float(color[k]) * 255))) for k in ("r", "g", "b"))
    except (KeyError, TypeError, ValueError):
        return ""
    return f"#{r:02x}{g:02x}{b:02x}"


def _fill(node: dict) -> str:
    """The first visible solid fill of ``node`` as a hex, a gradient/image marker, or ""."""
    for fill in node.get("fills") or []:
        if not isinstance(fill, dict) or fill.get("visible") is False:
            continue
        kind = str(fill.get("type") or "")
        if kind == "SOLID":
            colour = _hex(fill.get("color"))
            try:
                alpha = (float(fill.get("opacity", 1)) * float((fill.get("color") or {}).get("a", 1))
                         * float(node.get("opacity", 1)))
            except (TypeError, ValueError):
                alpha = 1.0
            # A wash is said to be one: "bg#d96f32/10%" is a pale orange panel, not an orange one.
            return colour + (f"/{round(alpha * 100)}%" if colour and alpha < 0.97 else "")
        if kind.startswith("GRADIENT"):
            return "gradient"
        if kind == "IMAGE":
            return "image"
    return ""


def _pad(node: dict) -> str:
    sides = [node.get(k) for k in ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft")]
    if not any(sides):
        return ""
    nums = [int(round(float(s or 0))) for s in sides]
    return f"pad{nums[0]}" if len(set(nums)) == 1 else "pad" + "/".join(str(n) for n in nums)


def _line(node: dict) -> str:
    """One node as one outline line (without its indent)."""
    kind = str(node.get("type") or "NODE")
    name = str(node.get("name") or "").strip()
    box = node.get("absoluteBoundingBox") if isinstance(node.get("absoluteBoundingBox"), dict) else {}
    parts = [kind]
    text = str(node.get("characters") or "").strip()
    if kind == "TEXT" and text:
        parts.append('"' + re.sub(r"\s+", " ", text)[:120] + '"')
        style = node.get("style") if isinstance(node.get("style"), dict) else {}
        size, weight = style.get("fontSize"), style.get("fontWeight")
        if size:
            parts.append(f"{int(round(float(size)))}" + (f"/{int(weight)}" if weight else ""))
        color = _fill(node)
        if color:
            parts.append(color)
        return " ".join(parts)
    if name:
        parts.append('"' + name[:60] + '"')
    try:
        if box.get("width") and box.get("height"):
            parts.append(f"{int(round(float(box['width'])))}x{int(round(float(box['height'])))}")
    except (TypeError, ValueError):
        pass
    mode = str(node.get("layoutMode") or "")
    if mode in ("HORIZONTAL", "VERTICAL"):
        parts.append("row" if mode == "HORIZONTAL" else "col")
        gap = node.get("itemSpacing")
        if gap:
            parts.append(f"gap{int(round(float(gap)))}")
    pad = _pad(node)
    if pad:
        parts.append(pad)
    fill = _fill(node)
    if fill:
        parts.append("bg" + fill if fill.startswith("#") else fill)
    radius = node.get("cornerRadius")
    if radius:
        parts.append(f"r{int(round(float(radius)))}")
    return " ".join(parts)


def outline(document: dict, limit: int = OUTLINE_CHARS) -> str:
    """Figma's native node tree reduced to an indented outline, cut at ``limit`` on a line."""
    lines: list[str] = []
    used = 0
    cut = False

    def walk(node: Any, depth: int) -> None:
        nonlocal used, cut
        if cut or not isinstance(node, dict) or node.get("visible") is False:
            return
        text = "  " * depth + _line(node)
        if used + len(text) + 1 > limit:
            cut = True
            return
        lines.append(text)
        used += len(text) + 1
        if depth >= MAX_DEPTH:
            return
        for child in node.get("children") or []:
            walk(child, depth + 1)

    walk(document, 0)
    if cut:
        lines.append("… (the rest of the frame is the same kind of content)")
    return "\n".join(lines)


def code_digest(code: str, limit: int = OUTLINE_CHARS * 2) -> str:
    """Generated TSX reduced to what decides the page: asset urls folded, whitespace collapsed,
    cut on a tag boundary."""
    text = _ASSET_URL.sub("<asset>", str(code or ""))
    text = re.sub(r"data:[a-z/+.-]+;base64,[A-Za-z0-9+/=]+", "data:", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    at = text.rfind(">", 0, limit)
    return text[: at + 1 if at > limit // 2 else limit] + " {/* …the rest is the same kind of markup */}"


def token_notes(tokens: Any) -> str:
    """The file's published colours and type as short lines, "" when it publishes none."""
    if tokens is None or getattr(tokens, "is_empty", lambda: True)():
        return ""
    out: list[str] = []
    for name, value in list((getattr(tokens, "colors", None) or {}).items())[:MAX_TOKENS]:
        out.append(f"- colour {name}: {value}")
    typography = getattr(tokens, "typography", None) or {}
    for name, value in list(typography.items())[: max(0, MAX_TOKENS - len(out))]:
        out.append(f"- type {name}: {value}")
    return "\n".join(out)


def _source_tokens(doc: dict, output_dir: str | Path, source_id: str) -> Any:
    from services.figma import store

    try:
        ref = store.load(source_id, output_dir)
    except Exception:  # noqa: BLE001 — tokens are a help, never a gate
        return None
    return getattr(ref, "tokens", None) if ref is not None else None


#: The most frames whose pictures go to the writer for one page: its main
#: frame first, then its tabs, dialogs, steps and states in the order listed.
MAX_FRAME_IMAGES = 6
#: Each part frame's outline is cut shorter than the main frame's.
PART_OUTLINE_CHARS = 3500


def _walk(node: Any):
    if not isinstance(node, dict) or node.get("visible") is False:
        return
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)


def exact_values(documents: list[dict]) -> str:
    """The values the frames are drawn with, counted: every fill, text
    colour, type style, corner radius, gap and padding, most used first.

    WHAT "THE SAME DESIGN" IS MEASURED IN. The outline says where things are;
    this says what they are made of, as numbers a page can be written in —
    `#0f766e`, 14/500/20, r10, gap16 — so reproducing the frame is copying
    values, not guessing at the nearest token."""
    from collections import Counter

    fills: Counter = Counter()
    texts: Counter = Counter()
    strokes: Counter = Counter()
    type_styles: Counter = Counter()
    radii: Counter = Counter()
    spacing: Counter = Counter()
    for document in documents:
        for node in _walk(document):
            kind = str(node.get("type") or "")
            colour = _fill(node)
            if kind == "TEXT":
                if colour:
                    texts[colour] += 1
                style = node.get("style") if isinstance(node.get("style"), dict) else {}
                if style.get("fontSize"):
                    line = style.get("lineHeightPx")
                    type_styles[" ".join(x for x in (
                        str(style.get("fontFamily") or ""),
                        f"{int(round(float(style['fontSize'])))}px",
                        str(int(style["fontWeight"])) if style.get("fontWeight") else "",
                        f"/{int(round(float(line)))}px" if line else "",
                        f"tracking {round(float(style['letterSpacing']), 2)}px"
                        if style.get("letterSpacing") else "",
                    ) if x)] += 1
                continue
            if colour.startswith("#"):
                fills[colour] += 1
            for stroke in node.get("strokes") or []:
                if isinstance(stroke, dict) and stroke.get("type") == "SOLID" and stroke.get("visible") is not False:
                    hx = _hex(stroke.get("color"))
                    if hx:
                        strokes[f"{hx} {int(round(float(node.get('strokeWeight') or 1)))}px"] += 1
            if node.get("cornerRadius"):
                radii[int(round(float(node["cornerRadius"])))] += 1
            if node.get("layoutMode") in ("HORIZONTAL", "VERTICAL"):
                if node.get("itemSpacing"):
                    spacing[f"gap {int(round(float(node['itemSpacing'])))}"] += 1
                pad = _pad(node)
                if pad:
                    spacing[pad.replace("pad", "padding ")] += 1

    def top(counter: Counter, n: int) -> str:
        return ", ".join(f"{k} (\u00d7{v})" for k, v in counter.most_common(n))

    lines = [f"- {label}: {top(c, n)}" for label, c, n in (
        ("surface fills", fills, 14), ("text colours", texts, 10), ("borders", strokes, 8),
        ("type styles (family size weight /line-height)", type_styles, 14),
        ("corner radii px", radii, 8), ("spacing", spacing, 14)) if c]
    return "\n".join(lines)


def drawn_palette(documents: list[dict]) -> tuple[list[str], bool]:
    """Every solid colour the frames are painted in — fills, text and box
    outlines — and whether any of them draws a gradient. A page reproducing
    them is held to these (`ui_engineer._drawn_findings`)."""
    colours: set[str] = set()
    gradients = False
    boxes = {"FRAME", "RECTANGLE", "INSTANCE", "COMPONENT", "COMPONENT_SET", "SECTION"}
    for document in documents:
        for node in _walk(document):
            colour = _fill(node)
            if colour == "gradient":
                gradients = True
            elif colour.startswith("#"):
                colours.add(colour.split("/", 1)[0])
            if str(node.get("type") or "") in boxes:
                for stroke in node.get("strokes") or []:
                    if isinstance(stroke, dict) and stroke.get("type") == "SOLID" and stroke.get("visible") is not False:
                        hx = _hex(stroke.get("color"))
                        if hx:
                            colours.add(hx)
    return sorted(colours), gradients


def content_box(document: Any) -> dict | None:
    """Where the page sits inside its frame: the frame less the application
    shell it draws — a full-height column at its left edge (the sidebar) and
    a full-width bar along its top. The built page is rendered without the
    shell, so this is the part of the drawing it is compared with. Fractions
    of the frame, or None when the frame draws no shell."""
    if not isinstance(document, dict):
        return None
    frame = document.get("absoluteBoundingBox") or {}
    try:
        fx, fy, fw, fh = (float(frame[k]) for k in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError):
        return None
    def boxes(node: dict, depth: int):
        for child in node.get("children") or []:
            if not isinstance(child, dict) or child.get("visible") is False:
                continue
            box = child.get("absoluteBoundingBox") or {}
            try:
                yield tuple(float(box[k]) for k in ("x", "y", "width", "height"))
            except (KeyError, TypeError, ValueError):
                continue
            if depth < 3:
                yield from boxes(child, depth + 1)

    left = 0.0
    for x, y, w, h in boxes(document, 1):
        if abs(x - fx) < 2 and w < fw * 0.3 and h > fh * 0.8:
            left = max(left, w)
    # THE TOP BAR MAY SIT IN THE MAIN COLUMN, beside the sidebar rather than
    # across the frame: a bar along the top of what is right of it.
    top = 0.0
    for x, y, w, h in boxes(document, 1):
        if abs(y - fy) < 2 and x >= fx + left - 2 and w > (fw - left) * 0.6 and 24 < h < min(140, fh * 0.2):
            top = max(top, h)
    if not left and not top:
        return None
    # A top bar drawn beside the sidebar starts after it; either way the
    # page is what is right of the one and below the other.
    return {"x": round(left / fw, 4), "y": round(top / fh, 4),
            "w": round(1 - left / fw, 4), "h": round(1 - top / fh, 4)}


def screen_image(screen: Any, output_dir: str | Path, source_id: str) -> Path | None:
    """The frame's picture as a file: the store keeps it beside the screen
    (`FIGMA-001/screens/<node>.png`); an older store kept it inline as a data
    URL, which is written out once beside the others."""
    import base64

    from services.figma import store

    image = str(getattr(screen, "image", "") or "")
    if not image:
        return None
    base = Path(output_dir) / store.STORE_DIR
    if image.startswith("data:") and "," in image:
        out = base / source_id / "screens" / (re.sub(r"[^A-Za-z0-9_-]+", "-", str(screen.node_id)) + ".png")
        if not out.is_file():
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(base64.b64decode(image.split(",", 1)[1]))
            except (OSError, ValueError):
                return None
        return out
    path = base / image
    return path if path.is_file() else None


def _exact(doc: dict, frame: str) -> bool:
    """A frame of a design connected as the specification is reproduced;
    one connected as a reference is adapted (§48)."""
    from services.figma.store import split_frame_ref

    source_id, _node = split_frame_ref(frame)
    for source in doc.get("designSources") or []:
        if not source_id or str(source.get("id")) == source_id:
            if any(str(f.get("nodeId")) == _node for f in source.get("frames") or []):
                return str(source.get("treatAs") or "evidence") == "specification"
    return False


def _part_frames(doc: dict, page: dict, output_dir: str | Path) -> list[dict]:
    """The page's other frames (`pages[].frames`), each with its picture and a
    short outline, in the order listed."""
    from services.blueprint import figma_layout

    out: list[dict] = []
    for entry in page.get("frames") or []:
        if not isinstance(entry, dict) or not entry.get("frame"):
            continue
        try:
            source, screen = figma_layout.locate(doc, output_dir, str(entry["frame"]))
        except Exception:  # noqa: BLE001 — a part's picture is a help, never a gate
            continue
        if screen is None:
            continue
        structure = screen.structure or {}
        document = structure.get("document") if isinstance(structure.get("document"), dict) else None
        out.append({"as": str(entry.get("as") or ""), "label": str(entry.get("label") or screen.name or ""),
                    "section": str(entry.get("section") or ""),
                    "size": [int(screen.width or 0), int(screen.height or 0)],
                    "outline": outline(document, PART_OUTLINE_CHARS) if document else "",
                    "document": document,
                    "image": screen_image(screen, output_dir, str((source or {}).get("id") or ""))})
    return out


def reference_for(doc: dict, page: dict, output_dir: str | Path) -> tuple[dict | None, str]:
    """``(reference, said)`` for the UI engineer: the page's Figma frame as
    ``{"html", "format", "frame", "tokens", "designId", "reused"}``, and one line for whoever
    watches the run.

    ``html`` is the writer's word for the drawing, whatever its shape (``format`` says which:
    ``figma-tsx`` or ``figma-outline``), so the writer's existing "adapt a design" path takes it
    as it is. A page with no frame, an auth page, a frame no extraction holds, or one drawn by
    UX Pilot (its own path) gets ``(None, "")`` — or, when a frame was named but could not be read,
    ``(None, <why>)`` so the person watching is told the page is written without it.
    """
    from services.blueprint import figma_layout

    if str(page.get("pattern") or "") == "auth":
        return None, ""
    node_id = figma_layout.frame_of(page)
    if not node_id:
        return None, ""
    route = page.get("route") or page.get("name") or page.get("id")
    try:
        screen = figma_layout.screen_for(doc, output_dir, node_id)
    except Exception as exc:  # noqa: BLE001 — a design is a help, never a gate
        return None, f"Figma frame for {route} could not be read ({type(exc).__name__}) — writing it without a design."
    if screen is None:
        return None, (f"{route} names Figma frame {node_id}, which no stored extraction holds — "
                      f"writing it without a design.")
    structure = screen.structure or {}
    source = structure.get("source")
    if source == "uxpilot_html":
        return None, ""                      # a UX Pilot drawing has its own reference
    if structure.get("code"):
        markup, fmt = code_digest(str(structure["code"])), "figma-tsx"
    elif source == "rest_node_document" and isinstance(structure.get("document"), dict):
        markup, fmt = outline(structure["document"]), "figma-outline"
    else:
        return None, f"Figma frame {node_id} for {route} has no structure to read — writing it without a design."
    if not markup.strip():
        return None, f"Figma frame {node_id} for {route} came back empty — writing it without a design."

    tokens = ""
    for src in doc.get("designSources") or []:
        sid = str((src or {}).get("id") or "")
        if sid.startswith("FIGMA"):
            tokens = token_notes(_source_tokens(doc, output_dir, sid))
            if tokens:
                break
    ref = {"html": markup, "format": fmt, "frame": screen.name, "tokens": tokens,
           "size": [int(screen.width or 0), int(screen.height or 0)],
           "previewUrl": "", "designId": node_id, "reused": True}
    if not _exact(doc, node_id):
        return ref, f"Adapting Figma frame {screen.name or node_id} for {route}."
    # THE DRAWING IS THE SPECIFICATION: REPRODUCED, NOT ADAPTED. The writer
    # gets every frame the page is made of — as pictures, its main frame
    # first — and the exact values they are drawn with, and is held to them.
    from services.blueprint import figma_layout

    owner, _screen = figma_layout.locate(doc, output_dir, node_id)
    main_image = screen_image(screen, output_dir, str((owner or {}).get("id") or ""))
    parts = _part_frames(doc, page, output_dir)
    documents = [d for d in [structure.get("document") if source == "rest_node_document" else None,
                             *(p.pop("document") for p in parts)] if isinstance(d, dict)]
    images = [str(x) for x in [main_image, *(p.pop("image") for p in parts)] if x][:MAX_FRAME_IMAGES]
    from services.figma.styles import named_styles

    named = named_styles(documents)
    values = exact_values(documents)
    if named["colors"]:
        values += "\n- the file's named colours: " + ", ".join(f"{k} {v}" for k, v in list(named["colors"].items())[:20])
    if named["text"]:
        values += "\n- the file's text styles: " + ", ".join(f"{k} = {v}" for k, v in list(named["text"].items())[:16])
    palette, gradients = drawn_palette(documents)
    ref.update({"exact": True, "images": images, "parts": parts, "values": values,
                "palette": palette, "gradients": gradients,
                **({"content": box} if (box := content_box(structure.get("document"))) else {})})
    return ref, (f"Reproducing Figma frame {screen.name or node_id} for {route}"
                 + (f" with its {len(parts)} other frame{'s' if len(parts) != 1 else ''}" if parts else "") + ".")
