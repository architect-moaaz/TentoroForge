"""Figma URL parser and design data transformation utilities."""

import re
from typing import Optional


def parse_figma_url(url: str) -> dict:
    """Parse a Figma URL and extract file_key and optional node_id.

    Supports:
      - https://www.figma.com/file/FILEKEY/Title
      - https://www.figma.com/design/FILEKEY/Title
      - https://www.figma.com/design/FILEKEY/Title?node-id=1-2
    """
    pattern = r"figma\.com/(?:file|design)/([a-zA-Z0-9]+)"
    match = re.search(pattern, url)
    if not match:
        raise ValueError(f"Invalid Figma URL: {url}")

    file_key = match.group(1)

    node_id: Optional[str] = None
    node_match = re.search(r"node-id=([^&]+)", url)
    if node_match:
        node_id = node_match.group(1).replace("-", ":")

    return {"file_key": file_key, "node_id": node_id}


def figma_color_to_css(color: dict, opacity: float = 1.0) -> str:
    """Convert Figma color {r,g,b,a} (0-1 floats) to CSS rgba() or hex string."""
    r = round(color.get("r", 0) * 255)
    g = round(color.get("g", 0) * 255)
    b = round(color.get("b", 0) * 255)
    a = color.get("a", 1.0) * opacity

    if a >= 1.0:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r}, {g}, {b}, {a:.2f})"


# Standard Tailwind color palette (subset for matching)
TAILWIND_COLORS = {
    "slate": {50: "#f8fafc", 100: "#f1f5f9", 200: "#e2e8f0", 300: "#cbd5e1", 400: "#94a3b8", 500: "#64748b", 600: "#475569", 700: "#334155", 800: "#1e293b", 900: "#0f172a", 950: "#020617"},
    "gray": {50: "#f9fafb", 100: "#f3f4f6", 200: "#e5e7eb", 300: "#d1d5db", 400: "#9ca3af", 500: "#6b7280", 600: "#4b5563", 700: "#374151", 800: "#1f2937", 900: "#111827", 950: "#030712"},
    "red": {50: "#fef2f2", 100: "#fee2e2", 200: "#fecaca", 300: "#fca5a5", 400: "#f87171", 500: "#ef4444", 600: "#dc2626", 700: "#b91c1c", 800: "#991b1b", 900: "#7f1d1d", 950: "#450a0a"},
    "orange": {50: "#fff7ed", 100: "#ffedd5", 200: "#fed7aa", 300: "#fdba74", 400: "#fb923c", 500: "#f97316", 600: "#ea580c", 700: "#c2410c", 800: "#9a3412", 900: "#7c2d12", 950: "#431407"},
    "yellow": {50: "#fefce8", 100: "#fef9c3", 200: "#fef08a", 300: "#fde047", 400: "#facc15", 500: "#eab308", 600: "#ca8a04", 700: "#a16207", 800: "#854d0e", 900: "#713f12", 950: "#422006"},
    "green": {50: "#f0fdf4", 100: "#dcfce7", 200: "#bbf7d0", 300: "#86efac", 400: "#4ade80", 500: "#22c55e", 600: "#16a34a", 700: "#15803d", 800: "#166534", 900: "#14532d", 950: "#052e16"},
    "blue": {50: "#eff6ff", 100: "#dbeafe", 200: "#bfdbfe", 300: "#93c5fd", 400: "#60a5fa", 500: "#3b82f6", 600: "#2563eb", 700: "#1d4ed8", 800: "#1e40af", 900: "#1e3a8a", 950: "#172554"},
    "indigo": {50: "#eef2ff", 100: "#e0e7ff", 200: "#c7d2fe", 300: "#a5b4fc", 400: "#818cf8", 500: "#6366f1", 600: "#4f46e5", 700: "#4338ca", 800: "#3730a3", 900: "#312e81", 950: "#1e1b4b"},
    "purple": {50: "#faf5ff", 100: "#f3e8ff", 200: "#e9d5ff", 300: "#d8b4fe", 400: "#c084fc", 500: "#a855f7", 600: "#9333ea", 700: "#7e22ce", 800: "#6b21a8", 900: "#581c87", 950: "#3b0764"},
    "pink": {50: "#fdf2f8", 100: "#fce7f3", 200: "#fbcfe8", 300: "#f9a8d4", 400: "#f472b6", 500: "#ec4899", 600: "#db2777", 700: "#be185d", 800: "#9d174d", 900: "#831843", 950: "#500724"},
    "white": {0: "#ffffff"},
    "black": {0: "#000000"},
}


