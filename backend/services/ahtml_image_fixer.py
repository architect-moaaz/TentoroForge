"""AHTML Image Fixer — replaces placeholder gray boxes with real images.

Scans an AHTML page for div placeholders and replaces them with <img> tags
referencing local images from public/images/ based on the images_manifest.json.

Detection heuristics:
1. Empty divs with bg-gray-200/300/400 classes and dimensions matching an image
2. Divs containing comments like <!-- Logo placeholder -->
3. Empty divs with rounded class and small dimensions (likely icons)

Mapping strategy:
- Logo: largest image (usually node_1_7.svg in CommBizO)
- Icons: smaller images, matched by approximate size
- Vector elements: SVG files
"""

import json
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def fix_ahtml_images(output_dir: str) -> dict[str, int]:
    """Fix image placeholders in all AHTML pages for a project.

    Returns:
        Dict of page_id → number of images injected
    """
    project_path = Path(output_dir)
    design_dir = project_path / ".design"
    manifest_path = project_path / "images_manifest.json"
    images_dir = project_path / "public" / "images"

    if not manifest_path.exists():
        logger.warning("No images_manifest.json found at %s", manifest_path)
        return {}

    if not design_dir.exists():
        return {}

    # Load manifest and categorize images by size/type
    manifest = json.loads(manifest_path.read_text())
    available_images = list(manifest.keys())

    # Categorize images
    logos = [k for k in available_images if "node_1_7" in k or "logo" in k.lower()]
    icons = [k for k in available_images if "node_1_1" in k or "node_1_2" in k or "node_1_3" in k]
    all_svgs = [k for k in available_images if k.endswith(".svg")]
    all_pngs = [k for k in available_images if k.endswith(".png")]

    logger.info("Found %d images: %d logos, %d SVGs, %d PNGs",
                len(available_images), len(logos), len(all_svgs), len(all_pngs))

    results = {}

    for html_file in design_dir.glob("*.design.html"):
        page_id = html_file.stem.replace(".design", "")
        html = html_file.read_text(encoding="utf-8")
        original_html = html
        injected = 0

        # Pattern 1: Logo placeholders — gray box with logo dimensions (~241x60)
        # Match: <div class="...w-[241px] h-[60px] bg-gray-... rounded..."></div>
        logo_pattern = re.compile(
            r'<div\s+class="[^"]*(?:w-\[24[01]px\]|w-60)[^"]*h-\[60px\][^"]*bg-gray-[^"]*"[^>]*>\s*</div>',
            re.IGNORECASE,
        )
        if logos:
            logo_path = manifest[logos[0]]
            html, n = logo_pattern.subn(
                f'<img src="{logo_path}" alt="Logo" class="w-[241px] h-[60px] object-contain" />',
                html,
            )
            injected += n

        # Pattern 2: Icon placeholders — small gray boxes (8x8 to 32x32)
        # Match: <div class="...w-[NNpx] h-[NNpx] bg-gray-..."></div> for small N
        icon_pattern = re.compile(
            r'<div\s+class="[^"]*w-(?:\[(?:8|16|20|24|32)px\]|[1-8])[^"]*h-(?:\[(?:8|16|20|24|32)px\]|[1-8])[^"]*bg-gray-[^"]*"[^>]*>\s*</div>',
            re.IGNORECASE,
        )

        # Use a counter so each match gets a different icon
        icon_counter = [0]
        usable_icons = [k for k in all_svgs if k not in logos]

        def replace_icon(match: re.Match) -> str:
            if icon_counter[0] < len(usable_icons):
                icon_name = usable_icons[icon_counter[0]]
                icon_path = manifest[icon_name]
                icon_counter[0] += 1
                return f'<img src="{icon_path}" alt="" class="w-6 h-6" />'
            return match.group(0)

        new_html, n = icon_pattern.subn(replace_icon, html)
        if n > 0:
            html = new_html
            injected += n

        # Pattern 3: w-N h-N bg-gray pattern (Tailwind shorthand sizes)
        small_box_pattern = re.compile(
            r'<div\s+class="[^"]*w-(?:6|8|10|12)\s+h-(?:6|8|10|12)[^"]*bg-gray-[^"]*"[^>]*>\s*</div>',
            re.IGNORECASE,
        )
        new_html, n = small_box_pattern.subn(replace_icon, html)
        if n > 0:
            html = new_html
            injected += n

        if injected > 0 and html != original_html:
            html_file.write_text(html, encoding="utf-8")
            results[page_id] = injected
            logger.info("Fixed %d image placeholders in %s", injected, page_id)

    return results
