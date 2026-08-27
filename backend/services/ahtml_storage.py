"""AHTML Storage Service — manages .design/ directory for annotated HTML files.

Each project stores its annotated HTML pages as individual files:
  output/{project_id}/.design/{page_id}.design.html

The storage service handles reading, writing, and listing these files.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_design_dir(output_dir: str) -> Path:
    """Get the .design/ directory path for a project."""
    return Path(output_dir) / ".design"


def ensure_design_dir(output_dir: str) -> Path:
    """Ensure the .design/ directory exists."""
    design_dir = get_design_dir(output_dir)
    design_dir.mkdir(parents=True, exist_ok=True)
    return design_dir


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def load_all_pages(output_dir: str) -> list[dict[str, Any]]:
    """Load all annotated HTML pages from .design/ directory.

    Returns:
        List of page dicts with pageId, route, title, html, css.
    """
    design_dir = get_design_dir(output_dir)
    if not design_dir.exists():
        return []

    pages = []
    for html_file in sorted(design_dir.glob("*.design.html")):
        page_id = html_file.stem.replace(".design", "")
        html = html_file.read_text(encoding="utf-8")

        # Load optional CSS sidecar
        css_file = design_dir / f"{page_id}.design.css"
        css = css_file.read_text(encoding="utf-8") if css_file.exists() else None

        # Load optional metadata sidecar
        meta_file = design_dir / f"{page_id}.meta.json"
        meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}

        pages.append({
            "pageId": page_id,
            "route": meta.get("route", f"/{page_id}"),
            "title": meta.get("title"),
            "html": html,
            "css": css,
        })

    return pages


def load_page(output_dir: str, page_id: str) -> dict[str, Any] | None:
    """Load a single annotated HTML page."""
    design_dir = get_design_dir(output_dir)
    html_file = design_dir / f"{page_id}.design.html"

    if not html_file.exists():
        return None

    html = html_file.read_text(encoding="utf-8")
    css_file = design_dir / f"{page_id}.design.css"
    css = css_file.read_text(encoding="utf-8") if css_file.exists() else None

    meta_file = design_dir / f"{page_id}.meta.json"
    meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}

    return {
        "pageId": page_id,
        "route": meta.get("route", f"/{page_id}"),
        "title": meta.get("title"),
        "html": html,
        "css": css,
    }


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def save_pages(output_dir: str, pages: list[dict[str, Any]]) -> list[str]:
    """Save annotated HTML pages to .design/ directory.

    Args:
        output_dir: Project output directory.
        pages: List of page dicts with pageId, route, title, html, css.

    Returns:
        List of saved file paths (relative to output_dir).
    """
    design_dir = ensure_design_dir(output_dir)
    saved = []

    for page in pages:
        page_id = page.get("pageId", "page")
        html = page.get("html", "")
        css = page.get("css")
        route = page.get("route", f"/{page_id}")
        title = page.get("title")

        # Write HTML
        html_file = design_dir / f"{page_id}.design.html"
        html_file.write_text(html, encoding="utf-8")
        saved.append(str(html_file.relative_to(output_dir)))

        # Write CSS sidecar (if present)
        if css:
            css_file = design_dir / f"{page_id}.design.css"
            css_file.write_text(css, encoding="utf-8")

        # Write metadata sidecar
        meta_file = design_dir / f"{page_id}.meta.json"
        meta = {"route": route}
        if title:
            meta["title"] = title
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        logger.info("Saved AHTML page: %s → %s", page_id, html_file)

    return saved


def save_annotated_app(output_dir: str, app: dict[str, Any]) -> list[str]:
    """Save an AnnotatedApp (from irToAnnotatedHtml) to .design/ directory.

    Args:
        output_dir: Project output directory.
        app: AnnotatedApp dict with name, pages, dataSources, navigation.

    Returns:
        List of saved file paths.
    """
    design_dir = ensure_design_dir(output_dir)

    # Save app-level metadata
    app_meta = {
        "name": app.get("name"),
        "theme": app.get("theme"),
        "navigation": app.get("navigation"),
    }
    meta_file = design_dir / "app.meta.json"
    meta_file.write_text(json.dumps(app_meta, indent=2), encoding="utf-8")

    # Save data sources
    data_sources = app.get("dataSources", {})
    if data_sources:
        ds_file = design_dir / "datasources.json"
        ds_file.write_text(json.dumps(data_sources, indent=2), encoding="utf-8")

    # Save pages
    return save_pages(output_dir, app.get("pages", []))


# ---------------------------------------------------------------------------
# Delete operations
# ---------------------------------------------------------------------------

def delete_page(output_dir: str, page_id: str) -> bool:
    """Delete a single page from .design/ directory."""
    design_dir = get_design_dir(output_dir)
    deleted = False

    for suffix in [".design.html", ".design.css", ".meta.json"]:
        f = design_dir / f"{page_id}{suffix}"
        if f.exists():
            f.unlink()
            deleted = True

    return deleted


def has_design(output_dir: str) -> bool:
    """Check if a project has any .design/ files."""
    design_dir = get_design_dir(output_dir)
    if not design_dir.exists():
        return False
    return any(design_dir.glob("*.design.html"))
