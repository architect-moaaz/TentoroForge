"""Custom MCP tools for Figma API access via Claude Agent SDK."""

import json
import os
from typing import Any

import httpx
# LG-4: claude-agent-sdk is optional now (its MCP server only fed the
# removed bundled-CLI executor). Degrade to no-op declarations when absent.
try:
    from claude_agent_sdk import tool, create_sdk_mcp_server
except Exception:  # noqa: BLE001
    def tool(*_a, **_k):  # type: ignore[misc]
        def _wrap(fn):
            return fn
        return _wrap

    def create_sdk_mcp_server(*_a, **_k):  # type: ignore[misc]
        return None

FIGMA_API_BASE = "https://api.figma.com/v1"


def _get_headers() -> dict:
    token = os.environ.get("FIGMA_TOKEN", "").strip()
    if not token:
        raise ValueError("FIGMA_TOKEN environment variable is not set")
    return {"X-Figma-Token": token}


def _color_to_hex(color: dict) -> str:
    """Convert Figma color {r,g,b,a} (0-1 floats) to hex string."""
    r = round(color.get("r", 0) * 255)
    g = round(color.get("g", 0) * 255)
    b = round(color.get("b", 0) * 255)
    a = color.get("a", 1.0)
    if a < 1:
        return f"rgba({r},{g},{b},{a:.2f})"
    return f"#{r:02x}{g:02x}{b:02x}"


def _extract_styles(node: dict, depth: int = 0) -> dict:
    """Recursively extract CSS-relevant style info from a Figma node tree."""
    result: dict[str, Any] = {
        "id": node.get("id", ""),
        "name": node.get("name", ""),
        "type": node.get("type", ""),
    }

    # Bounding box
    bbox = node.get("absoluteBoundingBox")
    if bbox:
        result["width"] = round(bbox.get("width", 0))
        result["height"] = round(bbox.get("height", 0))

    # Visibility
    if node.get("visible") is False:
        result["visible"] = False
        return result

    # Layout
    layout_mode = node.get("layoutMode")
    if layout_mode:
        result["layout"] = {
            "direction": "column" if layout_mode == "VERTICAL" else "row",
            "gap": node.get("itemSpacing", 0),
            "padding": {
                "top": node.get("paddingTop", 0),
                "right": node.get("paddingRight", 0),
                "bottom": node.get("paddingBottom", 0),
                "left": node.get("paddingLeft", 0),
            },
            "justify": node.get("primaryAxisAlignItems", "MIN"),
            "align": node.get("counterAxisAlignItems", "MIN"),
        }
        if node.get("layoutSizingHorizontal"):
            result["layout"]["sizingH"] = node["layoutSizingHorizontal"]
        if node.get("layoutSizingVertical"):
            result["layout"]["sizingV"] = node["layoutSizingVertical"]

    if node.get("layoutGrow"):
        result["flexGrow"] = node["layoutGrow"]
    if node.get("layoutPositioning") == "ABSOLUTE":
        result["position"] = "absolute"

    # Fills
    fills = node.get("fills", [])
    visible_fills = [f for f in fills if f.get("visible", True)]
    if visible_fills:
        result["fills"] = []
        for fill in visible_fills:
            fill_info: dict[str, Any] = {"type": fill["type"]}
            if fill["type"] == "SOLID":
                fill_info["color"] = _color_to_hex(fill.get("color", {}))
                if fill.get("opacity") is not None and fill["opacity"] < 1:
                    fill_info["opacity"] = round(fill["opacity"], 2)
            elif fill["type"] == "GRADIENT_LINEAR":
                stops = []
                for stop in fill.get("gradientStops", []):
                    stops.append({
                        "color": _color_to_hex(stop.get("color", {})),
                        "position": round(stop.get("position", 0), 2),
                    })
                fill_info["stops"] = stops
            elif fill["type"] == "IMAGE":
                fill_info["imageRef"] = fill.get("imageRef", "")
                fill_info["scaleMode"] = fill.get("scaleMode", "FILL")
            result["fills"].append(fill_info)

    # Strokes
    strokes = node.get("strokes", [])
    visible_strokes = [s for s in strokes if s.get("visible", True)]
    if visible_strokes:
        result["border"] = {
            "width": node.get("strokeWeight", 1),
            "color": _color_to_hex(visible_strokes[0].get("color", {})),
        }
        if node.get("strokeAlign"):
            result["border"]["align"] = node["strokeAlign"]

    # Corner radius
    cr = node.get("cornerRadius")
    if cr:
        result["borderRadius"] = cr
    rcr = node.get("rectangleCornerRadii")
    if rcr and any(r != rcr[0] for r in rcr):
        result["borderRadius"] = rcr

    # Effects
    effects = node.get("effects", [])
    visible_effects = [e for e in effects if e.get("visible", True)]
    if visible_effects:
        result["effects"] = []
        for eff in visible_effects:
            eff_info: dict[str, Any] = {"type": eff["type"]}
            if eff["type"] in ("DROP_SHADOW", "INNER_SHADOW"):
                offset = eff.get("offset", {})
                eff_info["x"] = offset.get("x", 0)
                eff_info["y"] = offset.get("y", 0)
                eff_info["blur"] = eff.get("radius", 0)
                eff_info["spread"] = eff.get("spread", 0)
                eff_info["color"] = _color_to_hex(eff.get("color", {}))
            elif eff["type"] in ("LAYER_BLUR", "BACKGROUND_BLUR"):
                eff_info["radius"] = eff.get("radius", 0)
            result["effects"].append(eff_info)

    # Typography (TEXT nodes)
    if node.get("type") == "TEXT":
        result["text"] = node.get("characters", "")
        style = node.get("style", {})
        if style:
            result["textStyle"] = {}
            for key in ("fontFamily", "fontSize", "fontWeight", "lineHeightPx",
                        "letterSpacing", "textAlignHorizontal", "textCase"):
                if key in style:
                    result["textStyle"][key] = style[key]
        # Text fill color
        text_fills = [f for f in fills if f.get("visible", True) and f.get("type") == "SOLID"]
        if text_fills:
            result["textColor"] = _color_to_hex(text_fills[0].get("color", {}))

    # Opacity
    if node.get("opacity") is not None and node["opacity"] < 1:
        result["opacity"] = round(node["opacity"], 2)

    # Clips
    if node.get("clipsContent"):
        result["overflow"] = "hidden"

    # Children
    children = node.get("children", [])
    if children:
        result["children"] = []
        for child in children:
            if child.get("visible", True):
                result["children"].append(_extract_styles(child, depth + 1))

    return result


