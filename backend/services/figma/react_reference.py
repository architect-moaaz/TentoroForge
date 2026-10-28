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
    return ref, f"Adapting Figma frame {screen.name or node_id} for {route}."
