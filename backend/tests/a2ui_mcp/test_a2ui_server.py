"""A2UI over MCP — the catalog answered by tool call, not by prose digest."""

from a2ui_mcp.a2ui_server import (
    build_server, get_component_tool, list_components_tool,
)


def test_every_component_is_listed_with_what_it_is():
    comps = list_components_tool()
    assert len(comps) > 100
    by_name = {c["name"]: c for c in comps}
    assert by_name["Table"]["category"] == "data"
    assert by_name["Stack"]["acceptsChildren"] is True


def test_listing_narrows_by_category_and_by_nesting():
    layout = {c["name"] for c in list_components_tool(category="layout")}
    assert "Accordion" in layout and "Table" not in layout
    leaves = list_components_tool(accepts_children=False)
    assert all(c["acceptsChildren"] is False for c in leaves)


def test_a_component_answers_with_its_real_schema_not_a_summary():
    """The digest said `action` took a workflow; authoring wrote `navigate`
    against it and four page trees were rejected. A tool call carries the
    enums and the required fields a prose summary approximates."""
    entry = get_component_tool("EmptyState")
    action = entry["props"]["properties"]["action"]
    shapes = [set(o["required"]) for o in action["anyOf"]]
    assert {"label", "workflow"} in shapes
    assert {"label", "navigate"} in shapes


def test_a_nesting_component_reports_its_child_contract():
    entry = get_component_tool("Tabs")
    assert entry["acceptsChildren"] is True
    assert entry["childContract"] is not None


def test_an_unknown_name_returns_near_misses_rather_than_silence():
    """An agent that asked for the wrong name will fill a silence with a
    guess; showing it the neighbours is what stops the next bad prop."""
    out = get_component_tool("KanbamBoard")
    assert "error" in out
    assert out["didYouMean"]


def test_the_server_registers_both_tools():
    server = build_server()
    assert server.name == "forge-a2ui"