def _hex_to_rgb(hex_str: str) -> tuple:
    hex_str = hex_str.lstrip("#")
    return tuple(int(hex_str[i : i + 2], 16) for i in (0, 2, 4))


def _color_distance(c1: tuple, c2: tuple) -> float:
    return sum((a - b) ** 2 for a, b in zip(c1, c2)) ** 0.5


def figma_color_to_tailwind(color: dict) -> str:
    """Map a Figma color to the nearest Tailwind color class or arbitrary value."""
    r = round(color.get("r", 0) * 255)
    g = round(color.get("g", 0) * 255)
    b = round(color.get("b", 0) * 255)
    target = (r, g, b)

    best_name = ""
    best_dist = float("inf")

    for name, shades in TAILWIND_COLORS.items():
        for shade, hex_val in shades.items():
            dist = _color_distance(target, _hex_to_rgb(hex_val))
            if dist < best_dist:
                best_dist = dist
                if name in ("white", "black"):
                    best_name = name
                else:
                    best_name = f"{name}-{shade}"

    # If the match is close enough, use the Tailwind name
    if best_dist < 30:
        return best_name

    # Otherwise return an arbitrary value
    return f"[#{r:02x}{g:02x}{b:02x}]"


def map_layout_to_css(node: dict) -> dict:
    """Convert Figma auto-layout properties to CSS flexbox properties."""
    css = {}
    layout_mode = node.get("layoutMode")
    if not layout_mode:
        return css

    css["display"] = "flex"
    css["flex-direction"] = "column" if layout_mode == "VERTICAL" else "row"

    gap = node.get("itemSpacing", 0)
    if gap:
        css["gap"] = f"{gap}px"

    # Padding
    pt = node.get("paddingTop", 0)
    pr = node.get("paddingRight", 0)
    pb = node.get("paddingBottom", 0)
    pl = node.get("paddingLeft", 0)
    if pt or pr or pb or pl:
        css["padding"] = f"{pt}px {pr}px {pb}px {pl}px"

    # Primary axis alignment
    primary = node.get("primaryAxisAlignItems", "MIN")
    align_map = {"MIN": "flex-start", "CENTER": "center", "MAX": "flex-end", "SPACE_BETWEEN": "space-between"}
    css["justify-content"] = align_map.get(primary, "flex-start")

    # Counter axis alignment
    counter = node.get("counterAxisAlignItems", "MIN")
    cross_map = {"MIN": "flex-start", "CENTER": "center", "MAX": "flex-end"}
    css["align-items"] = cross_map.get(counter, "flex-start")

    return css


def map_effects_to_css(effects: list) -> dict:
    """Convert Figma effects (shadows, blurs) to CSS properties."""
    css = {}
    shadows = []
    for effect in effects:
        if not effect.get("visible", True):
            continue
        etype = effect.get("type", "")
        if etype in ("DROP_SHADOW", "INNER_SHADOW"):
            color = effect.get("color", {})
            offset = effect.get("offset", {})
            x = offset.get("x", 0)
            y = offset.get("y", 0)
            radius = effect.get("radius", 0)
            spread = effect.get("spread", 0)
            color_str = figma_color_to_css(color)
            inset = "inset " if etype == "INNER_SHADOW" else ""
            shadows.append(f"{inset}{x}px {y}px {radius}px {spread}px {color_str}")
        elif etype == "LAYER_BLUR":
            radius = effect.get("radius", 0)
            css["filter"] = f"blur({radius}px)"
        elif etype == "BACKGROUND_BLUR":
            radius = effect.get("radius", 0)
            css["backdrop-filter"] = f"blur({radius}px)"

    if shadows:
        css["box-shadow"] = ", ".join(shadows)

    return css
