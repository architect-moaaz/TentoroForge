"""In-house FastMCP server exposing unDraw illustrations to the schema agent.

Two tools:
  - list_illustrations(tags, limit) -> [{slug, title, tags}]
  - get_illustration_svg(slug, color) -> SVG string (raw markup)

The schema agent calls these during generation. The bundler step in
page_schema_agent then copies the chosen SVG into
output/<id>/public/illustrations/<slug>.svg so the rendered app ships
with the asset.
"""
from __future__ import annotations
from pathlib import Path
import logging

# Official MCP SDK (different from our local illustrations_mcp package)
from mcp.server.fastmcp import FastMCP

from illustrations_mcp.undraw_client import UndrawClient

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CACHE_DIR = _REPO_ROOT / "backend" / ".cache" / "illustrations"

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = UndrawClient(cache_dir=_CACHE_DIR)
    return _client


def list_illustrations_tool(tags=None, limit=20):
    """Return up to `limit` illustrations matching any of `tags`."""
    metas = _get_client().list_illustrations(tags=tags, limit=limit)
    return [{"slug": m.slug, "title": m.title, "tags": m.tags} for m in metas]


def get_illustration_tool(slug, color="6b7280"):
    """Return the SVG markup for a slug, recolored to the given hex.

    Returns a sentinel error string when the slug is unknown - the LLM
    handles this by picking a different slug.
    """
    svg = _get_client().get_illustration_svg(slug, color=color)
    if svg is None:
        return f"<!-- illustration not found: {slug} -->"
    return svg.decode("utf-8", errors="replace")


def build_server():
    """Construct the FastMCP server and register both tools."""
    server = FastMCP("forge-illustrations")
    server.add_tool(
        list_illustrations_tool,
        name="list_illustrations",
        description=(
            "List unDraw illustrations filtered by tag keywords (e.g. "
            "['auth', 'fitness']). Returns slugs you can pass to "
            "get_illustration_svg. Use tags like: auth, login, signup, "
            "empty-state, dashboard, success, error, onboarding, "
            "travel, fitness, productivity, healthcare."
        ),
    )
    server.add_tool(
        get_illustration_tool,
        name="get_illustration_svg",
        description=(
            "Fetch the SVG markup for an illustration slug. Pass a hex "
            "color (no '#') to recolor it to your brand accent."
        ),
    )
    return server


if __name__ == "__main__":
    build_server().run()