@tool(
    "fetch_figma_file",
    "Fetch the Figma file tree. Use depth=1 or depth=2 to get an overview of pages and frames without too much data.",
    {"file_key": str, "depth": int},
)
async def fetch_figma_file(args: dict[str, Any]) -> dict[str, Any]:
    file_key = args["file_key"]
    depth = args.get("depth", 0)
    params = {}
    if depth and depth > 0:
        params["depth"] = depth

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{FIGMA_API_BASE}/files/{file_key}",
            headers=_get_headers(),
            params=params,
        )
        resp.raise_for_status()
        return {"content": [{"type": "text", "text": resp.text}]}


@tool(
    "fetch_figma_nodes",
    "Fetch specific node subtrees from a Figma file with full style details.",
    {"file_key": str, "node_ids": str},
)
async def fetch_figma_nodes(args: dict[str, Any]) -> dict[str, Any]:
    file_key = args["file_key"]
    node_ids = args["node_ids"]

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{FIGMA_API_BASE}/files/{file_key}/nodes",
            headers=_get_headers(),
            params={"ids": node_ids},
        )
        resp.raise_for_status()
        return {"content": [{"type": "text", "text": resp.text}]}


@tool(
    "get_node_css_styles",
    "Extract a COMPACT CSS-focused style summary from Figma nodes. Returns only CSS-relevant properties (colors as hex, layout as flex, typography, effects, image refs) in a clean nested structure. Use this INSTEAD of fetch_figma_nodes when you need to generate code — it's much smaller and easier to work with.",
    {"file_key": str, "node_ids": str},
)
async def get_node_css_styles(args: dict[str, Any]) -> dict[str, Any]:
    file_key = args["file_key"]
    node_ids = args["node_ids"]

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{FIGMA_API_BASE}/files/{file_key}/nodes",
            headers=_get_headers(),
            params={"ids": node_ids},
        )
        resp.raise_for_status()
        data = resp.json()

    results = {}
    for nid, node_data in data.get("nodes", {}).items():
        doc = node_data.get("document")
        if doc:
            results[nid] = _extract_styles(doc)

    return {"content": [{"type": "text", "text": json.dumps(results, indent=2)}]}


@tool(
    "export_figma_images",
    "Export Figma nodes as images (PNG or SVG). Returns download URLs. Use this to export reference screenshots of frames, icons, logos, and any node with image fills.",
    {
        "type": "object",
        "properties": {
            "file_key": {"type": "string", "description": "The Figma file key"},
            "node_ids": {"type": "string", "description": "Comma-separated node IDs to export"},
            "format": {"type": "string", "enum": ["png", "svg"], "description": "Image format"},
            "scale": {"type": "number", "description": "Export scale (1-4), only for PNG"},
        },
        "required": ["file_key", "node_ids"],
    },
)
async def export_figma_images(args: dict[str, Any]) -> dict[str, Any]:
    file_key = args["file_key"]
    node_ids = args["node_ids"]
    fmt = args.get("format", "png")
    scale = args.get("scale", 2.0)

    params = {"ids": node_ids, "format": fmt, "scale": scale}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{FIGMA_API_BASE}/images/{file_key}",
            headers=_get_headers(),
            params=params,
        )
        resp.raise_for_status()
        return {"content": [{"type": "text", "text": resp.text}]}


@tool(
    "get_image_fills",
    "Get download URLs for all image fills used in a Figma file. Returns a mapping of imageRef to download URL.",
    {"file_key": str},
)
async def get_image_fills(args: dict[str, Any]) -> dict[str, Any]:
    file_key = args["file_key"]

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{FIGMA_API_BASE}/files/{file_key}/images",
            headers=_get_headers(),
        )
        resp.raise_for_status()
        return {"content": [{"type": "text", "text": resp.text}]}


@tool(
    "download_asset",
    "Download an image from a URL and save it to a local file path. Use this to download exported images, logos, icons, and image fills.",
    {"url": str, "output_path": str},
)
async def download_asset(args: dict[str, Any]) -> dict[str, Any]:
    url = args["url"]
    output_path = args["output_path"]

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(resp.content)

    return {"content": [{"type": "text", "text": f"Downloaded {len(resp.content)} bytes to {output_path}"}]}


def create_figma_server():
    """Create an in-process MCP server with all Figma tools."""
    return create_sdk_mcp_server(
        name="figma",
        version="1.0.0",
        tools=[
            fetch_figma_file,
            fetch_figma_nodes,
            get_node_css_styles,
            export_figma_images,
            get_image_fills,
            download_asset,
        ],
    )
