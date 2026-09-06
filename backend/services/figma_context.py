"""Figma design context — the Figma adapter's token extraction.

The persisted file and the prompt section are provider-neutral and live in
:mod:`services.design_context`; this module keeps the Figma-specific half,
walking a ``styles.json`` tree for colours, fonts, sizes, radii and spacing,
and the three names its callers already import:

- extract_figma_context(): read styles.json, measure tokens, persist the design context
- should_refetch_figma(): detect if Figma data needs re-fetching (new URL or missing artifacts)
- get_figma_context_for_prompt(): the design-context prompt section
"""

import hashlib
import json
import logging
from pathlib import Path

from services.design_context import (
    context_ref_changed,
    get_design_context_for_prompt,
    read_design_context,
    write_design_context,
)

logger = logging.getLogger(__name__)


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

    tokens = tokens_from_styles(styles)
    return write_design_context(
        output_dir,
        provider="figma",
        design_ref=figma_url,
        tokens=tokens,
        extra={"styles_json_hash": styles_hash},
    )


def tokens_from_styles(styles: dict) -> dict:
    """Walk a Figma ``styles.json`` tree (one frame, or a dict of frames keyed
    by node id) and return the ``design_tokens`` dict: sorted, deduplicated
    colours, fonts, font sizes, border radii and spacings."""
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

    return {
        "colors": sorted(colors),
        "fonts": sorted(fonts),
        "font_sizes": sorted(font_sizes),
        "border_radii": sorted(border_radii),
        "spacings": sorted(spacings),
    }


def should_refetch_figma(output_dir: str, new_figma_url: str | None) -> bool:
    """Check if Figma data needs re-fetching (new URL or missing artifacts)."""
    if not new_figma_url:
        return False

    styles_path = Path(output_dir) / "styles.json"
    ref_path = Path(output_dir) / "reference.png"

    # Missing artifacts → need to fetch
    if not styles_path.exists() or not ref_path.exists():
        return True

    # No context file → need to extract (not necessarily re-fetch)
    if read_design_context(output_dir) is None:
        return False  # styles.json exists, just need extract_figma_context()

    if context_ref_changed(output_dir, new_figma_url):
        logger.info("[figma_context] URL changed → %s", new_figma_url)
        return True
    return False


def get_figma_context_for_prompt(output_dir: str) -> str:
    """The design-context prompt section (empty when the project was not
    built from a design). Kept under its Figma-era name for its callers."""
    return get_design_context_for_prompt(output_dir)
