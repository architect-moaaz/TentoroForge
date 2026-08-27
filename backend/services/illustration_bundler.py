"""Asset bundler — copies chosen unDraw SVGs from the cache into output/<id>/.

Runs after each page schema is emitted. Walks the schema tree, collects
every illustration.slug reference, and for each slug copies the cached
SVG into output_dir/public/illustrations/<slug>.svg so the generated
app ships with the asset.
"""
from __future__ import annotations
from pathlib import Path
import logging
import shutil

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _REPO_ROOT / "backend" / ".cache" / "illustrations"


def _collect_slugs(node: object, slugs: set) -> None:
    if not isinstance(node, dict):
        return
    props = node.get("props") or {}
    illu = props.get("illustration")
    if isinstance(illu, dict) and isinstance(illu.get("slug"), str):
        slugs.add(illu["slug"])
    for child in node.get("children") or []:
        _collect_slugs(child, slugs)


def bundle_illustrations_for_schema(output_dir: str, schema: dict, accent_color: str = "6b7280") -> int:
    """Walk the schema, find illustration slugs, copy cached SVGs into output.

    Returns the count of SVGs successfully bundled.
    """
    slugs: set = set()
    _collect_slugs(schema.get("root", {}), slugs)
    if not slugs:
        return 0
    dest_dir = Path(output_dir) / "public" / "illustrations"
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    accent = accent_color.lstrip("#").lower()
    for slug in slugs:
        src = _CACHE_DIR / f"{slug}__{accent}.svg"
        if not src.exists():
            logger.warning("illustration cache miss for slug=%s color=%s — skipping bundle", slug, accent)
            continue
        dest = dest_dir / f"{slug}.svg"
        shutil.copy2(src, dest)
        count += 1
    return count
