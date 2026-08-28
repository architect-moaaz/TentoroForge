"""In-house FastMCP server exposing the component catalog to the authoring agent.

Two tools:
  - list_components(category, acceptsChildren) -> [{name, category, summary}]
  - get_component(name) -> the component's real JSON Schema, enums and all

Authoring currently works from a 30,495-character prose digest carried in
every page's system prompt, and infers contracts from it. That inference is
where the failures came from: `action: {navigate}` against a component that
accepted only `{workflow}`, a `preserveValues` prop that does not exist,
`views[].filters` the picker rejects. Four page trees lost on one run, one of
three on another. The digest itself caused three separate defects — an
`array<object>` with no item shape, an item shape with no enums, a nested
option written as a string — each fixed by making the summary more precise,
which is treating a symptom.

A tool call answers what a prose summary can only approximate. Read-only by
design: this serves the contract, it does not author against it, so
`validate_props` remains the boundary that decides what reaches a Blueprint.

Run standalone with `python -m a2ui_mcp.a2ui_server`.
"""
from __future__ import annotations

import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from services.blueprint.page_planner import load_catalog

logger = logging.getLogger(__name__)


def list_components_tool(
    category: str | None = None,
    accepts_children: bool | None = None,
) -> list[dict[str, Any]]:
    """Names and one-line summaries; call get_component for the schema."""
    out: list[dict[str, Any]] = []
    for name, entry in sorted(load_catalog().items()):
        if category and entry.get("category") != category:
            continue
        if (accepts_children is not None
                and bool(entry.get("acceptsChildren")) != accepts_children):
            continue
        doc = str(entry.get("docs") or "").strip().splitlines()
        out.append({
            "name": name,
            "category": entry.get("category"),
            "acceptsChildren": bool(entry.get("acceptsChildren")),
            "summary": doc[0][:160] if doc else "",
        })
    return out


def get_component_tool(name: str) -> dict[str, Any]:
    """One component's full contract — props schema, child contract, docs.

    Unknown names return the near misses rather than an empty result: an agent
    that asked for `DataGrid` is better served by being shown `Table` than by a
    silence it will fill with a guess.
    """
    catalog = load_catalog()
    entry = catalog.get(name)
    if entry is None:
        lowered = name.lower()
        near = sorted(n for n in catalog if lowered in n.lower()
                      or n.lower() in lowered)
        return {"error": f"no component named {name!r}",
                "didYouMean": near[:8] or sorted(catalog)[:8]}
    return {
        "name": name,
        "category": entry.get("category"),
        "props": entry.get("props"),
        "acceptsChildren": bool(entry.get("acceptsChildren")),
        "childContract": entry.get("childContract"),
        "docs": entry.get("docs"),
    }


def build_server() -> FastMCP:
    server = FastMCP("forge-a2ui")
    server.add_tool(
        list_components_tool,
        name="list_components",
        description=(
            "List the components a generated page may use, optionally "
            "filtered by category (layout, data, form, feedback, "
            "navigation, structural) or by whether they accept children. "
            "Returns names and one-line summaries — call get_component for "
            "the full prop schema before using one."
        ),
    )
    server.add_tool(
        get_component_tool,
        name="get_component",
        description=(
            "The full contract for one component: its props as JSON Schema "
            "with the enums and required fields, whether it accepts "
            "children and under which roles, and its documentation. Call "
            "this rather than guessing a prop name or an enum value — an "
            "invalid prop is rejected and the page is not authored."
        ),
    )
    return server


if __name__ == "__main__":
    build_server().run()
