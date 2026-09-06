"""A UX Pilot page as a design reference (PRD §44, §47, §48, §53).

Fills :class:`services.figma.reference.DesignReference` — the shape the
store, the intelligence brief, the design-system projection and the layout
projection already read — from a UX Pilot page:

* each design on the page is a :class:`ScreenRef`; its ``node_id`` is the
  design id, its ``canvas`` the page name, its ``structure`` the design's
  HTML with the labels and assets harvested from it (``source:
  uxpilot_html``), its ``image`` the preview URL;
* the page's theme is :class:`DesignTokens` (§47), measured from the HTML
  when the page publishes none, and said so in ``gaps``;
* the page's diagrams give :class:`InteractionRef` edges where both ends
  are designs, and the absence is a gap (§55).

§48 holds unchanged: a design proves a screen exists, not who may use it.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from services.figma.reference import (
    DesignReference,
    DesignTokens,
    InteractionRef,
    ScreenRef,
    payload_of,
)
from services.figma.url import FigmaTarget
from services.uxpilot.gateway import UxPilotGateway, UxPilotGatewayError

logger = logging.getLogger(__name__)

_MAX_LABELS = 40
_HTML_MARK_RE = re.compile(r"<\s*(?:!doctype|html|body|div|section|main|header|nav)\b", re.I)
_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


# ---------------------------------------------------------------------------
# Payload readers — the server's JSON is not documented, so nothing here
# assumes a layout; keys are found where they are.
# ---------------------------------------------------------------------------

def _find_key(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() == key.lower():
                return v
        for v in obj.values():
            hit = _find_key(v, key)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_key(v, key)
            if hit is not None:
                return hit
    return None


def _first_str(obj: Any, keys: tuple[str, ...]) -> str:
    if not isinstance(obj, dict):
        return ""
    for k in keys:
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _first_num(obj: Any, keys: tuple[str, ...]) -> float:
    if not isinstance(obj, dict):
        return 0.0
    for k in keys:
        v = obj.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return float(v)
    return 0.0


def _find_html(obj: Any) -> str:
    if isinstance(obj, str):
        return obj if _HTML_MARK_RE.search(obj) else ""
    if isinstance(obj, dict):
        for k in ("html", "content", "source", "markup"):
            v = obj.get(k)
            if isinstance(v, str) and _HTML_MARK_RE.search(v):
                return v
        for v in obj.values():
            hit = _find_html(v)
            if hit:
                return hit
    if isinstance(obj, list):
        for v in obj:
            hit = _find_html(v)
            if hit:
                return hit
    return ""


def _walk_leaves(obj: Any, path: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_leaves(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_leaves(v, path)
    else:
        yield path, obj


def tokens_from_theme(theme: Any) -> DesignTokens:
    """§47 — the theme as the page publishes it, keyed by its own names.

    Hex strings are colours, strings under font keys are families, numbers
    and ``px`` strings under size / radius / spacing keys are what their key
    says. Names are the theme's paths, so a token stays traceable to the
    theme a user can open.
    """
    colors: dict[str, str] = {}
    typography: dict[str, Any] = {}
    spacing: dict[str, Any] = {}
    radius: dict[str, Any] = {}
    for path, val in _walk_leaves(theme):
        k = path.lower()
        if isinstance(val, str):
            v = val.strip()
            if _HEX_RE.match(v):
                h = v[1:]
                if len(h) == 3:
                    h = "".join(c * 2 for c in h)
                colors[path] = "#" + h.upper()
            elif "font" in k and "size" not in k and "weight" not in k:
                fam = v.split(",")[0].strip().strip("'\"")
                if fam and not fam.startswith("var("):
                    typography[path] = fam
            elif v.endswith("px"):
                if "radius" in k or "rounded" in k:
                    radius[path] = v
                elif "font" in k and "size" in k:
                    typography[path] = v
                elif any(w in k for w in ("spacing", "gap", "padding", "space")):
                    spacing[path] = v
        elif isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
            if "radius" in k or "rounded" in k:
                radius[path] = val
            elif "fontsize" in k.replace("_", "").replace("-", ""):
                typography[path] = val
            elif any(w in k for w in ("spacing", "gap", "padding")):
                spacing[path] = val
    return DesignTokens(colors=colors, typography=typography, spacing=spacing, radius=radius)


def tokens_measured_from(screens: list[ScreenRef]) -> DesignTokens:
    """The vocabulary the designs actually use, when no theme is published.
    Named by value (``measured/#1F2937``) because a measurement has no name."""
    from services.html_to_schema import tokens_from_html

    colors: dict[str, str] = {}
    typography: dict[str, Any] = {}
    spacing: dict[str, Any] = {}
    radius: dict[str, Any] = {}
    for screen in screens:
        html = str((screen.structure or {}).get("html") or "")
        if not html:
            continue
        t = tokens_from_html(html)
        for c in t.colors:
            colors[f"measured/{c}"] = c
        for f in t.fonts:
            typography[f"measured/font/{f}"] = f
        for s in t.font_sizes:
            typography[f"measured/size/{int(s) if float(s).is_integer() else s}"] = f"{int(s) if float(s).is_integer() else s}px"
        for r in t.border_radii:
            radius[f"measured/radius/{int(r) if float(r).is_integer() else r}"] = f"{int(r) if float(r).is_integer() else r}px"
        for sp in t.spacings:
            spacing[f"measured/space/{int(sp) if float(sp).is_integer() else sp}"] = f"{int(sp) if float(sp).is_integer() else sp}px"
    return DesignTokens(colors=colors, typography=typography, spacing=spacing, radius=radius)


def labels_of(html: str) -> list[str]:
    """Every visible label on the design, in document order, capped."""
    from services.html_to_schema import parse_html_tree
    from services.jsx_to_schema import JSXElement

    try:
        root, _ = parse_html_tree(html)
    except Exception:  # noqa: BLE001 — a label harvest never fails the extraction
        return []
    out: list[str] = []

    def _walk(node: Any) -> None:
        if len(out) >= _MAX_LABELS:
            return
        if isinstance(node, str):
            t = node.strip()
            if 1 < len(t) <= 80 and t not in out:
                out.append(t)
        elif isinstance(node, JSXElement):
            for c in node.children:
                _walk(c)

    _walk(root)
    return out


def structure_from_html(html: str) -> dict[str, Any]:
    from services.html_to_schema import extract_html_asset_urls

    return {
        "source": "uxpilot_html",
        "html": html,
        "labels": labels_of(html),
        "assets": extract_html_asset_urls(html),
    }


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

async def extract(
    gateway: UxPilotGateway,
    target: FigmaTarget,
    *,
    source_id: str = "UXPILOT-001",
    max_screens: int = 40,
    with_images: bool = True,
) -> DesignReference:
    """Build a :class:`DesignReference` from a live UX Pilot page.

    The page context is not optional: without it there is no reference. Every
    later step records a gap and continues, so a thin page reads as thin
    rather than as broken (§102).
    """
    ref = DesignReference(target=target, source_id=source_id, provider="uxpilot")
    page_id = target.file_key

    ctx = payload_of(await gateway.call("get_page_context", page=page_id))
    page = ctx.get("page") if isinstance(ctx, dict) and isinstance(ctx.get("page"), dict) else ctx
    page_name = _first_str(page, ("name", "title", "pageName")) or f"UX Pilot page {page_id}"
    designs = _find_key(ctx, "designs") or []
    if not isinstance(designs, list):
        designs = []

    screens: list[ScreenRef] = []
    for i, d in enumerate(designs[:max_screens]):
        if not isinstance(d, dict):
            continue
        design_id = _first_str(d, ("id", "designId", "design_id", "uuid"))
        if not design_id:
            continue
        prompt = _first_str(d, ("prompt", "aiContext", "ai_context", "description"))
        title = _first_str(d, ("title", "name")) or (prompt[:40] if prompt else "") or f"Design {i + 1}"
        screens.append(ScreenRef(
            node_id=design_id, name=title, canvas=page_name,
            width=_first_num(d, ("width", "w")), height=_first_num(d, ("height", "h")),
            image=_first_str(d, ("previewUrl", "preview_url", "imageUrl", "url")),
            structure={"prompt": prompt} if prompt else {},
        ))
    ref.screens = screens
    if not screens:
        ref.gaps.append("no designs found on the page")

    # §44/§53 — each design's HTML, and what it carries.
    for index, screen in enumerate(list(ref.screens)):
        try:
            blocks = await gateway.call("get_design", design=screen.node_id, include_html=True)
        except UxPilotGatewayError as exc:
            ref.gaps.append(f"no structure for {screen.name} ({exc.kind})")
            continue
        payload = payload_of(blocks)
        html = _find_html(payload)
        if not html:
            ref.gaps.append(f"no HTML returned for {screen.name}")
            continue
        structure = {**(screen.structure or {}), **structure_from_html(html)}
        image = screen.image or (
            _first_str(payload.get("design") if isinstance(payload, dict) and isinstance(payload.get("design"), dict) else payload,
                       ("previewUrl", "preview_url", "imageUrl"))
        )
        ref.screens[index] = _replace(screen, structure=structure, image=image)

    # §47 — the theme, or a measurement when the page publishes none.
    theme_ref = _find_key(ctx, "themeId") or _find_key(ctx, "theme_id")
    if theme_ref is None:
        theme = _find_key(ctx, "theme")
        theme_ref = _first_str(theme, ("id", "themeId")) if isinstance(theme, dict) else (theme if isinstance(theme, str) else None)
    if theme_ref:
        try:
            ref.tokens = tokens_from_theme(payload_of(await gateway.call("get_theme", theme=str(theme_ref))))
        except UxPilotGatewayError as exc:
            ref.gaps.append(f"design tokens unavailable ({exc.kind})")
    if ref.tokens.is_empty():
        ref.tokens = tokens_measured_from(ref.screens)
        ref.gaps.append("page publishes no theme; tokens measured from the designs' HTML")

    # §55 — flows, from the page's diagrams when their edges join designs.
    known = {s.node_id for s in ref.screens}
    try:
        diagrams = payload_of(await gateway.call("list_diagrams", page=page_id))
        items = _find_key(diagrams, "diagrams") if isinstance(diagrams, dict) else diagrams
        for diagram in items or []:
            if not isinstance(diagram, dict):
                continue
            for edge in _find_key(diagram, "edges") or []:
                if not isinstance(edge, dict):
                    continue
                src = _first_str(edge, ("from", "source", "sourceId", "source_id"))
                dst = _first_str(edge, ("to", "target", "targetId", "target_id"))
                if src in known and dst in known:
                    ref.interactions.append(InteractionRef(
                        source_node=src, target_node=dst,
                        trigger=_first_str(edge, ("trigger", "label")), action="NAVIGATE",
                    ))
    except UxPilotGatewayError as exc:
        logger.info("[uxpilot] diagrams unavailable for %s: %s", page_id, exc.kind)
    if not ref.interactions:
        ref.gaps.append(
            "prototype interactions unavailable: the page's diagrams name no "
            "design-to-design flow (§55) — navigation must be inferred and "
            "confirmed with the user"
        )

    if not with_images:
        ref.screens = [_replace(s, image="") for s in ref.screens]
    return ref


def _replace(screen: ScreenRef, **changes: Any) -> ScreenRef:
    from dataclasses import replace
    return replace(screen, **changes)
