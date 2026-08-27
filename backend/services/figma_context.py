"""Figma design context persistence — extracts design tokens from styles.json.

Provides:
- extract_figma_context(): parse styles.json, collect unique design tokens, write figma-context.json
- should_refetch_figma(): detect if Figma data needs re-fetching (new URL or missing artifacts)
- get_figma_context_for_prompt(): return a prompt section string for agents to include
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_CONTEXT_PATH = "src/contracts/figma-context.json"


def extract_figma_context(output_dir: str, figma_url: str) -> dict:
    """Parse styles.json, extract design tokens, write figma-context.json.

    Returns the context dict that was written.
    """
    styles_path = Path(output_dir) / "styles.json"
    if not styles_path.exists():
        logger.warning("[figma_context] styles.json not found in %s", output_dir)
        return {}

    raw = styles_path.read_text()
    styles_hash = f"sha256:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    try:
        styles = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("[figma_context] Failed to parse styles.json")
        return {}

    # Collect design tokens by walking the style tree
    colors: set[str] = set()
    fonts: set[str] = set()
    font_sizes: set[int | float] = set()
    border_radii: set[int | float] = set()
    spacings: set[int | float] = set()

    def _walk(node: dict) -> None:
        # Colors from fills
        for fill in node.get("fills", []):
            color = fill.get("color")
            if color and isinstance(color, str):
                colors.add(color)
            for stop in fill.get("stops", []):
                c = stop.get("color")
                if c and isinstance(c, str):
                    colors.add(c)

        # Text color
        tc = node.get("textColor")
        if tc and isinstance(tc, str):
            colors.add(tc)

        # Border color
        border = node.get("border")
        if isinstance(border, dict):
            bc = border.get("color")
            if bc and isinstance(bc, str):
                colors.add(bc)

        # Typography
        ts = node.get("textStyle")
        if isinstance(ts, dict):
            ff = ts.get("fontFamily")
            if ff:
                fonts.add(ff)
            fs = ts.get("fontSize")
            if isinstance(fs, (int, float)):
                font_sizes.add(fs)

        # Border radius
        br = node.get("borderRadius")
        if isinstance(br, (int, float)) and br > 0:
            border_radii.add(br)
        elif isinstance(br, list):
            for v in br:
                if isinstance(v, (int, float)) and v > 0:
                    border_radii.add(v)

        # Spacings from layout
        layout = node.get("layout")
        if isinstance(layout, dict):
            gap = layout.get("gap")
            if isinstance(gap, (int, float)) and gap > 0:
                spacings.add(gap)
            padding = layout.get("padding")
            if isinstance(padding, dict):
                for side in ("top", "right", "bottom", "left"):
                    val = padding.get(side)
                    if isinstance(val, (int, float)) and val > 0:
                        spacings.add(val)

        # Recurse
        for child in node.get("children", []):
            _walk(child)

    # styles can be a single tree or a dict of trees keyed by node ID
    if "children" in styles or "type" in styles:
        _walk(styles)
    else:
        for tree in styles.values():
            if isinstance(tree, dict):
                _walk(tree)

    context = {
        "figma_url": figma_url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "styles_json_hash": styles_hash,
        "design_tokens": {
            "colors": sorted(colors),
            "fonts": sorted(fonts),
            "font_sizes": sorted(font_sizes),
            "border_radii": sorted(border_radii),
            "spacings": sorted(spacings),
        },
    }

    # Write to src/contracts/figma-context.json
    ctx_path = Path(output_dir) / _CONTEXT_PATH
    ctx_path.parent.mkdir(parents=True, exist_ok=True)
    ctx_path.write_text(json.dumps(context, indent=2))
    logger.info("[figma_context] Wrote %s with %d colors, %d fonts",
                ctx_path, len(colors), len(fonts))

    return context


def should_refetch_figma(output_dir: str, new_figma_url: str | None) -> bool:
    """Check if Figma data needs re-fetching (new URL or missing artifacts)."""
    if not new_figma_url:
        return False

    ctx_path = Path(output_dir) / _CONTEXT_PATH
    styles_path = Path(output_dir) / "styles.json"
    ref_path = Path(output_dir) / "reference.png"

    # Missing artifacts → need to fetch
    if not styles_path.exists() or not ref_path.exists():
        return True

    # No context file → need to extract (not necessarily re-fetch)
    if not ctx_path.exists():
        return False  # styles.json exists, just need extract_figma_context()

    # Compare URLs
    try:
        existing = json.loads(ctx_path.read_text())
        existing_url = existing.get("figma_url", "")
        if existing_url != new_figma_url:
            logger.info("[figma_context] URL changed: %s → %s", existing_url, new_figma_url)
            return True
    except (json.JSONDecodeError, OSError):
        return True

    return False


def get_figma_context_for_prompt(output_dir: str) -> str:
    """Return a prompt section string for agents to include.

    Returns empty string if no figma-context.json exists.
    """
    ctx_path = Path(output_dir) / _CONTEXT_PATH
    if not ctx_path.exists():
        return ""

    try:
        ctx = json.loads(ctx_path.read_text())
    except (json.JSONDecodeError, OSError):
        return ""

    tokens = ctx.get("design_tokens", {})
    colors = tokens.get("colors", [])
    fonts = tokens.get("fonts", [])
    font_sizes = tokens.get("font_sizes", [])
    border_radii = tokens.get("border_radii", [])
    spacings = tokens.get("spacings", [])

    sections = [
        "\n## Figma Design Context",
        "This project was generated from a Figma design. Use these design tokens for visual consistency:",
    ]

    if colors:
        sections.append(f"- Colors: {', '.join(colors[:20])}")
    if fonts:
        sections.append(f"- Fonts: {', '.join(fonts)}")
    if font_sizes:
        sections.append(f"- Font sizes: {', '.join(str(s) + 'px' for s in font_sizes)}")
    if border_radii:
        sections.append(f"- Border radii: {', '.join(str(r) + 'px' for r in border_radii)}")
    if spacings:
        sections.append(f"- Spacings: {', '.join(str(s) + 'px' for s in spacings)}")

    sections.append("- Reference design: reference.png (read if helpful)")
    sections.append("When making visual changes, prefer values from the original design system.")

    return "\n".join(sections)
